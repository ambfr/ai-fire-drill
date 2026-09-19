import { motion } from "framer-motion";
import { Radio, Gauge, AlertTriangle, GitBranch, Zap } from "lucide-react";

export default function StatusPanel({ metrics, onBreak, onForceIncident, phase }) {
  const isHealthy = metrics.status === "healthy";
  const isBroken = metrics.status === "broken";

  return (
    <div className="glass shadow-panel rounded-2xl p-7 flex flex-col gap-7">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-muted">
          <Radio size={13} />
          <span className="text-[11px] tracking-[0.14em] font-mono">PRODUCTION</span>
        </div>
        <span className="text-[11px] text-muted2 font-mono">payment-api</span>
      </div>

      <div className="flex items-center gap-4">
        <div className="relative flex items-center justify-center">
          <span className={`w-3 h-3 rounded-full ${isHealthy ? "bg-healthy" : "bg-critical"}`} />
          {!isHealthy && (
            <span className="absolute w-3 h-3 rounded-full bg-critical animate-pulseRing" />
          )}
        </div>
        <span className={`text-[26px] leading-none font-semibold tracking-tight ${isHealthy ? "text-healthy" : "text-critical"}`}>
          {isHealthy ? "Production healthy" : isBroken ? "Incident detected" : "Recovering"}
        </span>
      </div>

      <div className="grid grid-cols-3 gap-3">
        <Metric icon={Gauge} label="Latency" value={`${metrics.latency_ms}ms`} warn={metrics.latency_ms > 500} />
        <Metric icon={AlertTriangle} label="Errors" value={`${metrics.error_rate}%`} warn={metrics.error_rate > 5} />
        <Metric icon={GitBranch} label="Version" value={metrics.version} />
      </div>

      <div className="flex flex-col gap-2.5 pt-1">
        <motion.button
          onClick={onBreak}
          disabled={phase !== "HEALTHY"}
          whileTap={phase === "HEALTHY" ? { scale: 0.98 } : {}}
          className={`w-full py-4 rounded-xl font-semibold text-[15px] tracking-tight transition-all flex items-center justify-center gap-2
            ${
              phase === "HEALTHY"
                ? "bg-gradient-to-b from-[#FB7B7B] to-[#F04747] text-[#2A0808] shadow-glowRed hover:brightness-105"
                : "bg-white/5 text-muted2 cursor-not-allowed"
            }`}
        >
          <Zap size={16} strokeWidth={2.5} />
          {phase === "HEALTHY" ? "Break production" : "Production unstable"}
        </motion.button>

        {phase === "HEALTHY" && (
          <button
            onClick={onForceIncident}
            className="w-full text-[11px] text-muted2 hover:text-muted font-mono py-1.5 transition-colors"
            title="Deterministic fallback path — bypasses live AWS event timing for the demo"
          >
            force incident · demo fallback
          </button>
        )}
      </div>
    </div>
  );
}

function Metric({ icon: Icon, label, value, warn }) {
  return (
    <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] px-3.5 py-3 flex flex-col gap-2">
      <div className="flex items-center gap-1.5 text-muted2">
        <Icon size={12} />
        <span className="text-[10px] tracking-wide">{label}</span>
      </div>
      <div className={`font-mono text-[15px] tabular ${warn ? "text-critical" : "text-text"}`}>{value}</div>
    </div>
  );
}
