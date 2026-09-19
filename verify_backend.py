"""
Local verification for backend/app.py — no AWS required.

Run with: .venv/Scripts/python.exe verify_backend.py

The DynamoDB stand-in is deliberately strict: `put_item` / `update_item` raise
TypeError if they ever see a `float` (exactly like real DynamoDB), and reads
come back as `Decimal`. That is what catches missing recursive conversion.
"""

import contextlib
import io
import json
import os
import sys
from decimal import Decimal

os.environ["TABLE_NAME"] = "ai-fire-drill-incidents"
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
        key = Key["incident_id"]
        # DynamoDB returns Decimals; return them that way to prove app.py
        # converts back before serializing the FastAPI response.
        return {"Item": self.items[key]} if key in self.items else {}

    def put_item(self, Item):
        assert_no_float(Item)
        self.items[Item["incident_id"]] = to_decimal_storage(Item)

    def update_item(self, Key, UpdateExpression, ExpressionAttributeNames,
                    ExpressionAttributeValues, **kwargs):
        assert_no_float(ExpressionAttributeValues, "ExpressionAttributeValues")
        item = self.items.setdefault(Key["incident_id"], {"incident_id": Key["incident_id"]})
        names = ExpressionAttributeNames or {}
        for part in UpdateExpression.split("SET", 1)[1].split(","):
            name, val = part.split("=", 1)
            name, val = name.strip(), val.strip()
            if name.startswith("#"):
                name = names[name]
            item[name] = to_decimal_storage(ExpressionAttributeValues[val])

    def stored(self, key):
        """Read a stored item back as plain Python (Decimal conversion applied)."""
        return backend.from_dynamodb(self.items[key])

    def stored_state(self):
        """CURRENT_STATE without its DynamoDB key — the API-facing shape."""
        item = self.stored("CURRENT_STATE").copy()
        item.pop("incident_id", None)
        return item


table = FakeTable()
backend._table_resource = table
client = TestClient(backend.app)


def reset_backend():
    table.clear()
    backend._table_resource = table


GROQ_CONTENT = json.dumps({
    "root_cause": "Groq: bad query in v17.",
    "confidence": 0.87,
    "evidence": ["errors spiked", "v17 shipped seconds earlier"],
    "recommended_action": "rollback",
    "target_version": "v16",
})
GROQ_PAYLOAD = {"choices": [{"message": {"content": GROQ_CONTENT}}]}

SPEC_FALLBACK = {
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

HEALTHY_DEFAULT = {"status": "healthy", "version": "v16", "error_rate": 0.3, "latency_ms": 83}
BROKEN_STATE = {"status": "broken", "version": "v17", "error_rate": 17.8, "latency_ms": 1842}
REMEDIATED_STATE = {"status": "healthy", "version": "v16", "error_rate": 0.2, "latency_ms": 91}

groq_calls = []


def groq_success(url, **kwargs):
    groq_calls.append((url, kwargs))
    return FakeResp(GROQ_PAYLOAD)


# =========================================================================== #
# Test 1 — GET /status
# =========================================================================== #
print("\n--- Test 1: GET /status ---")
reset_backend()
backend.requests.post = groq_success
r = client.get("/status")
check("GET /status -> 200", r.status_code == 200, str(r.status_code))
check_eq("status returns default healthy state", r.json(), HEALTHY_DEFAULT)

# =========================================================================== #
# Test 7 — Groq success path: request shape + markdown-fenced JSON parsing
# =========================================================================== #
print("\n--- Test 7: Groq success path ---")
fenced = "```json\n" + GROQ_CONTENT + "\n```"
groq_calls.clear()


def groq_success_fenced(url, **kwargs):
    groq_calls.append((url, kwargs))
    return FakeResp({"choices": [{"message": {"content": fenced}}]})


backend.requests.post = groq_success_fenced
r = client.get("/status")  # ensure clean; real call happens below
reset_backend()
r = client.post("/break")
body = r.json()
check("POST /break -> 200 (groq path)", r.status_code == 200, r.text[:200])
check("groq uses POST", len(groq_calls) == 1, f"calls={len(groq_calls)}")
url, kwargs = groq_calls[0]
check_eq("groq endpoint is OpenAI-compatible chat completions", url, backend.GROQ_URL)
check_eq("groq URL default is correct",
         backend.GROQ_URL, "https://api.groq.com/openai/v1/chat/completions")
check_eq("groq Authorization header from env",
         kwargs["headers"]["Authorization"], "Bearer local-test-key")
check_eq("groq Content-Type is application/json",
         kwargs["headers"]["Content-Type"], "application/json")
check_eq("groq model is llama-3.3-70b-versatile",
         kwargs["json"]["model"], "llama-3.3-70b-versatile")
check("groq request body has messages list",
      isinstance(kwargs["json"].get("messages"), list) and kwargs["json"]["messages"],
      str(kwargs["json"].get("messages"))[:120])
check("groq request asks for JSON object response",
      kwargs["json"].get("response_format") == {"type": "json_object"},
      str(kwargs["json"].get("response_format")))
check("groq timeout configured", kwargs["timeout"] == backend.GROQ_TIMEOUT_S)
check("markdown-fenced Groq JSON parsed", body["diagnosis"]["root_cause"] == "Groq: bad query in v17.")
check_eq("parsed confidence is a JSON number", body["diagnosis"]["confidence"], 0.87)
check("parsed evidence is a list", isinstance(body["diagnosis"]["evidence"], list))

# =========================================================================== #
# Test 2 — POST /break (broken state, incident, diagnosis, awaiting_approval)
# =========================================================================== #
print("\n--- Test 2: POST /break ---")
incident_id = body.get("incident_id", "")
check("break returns incident_id INC-xxxxxx",
      incident_id.startswith("INC-") and len(incident_id) == 10, incident_id)
check("break returns diagnosis immediately", isinstance(body.get("diagnosis"), dict))
check_eq("break response status", body.get("status"), "triggered")

state = client.get("/status").json()
check_eq("CURRENT_STATE is the deterministic broken state", state, BROKEN_STATE)
check_eq("broken state persisted in DynamoDB", table.stored_state(), BROKEN_STATE)

incident = table.stored(incident_id)
check_eq("incident status awaiting_approval", incident.get("status"), "awaiting_approval")
check_eq("incident stores root_cause", incident.get("root_cause"), "Groq: bad query in v17.")
check_eq("incident stores confidence as a number", float(incident.get("confidence")), 0.87)
check("incident stores evidence list", isinstance(incident.get("evidence"), list))
check_eq("incident service", incident.get("service"), "payment-api")
check("incident has created_at + diagnosed_at",
      bool(incident.get("created_at")) and bool(incident.get("diagnosed_at")))

# =========================================================================== #
# Test 3 — GET /verify shows broken state
# =========================================================================== #
print("\n--- Test 3: GET /verify (broken) ---")
r = client.get("/verify")
check("GET /verify -> 200", r.status_code == 200, str(r.status_code))
check_eq("verify shows broken state", r.json(), BROKEN_STATE)
check("verify numbers are plain JSON types (no Decimal leak)",
      isinstance(r.json()["error_rate"], float) and isinstance(r.json()["latency_ms"], int),
      str({k: type(v).__name__ for k, v in r.json().items()}))

# =========================================================================== #
# Test 4 — POST /remediate
# =========================================================================== #
print("\n--- Test 4: POST /remediate ---")
r = client.post("/remediate", json={"incident_id": incident_id, "action": "rollback"})
check("POST /remediate rollback -> 200", r.status_code == 200, r.text[:200])
check_eq("remediate reports resolved", r.json().get("status"), "resolved")
check_eq("incident marked resolved", table.stored(incident_id).get("status"), "resolved")
check("incident has resolved_at", bool(table.stored(incident_id).get("resolved_at")))
check_eq("CURRENT_STATE restored to remediated healthy", table.stored_state(), REMEDIATED_STATE)

# =========================================================================== #
# Test 5 — GET /verify shows healthy/remediated
# =========================================================================== #
print("\n--- Test 5: GET /verify (healthy/remediated) ---")
r = client.get("/verify")
check_eq("verify shows healthy remediated state", r.json(), REMEDIATED_STATE)

# =========================================================================== #
# Test 6 — POST /reset
# =========================================================================== #
print("\n--- Test 6: POST /reset ---")
r = client.post("/reset")
check("POST /reset -> 200", r.status_code == 200, r.text[:200])
check_eq("reset response", r.json(), {"status": "reset"})
check_eq("CURRENT_STATE back to default healthy", table.stored_state(), HEALTHY_DEFAULT)
check_eq("GET /verify after reset", client.get("/verify").json(), HEALTHY_DEFAULT)

# =========================================================================== #
# Test 8 — Groq failure path -> exact fallback returned AND stored
# =========================================================================== #
print("\n--- Test 8: Groq failure fallback ---")
reset_backend()
check_eq("hardcoded fallback matches spec exactly", backend.FALLBACK_DIAGNOSIS, SPEC_FALLBACK)

fail_calls = {"n": 0}


def groq_404(url, **kwargs):
    fail_calls["n"] += 1
    return FakeResp({"error": {"message": "model not found"}}, status=404,
                    text='{"error":{"message":"model not found"}}')


backend.requests.post = groq_404
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    r = client.post("/break")
logs = buf.getvalue()
fb_body = r.json()
expected_calls = backend.GROQ_MAX_ATTEMPTS * len(backend._groq_models())
check_eq("groq retried (attempts x models)", fail_calls["n"], expected_calls)
check_eq("fallback diagnosis returned exactly", fb_body["diagnosis"], SPEC_FALLBACK)
check("failed incident stored with fallback diagnosis",
      table.stored(fb_body["incident_id"])["root_cause"] == SPEC_FALLBACK["root_cause"])
check_eq("fallback confidence stored as number",
         float(table.stored(fb_body["incident_id"])["confidence"]), 0.91)
check("log says path=fallback", "path=fallback" in logs)
check("log surfaces groq error body", "model not found" in logs)
check("debug path not exposed in API response",
      "path" not in fb_body and "path" not in fb_body["diagnosis"])

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
    r = client.post("/break")
check("retry recovers to groq diagnosis",
      r.json()["diagnosis"]["root_cause"] == "Groq: bad query in v17.", r.text[:200])
check("log says path=groq attempt=2", "path=groq attempt=2" in buf.getvalue(), buf.getvalue())

# Missing API key must not crash the demo.
backend.requests.post = groq_success
saved_key = backend.GROQ_API_KEY
backend.GROQ_API_KEY = ""
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    r = client.post("/break")
check("empty GROQ_API_KEY falls back without crashing",
      r.status_code == 200 and r.json()["diagnosis"] == SPEC_FALLBACK, r.text[:200])
backend.GROQ_API_KEY = saved_key

# =========================================================================== #
# Test 9 — DynamoDB Decimal handling (nested floats)
# =========================================================================== #
print("\n--- Test 9: DynamoDB Decimal handling ---")
nested = {
    "confidence": 0.91,
    "evidence": ["a", "b"],
    "meta": {"rates": [17.8, 0.3], "count": 5, "ok": True},
}
converted = backend.to_dynamodb(nested)
check("nested floats converted to Decimal at every depth",
      all(isinstance(converted[k], Decimal) for k in ("confidence",)) and
      all(isinstance(v, Decimal) for v in converted["meta"]["rates"]))
assert_no_float(converted)
check("converted dict is DynamoDB-safe (no float anywhere)", True)

round_tripped = backend.from_dynamodb(to_decimal_storage(converted))
check_eq("round-trip preserves nested values", round_tripped, nested)
check("round-trip confidence is a plain float",
      isinstance(round_tripped["confidence"], float), type(round_tripped["confidence"]).__name__)
check("round-trip preserves int as int",
      isinstance(round_tripped["meta"]["count"], int)
      and not isinstance(round_tripped["meta"]["count"], bool))
check("round-trip preserves bool", round_tripped["meta"]["ok"] is True)

table.clear()
table.put_item(Item={"incident_id": "DEC-1", **converted})
raw = table.items["DEC-1"]
check("stored row really contains Decimals (DynamoDB simulation)",
      isinstance(raw["confidence"], Decimal))
read_back = backend.from_dynamodb(table.get_item(Key={"incident_id": "DEC-1"})["Item"])
check("read-back contains no Decimal",
      not any(isinstance(v, Decimal) for v in (read_back["confidence"], *read_back["meta"]["rates"])))
check_eq("read-back values are JSON numbers", read_back["confidence"], 0.91)

try:
    table.put_item(Item={"incident_id": "BAD", "x": {"y": 1.5}})
    check("FakeTable rejects raw floats (guard is meaningful)", False)
except TypeError:
    check("FakeTable rejects raw floats (guard is meaningful)", True)

# API responses must be JSON-serializable with no Decimal objects.
for path in ("/status", "/verify"):
    r = client.get(path)
    check(f"{path} response serializes to JSON numbers",
          "Decimal" not in r.text and isinstance(r.json()["error_rate"], float), r.text[:120])

# =========================================================================== #
# Test 10 — Mangum / API Gateway style events for all routes
# =========================================================================== #
print("\n--- Test 10: Mangum / API Gateway events ---")
reset_backend()
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
check_eq("mangum CORS allow-origin *",
         cors(resp["headers"]).get("access-control-allow-origin"), "*")
check_eq("mangum /status body", json.loads(resp["body"]), HEALTHY_DEFAULT)

resp = backend.handler(api_event("POST", "/break"), None)
check("mangum POST /break -> 200", resp["statusCode"] == 200, resp["body"][:200])
break_body = json.loads(resp["body"])
check("mangum /break returns incident_id + diagnosis",
      break_body["incident_id"].startswith("INC-") and isinstance(break_body["diagnosis"], dict),
      resp["body"][:200])

resp = backend.handler(api_event("GET", "/verify"), None)
check("mangum GET /verify -> 200", resp["statusCode"] == 200, resp["body"][:200])
check_eq("mangum /verify shows broken state", json.loads(resp["body"]), BROKEN_STATE)

resp = backend.handler(
    api_event("POST", "/remediate",
              body={"incident_id": break_body["incident_id"], "action": "rollback"}), None)
check("mangum POST /remediate -> 200", resp["statusCode"] == 200, resp["body"][:200])
check_eq("mangum /remediate resolved", json.loads(resp["body"])["status"], "resolved")

resp = backend.handler(api_event("POST", "/remediate", body={"action": "nope"}), None)
check("mangum invalid action -> 400", resp["statusCode"] == 400, str(resp["statusCode"]))

resp = backend.handler(api_event("POST", "/remediate", body={"action": "reset"}), None)
check("mangum accepts reset action -> 200", resp["statusCode"] == 200, str(resp["statusCode"]))

resp = backend.handler(api_event("POST", "/reset"), None)
check("mangum POST /reset -> 200", resp["statusCode"] == 200, resp["body"][:200])

resp = backend.handler(
    api_event("OPTIONS", "/remediate", extra_headers={"Access-Control-Request-Method": "POST"}), None)
check("mangum CORS preflight -> 200 with CORS headers",
      resp["statusCode"] == 200 and cors(resp["headers"]).get("access-control-allow-origin") == "*",
      f"{resp['statusCode']} {resp['headers']}")

resp = backend.handler(api_event("GET", "/investigate"), None)
check("removed /investigate route -> 404", resp["statusCode"] == 404, str(resp["statusCode"]))

# ------------------------------------------------------------------ #
print(f"\n{'=' * 60}\nRESULT: {len(passed)} passed, {len(failed)} failed")
if failed:
    print("FAILED:")
    for name in failed:
        print(f"  - {name}")
sys.exit(1 if failed else 0)
