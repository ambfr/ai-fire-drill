# AI Fire Drill

**AWS-Native AI Incident Commander** — built for the WeMakeDevs x AWS "First Commit" hackathon.

AI Fire Drill simulates a small production service, deliberately breaks it, and lets an AI agent (Amazon Bedrock) investigate the failure, diagnose the root cause, and recommend a fix — which a human must approve before it's executed.

> We didn't build another chatbot. We built an AI incident commander that can observe, diagnose, and recover an AWS system — with a human still in control.

## Core Loop

```
HEALTHY → BREAK → INCIDENT → INVESTIGATE → DIAGNOSE → HUMAN APPROVAL → REMEDIATE → VERIFY → RECOVERED
```

## How It Works

1. User clicks **BREAK PRODUCTION** → app deterministically enters a failure state (`v16 → v17`, latency and error rate spike).
2. Failure telemetry is written to CloudWatch and an incident is created in DynamoDB.
3. An incident event is published to EventBridge, triggering the Investigation Lambda.
4. The Investigation Lambda gathers evidence (telemetry, deployment info, logs, DB health) and sends it to **Amazon Bedrock**.
5. Bedrock returns a structured diagnosis: root cause, confidence, evidence, recommended action.
6. The frontend displays the diagnosis and asks for **human approval**.
7. On approval, the Remediation Lambda rolls back `v17 → v16`.
8. The system verifies recovery and marks the incident **RESOLVED**.

The `/break` endpoint always triggers the incident deterministically — the demo never depends on CloudWatch/EventBridge timing, random behavior, or external services.

## Architecture

```
React Frontend → API Gateway → Lambda (Demo Controller)
                                   ├── CloudWatch (telemetry)
                                   ├── DynamoDB (incident state)
                                   └── EventBridge → Investigation Lambda → Bedrock
                                                                              │
                                                                       AI Diagnosis
                                                                              │
                                                                      Human Approval
                                                                              │
                                                                    Remediation Lambda
                                                                              │
                                                                        Verification
                                                                              │
                                                                        🟢 RECOVERED
```

## AWS Services Used

| Service | Purpose |
|---|---|
| Amazon Bedrock | Root-cause analysis & remediation recommendation |
| AWS Lambda | API handlers, failure injection, investigation, remediation |
| API Gateway | Exposes backend to frontend |
| CloudWatch | Application logs & telemetry (incident evidence) |
| EventBridge | Connects incident events to the investigation workflow |
| DynamoDB | Stores incidents, deployment state, remediation history |

All serverless/pay-per-request — no EC2, RDS, OpenSearch, or SageMaker endpoints. Target cost: **<$10** of the $100 available credits.

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| GET | `/status` | Current system status |
| POST | `/break` | Deterministically triggers the incident |
| POST | `/investigate` | Runs the investigation pipeline |
| POST | `/remediate` | Executes approved remediation |
| GET | `/verify` | Confirms recovery |
| POST | `/reset` | Resets demo to healthy state |

## Tech Stack

- **Frontend:** React (dark "mission control" UI, terminal-style event stream)
- **Backend:** AWS Lambda (Node/Python), API Gateway
- **Infra:** AWS SAM (Infrastructure as Code) — see `template.yaml`
- **AI:** Amazon Bedrock
- **Data:** DynamoDB (single table), CloudWatch Logs

## Project Structure

```
ai-fire-drill/
├── frontend/
│   ├── src/
│   └── package.json
├── backend/
│   ├── handlers/       # status, break, investigate, remediate, verify, reset
│   ├── services/       # bedrock, cloudwatch, dynamodb
│   └── prompts/
├── infrastructure/
├── template.yaml
└── README.md
```

## Setup

### Prerequisites
- AWS account + AWS CLI configured
- AWS SAM CLI installed
- Node.js (for frontend)

### Deploy

```bash
# Build and deploy backend
sam build
sam deploy --guided

# Run frontend
cd frontend
npm install
npm start
```

### Reset / Demo Loop

The `/reset` endpoint restores the system to healthy state, so the demo can be run repeatedly:

```bash
curl -X POST https://<api-url>/reset
```

## Safety Model

Bedrock never executes anything directly. It can only *recommend* an action from an allowlist (`rollback`, `reset`). The backend validates the action, requires human approval, and only then triggers the Remediation Lambda.

```
AI recommends → Human authorizes → AWS executes → System verifies
```
