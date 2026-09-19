"""
AI Fire Drill — commit regression analyzer (FastAPI on AWS Lambda via Mangum).

The product: detect WHICH code commit broke a working application, then
explain WHAT changed, WHY it broke, and HOW to fix it — strictly from the
evidence (commit diff, CI check results, optional health endpoint).

Flow (POST /analyze):
  1. Parse the GitHub repo URL + branch (default main).
  2. List recent commits on the branch.
  3. Evaluate CI for each commit (check-runs, falling back to commit statuses).
  4. Head = newest commit; baseline = newest older commit whose CI passes.
  5. Fetch the diff between baseline and head (GitHub compare API).
  6. Optionally probe the deployed health URL (supporting evidence only).
  7. Ask Groq to produce the WHAT / WHY / HOW report from that evidence only.
  8. Persist the analysis in DynamoDB and return it.

If a repo has no CI and no health URL, the analysis honestly reports that
there is nothing to verify — nothing is invented. If Groq fails, the API
returns a summary assembled directly from the raw evidence, never a made-up
root cause.

DynamoDB only accepts `Decimal` (never `float`), at any nesting depth, and
returns `Decimal` values on reads. Every value crossing that boundary goes
through `to_dynamodb` / `from_dynamodb` so nothing leaks either way.

Endpoints:
  GET  /status    -> service info
  POST /analyze   -> run a fire-drill analysis for repo_url (+ branch, health_url)
  GET  /analyses  -> recent analysis history
"""

import json
import os
import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Optional

import boto3
import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from mangum import Mangum
from pydantic import BaseModel

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

# Load backend/.env (if present) BEFORE any config value is read below. The
# path is resolved relative to this file, so loading works no matter which
# working directory the process was started from (repo root, backend/,
# `uvicorn --app-dir backend`, Lambda container, ...). Variables already set
# in the real environment (e.g. Lambda/template.yaml) always win over .env.
load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env", override=False)

TABLE_NAME = os.environ.get("TABLE_NAME", "ai-fire-drill-analyses").strip()

GITHUB_API = "https://api.github.com"
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()
GITHUB_TIMEOUT_S = float(os.environ.get("GITHUB_TIMEOUT_S", "15"))

# Groq (OpenAI-compatible chat completions). Values are configurable so a
# deployment can be corrected without a code change, but every default here is
# the currently documented, valid value:
#   POST https://api.groq.com/openai/v1/chat/completions
#   Authorization: Bearer $GROQ_API_KEY
#   {"model": "llama-3.3-70b-versatile", "messages": [...]}
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "").strip()
GROQ_URL = os.environ.get(
    "GROQ_URL", "https://api.groq.com/openai/v1/chat/completions"
).strip()
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile").strip()
# Tried only if the primary model is unavailable (e.g. a 404 model-not-found
# from an API key whose project lacks permission for that model).
GROQ_FALLBACK_MODELS = [
    m.strip()
    for m in os.environ.get(
        "GROQ_FALLBACK_MODELS", "openai/gpt-oss-120b,llama-3.1-8b-instant"
    ).split(",")
    if m.strip()
]
GROQ_TIMEOUT_S = float(os.environ.get("GROQ_TIMEOUT_S", "10"))
GROQ_MAX_ATTEMPTS = 2

HEALTH_TIMEOUT_S = float(os.environ.get("HEALTH_TIMEOUT_S", "8"))

# Diff truncation keeps prompt + stored items bounded on big diffs.
PATCH_CAP_PER_FILE = 3000
PATCH_CAP_TOTAL = 10000
STORED_TEXT_CAP = 500

# CI conclusions that count as a failing check.
FAILING_CONCLUSIONS = {
    "failure",
    "timed_out",
    "action_required",
    "cancelled",
    "startup_failure",
}

FINDING_FIELDS = ("what_changed", "what_broke", "why", "evidence", "how_to_fix")

# --------------------------------------------------------------------------- #
# DynamoDB <-> Python type conversion
# --------------------------------------------------------------------------- #


def to_dynamodb(value):
    """
    Recursively convert a Python value into something DynamoDB accepts.

    DynamoDB rejects `float` at any depth ("Float types are not supported"),
    so floats become `Decimal` via `str()` to avoid binary float artifacts.
    Booleans are preserved (they are a distinct DynamoDB type, even though
    `bool` subclasses `int`).
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {key: to_dynamodb(val) for key, val in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_dynamodb(item) for item in value]
    return value


def from_dynamodb(value):
    """
    Recursively convert DynamoDB `Decimal` values back into JSON-safe Python
    numbers so they never leak into FastAPI responses.
    """
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)
        return float(value)
    if isinstance(value, dict):
        return {key: from_dynamodb(val) for key, val in value.items()}
    if isinstance(value, (list, tuple)):
        return [from_dynamodb(item) for item in value]
    return value


# --------------------------------------------------------------------------- #
# DynamoDB helpers
# --------------------------------------------------------------------------- #

_table_resource = None


def _table():
    """Lazily create (and cache) the DynamoDB Table resource for this container."""
    global _table_resource
    if _table_resource is None:
        _table_resource = boto3.resource("dynamodb").Table(TABLE_NAME)
    return _table_resource


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------- #
# GitHub client
# --------------------------------------------------------------------------- #


def parse_repo_url(repo_url: str) -> tuple:
    """
    Accept https://github.com/owner/repo(.git), github.com/owner/repo or the
    bare "owner/repo" shorthand. Returns (owner, repo). Raises ValueError.
    """
    text = (repo_url or "").strip()
    if not text:
        raise ValueError("repo_url is required")
    text = re.sub(r"\.git$", "", text)
    match = re.search(r"github\.com[/:]([\w.-]+)/([\w.-]+)", text)
    if match:
        return match.group(1), match.group(2)
    match = re.fullmatch(r"([\w.-]+)/([\w.-]+)", text)
    if match:
        return match.group(1), match.group(2)
    raise ValueError(f"not a GitHub repository URL: {repo_url!r}")


def gh(path: str) -> dict:
    """One GitHub API GET. Raises HTTPException on bad status / network error."""
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "ai-fire-drill",
    }
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    # Safe debug logging: the full request URL, never the headers (the
    # Authorization header carries the GitHub token and must never be logged).
    print(f"[github] GET {GITHUB_API}{path} (token={'set' if GITHUB_TOKEN else 'not set'})")
    try:
        resp = requests.get(f"{GITHUB_API}{path}", headers=headers, timeout=GITHUB_TIMEOUT_S)
    except Exception as exc:  # noqa: BLE001 — surface as 502, never crash the Lambda
        raise HTTPException(status_code=502, detail=f"GitHub API unreachable: {exc}") from exc

    if resp.status_code == 404:
        raise HTTPException(
            status_code=404,
            detail=f"GitHub resource not found (private repo or missing token?): {path}",
        )
    if resp.status_code >= 400:
        body = ""
        try:
            body = (resp.text or "")[:300]
        except Exception:  # noqa: BLE001 — logging must never mask the real error
            body = "<unreadable body>"
        raise HTTPException(
            status_code=502, detail=f"GitHub API returned {resp.status_code}: {body}"
        )
    try:
        return resp.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="GitHub API returned non-JSON body") from exc


def list_commits(owner: str, repo: str, branch: str, max_commits: int) -> list:
    """Newest-first list of commits on the branch: [{sha, message, author, date, html_url, parents}]."""
    data = gh(f"/repos/{owner}/{repo}/commits?sha={branch}&per_page={max_commits}")
    if not isinstance(data, list) or not data:
        raise HTTPException(status_code=404, detail=f"No commits found on branch '{branch}'")
    commits = []
    for item in data:
        info = item.get("commit") or {}
        author = (info.get("author") or {}).get("name", "unknown")
        commits.append(
            {
                "sha": item.get("sha", ""),
                "message": (info.get("message") or "").splitlines()[0][:200],
                "author": author,
                "author_date": (info.get("author") or {}).get("date", ""),
                "html_url": item.get("html_url", ""),
                "parents": [p.get("sha") for p in (item.get("parents") or [])],
            }
        )
    return commits


def commit_ci(owner: str, repo: str, sha: str) -> dict:
    """
    CI verdict for one commit: {"state": success|failure|pending|unknown,
    "failing": [{name, title, details_url}], "passing": int, "total": int}.
    Uses check-runs first; falls back to the combined commit status.
    """
    failing, passing, total = [], [], 0
    data = gh(f"/repos/{owner}/{repo}/commits/{sha}/check-runs")
    runs = data.get("check_runs") or []
    total = data.get("total_count", len(runs))
    for run in runs:
        entry = {
            "name": run.get("name", "check"),
            "title": ((run.get("output") or {}).get("title") or "")[:200],
            "details_url": run.get("html_url", ""),
        }
        conclusion = run.get("conclusion")
        if conclusion == "success":
            passing.append(entry)
        elif conclusion in FAILING_CONCLUSIONS:
            failing.append(entry)

    if total > 0 or runs:
        if failing:
            state = "failure"
        elif passing:
            state = "success"
        else:
            state = "pending" if runs else "unknown"
        return {"state": state, "failing": failing, "passing": len(passing), "total": total}

    # Fallback: combined commit status (classic commit statuses).
    status = gh(f"/repos/{owner}/{repo}/commits/{sha}/status")
    for st in status.get("statuses") or []:
        entry = {
            "name": st.get("context", "status"),
            "title": st.get("context", "status"),
            "details_url": st.get("target_url") or "",
        }
        if st.get("state") == "success":
            passing.append(entry)
        elif st.get("state") in ("failure", "error"):
            failing.append(entry)
    combined = status.get("state")
    if combined in ("success", "failure", "error"):
        state = "success" if combined == "success" else "failure"
    elif combined in ("pending", "expected"):
        state = "pending"
    else:
        state = "unknown"
    return {"state": state, "failing": failing, "passing": len(passing), "total": len(status.get("statuses") or [])}


def fetch_compare(owner: str, repo: str, base_sha: str, head_sha: str) -> dict:
    """
    Diff between two commits. Returns {"files": [...], "total_commits": int,
    "capped": bool}. Long patches are truncated (never silently dropped files).
    """
    data = gh(f"/repos/{owner}/{repo}/compare/{base_sha}...{head_sha}")
    files, used = [], 0
    for f in data.get("files") or []:
        patch = f.get("patch") or ""
        capped = False
        if len(patch) > PATCH_CAP_PER_FILE:
            patch, capped = patch[:PATCH_CAP_PER_FILE], True
        if used + len(patch) > PATCH_CAP_TOTAL:
            remaining = max(PATCH_CAP_TOTAL - used, 0)
            patch, capped, used = patch[:remaining], True, PATCH_CAP_TOTAL
        else:
            used += len(patch)
        files.append(
            {
                "filename": f.get("filename", ""),
                "status": f.get("status", ""),
                "additions": f.get("additions", 0),
                "deletions": f.get("deletions", 0),
                "patch": patch,
                "patch_capped": capped,
            }
        )
    return {
        "files": files,
        "total_commits": data.get("total_commits", 0),
        "capped": used >= PATCH_CAP_TOTAL,
    }


# --------------------------------------------------------------------------- #
# Health probe (supporting evidence only)
# --------------------------------------------------------------------------- #


def probe_health(url: str) -> Optional[dict]:
    """GET the health URL once. Never raises; unknowns become ok=False."""
    if not url:
        return None
    started = datetime.now()
    try:
        resp = requests.get(url, timeout=HEALTH_TIMEOUT_S, headers={"User-Agent": "ai-fire-drill"})
        latency_ms = int((datetime.now() - started).total_seconds() * 1000)
        ok = 200 <= resp.status_code < 300
        detail = "" if ok else (resp.text or "")[:200]
        return {
            "url": url,
            "reachable": True,
            "ok": ok,
            "status_code": resp.status_code,
            "latency_ms": latency_ms,
            "detail": detail,
        }
    except Exception as exc:  # noqa: BLE001 — health failures are evidence, not crashes
        latency_ms = int((datetime.now() - started).total_seconds() * 1000)
        return {
            "url": url,
            "reachable": False,
            "ok": False,
            "status_code": None,
            "latency_ms": latency_ms,
            "detail": f"{type(exc).__name__}: {exc}"[:200],
        }


# --------------------------------------------------------------------------- #
# Groq analysis (OpenAI-compatible chat completions)
# --------------------------------------------------------------------------- #

SYSTEM_PROMPT = (
    "You are an expert software engineer performing a fire-drill regression "
    "analysis on a GitHub repository. You receive structured evidence: the code "
    "diff between the last known-good commit and the newest commit, CI check "
    "results, and an optional HTTP health check. Respond with ONLY a single "
    "valid JSON object and nothing else — no markdown, no code fences. Base "
    "every statement strictly on the provided evidence. Never invent logs, "
    "metrics, stack traces, or causes. If the evidence is insufficient to "
    "explain the failure, say so explicitly in 'why' and lower 'confidence'."
)


def build_prompt(repo: dict, head: dict, baseline: Optional[dict], ci: dict,
                 health: Optional[dict], compare: dict) -> str:
    failing = [
        {"name": f["name"], "title": f["title"]} for f in ci.get("failing", [])
    ]
    file_list = [
        {
            "filename": f["filename"],
            "status": f["status"],
            "additions": f["additions"],
            "deletions": f["deletions"],
        }
        for f in compare["files"]
    ]
    patches = "\n\n".join(
        f"--- a/{f['filename']} (patch{', truncated' if f['patch_capped'] else ''})\n{f['patch']}"
        for f in compare["files"]
        if f["patch"]
    ) or "(no textual diff available)"

    base_desc = (
        f"{baseline['sha'][:7]} — {baseline['message']}" if baseline else "none found"
    )
    return (
        "Analyse this potential regression.\n\n"
        f"Repository: {repo['full_name']} (branch {repo['branch']})\n"
        f"Head commit: {head['sha'][:7]} — {head['message']}\n"
        f"Previous working commit: {base_desc}\n\n"
        f"CI checks on head commit: {json.dumps({'state': ci['state'], 'failing': failing, 'passing': ci['passing'], 'total': ci['total']})}\n"
        f"Health check: {json.dumps(health) if health else 'not provided'}\n"
        f"Changed files ({len(file_list)}): {json.dumps(file_list)}\n\n"
        f"Diff:\n{patches}\n\n"
        "Respond with ONLY a JSON object with exactly these fields:\n"
        "regression_detected (boolean),\n"
        "what_changed (string — summarize the actual code changes),\n"
        "what_broke (string — the observed failure; empty string if nothing broke),\n"
        "why (string — root cause, based only on the diff and evidence above),\n"
        "evidence (array of strings — quote failing checks, specific diff lines, health results),\n"
        "how_to_fix (string — a concrete fix referencing the actual code),\n"
        "confidence (number 0-1)"
    )


def strip_code_fences(text: str) -> str:
    """Remove ```json ... ``` fences if the model wraps its JSON in them."""
    if not isinstance(text, str):
        raise ValueError("groq response content is not text")
    match = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    text = text.strip()
    if text.startswith("```"):  # unclosed fence
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text


def normalize_finding(parsed) -> dict:
    """Validate/coerce the model output into the exact report shape."""
    if not isinstance(parsed, dict):
        raise ValueError("finding is not a JSON object")
    for field in FINDING_FIELDS:
        if field not in parsed:
            raise ValueError(f"missing field: {field}")

    evidence = parsed["evidence"]
    if isinstance(evidence, str):
        evidence = [evidence]
    elif not isinstance(evidence, (list, tuple)):
        evidence = [str(evidence)]
    evidence = [str(item) for item in evidence]

    try:
        confidence = float(parsed["confidence"])
    except (TypeError, ValueError):
        raise ValueError("confidence is not a number") from None

    return {
        "regression_detected": bool(parsed.get("regression_detected", True)),
        "what_changed": str(parsed["what_changed"]).strip(),
        "what_broke": str(parsed["what_broke"]).strip(),
        "why": str(parsed["why"]).strip(),
        "evidence": evidence,
        "how_to_fix": str(parsed["how_to_fix"]).strip(),
        "confidence": min(max(confidence, 0.0), 1.0),
    }


def parse_finding(text: str) -> dict:
    try:
        parsed = json.loads(strip_code_fences(text))
    except json.JSONDecodeError as exc:
        raise ValueError(f"finding is not valid JSON: {exc}") from exc
    return normalize_finding(parsed)


def call_groq(model: str = None) -> dict:
    """
    One attempt against Groq's OpenAI-compatible chat completions endpoint.
    The prompt is supplied by the caller via _current_prompt (set in
    get_finding). Raises on any failure.
    """
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY is not set")

    resp = requests.post(
        GROQ_URL,
        headers={
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        json={
            "model": model or GROQ_MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": _current_prompt},
            ],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        },
        timeout=GROQ_TIMEOUT_S,
    )

    if resp.status_code >= 400:
        # Surface Groq's own error body — a bare "404 Not Found" hides whether
        # the endpoint, the model, or the API key's permissions are the cause.
        body = ""
        try:
            body = (resp.text or "")[:500]
        except Exception:  # noqa: BLE001 — logging must never mask the real error
            body = "<unreadable body>"
        raise RuntimeError(f"groq HTTP {resp.status_code}: {body}")

    payload = resp.json()
    try:
        text = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError(f"unexpected groq response shape: {payload}") from exc
    if not text:
        raise ValueError("groq returned empty content")
    return parse_finding(text)


# The user prompt for the analysis currently being run (set per request).
_current_prompt = ""


def _groq_models():
    """Primary model first, then any configured fallbacks (de-duplicated)."""
    models = [GROQ_MODEL]
    for model in GROQ_FALLBACK_MODELS:
        if model not in models:
            models.append(model)
    return models


def fallback_finding(head, baseline, ci, health, compare) -> dict:
    """
    Evidence-only summary used when Groq is unavailable. Every string is
    assembled from collected data — nothing is inferred or invented.
    """
    failing = ci.get("failing", [])
    files = compare.get("files", [])
    file_names = ", ".join(f["filename"] for f in files[:5]) or "no textual diff returned"
    evidence = []
    for f in failing:
        line = f"CI check failed: {f['name']}" + (f" — {f['title']}" if f["title"] else "")
        evidence.append(line)
    if health:
        if health["reachable"]:
            evidence.append(
                f"Health check {health['url']} returned HTTP {health['status_code']} "
                f"({health['latency_ms']}ms)"
            )
        else:
            evidence.append(f"Health check {health['url']} unreachable: {health['detail']}")
    for f in files:
        evidence.append(
            f"{f['filename']}: +{f['additions']}/-{f['deletions']} ({f['status']})"
        )
    base_desc = baseline["sha"][:7] if baseline else "the previous commit"
    return {
        "regression_detected": True,
        "what_changed": f"{len(files)} file(s) changed between {base_desc} and "
                        f"{head['sha'][:7]}: {file_names}",
        "what_broke": "; ".join(
            f["title"] or f["name"] for f in failing
        ) or (f"Health check failed (HTTP {health['status_code']})" if health and health["reachable"]
              else "Failure reported by CI or health check."),
        "why": "AI analysis unavailable — this summary lists the collected evidence only; "
               "no root cause was inferred.",
        "evidence": evidence or ["No evidence was collected."],
        "how_to_fix": f"Review the diff between {base_desc} and {head['sha'][:7]}, focusing on "
                      f"{file_names}; re-run the failing checks locally after fixing.",
        "confidence": 0.3,
    }


def get_finding(prompt: str, head, baseline, ci, health, compare) -> tuple:
    """
    Try Groq (primary model, then configured fallbacks), retry once, then use
    the evidence-only fallback. Returns (finding, source) where source is
    "groq" or "fallback"; the source is logged, never returned to the API.
    """
    global _current_prompt
    _current_prompt = prompt
    # Safe status logging: whether the Groq key is present, never its value.
    print(f"[finding] groq key: {'set' if GROQ_API_KEY else 'NOT SET'}")
    last_error = None
    for attempt in range(1, GROQ_MAX_ATTEMPTS + 1):
        for model in _groq_models():
            try:
                finding = call_groq(model)
                print(f"[finding] path=groq attempt={attempt} model={model}")
                return finding, "groq"
            except Exception as exc:  # noqa: BLE001 — any failure triggers retry/fallback
                last_error = exc
                print(f"[finding] groq attempt {attempt} model {model} failed: {exc}")
    print(f"[finding] path=fallback last_error={last_error}")
    return fallback_finding(head, baseline, ci, health, compare), "fallback"


# --------------------------------------------------------------------------- #
# FastAPI app + endpoints
# --------------------------------------------------------------------------- #

app = FastAPI(title="AI Fire Drill Backend")

# CORS: a React frontend calls this API from a different origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=False,
)


class AnalyzeRequest(BaseModel):
    repo_url: str
    branch: str = "main"
    health_url: Optional[str] = None
    max_commits: int = 10


def save_analysis(item: dict) -> bool:
    """
    Persist an analysis to DynamoDB. History is a nice-to-have: if the table is
    missing or DynamoDB is unreachable (e.g. running locally without AWS), log
    a warning and keep serving the report instead of failing the request.
    Returns True if stored.
    """
    try:
        _table().put_item(Item=item)
        return True
    except Exception as exc:  # noqa: BLE001 — history must never break analysis
        print(f"[history] save failed (analysis still returned): {type(exc).__name__}: {exc}")
        return False


@app.get("/status")
def status():
    """Service info — also used by the frontend as a reachability check."""
    return {
        "service": "ai-fire-drill",
        "version": "2.0",
        "mode": "commit-regression-analysis",
        "endpoints": ["/analyze", "/analyses", "/status"],
    }


@app.post("/analyze")
def analyze(body: AnalyzeRequest):
    """
    Full fire-drill: newest commit vs the newest commit whose CI passes,
    diff + CI + health evidence -> Groq WHAT/WHY/HOW report.
    """
    try:
        owner, repo = parse_repo_url(body.repo_url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    full_name = f"{owner}/{repo}"
    branch = (body.branch or "main").strip() or "main"
    max_commits = min(max(body.max_commits or 10, 2), 30)

    # 1. Commit history (newest first).
    commits = list_commits(owner, repo, branch, max_commits)
    head = commits[0]

    # 2. CI verdicts, newest first.
    ci_by_sha = {}
    for c in commits:
        ci_by_sha[c["sha"]] = commit_ci(owner, repo, c["sha"])
    head_ci = ci_by_sha[head["sha"]]

    # 3. Baseline = newest older commit with passing CI.
    baseline = next(
        (c for c in commits[1:] if ci_by_sha[c["sha"]]["state"] == "success"), None
    )
    baseline_verified = baseline is not None
    if baseline is None and len(head["parents"]) > 0:
        # No verified-good commit in the window: fall back to the direct parent
        # for the diff, flagged as unverified.
        parent_sha = head["parents"][0]
        baseline = next((c for c in commits[1:] if c["sha"] == parent_sha), None)
        if baseline is None and parent_sha:
            baseline = {
                "sha": parent_sha,
                "message": "(parent of head)",
                "author": "unknown",
                "author_date": "",
                "html_url": f"https://github.com/{full_name}/commit/{parent_sha}",
                "parents": [],
            }

    # 4. Health probe — supporting evidence only.
    health = probe_health((body.health_url or "").strip() or None)

    # 5. Decide whether a regression happened.
    caveats = []
    regression = None
    if head_ci["state"] == "failure":
        regression = True
    elif head_ci["state"] == "success":
        regression = False
    else:  # no CI verdict for head
        if health is None:
            regression = False
            caveats.append(
                "No CI checks found on the head commit and no health URL was provided — "
                "nothing could be verified."
            )
        elif health["ok"]:
            regression = False
            caveats.append("No CI checks found on the head commit; verdict is based on the health check only.")
        else:
            regression = True
            caveats.append("No CI checks found on the head commit; regression inferred from the failing health check.")
    if regression and not baseline_verified:
        caveats.append(
            "No commit with passing CI was found in the recent history — the diff is against "
            "the direct parent commit, which is unverified."
        )

    # 6. Diff between baseline and head.
    compare = {"files": [], "total_commits": 0, "capped": False}
    if baseline is not None:
        compare = fetch_compare(owner, repo, baseline["sha"], head["sha"])
    else:
        caveats.append("Could not determine any previous commit to diff against.")

    # 7. Groq WHAT/WHY/HOW from the evidence only.
    repo_ctx = {"full_name": full_name, "branch": branch}
    prompt = build_prompt(repo_ctx, head, baseline, head_ci, health, compare)
    finding, _source = get_finding(prompt, head, baseline, head_ci, health, compare)
    # The deterministic evidence check wins over the model's opinion.
    finding["regression_detected"] = regression

    analysis_id = f"AN-{uuid.uuid4().hex[:8]}"

    # 8. Persist the analysis (Decimal-safe at every level).
    # The deployed table's partition key is `incident_id`; keep storing new
    # analysis rows in the same table by mirroring the key attribute.
    item = to_dynamodb(
        {
            "analysis_id": analysis_id,
            "incident_id": analysis_id,
            "created_at": _now(),
            "repo": full_name,
            "branch": branch,
            "head_sha": head["sha"],
            "head_message": head["message"][:STORED_TEXT_CAP],
            "baseline_sha": baseline["sha"] if baseline else None,
            "baseline_verified": baseline_verified,
            "regression_detected": regression,
            "confidence": finding["confidence"],
            "what_changed": finding["what_changed"][:STORED_TEXT_CAP],
            "what_broke": finding["what_broke"][:STORED_TEXT_CAP],
            "why": finding["why"][:STORED_TEXT_CAP],
            "how_to_fix": finding["how_to_fix"][:STORED_TEXT_CAP],
            "status": "regression" if regression else "clean",
        }
    )
    stored = save_analysis(item)

    return {
        "analysis_id": analysis_id,
        "regression_detected": regression,
        "history_stored": stored,
        "repo": {
            "full_name": full_name,
            "owner": owner,
            "name": repo,
            "branch": branch,
            "url": f"https://github.com/{full_name}",
        },
        "commit": {
            "sha": head["sha"],
            "short": head["sha"][:7],
            "message": head["message"],
            "author": head["author"],
            "date": head["author_date"],
            "url": head["html_url"],
        },
        "previous_commit": (
            {
                "sha": baseline["sha"],
                "short": baseline["sha"][:7],
                "message": baseline["message"],
                "url": baseline.get("html_url", ""),
                "verified": baseline_verified,
            }
            if baseline
            else None
        ),
        "ci": {
            "state": head_ci["state"],
            "failing_checks": head_ci["failing"],
            "passing_checks": head_ci["passing"],
            "total_checks": head_ci["total"],
        },
        "health": health,
        "changed_files": compare["files"],
        "diff_capped": compare["capped"],
        "analysis": finding,
        "caveats": caveats,
    }


@app.get("/analyses")
def analyses():
    """Recent analyses, newest first (top 10). Degrades to an empty list."""
    try:
        resp = _table().scan(
            FilterExpression="begins_with(#id, :prefix)",
            ExpressionAttributeNames={"#id": "analysis_id"},
            ExpressionAttributeValues={":prefix": "AN-"},
        )
        items = [from_dynamodb(item) for item in resp.get("Items", [])]
    except Exception as exc:  # noqa: BLE001 — history must never break the UI
        print(f"[history] list failed: {type(exc).__name__}: {exc}")
        items = []
    items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return {"analyses": items[:10]}


# --------------------------------------------------------------------------- #
# Lambda adapter
# --------------------------------------------------------------------------- #

# SAM's default REST API never includes the stage ("/Prod") in the event path,
# so no api_gateway_base_path is needed — the FastAPI routes stay "/analyze",
# "/analyses", "/status".
handler = Mangum(app)
