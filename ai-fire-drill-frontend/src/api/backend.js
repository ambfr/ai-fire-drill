// backend.js
// ---------------------------------------------------------------------------
// This module is the ONLY place that talks to the AI Fire Drill backend.
// Every component calls the functions below and never touches fetch()
// directly. The API base URL comes from VITE_API_BASE_URL (see .env).
//
// Endpoints (commit-regression analyzer):
//   GET  /status    -> service info
//   POST /analyze   -> { repo_url, branch?, health_url? } -> full report
//   GET  /analyses  -> recent analysis history
// ---------------------------------------------------------------------------

// Deployed backend (AWS API Gateway). Override via VITE_API_BASE_URL in .env.
const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ||
  "https://6i7esellna.execute-api.ap-south-1.amazonaws.com/Prod";

async function request(path, options = {}) {
  const res = await fetch(`${API_BASE_URL}${path}`, options);
  let body = null;
  try {
    body = await res.json();
  } catch {
    // non-JSON response (e.g. gateway error page) — fall through to !res.ok
  }
  if (!res.ok) {
    const detail = body?.detail ?? body?.message ?? res.statusText;
    throw new Error(`API ${res.status}: ${detail}`);
  }
  return body;
}

// ---- GET /status ----------------------------------------------------------
// -> { service, version, mode, endpoints }
export async function getStatus() {
  return request("/status");
}

// ---- POST /analyze ---------------------------------------------------------
// Body: { repo_url, branch = "main", health_url? }
// Runs the whole fire-drill server-side and returns:
// { analysis_id, regression_detected, repo{full_name,branch,url},
//   commit{sha,short,message,author,date,url},
//   previous_commit{sha,short,message,url,verified} | null,
//   ci{state,failing_checks,passing_checks,total_checks},
//   health{url,reachable,ok,status_code,latency_ms,detail} | null,
//   changed_files[{filename,status,additions,deletions,patch,patch_capped}],
//   analysis{regression_detected,what_changed,what_broke,why,evidence,
//            how_to_fix,confidence},
//   caveats[] }
export async function analyzeRepo({ repoUrl, branch = "main", healthUrl = null }) {
  return request("/analyze", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ repo_url: repoUrl, branch, health_url: healthUrl }),
  });
}

// ---- GET /analyses ----------------------------------------------------------
// -> { analyses: [{ analysis_id, created_at, repo, head_sha, status, ... }] }
export async function listAnalyses() {
  return request("/analyses");
}
