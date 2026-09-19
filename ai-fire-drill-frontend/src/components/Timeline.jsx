import { motion, AnimatePresence } from "framer-motion";
import { Check, ListChecks } from "lucide-react";

const STEPS = [
  "Incident detected",
  "Application logs collected",
  "Deployment checked",
  "Database checked",
  "Errors correlated",
  "Root cause identified",
];

export default function Timeline({ activeCount, running }) {
  if (activeCount < 0) return null;

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className="glass shadow-panel rounded-2xl p-7"
    >
      <div className="flex items-center gap-2 text-muted mb-5">
        <ListChecks size={13} />
        <span className="text-[11px] tracking-[0.14em] font-mono">INVESTIGATION</span>
      </div>

      <ul className="relative flex flex-col">
        {STEPS.map((step, i) => {
          const done = i < activeCount;
          const isCurrent = i === activeCount && running;
          const isLast = i === STEPS.length - 1;
          return (
            <li key={step} className="relative flex items-start gap-3.5 pb-5 last:pb-0">
              {!isLast && (
                <span className="absolute left-[9px] top-5 bottom-0 w-px bg-white/[0.08]" />
              )}
              {!isLast && done && (
                <motion.span
                  className="absolute left-[9px] top-5 w-px bg-healthy"
                  initial={{ height: 0 }}
                  animate={{ height: "100%" }}
                  transition={{ duration: 0.3 }}
                />
              )}
              <span
                className={`relative z-10 w-[19px] h-[19px] shrink-0 rounded-full flex items-center justify-center border transition-colors
                  ${
                    done
                      ? "bg-healthy border-healthy"
                      : isCurrent
                      ? "border-progress bg-progressDim"
                      : "border-white/[0.12] bg-bg"
                  }`}
              >
                <AnimatePresence>
                  {done && (
                    <motion.span initial={{ scale: 0 }} animate={{ scale: 1 }}>
                      <Check size={12} strokeWidth={3} className="text-[#08090B]" />
                    </motion.span>
                  )}
                </AnimatePresence>
                {isCurrent && <span className="w-1.5 h-1.5 rounded-full bg-progress animate-pulse" />}
              </span>
              <span
                className={`text-sm pt-0.5 transition-colors ${
                  done ? "text-text" : isCurrent ? "text-progress" : "text-muted2"
                }`}
              >
                {step}
              </span>
            </li>
          );
        })}
      </ul>
    </motion.div>
  );
}
