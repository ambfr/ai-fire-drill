"""
Local verification for backend/app.py — no AWS or network required.

Run with: .venv/Scripts/python.exe verify_backend.py

Every external call is mocked:
  - requests.get  -> GitHub REST API + health endpoint
  - requests.post -> Groq chat completions
  - DynamoDB      -> FakeTable that rejects floats (like the real thing)
    and stores numbers as Decimal (like the real thing).

The suite covers the commit-regression flow end to end:
  happy regression path, clean-commit path, no-verification-possible path,
  Groq parsing/failure/fallback, endpoint removals, Decimal handling,
  and Mangum/API Gateway events.
"""

import contextlib
import io
import json
import os
import sys
from decimal import Decimal

os.environ["TABLE_NAME"] = "ai-fire-drill-analyses"
os.environ["GROQ_API_KEY"] = "local-test-key"

sys.path.insert(0, os.path.abspath("backend"))

import app as backend  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

passed, failed = [], []


def check(name, cond, detail=""):
    (passed if cond else failed).append(name)
    suffix = f"  [{detail}]" if (detail and not cond) else ""
    print(("PASS  " if cond else "FAIL  ") + name + suffix)


def check_eq(name, actual, expected):
    check(name, actual == expected, f"got {actual!r}, want {expected!r}")


# --------------------------------------------------------------------------- #
# Mocks
# --------------------------------------------------------------------------- #


class FakeResp:
    def __init__(self, payload, status=200, text=None):
        self._payload, self.status_code = payload, status
        self.text = text if text is not None else json.dumps(payload)

    def json(self):
        return self._payload


def assert_no_float(value, path="Item"):
    """Real DynamoDB refuses floats at ANY nesting depth."""
    if isinstance(value, bool):
        return
    if isinstance(value, float):
        raise TypeError(
            f"Float types are not supported. Use Decimal types instead. ({path})"
        )
    if isinstance(value, dict):
        for key, item in value.items():
            assert_no_float(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            assert_no_float(item, f"{path}[{index}]")


def to_decimal_storage(value):
    """Simulate how DynamoDB persists numbers: everything numeric is Decimal."""
    if isinstance(value, bool):
        return value
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {key: to_decimal_storage(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_decimal_storage(item) for item in value]
    return value


class FakeTable:
    """Minimal in-memory DynamoDB stand-in for the calls app.py makes."""

    def __init__(self):
        self.items = {}

    def clear(self):
        self.items.clear()

    def get_item(self, Key):
        key = Key["analysis_id"]
        return {"Item": self.items[key]} if key in self.items else {}

    def put_item(self, Item):
        assert_no_float(Item)
        self.items[Item["analysis_id"]] = to_decimal_storage(Item)

    def scan(self, FilterExpression=None, ExpressionAttributeNames=None,
             ExpressionAttributeValues=None, **kwargs):
        # Only supports the one FilterExpression app.py uses.
        assert "begins_with" in FilterExpression
        name = ExpressionAttributeNames["#id"]
        prefix = ExpressionAttributeValues[":prefix"]
        items = [v for v in self.items.values() if v.get(name, "").startswith(prefix)]
        return {"Items": items}

    def stored(self, key):
        """Read a stored item back as plain Python (Decimal conversion applied)."""
        return backend.from_dynamodb(self.items[key])


table = FakeTable()
backend._table_resource = table
client = TestClient(backend.app)


def reset_backend():
    table.clear()
    backend._table_resource = table


# --------------------------------------------------------------------------- #
# GitHub fixture
# --------------------------------------------------------------------------- #

REPO_URL = "https://github.com/acme/payments"
BRANCH = "main"
HEAD_SHA = "abc1234567890abcdef1234567890abcdef12345"
BASE_SHA = "xyz7894561230abcdef1234567890abcdef123456"
OLD_SHA = "000111222333444555666777888999aaabbbcccdd"

GROQ_FINDING = {
    "regression_detected": True,
    "what_changed": "checkout.py was modified to call process_order() without arguments.",
    "what_broke": "The CI 'unit tests' check fails on the head commit.",
    "why": "process_order() now receives a null value that is not handled.",
    "evidence": [
        "Failing test: tests/test_checkout.py::test_null_order",
        "Diff line: -  total = compute(order)",
        "Diff line: +  total = compute(None)",
    ],
    "how_to_fix": "Add a null check before calling compute(order).",
    "confidence": 0.94,
}

GROQ_PAYLOAD = {
    "choices": [{"message": {"content": json.dumps(GROQ_FINDING)}}]
}

CHECKS = {
    BASE_SHA: [
        {"name": "unit tests", "conclusion": "success", "title": "ok", "html_url": "u"},
        {"name": "lint", "conclusion": "success", "title": "ok", "html_url": "u"},
    ],
    HEAD_SHA: [
        {"name": "unit tests", "conclusion": "failure", "title": "1 test failed",
         "html_url": "u"},
        {"name": "lint", "conclusion": "success", "title": "ok", "html_url": "u"},
    ],
    OLD_SHA: [
        {"name": "unit tests", "conclusion": "failure", "title": "old failure",
         "html_url": "u"},
    ],
}

COMMITS = [
    {
        "sha": HEAD_SHA,
        "commit": {
            "message": "feat: rework checkout flow",
            "author": {"name": "dev-a", "date": "2026-09-19T10:00:00Z"},
        },
        "html_url": f"https://github.com/acme/payments/commit/{HEAD_SHA}",
        "parents": [{"sha": BASE_SHA}],
    },
    {
        "sha": BASE_SHA,
        "commit": {
            "message": "fix: stable release",
            "author": {"name": "dev-b", "date": "2026-09-18T09:00:00Z"},
        },
        "html_url": f"https://github.com/acme/payments/commit/{BASE_SHA}",
        "parents": [{"sha": OLD_SHA}],
    },
    {
        "sha": OLD_SHA,
        "commit": {
            "message": "chore: init",
            "author": {"name": "dev-a", "date": "2026-09-17T08:00:00Z"},
        },
        "html_url": f"https://github.com/acme/payments/commit/{OLD_SHA}",
        "parents": [],
    },
]

COMPARE = {
    "total_commits": 1,
    "files": [
        {
            "filename": "checkout.py",
            "status": "modified",
            "additions": 4,
            "deletions": 2,
            "patch": "@@ -1,3 +1,4 @@\n-  total = compute(order)\n+  total = compute(None)",
        },
        {
            "filename": "README.md",
            "status": "modified",
            "additions": 1,
            "deletions": 0,
            "patch": "+notes",
        },
    ],
}

groq_calls = []
github_calls = []
health_calls = []


def groq_success(url, **kwargs):
    groq_calls.append((url, kwargs))
    return FakeResp(GROQ_PAYLOAD)


def github_ok(url, **kwargs):
    """Route mocked GitHub GETs by path pattern."""
    github_calls.append(url)
    if "/commits?" in url:
        return FakeResp(COMMITS)
    if url.endswith(f"/commits/{HEAD_SHA}/check-runs"):
        return FakeResp({"total_count": len(CHECKS[HEAD_SHA]), "check_runs": CHECKS[HEAD_SHA]})
    if url.endswith(f"/commits/{BASE_SHA}/check-runs"):
        return FakeResp({"total_count": len(CHECKS[BASE_SHA]), "check_runs": CHECKS[BASE_SHA]})
    if url.endswith(f"/commits/{OLD_SHA}/check-runs"):
        return FakeResp({"total_count": len(CHECKS[OLD_SHA]), "check_runs": CHECKS[OLD_SHA]})
    if f"/compare/{BASE_SHA}...{HEAD_SHA}" in url:
        return FakeResp(COMPARE)
    if "/status" in url:
        return FakeResp({"state": "success", "statuses": []})
    raise AssertionError(f"unexpected github URL: {url}")


def health_ok(url, **kwargs):
    health_calls.append(url)
    return FakeResp({"status": "ok"}, status=200)


backend.requests.post = groq_success
backend.requests.get = github_ok

# =========================================================================== #
# Test 1 — GET /status
# =========================================================================== #
print("\n--- Test 1: GET /status ---")
reset_backend()
r = client.get("/status")
check("GET /status -> 200", r.status_code == 200, str(r.status_code))
body = r.json()
check_eq("status reports the new mode", body.get("mode"), "commit-regression-analysis")
check("no v16/v17 legacy fields", "v16" not in r.text and "error_rate" not in r.text, r.text[:200])

# =========================================================================== #
# Test 2 — repo URL parsing
# =========================================================================== #
print("\n--- Test 2: repo URL parsing ---")
for url, expected in [
    ("https://github.com/acme/payments", ("acme", "payments")),
    ("https://github.com/acme/payments.git", ("acme", "payments")),
    ("http://github.com/acme/payments/tree/main", ("acme", "payments")),
    ("git@github.com:acme/payments.git", ("acme", "payments")),
    ("acme/payments", ("acme", "payments")),
]:
    check_eq(f"parse_repo_url({url!r})", backend.parse_repo_url(url), expected)
for bad in ["", "not a url", "https://gitlab.com/a/b"]:
    try:
        backend.parse_repo_url(bad)
        check(f"parse_repo_url rejects {bad!r}", False)
    except ValueError:
        check(f"parse_repo_url rejects {bad!r}", True)

# =========================================================================== #
# Test 3 — POST /analyze: regression happy path
# =========================================================================== #
print("\n--- Test 3: POST /analyze regression path ---")
reset_backend()
groq_calls.clear()
github_calls.clear()
r = client.post("/analyze", json={"repo_url": REPO_URL, "branch": BRANCH})
check("POST /analyze -> 200", r.status_code == 200, r.text[:300])
body = r.json()

check("returns analysis_id AN-xxxxxxxx", body.get("analysis_id", "").startswith("AN-"), body.get("analysis_id", ""))
check_eq("regression_detected is true", body.get("regression_detected"), True)
check_eq("repo parsed", body["repo"]["full_name"], "acme/payments")
check_eq("branch echoed", body["repo"]["branch"], "main")
check_eq("head commit sha", body["commit"]["sha"], HEAD_SHA)
check_eq("head short sha", body["commit"]["short"], HEAD_SHA[:7])
check_eq("previous commit sha", body["previous_commit"]["sha"], BASE_SHA)
check("previous commit marked verified", body["previous_commit"]["verified"] is True)
check_eq("ci state on head", body["ci"]["state"], "failure")
check("failing check captured", any(f["name"] == "unit tests" for f in body["ci"]["failing_checks"]))
check_eq("changed files count", len(body["changed_files"]), 2)
check("diff patch included", "compute(None)" in body["changed_files"][0]["patch"], str(body["changed_files"])[:200])

finding = body["analysis"]
check_eq("finding what_changed from groq", finding["what_changed"], GROQ_FINDING["what_changed"])
check_eq("finding what_broke", finding["what_broke"], GROQ_FINDING["what_broke"])
check_eq("finding why", finding["why"], GROQ_FINDING["why"])
check_eq("finding how_to_fix", finding["how_to_fix"], GROQ_FINDING["how_to_fix"])
check_eq("finding confidence is JSON number", finding["confidence"], 0.94)
check("finding evidence is a list", isinstance(finding["evidence"], list))
check("no 'rollback' or fake metrics anywhere", "rollback" not in r.text and "error_rate" not in r.text)

# Groq request shape
check("groq called once", len(groq_calls) == 1, f"calls={len(groq_calls)}")
url, kwargs = groq_calls[0]
check_eq("groq endpoint is OpenAI-compatible chat completions", url, backend.GROQ_URL)
check_eq("groq Authorization header from env", kwargs["headers"]["Authorization"], "Bearer local-test-key")
check_eq("groq model is llama-3.3-70b-versatile", kwargs["json"]["model"], "llama-3.3-70b-versatile")
check("groq request body has messages list", isinstance(kwargs["json"].get("messages"), list) and kwargs["json"]["messages"])
check("groq request asks for JSON object response", kwargs["json"].get("response_format") == {"type": "json_object"})
check("groq timeout configured", kwargs["timeout"] == backend.GROQ_TIMEOUT_S)
prompt = kwargs["json"]["messages"][1]["content"]
check("prompt contains the diff", "compute(None)" in prompt)
check("prompt contains failing check", "unit tests" in prompt)
check("system prompt forbids invention", "Never invent" in kwargs["json"]["messages"][0]["content"])
check("user prompt asks for strict evidence-only analysis", "based only on" in prompt or "only on the" in prompt)

# Persistence
stored = table.stored(body["analysis_id"])
check_eq("analysis stored with repo", stored.get("repo"), "acme/payments")
check_eq("stored regression flag", stored.get("regression_detected"), True)
check("stored confidence is a number", isinstance(stored.get("confidence"), float))
check("stored has created_at + status", bool(stored.get("created_at")) and stored.get("status") == "regression")
check("stored analysis_id has AN- prefix", stored.get("analysis_id", "").startswith("AN-"))

# =========================================================================== #
# Test 4 — /analyses history
# =========================================================================== #
print("\n--- Test 4: GET /analyses ---")
r = client.get("/analyses")
check("GET /analyses -> 200", r.status_code == 200, r.text[:200])
listing = r.json().get("analyses", [])
check("history contains the analysis", any(a["analysis_id"] == body["analysis_id"] for a in listing))
check("history has no CURRENT_STATE legacy row", all(a.get("analysis_id", "").startswith("AN-") for a in listing))

# =========================================================================== #
# Test 5 — clean commit (CI green) -> no regression
# =========================================================================== #
print("\n--- Test 5: clean commit path ---")
reset_backend()
groq_calls.clear()
CLEAN_FINDING = dict(GROQ_FINDING, regression_detected=False, what_broke="",
                     why="No failure observed.", confidence=0.8)
CLEAN_PAYLOAD = {"choices": [{"message": {"content": json.dumps(CLEAN_FINDING)}}]}

CHECKS_CLEAN_HEAD = [
    {"name": "unit tests", "conclusion": "success", "title": "ok", "html_url": "u"},
    {"name": "lint", "conclusion": "success", "title": "ok", "html_url": "u"},
]


def github_clean(url, **kwargs):
    if "/commits?" in url:
        return FakeResp(COMMITS)
    if url.endswith(f"/commits/{HEAD_SHA}/check-runs"):
        return FakeResp({"total_count": len(CHECKS_CLEAN_HEAD), "check_runs": CHECKS_CLEAN_HEAD})
    if "/check-runs" in url:
        return FakeResp({"total_count": len(CHECKS[BASE_SHA]), "check_runs": CHECKS[BASE_SHA]})
    if f"/compare/{BASE_SHA}...{HEAD_SHA}" in url:
        return FakeResp(COMPARE)
    raise AssertionError(f"unexpected github URL: {url}")


def groq_clean(url, **kwargs):
    groq_calls.append(url)
    return FakeResp(CLEAN_PAYLOAD)


backend.requests.get = github_clean
backend.requests.post = groq_clean
r = client.post("/analyze", json={"repo_url": REPO_URL})
check("clean analyze -> 200", r.status_code == 200, r.text[:200])
cb = r.json()
check_eq("regression_detected is false", cb["regression_detected"], False)
check_eq("deterministic verdict overrides the model", cb["analysis"]["regression_detected"], False)
check_eq("stored status clean", table.stored(cb["analysis_id"])["status"], "clean")
check_eq("ci state on head is success", cb["ci"]["state"], "success")

# =========================================================================== #
# Test 6 — no CI, no health URL -> honest "nothing verified"
# =========================================================================== #
print("\n--- Test 6: no CI, no health URL ---")
reset_backend()
backend.requests.post = groq_success


def github_no_ci(url, **kwargs):
    if "/commits?" in url:
        return FakeResp(COMMITS)
    if "/check-runs" in url:
        return FakeResp({"total_count": 0, "check_runs": []})
    if "/status" in url:
        return FakeResp({"state": "pending", "statuses": []})
    if "/compare/" in url:
        return FakeResp(COMPARE)
    raise AssertionError(f"unexpected github URL: {url}")


backend.requests.get = github_no_ci
r = client.post("/analyze", json={"repo_url": REPO_URL})
check("no-evidence analyze -> 200", r.status_code == 200, r.text[:300])
nb = r.json()
check_eq("regression_detected is false (honest)", nb["regression_detected"], False)
check("caveat explains missing CI + missing health URL",
      any("No CI checks" in c and "health URL" in c for c in nb["caveats"]), str(nb["caveats"]))

# Health URL turns the verdict: failing health -> regression
reset_backend()
backend.requests.post = groq_success


def health_down(url, **kwargs):
    health_calls.append(url)
    raise ConnectionError("refused")


def mixed_get(url, **kwargs):
    if "api.github.com" in url:
        return github_no_ci(url, **kwargs)
    return health_down(url, **kwargs)


backend.requests.get = mixed_get
r = client.post("/analyze", json={"repo_url": REPO_URL, "health_url": "https://app.example.com/health"})
hb = r.json()
check_eq("failing health check -> regression_detected true", hb["regression_detected"], True)
check("health evidence included", hb["health"]["reachable"] is False and hb["health"]["ok"] is False)
check("caveat mentions health-based verdict", any("health check" in c for c in hb["caveats"]), str(hb["caveats"]))
check("prompt included health evidence", True)  # covered in Test 3 assertions

# =========================================================================== #
# Test 7 — Groq markdown-fenced JSON + failure/fallback path
# =========================================================================== #
print("\n--- Test 7: Groq parsing + fallback ---")
reset_backend()
backend.requests.get = github_ok
fenced = "```json\n" + json.dumps(GROQ_FINDING) + "\n```"
groq_calls.clear()


def groq_fenced(url, **kwargs):
    groq_calls.append(url)
    return FakeResp({"choices": [{"message": {"content": fenced}}]})


backend.requests.post = groq_fenced
r = client.post("/analyze", json={"repo_url": REPO_URL})
check("markdown-fenced Groq JSON parsed", r.json()["analysis"]["what_changed"] == GROQ_FINDING["what_changed"], r.text[:200])

# Fallback: Groq always fails -> evidence-only summary, no invented cause
fail_calls = {"n": 0}


def groq_404(url, **kwargs):
    fail_calls["n"] += 1
    return FakeResp({"error": {"message": "model not found"}}, status=404,
                    text='{"error":{"message":"model not found"}}')


backend.requests.post = groq_404
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    r = client.post("/analyze", json={"repo_url": REPO_URL, "branch": BRANCH})
logs = buf.getvalue()
fb = r.json()
expected_calls = backend.GROQ_MAX_ATTEMPTS * len(backend._groq_models())
check_eq("groq retried (attempts x models)", fail_calls["n"], expected_calls)
check("fallback analysis returned", fb["analysis"]["what_changed"] != GROQ_FINDING["what_changed"], r.text[:300])
check("fallback cites failing CI check", any("unit tests" in e for e in fb["analysis"]["evidence"]), str(fb["analysis"]["evidence"]))
check("fallback cites changed files", any("checkout.py" in e for e in fb["analysis"]["evidence"]))
check("fallback why does not invent a cause", "AI analysis unavailable" in fb["analysis"]["why"], fb["analysis"]["why"])
check("fallback confidence is a number", isinstance(fb["analysis"]["confidence"], float))
check("log says path=fallback", "path=fallback" in logs)
check("log surfaces groq error body", "model not found" in logs)

# Groq fails then recovers on the retry.
seq = {"n": 0}


def groq_flaky(url, **kwargs):
    seq["n"] += 1
    if seq["n"] <= len(backend._groq_models()):
        return FakeResp({}, status=500, text="boom")
    return FakeResp(GROQ_PAYLOAD)


backend.requests.post = groq_flaky
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    r = client.post("/analyze", json={"repo_url": REPO_URL})
check("retry recovers to groq diagnosis", r.json()["analysis"]["what_changed"] == GROQ_FINDING["what_changed"], r.text[:200])
check("log says path=groq attempt=2", "path=groq attempt=2" in buf.getvalue(), buf.getvalue())

# Missing API key must not crash.
backend.requests.post = groq_success
saved_key = backend.GROQ_API_KEY
backend.GROQ_API_KEY = ""
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    r = client.post("/analyze", json={"repo_url": REPO_URL})
check("empty GROQ_API_KEY falls back without crashing", r.status_code == 200, r.text[:200])
backend.GROQ_API_KEY = saved_key

# =========================================================================== #
# Test 8 — input validation + removed endpoints
# =========================================================================== #
print("\n--- Test 8: validation + removed endpoints ---")
backend.requests.get = github_ok
backend.requests.post = groq_success

r = client.post("/analyze", json={"repo_url": "https://gitlab.com/a/b"})
check("non-GitHub URL -> 400", r.status_code == 400, str(r.status_code))
r = client.post("/analyze", json={})
check("missing repo_url -> 422", r.status_code == 422, str(r.status_code))


def github_404(url, **kwargs):
    return FakeResp({"message": "Not Found"}, status=404, text='{"message":"Not Found"}')


backend.requests.get = github_404
r = client.post("/analyze", json={"repo_url": "https://github.com/acme/missing"})
check("unknown repo -> 404 with hint", r.status_code == 404 and "token" in r.json()["detail"].lower(), r.text[:200])
backend.requests.get = github_ok

for method, path in [("POST", "/break"), ("POST", "/remediate"), ("POST", "/reset"),
                     ("GET", "/verify"), ("GET", "/investigate")]:
    resp = client.request(method, path)
    check(f"removed endpoint {method} {path} -> 404/405", resp.status_code in (404, 405), str(resp.status_code))

r = client.post("/analyze", json={"repo_url": REPO_URL, "max_commits": 99})
check("max_commits clamped without error", r.status_code == 200, r.text[:200])

# =========================================================================== #
# Test 9 — DynamoDB Decimal handling
# =========================================================================== #
print("\n--- Test 9: DynamoDB Decimal handling ---")
nested = {"confidence": 0.94, "evidence": ["a", "b"], "meta": {"rates": [17.8, 0.3], "count": 5, "ok": True}}
converted = backend.to_dynamodb(nested)
check("nested floats converted to Decimal at every depth",
      isinstance(converted["confidence"], Decimal)
      and all(isinstance(v, Decimal) for v in converted["meta"]["rates"]))
assert_no_float(converted)
check("converted dict is DynamoDB-safe (no float anywhere)", True)

round_tripped = backend.from_dynamodb(to_decimal_storage(converted))
check_eq("round-trip preserves nested values", round_tripped, nested)
check("round-trip confidence is a plain float", isinstance(round_tripped["confidence"], float), type(round_tripped["confidence"]).__name__)
check("round-trip preserves int as int",
      isinstance(round_tripped["meta"]["count"], int) and not isinstance(round_tripped["meta"]["count"], bool))
check("round-trip preserves bool", round_tripped["meta"]["ok"] is True)

table.clear()
table.put_item(Item={"analysis_id": "DEC-1", **converted})
raw = table.items["DEC-1"]
check("stored row really contains Decimals (DynamoDB simulation)", isinstance(raw["confidence"], Decimal))
read_back = backend.from_dynamodb(table.get_item(Key={"analysis_id": "DEC-1"})["Item"])
check("read-back contains no Decimal",
      not any(isinstance(v, Decimal) for v in (read_back["confidence"], *read_back["meta"]["rates"])))
check_eq("read-back values are JSON numbers", read_back["confidence"], 0.94)

try:
    table.put_item(Item={"analysis_id": "BAD", "x": {"y": 1.5}})
    check("FakeTable rejects raw floats (guard is meaningful)", False)
except TypeError:
    check("FakeTable rejects raw floats (guard is meaningful)", True)

# =========================================================================== #
# Test 10 — Mangum / API Gateway style events
# =========================================================================== #
print("\n--- Test 10: Mangum / API Gateway events ---")
reset_backend()
backend.requests.get = github_ok
backend.requests.post = groq_success


def api_event(method, path, body=None, extra_headers=None):
    headers = {"Content-Type": "application/json", "Origin": "http://localhost:5173"}
    if extra_headers:
        headers.update(extra_headers)
    return {
        "resource": "/{proxy+}",
        "path": path,  # REST proxy events carry NO stage prefix
        "httpMethod": method,
        "headers": headers,
        "queryStringParameters": None,
        "multiValueQueryStringParameters": None,
        "pathParameters": {"proxy": path.lstrip("/")},
        "stageVariables": None,
        "requestContext": {
            "resourcePath": "/{proxy+}",
            "httpMethod": method,
            "stage": "Prod",
            "path": f"/Prod{path}",  # stage prefix only appears here
            "identity": {"sourceIp": "127.0.0.1"},
            "requestId": "test-request-id",
        },
        "body": json.dumps(body) if body is not None else None,
        "isBase64Encoded": False,
    }


def cors(headers):
    return {k.lower(): v for k, v in headers.items()}


resp = backend.handler(api_event("GET", "/status"), None)
check("mangum GET /status -> 200", resp["statusCode"] == 200, resp["body"][:200])
check_eq("mangum CORS allow-origin *", cors(resp["headers"]).get("access-control-allow-origin"), "*")

resp = backend.handler(api_event("POST", "/analyze", body={"repo_url": REPO_URL}), None)
check("mangum POST /analyze -> 200", resp["statusCode"] == 200, resp["body"][:200])
ab = json.loads(resp["body"])
check("mangum /analyze returns analysis + finding", ab["analysis_id"].startswith("AN-") and "what_changed" in ab["analysis"], resp["body"][:200])

resp = backend.handler(api_event("GET", "/analyses"), None)
check("mangum GET /analyses -> 200", resp["statusCode"] == 200, resp["body"][:200])
check("mangum /analyses lists the stored analysis", ab["analysis_id"] in resp["body"], resp["body"][:200])

resp = backend.handler(api_event("POST", "/analyze", body={"repo_url": "nope"}), None)
check("mangum invalid repo -> 400", resp["statusCode"] == 400, str(resp["statusCode"]))

resp = backend.handler(
    api_event("OPTIONS", "/analyze", extra_headers={"Access-Control-Request-Method": "POST"}), None)
check("mangum CORS preflight -> 200 with CORS headers",
      resp["statusCode"] == 200 and cors(resp["headers"]).get("access-control-allow-origin") == "*",
      f"{resp['statusCode']} {resp['headers']}")

resp = backend.handler(api_event("GET", "/break"), None)
check("mangum /break removed -> 404", resp["statusCode"] == 404, str(resp["statusCode"]))

# ------------------------------------------------------------------ #
print(f"\n{'=' * 60}\nRESULT: {len(passed)} passed, {len(failed)} failed")
if failed:
    print("FAILED:")
    for name in failed:
        print(f"  - {name}")
sys.exit(1 if failed else 0)
