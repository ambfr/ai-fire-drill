# AI Fire Drill

## Evidence-first commit regression analysis

AI Fire Drill investigates whether the newest commit on a GitHub branch caused
a regression. It compares that commit with the most recent known-good commit,
collects CI and optional health-check evidence, and produces a report answering:

**What changed? Why did it break? How should it be fixed?**

The application under investigation is never modified. AI Fire Drill is not an
uptime monitor and does not simulate outages, fake metrics, or rollback flows.

## How it works

1. Enter a GitHub repository, branch, and optional deployed health URL.
2. The backend reads recent commits and evaluates GitHub check-runs, falling
       back to commit statuses when check-runs are unavailable.
3. The newest commit becomes the head. The newest older commit with passing CI
       becomes the baseline; otherwise the direct parent is used and marked
       unverified.
4. The GitHub compare API supplies the changed files and patches.
5. The optional health URL is checked once as supporting evidence.
6. Code computes the regression verdict deterministically. Groq explains the
       collected evidence but cannot override that verdict.
7. The result is saved to DynamoDB and displayed in the React interface.

If there is no CI and no health URL, the service reports that nothing could be
verified instead of guessing. If Groq is unavailable, the API returns an
evidence-only summary.

## Architecture

```text
React + Vite
            |
            v
API Gateway -> AWS Lambda (FastAPI + Mangum)
                                                      |-> GitHub REST API
                                                      |-> Groq chat completions
                                                      `-> DynamoDB (analysis history)
```

### Stack

- Frontend: React 19, Vite, Tailwind CSS, Framer Motion, Lucide
- Backend: Python 3.12, FastAPI, Mangum, Requests, Boto3
- Infrastructure: AWS SAM, API Gateway, Lambda, DynamoDB
- AI: Groq OpenAI-compatible chat completions

## Repository layout

```text
.
├── backend/
│   ├── app.py                 # FastAPI application and analysis workflow
│   └── requirements.txt       # Lambda/runtime dependencies
├── ai-fire-drill-frontend/
│   ├── src/
│   │   ├── App.jsx            # UI state machine and analysis flow
│   │   ├── api/backend.js     # frontend/backend API client
│   │   └── components/        # form, timeline, report, and event stream
│   ├── package.json
│   └── .env.example           # create locally if needed
├── template.yaml              # SAM infrastructure definition
├── samconfig.toml             # default SAM deployment configuration
└── verify_backend.py          # fully mocked backend verification suite
```

## API

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/status` | Service information and reachability check |
| `POST` | `/analyze` | Analyze the latest commit on a branch |
| `GET` | `/analyses` | Return recent saved analyses |

Example request:

```json
{
      "repo_url": "https://github.com/owner/repo",
      "branch": "main",
      "health_url": "https://your-app.example.com/health"
}
```

`health_url` is optional. The response includes the head and baseline commits,
CI state and failing checks, health-check results, changed files, caveats, and
an `analysis` object with `what_changed`, `what_broke`, `why`, `evidence`,
`how_to_fix`, and `confidence`.

## Local development

### Prerequisites

- Python 3.12
- Node.js and npm
- AWS SAM CLI for template validation and deployment
- AWS credentials configured for deployment
- A Groq API key for live analysis
- A GitHub token is optional, but recommended for private repositories and API
      rate limits

### Backend verification

The verification suite does not call AWS, GitHub, a health endpoint, or Groq.
It replaces those services with local mocks and exercises the analysis flow.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r backend/requirements.txt
python verify_backend.py
```

### Validate and build the SAM application

```bash
sam validate
sam build
```

### Run the frontend

```bash
cd ai-fire-drill-frontend
npm install
npm run dev
```

The frontend uses the deployed API URL by default. To point it at another
backend, create `ai-fire-drill-frontend/.env`:

```dotenv
VITE_API_BASE_URL=https://your-api.execute-api.ap-south-1.amazonaws.com/Prod
```

Useful frontend checks:

```bash
npm run lint
npm run build
```

## Deployment

The SAM template provisions an API Gateway endpoint, a Python 3.12 Lambda, and
the `ai-fire-drill-incidents` DynamoDB table. Deploy interactively:

```bash
sam build
sam deploy --guided
```

When prompted, provide `GroqApiKey`. `GithubToken` is optional. The deployed
API URL is printed as the `ApiUrl` stack output; set that URL in the frontend's
`VITE_API_BASE_URL` before running the UI.

The default region in `samconfig.toml` is `ap-south-1`. Change it in that file
or pass `--region` if the deployment should use another region.

## Configuration

Lambda configuration is supplied through the SAM template or environment:

| Variable | Required | Description |
| --- | --- | --- |
| `GROQ_API_KEY` | Yes for AI explanations | Groq API key |
| `GITHUB_TOKEN` | No | Private-repository access and higher rate limits |
| `GROQ_MODEL` | No | Primary Groq model; defaults to `openai/gpt-oss-120b` in SAM |
| `GROQ_FALLBACK_MODELS` | No | Comma-separated fallback models |
| `TABLE_NAME` | No | DynamoDB table name |
| `GITHUB_TIMEOUT_S` | No | GitHub request timeout |
| `GROQ_TIMEOUT_S` | No | Groq request timeout |
| `HEALTH_TIMEOUT_S` | No | Health URL timeout |

Do not commit `.env` files or API keys. The SAM parameters marked `NoEcho` are
passed to CloudFormation without being displayed in deployment output.

## Limitations

- Analysis depends on the GitHub API and the repository's available CI data.
- A health URL is supporting evidence only; it does not replace commit-level CI.
- Large diffs are truncated before being sent to Groq and stored.
- Public repositories can be analyzed without a token; private repositories
       require `GITHUB_TOKEN`.
