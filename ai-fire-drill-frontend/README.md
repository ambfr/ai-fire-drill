# AI Fire Drill — Commit Regression Analyzer

> **"Your latest push broke the application. Here's the change that caused it,
> why it caused the failure, the evidence, and how to fix it."**

AI Fire Drill takes a GitHub repository, inspects the newest commit against the
last known-good commit, gathers evidence (code diff, CI check results, optional
health endpoint), and produces a **WHAT changed / WHY it broke / HOW to fix it**
report — strictly from that evidence. Nothing is broken on purpose, nothing is
invented.

## What it does

```text
Working application
      ↓
New GitHub commit
      ↓
AI Fire Drill checks the new commit
      ↓
Compare previous working commit vs new commit
      ↓
Check tests (CI) / provided health endpoint
      ↓
If regression detected:
      ↓
WHAT changed? · WHY did it break? · HOW to fix it?
```

- **Primary evidence**: GitHub commit history, the commit diff, CI check-runs
- **Supporting evidence**: an optional deployed health URL (HTTP status + latency)
- **No fake metrics**: v16/v17, error_rate/latency dashboards, `/break`,
  rollback flows — all removed

## Repository layout

```
backend/                  FastAPI + Mangum Lambda (commit regression analyzer)
template.yaml             SAM template (API Gateway + Lambda + DynamoDB)
verify_backend.py         Local test suite — no AWS or network required
ai-fire-drill-frontend/   Vite + React mission-control UI
```

## Backend

Endpoints:

| Method | Path         | Purpose                                            |
|--------|--------------|----------------------------------------------------|
| GET    | `/status`    | Service info / reachability check                  |
| POST   | `/analyze`   | Run the full fire drill for `repo_url` (+ branch)  |
| GET    | `/analyses`  | Recent analysis history (top 10)                   |

`POST /analyze` request:

```json
{
  "repo_url": "https://github.com/owner/repo",
  "branch": "main",
  "health_url": "https://your-app.example.com/health"
}
```

Response highlights: `regression_detected`, `commit`, `previous_commit`
(with `verified` flag), `ci` (failing check names + titles), `health`,
`changed_files` (with patches), and `analysis` containing `what_changed`,
`what_broke`, `why`, `evidence[]`, `how_to_fix`, `confidence`.

Verdict logic (deterministic, the model cannot override it):

- Head commit CI **failed** → regression
- Head commit CI **passed** → no regression
- **No CI** → health check decides; with neither, the report says honestly
  that nothing could be verified (and says so via `caveats`)
- Baseline = newest older commit whose CI passes; if none exists, the direct
  parent is used and flagged as unverified

The AI (Groq) only explains the evidence — its system prompt forbids
inventing logs, metrics, or causes. If Groq is unavailable, the API returns an
evidence-only summary assembled from the collected data, never a fabricated
root cause.

Environment variables: `TABLE_NAME`, `GROQ_API_KEY`, `GROQ_MODEL`,
`GROQ_FALLBACK_MODELS`, `GITHUB_TOKEN` (optional — higher rate limits and
private repos), `GITHUB_TIMEOUT_S`, `GROQ_TIMEOUT_S`, `HEALTH_TIMEOUT_S`.

## Frontend

```bash
cd ai-fire-drill-frontend
npm install
npm run dev
```

Set the backend URL in `ai-fire-drill-frontend/.env`:

```
VITE_API_BASE_URL=https://your-api.execute-api.region.amazonaws.com/Prod
```

Structure:

- `src/api/backend.js` — the only file that talks to the API
- `src/components/RepoForm.jsx` — repo URL + branch + optional health URL,
  **Analyze Latest Commit · Run Fire Drill** button
- `src/components/Timeline.jsx` — 6-step investigation checklist
- `src/components/ResultPanel.jsx` — verdict header (commit / previous commit /
  confidence), WHAT CHANGED / WHAT BROKE / WHY / EVIDENCE / HOW TO FIX,
  caveats, failing-check links
- `src/components/EventStream.jsx` — terminal-style event log

## Local verification (nothing is deployed)

```bash
# Backend tests (mocks GitHub, Groq, health endpoint, DynamoDB)
.venv/Scripts/python.exe verify_backend.py

# SAM template validation + build
sam validate
sam build

# Frontend
cd ai-fire-drill-frontend && npm run lint && npm run build
```
