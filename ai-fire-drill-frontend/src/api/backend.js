// backend.js
// -----------------------------------------------------------------------
// This module is the ONLY place that knows whether we're talking to a real
// AWS API Gateway URL or a fully in-browser mock. Every component calls
// the functions below (e.g. breakProduction()) and never touches fetch()
// or the mock data directly. When Dev A's API is ready, flip USE_MOCK to
// false and set API_BASE_URL — nothing else in the app needs to change.
// -----------------------------------------------------------------------

const USE_MOCK = true;
const API_BASE_URL = "https://YOUR-API-ID.execute-api.ap-south-1.amazonaws.com/prod";

const delay = (ms) => new Promise((res) => setTimeout(res, ms));

// ---- Mock state -------------------------------------------------------
let mockState = {
  status: "healthy",
  version: "v16",
  error_rate: 0.3,
  latency_ms: 83,
  incident_id: null,
};

function resetMockState() {
  mockState = {
    status: "healthy",
    version: "v16",
    error_rate: 0.3,
    latency_ms: 83,
    incident_id: null,
  };
}

// ---- GET /status --------------------------------------------------------
export async function getStatus() {
  if (USE_MOCK) {
    await delay(200);
    return {
      status: mockState.status,
      version: mockState.version,
      error_rate: mockState.error_rate,
      latency_ms: mockState.latency_ms,
    };
  }
  const res = await fetch(`${API_BASE_URL}/status`);
  return res.json();
}

// ---- POST /break ----------------------------------------------------
// Per the design doc, this endpoint MUST deterministically create the
// incident and return immediately — the UI never waits on CloudWatch or
// EventBridge to "notice" anything.
export async function breakProduction() {
  if (USE_MOCK) {
    await delay(250);
    mockState.status = "broken";
    mockState.version = "v17";
    mockState.error_rate = 17.8;
    mockState.latency_ms = 1842;
    mockState.incident_id = "INC-001";
    return { incident_id: "INC-001", status: "triggered" };
  }
  const res = await fetch(`${API_BASE_URL}/break`, { method: "POST" });
  return res.json();
}

// ---- POST /investigate --------------------------------------------------
// Returns the structured Bedrock diagnosis shape from the design doc.
export async function investigate(incidentId) {
  if (USE_MOCK) {
    await delay(900);
    return {
      root_cause: "Deployment v17 introduced a malformed database query.",
      confidence: 0.91,
      evidence: [
        "Error rate rose from 0.3% to 17.8% immediately after deployment.",
        "Latency increased from 83ms to 1842ms in the same window.",
        "Deployment v17 was pushed immediately before the errors began.",
        "Database infrastructure health checks remain green.",
        "Malformed query errors dominate the application logs.",
      ],
      recommended_action: "rollback",
      target_version: "v16",
    };
  }
  const res = await fetch(`${API_BASE_URL}/investigate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ incident_id: incidentId }),
  });
  return res.json();
}

// ---- POST /remediate ------------------------------------------------
export async function remediate(incidentId, targetVersion) {
  if (USE_MOCK) {
    await delay(700);
    mockState.status = "recovering";
    mockState.version = targetVersion;
    return { incident_id: incidentId, status: "remediating" };
  }
  const res = await fetch(`${API_BASE_URL}/remediate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      incident_id: incidentId,
      action: "rollback",
      target_version: targetVersion,
    }),
  });
  return res.json();
}

// ---- GET /verify ------------------------------------------------------
export async function verify() {
  if (USE_MOCK) {
    await delay(500);
    mockState.status = "healthy";
    mockState.error_rate = 0.2;
    mockState.latency_ms = 91;
    return {
      status: "healthy",
      version: mockState.version,
      error_rate: mockState.error_rate,
      latency_ms: mockState.latency_ms,
    };
  }
  const res = await fetch(`${API_BASE_URL}/verify`);
  return res.json();
}

// ---- POST /reset --------------------------------------------------------
export async function resetDemo() {
  if (USE_MOCK) {
    await delay(150);
    resetMockState();
    return { status: "reset" };
  }
  const res = await fetch(`${API_BASE_URL}/reset`, { method: "POST" });
  return res.json();
}
