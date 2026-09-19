import { motion, AnimatePresence } from "framer-motion";
import { ShieldCheck, ArrowRight, Loader2, CheckCircle2, RotateCcw } from "lucide-react";
import ConfidenceRing from "./ConfidenceRing";

export default function DiagnosisPanel({ diagnosis, phase, onAuthorize, onReset }) {
  const awaitingApproval = phase === "AWAITING_APPROVAL";
  const remediating = phase === "REMEDIATING" || phase === "VERIFYING";
  const resolved = phase === "RESOLVED";

  if (!diagnosis) {
    return (
      <div className="rounded-2xl border border-dashed border-white/[0.09] p-7 flex-1 flex flex-col items-center justify-center gap-2 min-h-[280px]">
        <ShieldCheck size={20} className="text-muted2" />
        <span className="text-sm text-muted2 font-mono">awaiting incident…</span>
      </div>
    );
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className="glass shadow-panel rounded-2xl p-7 flex flex-col gap-6"
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-muted">
          <ShieldCheck size={13} />
          <span className="text-[11px] tracking-[0.14em] font-mono">AI DIAGNOSIS</span>
        </div>
        <ConfidenceRing value={diagnosis.confidence} />
      </div>

      <div>
        <div className="text-[10px] tracking-wide text-muted2 mb-1.5 font-mono">ROOT CAUSE</div>
        <div className="text-[17px] leading-snug text-text font-medium">{diagnosis.root_cause}</div>
      </div>

      <div>
        <div className="text-[10px] tracking-wide text-muted2 mb-2.5 font-mono">EVIDENCE</div>
        <ul className="flex flex-col gap-2">
          {diagnosis.evidence.map((e, i) => (
            <motion.li
              key={i}
              initial={{ opacity: 0, x: -4 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: i * 0.05 }}
              className="text-[13.5px] text-muted leading-relaxed flex gap-2.5"
            >
              <span className="w-1 h-1 rounded-full bg-white/25 mt-2 shrink-0" />
              <span>{e}</span>
            </motion.li>
          ))}
        </ul>
      </div>

      <div className="border-t border-white/[0.07] pt-6 flex flex-col gap-4">
        <div className="flex items-center gap-2.5">
          <span className="text-[10px] tracking-wide text-muted2 font-mono">RECOMMENDATION</span>
          <div className="flex items-center gap-1.5 font-mono text-sm">
            <span className="text-critical">v17</span>
            <ArrowRight size={13} className="text-muted2" />
            <span className="text-healthy">{diagnosis.target_version}</span>
          </div>
        </div>

        <AnimatePresence mode="wait">
          {awaitingApproval && (
            <motion.button
              key="auth"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              whileTap={{ scale: 0.98 }}
              onClick={onAuthorize}
              className="w-full py-3.5 rounded-xl font-semibold text-[15px] bg-gradient-to-b from-[#4ADE9A] to-[#2FBE7E] text-[#062A1B] shadow-glowGreen hover:brightness-105 transition"
            >
              Authorize rollback
            </motion.button>
          )}

          {remediating && (
            <motion.div
              key="remediating"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              className="w-full py-3.5 rounded-xl font-mono text-sm text-progress bg-progressDim border border-progress/20 flex items-center justify-center gap-2"
            >
              <Loader2 size={15} className="animate-spin" />
              {phase === "REMEDIATING" ? "Executing rollback…" : "Verifying recovery…"}
            </motion.div>
          )}

          {resolved && (
            <motion.div key="resolved" initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="flex flex-col gap-3">
              <div className="w-full py-3.5 rounded-xl font-semibold bg-healthyDim text-healthy border border-healthy/20 flex items-center justify-center gap-2">
                <CheckCircle2 size={17} />
                Incident resolved
              </div>
              <button
                onClick={onReset}
                className="w-full py-2.5 rounded-xl font-mono text-xs text-muted2 hover:text-muted border border-white/[0.08] flex items-center justify-center gap-1.5 transition-colors"
              >
                <RotateCcw size={12} />
                reset demo
              </button>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </motion.div>
  );
}
