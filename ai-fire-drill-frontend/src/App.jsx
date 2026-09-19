import { useState, useCallback, useEffect, useRef } from "react";
import { Flame } from "lucide-react";
import RepoForm from "./components/RepoForm";
import Timeline from "./components/Timeline";
import ResultPanel from "./components/ResultPanel";
import EventStream from "./components/EventStream";
import { getStatus, analyzeRepo } from "./api/backend";

const TIMELINE_STEPS = 6;

export default function App() {
  const [phase, setPhase] = useState("IDLE"); // IDLE | ANALYZING | REPORT | ERROR
  const [result, setResult] = useState(null);
  const [timelineCount, setTimelineCount] = useState(-1);
  const [events, setEvents] = useState([]);
  const timelineTimer = useRef(null);

  const log = useCallback((level, message) => {
    const time = new Date().toLocaleTimeString("en-US", { hour12: false });
    setEvents((prev) => [...prev, { time, level, message }]);
  }, []);

  // The analysis is already complete when the timeline runs (the backend
  // returns everything synchronously) — the steps animate on a local clock
  // while the report is revealed as each step "completes".
  const runTimeline = useCallback((onDone) => {
    setTimelineCount(0);
    let step = 1;
    timelineTimer.current = setInterval(() => {
      setTimelineCount(step);
      step += 1;
      if (step > TIMELINE_STEPS) {
        clearInterval(timelineTimer.current);
        onDone?.();
      }
    }, 420);
  }, []);

  // Reachability check on first load.
  useEffect(() => {
    getStatus()
      .then(() => log("OK", "Backend connected — fire drill service ready"))
      .catch((err) => log("ERROR", `Backend unreachable: ${err.message}`));
  }, [log]);

  const handleAnalyze = useCallback(
    async ({ repoUrl, branch, healthUrl }) => {
      setPhase("ANALYZING");
      setResult(null);
      setTimelineCount(-1);
      log("INFO", `Fire drill started — ${repoUrl} (branch: ${branch})`);
      if (healthUrl) log("INFO", `Health endpoint attached: ${healthUrl}`);
      log("INFO", "Fetching commit history from GitHub…");

      const started = Date.now();
      try {
        const data = await analyzeRepo({ repoUrl, branch, healthUrl });
        log(
          "OK",
          `Analysis complete in ${((Date.now() - started) / 1000).toFixed(1)}s — head ${data.commit.short}` +
            (data.previous_commit ? ` vs ${data.previous_commit.short}` : "")
        );

        if (data.ci.state === "failure") {
          log("ERROR", `CI checks failed on ${data.commit.short} (${data.ci.failing_checks.length} failing)`);
        } else if (data.ci.state === "success") {
          log("OK", `CI checks passed on ${data.commit.short} (${data.ci.total_checks} checks)`);
        } else {
          log("INFO", "No CI verdict available for the head commit");
        }
        if (data.health) {
          log(data.health.ok ? "OK" : "ERROR",
              `Health check ${data.health.ok ? "passed" : "failed"} (HTTP ${data.health.status_code ?? "n/a"}, ${data.health.latency_ms}ms)`);
        }
        log("INFO", `Diff analyzed: ${data.changed_files.length} changed file(s)`);
        log("INFO", "Generating WHAT / WHY / HOW from the evidence…");

        // Reveal the report as the investigation timeline "walks through" it.
        runTimeline(() => {
          if (data.regression_detected) {
            log("ERROR", `Regression confirmed (confidence ${Math.round(data.analysis.confidence * 100)}%)`);
          } else {
            log("OK", `No regression — ${data.commit.short} looks healthy`);
          }
          setResult(data);
          setPhase("REPORT");
        });
      } catch (err) {
        log("ERROR", `Fire drill failed: ${err.message}`);
        setResult({ message: err.message });
        setPhase("ERROR");
      }
    },
    [log, runTimeline]
  );

  const handleReset = useCallback(() => {
    if (timelineTimer.current) clearInterval(timelineTimer.current);
    setPhase("IDLE");
    setResult(null);
    setTimelineCount(-1);
    setEvents([]);
  }, []);

  const running = phase === "ANALYZING";

  return (
    <div className="min-h-screen bg-console-field px-6 py-10 md:px-14 md:py-14">
      <header className="max-w-5xl mx-auto mb-10 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-[#F87171] to-[#EA580C] flex items-center justify-center shadow-glowRed shrink-0">
            <Flame size={17} className="text-[#2A0808]" strokeWidth={2.5} />
          </div>
          <div>
            <h1 className="text-[15px] font-semibold tracking-tight text-text leading-none">AI Fire Drill</h1>
            <p className="text-[11px] text-muted2 font-mono mt-1">commit regression analyzer</p>
          </div>
        </div>

        <div className="flex items-center gap-2 px-3 py-1.5 rounded-full border border-white/[0.08] bg-white/[0.02]">
          <span className={`w-1.5 h-1.5 rounded-full ${running ? "bg-progress animate-blink" : phase === "REPORT" ? "bg-healthy" : "bg-muted2"}`} />
          <span className="text-[11px] font-mono text-muted tracking-wide">
            {phase === "IDLE" ? "Ready" : phase === "ANALYZING" ? "Analyzing" : phase === "REPORT" ? (result?.regression_detected ? "Regression" : "Healthy") : "Failed"}
          </span>
        </div>
      </header>

      <main className="grid grid-cols-1 lg:grid-cols-2 gap-6 max-w-5xl mx-auto items-start">
        <div className="flex flex-col gap-6">
          <RepoForm onSubmit={handleAnalyze} running={running} />
          <Timeline activeCount={timelineCount} running={running} />
        </div>

        <div className="flex flex-col gap-6 h-full">
          <ResultPanel result={result} phase={phase} onReset={handleReset} />
        </div>
      </main>

      <div className="max-w-5xl mx-auto mt-6">
        <EventStream events={events} />
      </div>
    </div>
  );
}
