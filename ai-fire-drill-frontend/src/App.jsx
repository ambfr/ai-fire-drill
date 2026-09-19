import { useState, useCallback, useRef } from "react";
import { Flame } from "lucide-react";
import StatusPanel from "./components/StatusPanel";
import Timeline from "./components/Timeline";
import DiagnosisPanel from "./components/DiagnosisPanel";
import EventStream from "./components/EventStream";
import { breakProduction, investigate, remediate, verify, resetDemo } from "./api/backend";

const initialMetrics = { status: "healthy", version: "v16", error_rate: 0.3, latency_ms: 83 };

const PHASE_LABEL = {
  HEALTHY: "Idle",
  BREAKING: "Breaking",
  INCIDENT: "Incident",
  INVESTIGATING: "Investigating",
  AWAITING_APPROVAL: "Awaiting approval",
  REMEDIATING: "Remediating",
  VERIFYING: "Verifying",
  RESOLVED: "Resolved",
};

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

  const isHealthy = phase === "HEALTHY";

  return (
    <div className="min-h-screen bg-console-field px-6 py-10 md:px-14 md:py-14">
      <header className="max-w-5xl mx-auto mb-10 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-[#F87171] to-[#EA580C] flex items-center justify-center shadow-glowRed shrink-0">
            <Flame size={17} className="text-[#2A0808]" strokeWidth={2.5} />
          </div>
          <div>
            <h1 className="text-[15px] font-semibold tracking-tight text-text leading-none">AI Fire Drill</h1>
            <p className="text-[11px] text-muted2 font-mono mt-1">AWS-native incident commander</p>
          </div>
        </div>

        <div className="flex items-center gap-2 px-3 py-1.5 rounded-full border border-white/[0.08] bg-white/[0.02]">
          <span className={`w-1.5 h-1.5 rounded-full ${isHealthy ? "bg-healthy" : "bg-progress"}`} />
          <span className="text-[11px] font-mono text-muted tracking-wide">{PHASE_LABEL[phase]}</span>
        </div>
      </header>

      <main className="grid grid-cols-1 lg:grid-cols-2 gap-6 max-w-5xl mx-auto items-start">
        <div className="flex flex-col gap-6">
          <StatusPanel metrics={metrics} phase={phase} onBreak={handleBreak} onForceIncident={handleForceIncident} />
          <Timeline activeCount={timelineCount} running={phase === "INVESTIGATING"} />
        </div>

        <div className="flex flex-col gap-6 h-full">
          <DiagnosisPanel diagnosis={diagnosis} phase={phase} onAuthorize={handleAuthorize} onReset={handleReset} />
        </div>
      </main>

      <div className="max-w-5xl mx-auto mt-6">
        <EventStream events={events} />
      </div>
    </div>
  );
}
