# AI Fire Drill — Commit Regression Analyzer

> **"Your latest push broke the application. Here's the change that caused it,
> why it caused the failure, the evidence, and how to fix it."**

AI Fire Drill takes a GitHub repository, inspects the newest commit against the
last known-good commit, gathers evidence (code diff, CI check results, optional
health endpoint), and produces a **WHAT changed / WHY it broke / HOW to fix it**
report — strictly from that evidence. It is **not** a website uptime monitor and
**not** a tool that breaks anything: the app under test is never touched.

## Core Flow

```text
Working application
      ↓
New GitHub commit
      ↓
AI Fire Drill detects/checks the new commit
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
- **No fake production**: no `/break`, no v16/v17, no fake error_rate/latency,
  no rollback scenario, no "break production" button

## How It Works

1. The user enters a GitHub repo URL (branch defaults to `main`) and an optional
   deployed health URL, then clicks **Analyze Latest Commit · Run Fire Drill**.
2. `POST /analyze` lists recent commits on the branch via the GitHub API.
3. CI is evaluated per commit (GitHub check-runs, falling back to commit statuses).
4. **Head** = newest commit. **Baseline** = newest older commit whose CI passes
   (falls back to the direct parent, flagged unverified).
5. The diff between baseline and head is fetched (GitHub compare API).
6. The health URL (if provided) is probed once — supporting evidence only.
7. Verdict is deterministic: failing CI (or failing health) ⇒ regression;
   passing CI ⇒ clean; no CI and no health URL ⇒ honest "nothing verified".
8. The evidence (diff, failing checks, health result) goes to **Groq**, which
   returns `what_changed` / `what_broke` / `why` / `evidence` / `how_to_fix` /
   `confidence`. Its system prompt forbids inventing logs, metrics, or causes.
9. The analysis is stored in DynamoDB and returned; the frontend renders the
   report above.

## Architecture

```
React Frontend → API Gateway → Lambda (FastAPI + Mangum)
                                  ├── GitHub REST API (commits, compare, check-runs)
                                  ├── Groq chat completions (WHAT/WHY/HOW report)
                                  └── DynamoDB (analysis history)
```

Reused from the previous version: AWS API Gateway, Lambda/FastAPI, DynamoDB,
the Groq integration, and the existing frontend structure. No new AWS services.

## AWS Services Used

| Service | Purpose |
|---|---|
| AWS Lambda | `POST /analyze` — GitHub + Groq + DynamoDB orchestration |
| API Gateway | Exposes the backend to the frontend |
| DynamoDB | Stores analysis history |
| Groq | Evidence-only regression report (OpenAI-compatible API) |

All serverless/pay-per-request — no EC2, RDS, OpenSearch, or SageMaker.

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| GET | `/status` | Service info / reachability check |
| POST | `/analyze` | Run the fire drill for `repo_url` (+ branch, health_url) |
| GET | `/analyses` | Recent analysis history (top 10) |

`POST /analyze` request:

```json
{
  "repo_url": "https://github.com/owner/repo",
  "branch": "main",
  "health_url": "https://your-app.example.com/health"
}
```

Response highlights: `analysis_id`, `regression_detected`, `repo`, `commit`,
`previous_commit` (with `verified` flag), `ci` (failing check names/titles),
`health`, `changed_files` (with patches), `analysis` (`what_changed`,
`what_broke`, `why`, `evidence[]`, `how_to_fix`, `confidence`), `caveats[]`.

## Tech Stack

- **Frontend:** Vite + React (dark "mission control" UI, terminal-style event stream)
- **Backend:** Python 3.12 Lambda, FastAPI + Mangum, AWS SAM (`template.yaml`)
- **AI:** Groq (`llama-3.3-70b-versatile` with configured fallback models)
- **Data:** DynamoDB single table (`ai-fire-drill-analyses`)

## Project Structure

```
ai-fire-drill/
├── backend/
│   ├── app.py              # FastAPI app: /status, /analyze, /analyses
│   └── requirements.txt
├── ai-fire-drill-frontend/
│   ├── src/
│   │   ├── App.jsx         # IDLE → ANALYZING → REPORT/ERROR state machine
│   │   ├── api/backend.js  # the only file that talks to the API
│   │   └── components/     # RepoForm, Timeline, ResultPanel, EventStream
│   └── .env                # VITE_API_BASE_URL
├── template.yaml           # SAM template (API Gateway + Lambda + DynamoDB)
├── verify_backend.py       # local test suite (mocks GitHub/Groq/DynamoDB)
└── samconfig.toml
```

## Setup

### Prerequisites

- AWS account + AWS CLI configured
- AWS SAM CLI installed
- Node.js (for the frontend)
- A Groq API key (`GROQ_API_KEY`); optionally a GitHub token for private repos

### Local verification (nothing is deployed)

```bash
# Backend tests — mock GitHub, Groq, health endpoint, DynamoDB
.venv/Scripts/python.exe verify_backend.py

# SAM template validation + build
sam validate
sam build

# Frontend lint + build
cd ai-fire-drill-frontend
npm run lint
npm run build
```

### Deploy (when ready)

```bash
sam build
sam deploy --guided   # prompts for GROQ_API_KEY and optional GITHUB_TOKEN

cd ai-fire-drill-frontend
# put the deployed API URL into .env as VITE_API_BASE_URL
npm run dev
```

## Honesty Model

The AI never invents evidence:

- The system prompt requires the model to base every statement on the provided
  diff/CI/health evidence and to say so explicitly when evidence is insufficient.
- The regression verdict is computed deterministically in code — the model
  cannot override it.
- If Groq is unreachable, the API returns an evidence-only summary (failing
  checks, changed files, health result) and states that no root cause was
  inferred.
- If a repo has no CI and no health URL, the report says that nothing could be
  verified instead of guessing.
