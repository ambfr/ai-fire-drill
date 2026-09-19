# AI Fire Drill — Frontend

Mission-control style dashboard for the AI Fire Drill hackathon project.
Built with Vite + React + Tailwind.

## Setup

```bash
npm install
npm run dev
```

Opens at http://localhost:5173

## How this is structured

- `src/App.jsx` — the whole app is driven by ONE state machine:
  `HEALTHY → BREAKING → INCIDENT → INVESTIGATING → DIAGNOSED →
  AWAITING_APPROVAL → REMEDIATING → VERIFYING → RESOLVED`
  Every component just reads `phase` and renders accordingly.

- `src/api/backend.js` — the ONLY file that knows whether you're talking
  to the real AWS API or the in-browser mock. Right now `USE_MOCK = true`
  at the top of that file, so the whole demo runs with zero backend.

  **When Dev A's API Gateway URL is ready:**
  1. Set `API_BASE_URL` in `backend.js` to the real endpoint
  2. Flip `USE_MOCK` to `false`
  3. Nothing else in the app changes — every component already calls
     `breakProduction()`, `investigate()`, `remediate()`, `verify()`,
     `resetDemo()` instead of touching fetch directly.

- `src/components/`
  - `StatusPanel.jsx` — health badge, metrics, BREAK PRODUCTION button,
    and the hidden "force incident" fallback the design doc requires
    (in case live AWS timing misbehaves mid-demo)
  - `Timeline.jsx` — the 6-step investigation checklist, animated on its
    own fixed local clock (never blocked on real backend timing, per
    the design doc's determinism requirement)
  - `DiagnosisPanel.jsx` — root cause, confidence bar, evidence list,
    AUTHORIZE ROLLBACK button, resolved state + reset
  - `EventStream.jsx` — terminal-style scrolling event log

## Demo flow

1. Click **BREAK PRODUCTION** → status flips, timeline starts running
2. Timeline completes → diagnosis panel populates with root cause + evidence
3. Click **AUTHORIZE ROLLBACK** → remediating → verifying → resolved
4. Click **reset demo** to run it again

Matches the ~90 second demo script in the design doc (section 34).
