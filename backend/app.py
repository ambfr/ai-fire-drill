"""
AI Fire Drill — unified backend (FastAPI on AWS Lambda via Mangum).

One Lambda function serves every endpoint through API Gateway's proxy.
State lives in a single DynamoDB table (partition key: incident_id):
  - The CURRENT_STATE item holds the simulated app status/version/metrics.
  - Each break triggers an incident record (INC-xxxxxxxx) with its diagnosis.

Diagnosis is produced by Groq's OpenAI-compatible chat API
(https://api.groq.com/openai/v1/chat/completions). If the call fails after a
retry (and after trying the configured fallback models), a hardcoded diagnosis
is used so the demo never crashes.

DynamoDB only accepts `Decimal` (never `float`), at any nesting depth, and
returns `Decimal` values on reads. Every value crossing that boundary goes
through `to_dynamodb` / `from_dynamodb` so nothing leaks either way.
"""

import json
import os
import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

import boto3
import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from mangum import Mangum
from pydantic import BaseModel

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

TABLE_NAME = os.environ.get("TABLE_NAME", "ai-fire-drill-incidents").strip()

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

HEALTHY_DEFAULT = {
    "status": "healthy",
    "version": "v16",
    "error_rate": 0.3,
    "latency_ms": 83,
}
HEALTHY_AFTER_REMEDIATION = {
    "status": "healthy",
    "version": "v16",
    "error_rate": 0.2,
    "latency_ms": 91,
}
BROKEN_STATE = {
    "status": "broken",
    "version": "v17",
    "error_rate": 17.8,
    "latency_ms": 1842,
}

CURRENT_STATE_KEY = "CURRENT_STATE"
ALLOWED_ACTIONS = {"rollback", "reset"}
DIAGNOSIS_FIELDS = (
    "root_cause",
    "confidence",
    "evidence",
    "recommended_action",
    "target_version",
)

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


def get_current_state() -> dict:
    """Return the CURRENT_STATE item, or the default healthy values if absent."""
    item = _table().get_item(Key={"incident_id": CURRENT_STATE_KEY}).get("Item")
    if not item:
        return dict(HEALTHY_DEFAULT)
    item = from_dynamodb(item)  # Decimal -> int/float before it reaches FastAPI
    return {
        "status": item.get("status", HEALTHY_DEFAULT["status"]),
        "version": item.get("version", HEALTHY_DEFAULT["version"]),
        "error_rate": item.get("error_rate", HEALTHY_DEFAULT["error_rate"]),
        "latency_ms": item.get("latency_ms", HEALTHY_DEFAULT["latency_ms"]),
    }


def put_current_state(values: dict) -> None:
    """Overwrite the CURRENT_STATE item with `values` (converted for DynamoDB)."""
    item = {"incident_id": CURRENT_STATE_KEY}
    item.update(to_dynamodb(values))
    _table().put_item(Item=item)


# --------------------------------------------------------------------------- #
# Groq diagnosis (OpenAI-compatible chat completions)
# --------------------------------------------------------------------------- #

FALLBACK_DIAGNOSIS = {
    "root_cause": "Deployment v17 introduced a malformed database query.",
    "confidence": 0.91,
    "evidence": [
        "Error rate rose from 0.3% to 17.8% immediately after deployment.",
        "Latency increased from 83ms to 1842ms in the same window.",
        "Database infrastructure health checks remain green.",
        "Malformed query errors dominate the application logs.",
    ],
    "recommended_action": "rollback",
    "target_version": "v16",
}

SYSTEM_PROMPT = (
    "You are an expert AI Incident Commander for production services. "
    "You always reply with a single valid JSON object and nothing else — "
    "no markdown, no code fences, no commentary."
)


def _groq_models():
    """Primary model first, then any configured fallbacks (de-duplicated)."""
    models = [GROQ_MODEL]
    for model in GROQ_FALLBACK_MODELS:
        if model not in models:
            models.append(model)
    return models


def build_prompt() -> str:
    evidence = {
        "error_rate": 17.8,
        "latency_ms": 1842,
        "current_version": "v17",
        "previous_version": "v16",
        "database": "healthy",
        "log_error": "Malformed database query",
    }
    return (
        "Diagnose the incident based ONLY on the evidence below.\n"
        "Respond with ONLY a JSON object (no markdown, no prose) with fields:\n"
        "root_cause (string), confidence (number 0-1), evidence (array of strings), "
        "recommended_action (one of 'rollback' or 'reset'), target_version (string).\n\n"
        f"Evidence: {json.dumps(evidence)}"
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


def normalize_diagnosis(parsed) -> dict:
    """
    Validate/coerce a parsed diagnosis into the exact required shape so we never
    store or return a partial/oddly-typed object. Raises on unusable input.
    """
    if not isinstance(parsed, dict):
        raise ValueError("diagnosis is not a JSON object")
    for field in DIAGNOSIS_FIELDS:
        if field not in parsed:
            raise ValueError(f"missing field: {field}")

    evidence = parsed["evidence"]
    if isinstance(evidence, str):
        evidence = [evidence]
    elif not isinstance(evidence, (list, tuple)):
        evidence = [str(evidence)]
    evidence = [str(item) for item in evidence]
    if not evidence:
        raise ValueError("evidence is empty")

    try:
        confidence = float(parsed["confidence"])
    except (TypeError, ValueError):
        raise ValueError("confidence is not a number")

    action = str(parsed["recommended_action"]).strip().lower()
    if action not in ALLOWED_ACTIONS:
        # Keep the diagnosis actionable: only rollback/reset are ever executed.
        action = "rollback"

    return {
        "root_cause": str(parsed["root_cause"]).strip(),
        "confidence": min(max(confidence, 0.0), 1.0),
        "evidence": evidence,
        "recommended_action": action,
        "target_version": str(parsed["target_version"]).strip(),
    }


def parse_diagnosis(text: str) -> dict:
    """Parse the model's text into a validated diagnosis dict."""
    try:
        parsed = json.loads(strip_code_fences(text))
    except json.JSONDecodeError as exc:
        raise ValueError(f"diagnosis is not valid JSON: {exc}") from exc
    return normalize_diagnosis(parsed)


def call_groq(model: str = None) -> dict:
    """
    One attempt against Groq's OpenAI-compatible chat completions endpoint.
    Raises on any failure (network, HTTP status, parse, validation).
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
                {"role": "user", "content": build_prompt()},
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
    return parse_diagnosis(text)


def get_diagnosis() -> dict:
    """
    Try Groq (primary model, then configured fallbacks), retry once, then fall
    back to the hardcoded diagnosis. Logs which path answered (groq/fallback);
    the log line is internal only and never included in the API response.
    """
    last_error = None
    for attempt in range(1, GROQ_MAX_ATTEMPTS + 1):
        for model in _groq_models():
            try:
                diagnosis = call_groq(model)
                print(f"[diagnosis] path=groq attempt={attempt} model={model}")
                return diagnosis
            except Exception as exc:  # noqa: BLE001 — any failure triggers retry/fallback
                last_error = exc
                print(
                    f"[diagnosis] groq attempt {attempt} model {model} failed: {exc}"
                )
    print(f"[diagnosis] path=fallback last_error={last_error}")
    return dict(FALLBACK_DIAGNOSIS)


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


class RemediateRequest(BaseModel):
    incident_id: Optional[str] = None
    action: str


@app.get("/status")
def status():
    """Current app state; defaults to healthy if nothing has been written yet."""
    return get_current_state()


@app.get("/verify")
def verify():
    """Same payload as /status — confirms recovery after remediation."""
    return get_current_state()


@app.post("/break")
def break_production():
    """
    Deterministically break the simulated app and diagnose it synchronously.
    Returns incident_id + diagnosis immediately; the UI never waits on
    CloudWatch/EventBridge timing.
    """
    incident_id = f"INC-{uuid.uuid4().hex[:6]}"

    # 1. Flip CURRENT_STATE to broken
    put_current_state(BROKEN_STATE)

    # 2. Create the incident record
    _table().put_item(
        Item=to_dynamodb(
            {
                "incident_id": incident_id,
                "service": "payment-api",
                "created_at": _now(),
                "status": "investigating",
                "failure_type": "deployment_regression",
            }
        )
    )

    # 3. Diagnose via Groq (with retry, model fallback, then hardcoded fallback)
    diagnosis = get_diagnosis()

    # 4. Store diagnosis on the incident and mark it awaiting approval
    _table().update_item(
        Key={"incident_id": incident_id},
        UpdateExpression=(
            "SET root_cause = :rc, confidence = :c, evidence = :e, "
            "recommended_action = :ra, target_version = :tv, "
            "#s = :s, diagnosed_at = :da"
        ),
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues=to_dynamodb(
            {
                ":rc": diagnosis["root_cause"],
                ":c": diagnosis["confidence"],
                ":e": diagnosis["evidence"],
                ":ra": diagnosis["recommended_action"],
                ":tv": diagnosis["target_version"],
                ":s": "awaiting_approval",
                ":da": _now(),
            }
        ),
    )

    return {"incident_id": incident_id, "status": "triggered", "diagnosis": diagnosis}


@app.post("/remediate")
def remediate(body: RemediateRequest):
    """Validate the action, restore healthy state, mark the incident resolved."""
    action = (body.action or "").strip().lower()
    if action not in ALLOWED_ACTIONS:
        raise HTTPException(status_code=400, detail="action not allowed")

    # Revert the simulated application state to healthy
    put_current_state(HEALTHY_AFTER_REMEDIATION)

    # Mark the incident resolved (if an incident_id was supplied)
    if body.incident_id:
        _table().update_item(
            Key={"incident_id": body.incident_id},
            UpdateExpression="SET #s = :s, resolved_at = :r",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues=to_dynamodb(
                {":s": "resolved", ":r": _now()}
            ),
        )

    return {
        "incident_id": body.incident_id,
        "status": "resolved",
        "action": action,
        "version": "v16",
        "state": get_current_state(),
    }


@app.post("/reset")
def reset():
    """Reset CURRENT_STATE to the default healthy values."""
    put_current_state(HEALTHY_DEFAULT)
    return {"status": "reset"}


# --------------------------------------------------------------------------- #
# Lambda adapter
# --------------------------------------------------------------------------- #

# SAM's default REST API never includes the stage ("/Prod") in the event path,
# so no api_gateway_base_path is needed — the FastAPI routes stay "/status",
# "/break", etc.
handler = Mangum(app)
