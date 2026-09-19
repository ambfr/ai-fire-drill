import { useState, useCallback, useRef } from "react";
import StatusPanel from "./components/StatusPanel";
import Timeline from "./components/Timeline";
import DiagnosisPanel from "./components/DiagnosisPanel";
import EventStream from "./components/EventStream";
import { breakProduction, investigate, remediate, verify, resetDemo } from "./api/backend";

// -----------------------------------------------------------------------
// The whole app is driven by ONE state machine, matching the design doc:
// HEALTHY -> BREAKING -> INCIDENT -> INVESTIGATING -> DIAGNOSED
//         -> AWAITING_APPROVAL -> REMEDIATING -> VERIFYING -> RESOLVED
//
// Every panel just reads `phase` and renders itself accordingly. Nothing
// waits on real AWS timing to update the UI — see handleBreak below.
// -----------------------------------------------------------------------

const initialMetrics = { status: "healthy", version: "v16", error_rate: 0.3, latency_ms: 83 };

export default function App() {
  const [phase, setPhase] = useState("HEALTHY");
  const [metrics, setMetrics] = useState(initialMetrics);
  const [incidentId, setIncidentId] = useState(null);
  const [diagnosis, setDiagnosis] = useState(null);
  const [timelineCount, setTimelineCount] = useState(-1);
  const [events, setEvents] = useState([]);
  const timelineTimer = useRef(null);

  const log = useCallback((level, message) => {
    const time = new Date().toLocaleTimeString("en-US", { hour12: false });
    setEvents((prev) => [...prev, { time, level, message }]);
  }, []);

  // Advances the visible timeline on its own clock. Per the design doc,
  // this must NEVER be literally blocked on CloudWatch/EventBridge —
  // it's a fixed local cadence, independent of the backend call timing.
  const runTimeline = useCallback((onDone) => {
    setTimelineCount(0);
    let step = 1;
    timelineTimer.current = setInterval(() => {
      setTimelineCount(step);
      step += 1;
      if (step > 6) {
        clearInterval(timelineTimer.current);
        onDone?.();
      }
    }, 420);
  }, []);

  const beginIncidentFlow = useCallback(
    async (id) => {
      setPhase("INCIDENT");
      log("ERROR", `Incident ${id} created — payment-api reporting elevated errors`);

      setPhase("INVESTIGATING");
      log("INFO", "EventBridge published ProductionIncident event");
      log("INFO", "Investigation Lambda invoked");

      runTimeline(async () => {
        log("INFO", "Evidence package sent to Bedrock");
        const result = await investigate(id);
        setDiagnosis(result);
        log("OK", `Root cause identified (confidence ${Math.round(result.confidence * 100)}%)`);
        setPhase("AWAITING_APPROVAL");
      });
    },
    [log, runTimeline]
  );

  const handleBreak = useCallback(async () => {
    setPhase("BREAKING");
    const { incident_id } = await breakProduction();
    setIncidentId(incident_id);
    setMetrics((m) => ({ ...m, status: "broken", version: "v17", error_rate: 17.8, latency_ms: 1842 }));
    log("ERROR", "Deployment v17 detected — malformed database query in logs");
    beginIncidentFlow(incident_id);
  }, [beginIncidentFlow, log]);

  // Same deterministic path as handleBreak — this is the "FORCE INCIDENT"
  // fallback the design doc requires in case live AWS timing misbehaves
  // mid-demo. It reuses the identical pipeline, just without re-calling /break.
  const handleForceIncident = useCallback(() => {
    handleBreak();
  }, [handleBreak]);

  const handleAuthorize = useCallback(async () => {
    setPhase("REMEDIATING");
    log("INFO", "Rollback authorized by operator");
    await remediate(incidentId, diagnosis.target_version);
    log("OK", `Rolling back to ${diagnosis.target_version}`);

    setPhase("VERIFYING");
    log("INFO", "Verifying recovery…");
    const result = await verify();
    setMetrics((m) => ({ ...m, ...result }));
    log("OK", `Recovery verified — error rate ${result.error_rate}%, latency ${result.latency_ms}ms`);
    setPhase("RESOLVED");
  }, [diagnosis, incidentId, log]);

  const handleReset = useCallback(async () => {
    await resetDemo();
    setPhase("HEALTHY");
    setMetrics(initialMetrics);
    setIncidentId(null);
    setDiagnosis(null);
    setTimelineCount(-1);
    setEvents([]);
  }, []);

  return (
    <div className="min-h-screen bg-bg px-6 py-8 md:px-12 md:py-10">
      <header className="mb-8 flex items-baseline justify-between">
        <div>
          <h1 className="text-lg font-semibold tracking-tight text-text">AI Fire Drill</h1>
          <p className="text-xs text-muted font-mono mt-0.5">AWS-native AI Incident Commander</p>
        </div>
        <span className="text-xs font-mono text-muted">{phase}</span>
      </header>

      <main className="grid grid-cols-1 lg:grid-cols-2 gap-6 max-w-5xl mx-auto">
        <div className="flex flex-col gap-6">
          <StatusPanel
            status={metrics.status}
            metrics={metrics}
            phase={phase}
            onBreak={handleBreak}
            onForceIncident={handleForceIncident}
          />
          <Timeline activeCount={timelineCount} running={phase === "INVESTIGATING"} />
        </div>

        <div className="flex flex-col gap-6">
          <DiagnosisPanel
            diagnosis={diagnosis}
            phase={phase}
            onAuthorize={handleAuthorize}
            onReset={handleReset}
          />
          {!diagnosis && (
            <div className="border border-dashed border-line rounded-sm p-6 text-sm text-muted font-mono flex items-center justify-center h-full min-h-[160px]">
              awaiting incident…
            </div>
          )}
        </div>
      </main>

      <div className="max-w-5xl mx-auto mt-6">
        <EventStream events={events} />
      </div>
    </div>
  );
}
