export default function StatusPanel({ status, metrics, onBreak, onForceIncident, phase }) {
  const isHealthy = status === "healthy";
  const isBroken = status === "broken";

  return (
    <div className="border border-line bg-panel rounded-sm p-6 flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <span className="text-xs tracking-wide text-muted font-mono">PRODUCTION</span>
        <span className="text-xs text-muted font-mono">payment-api</span>
      </div>

      <div className="flex items-center gap-3">
        <span
          className={`w-2.5 h-2.5 rounded-full ${
            isHealthy ? "bg-healthy" : "bg-critical animate-blink"
          }`}
        />
        <span
          className={`text-2xl font-semibold tracking-tight ${
            isHealthy ? "text-healthy" : "text-critical"
          }`}
        >
          {isHealthy ? "PRODUCTION HEALTHY" : isBroken ? "INCIDENT DETECTED" : "RECOVERING"}
        </span>
      </div>

      <div className="grid grid-cols-3 gap-4 font-mono">
        <Metric label="LATENCY" value={`${metrics.latency_ms} ms`} warn={metrics.latency_ms > 500} />
        <Metric label="ERROR RATE" value={`${metrics.error_rate}%`} warn={metrics.error_rate > 5} />
        <Metric label="VERSION" value={metrics.version} />
      </div>

      <div className="pt-2">
        <button
          onClick={onBreak}
          disabled={phase !== "HEALTHY"}
          className={`w-full py-4 rounded-sm font-semibold text-lg tracking-wide transition
            ${
              phase === "HEALTHY"
                ? "bg-critical text-bg hover:brightness-110 active:scale-[0.99]"
                : "bg-line text-muted cursor-not-allowed"
            }`}
        >
          {phase === "HEALTHY" ? "BREAK PRODUCTION" : "PRODUCTION UNSTABLE"}
        </button>

        {phase === "HEALTHY" && (
          <button
            onClick={onForceIncident}
            className="mt-2 w-full text-xs text-muted hover:text-text font-mono py-2 transition"
            title="Deterministic fallback path — bypasses live AWS event timing for the demo"
          >
            force incident (demo fallback)
          </button>
        )}
      </div>
    </div>
  );
}

function Metric({ label, value, warn }) {
  return (
    <div className="border border-line rounded-sm px-3 py-2">
      <div className="text-[10px] text-muted tracking-wide mb-1">{label}</div>
      <div className={`text-base font-medium ${warn ? "text-critical" : "text-text"}`}>{value}</div>
    </div>
  );
}
