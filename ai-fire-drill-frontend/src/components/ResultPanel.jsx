import { motion, AnimatePresence } from "framer-motion";
import {
  ExternalLink,
  ShieldAlert,
  ShieldCheck,
  FileText,
  FileDiff,
  FlaskConical,
  Lightbulb,
  Wrench,
  CircleAlert,
  Loader2,
  RotateCcw,
} from "lucide-react";
import ConfidenceRing from "./ConfidenceRing";

function Section({ icon: Icon, label, children }) {
  return (
    <div>
      <div className="flex items-center gap-1.5 text-muted2 mb-1.5">
        <Icon size={11} />
        <span className="text-[10px] tracking-wide font-mono">{label}</span>
      </div>
      {children}
    </div>
  );
}

export default function ResultPanel({ result, phase, onReset }) {
  const analyzing = phase === "ANALYZING";
  const hasResult = phase === "REPORT" || phase === "ERROR";

  if (!hasResult) {
    return (
      <div className="rounded-2xl border border-dashed border-white/[0.09] p-7 flex-1 flex flex-col items-center justify-center gap-2 min-h-[280px]">
        <ShieldCheck size={20} className="text-muted2" />
        <span className="text-sm text-muted2 font-mono">awaiting fire drill…</span>
      </div>
    );
  }

  if (phase === "ERROR") {
    const message = result?.message || "Analysis failed";
    return (
      <div className="glass shadow-panel rounded-2xl p-7 flex flex-col gap-4">
        <div className="flex items-center gap-2 text-critical">
          <CircleAlert size={16} />
          <span className="text-[11px] tracking-[0.14em] font-mono">FIRE DRILL FAILED</span>
        </div>
        <div className="text-[14px] text-muted leading-relaxed font-mono break-words">{message}</div>
      </div>
    );
  }

  const { commit, previous_commit, ci, health, changed_files, analysis, caveats, repo } = result;
  const regression = result.regression_detected;

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className="glass shadow-panel rounded-2xl p-7 flex flex-col gap-6"
    >
      {/* Header: verdict */}
      <div className="flex items-start justify-between gap-4">
        <div className="flex flex-col gap-2">
          <div
            className={`flex items-center gap-2 ${
              regression ? "text-critical" : "text-healthy"
            }`}
          >
            {regression ? <ShieldAlert size={16} /> : <ShieldCheck size={16} />}
            <span className="text-[11px] tracking-[0.14em] font-mono">
              {regression ? "REGRESSION DETECTED" : "NO REGRESSION"}
            </span>
          </div>
          <div className="flex items-center gap-2.5 font-mono text-[13px] flex-wrap">
            <span className="text-muted">Commit</span>
            <a
              href={commit.url}
              target="_blank"
              rel="noreferrer"
              className="text-critical hover:underline inline-flex items-center gap-1"
            >
              {commit.short} <ExternalLink size={10} />
            </a>
            <span className="text-muted">·</span>
            <span className="text-muted">Previous</span>
            {previous_commit ? (
              <a
                href={previous_commit.url}
                target="_blank"
                rel="noreferrer"
                className="text-healthy hover:underline inline-flex items-center gap-1"
              >
                {previous_commit.short}
                {previous_commit.verified && (
                  <span className="text-[9px] text-healthy/70">(verified)</span>
                )}
                <ExternalLink size={10} />
              </a>
            ) : (
              <span className="text-muted2">none found</span>
            )}
          </div>
          <div className="text-sm text-muted leading-snug max-w-[420px]">{commit.message}</div>
        </div>
        <ConfidenceRing value={analysis.confidence} />
      </div>

      {/* Caveats */}
      {caveats?.length > 0 && (
        <div className="rounded-xl border border-progress/25 bg-progressDim px-4 py-3 flex flex-col gap-1.5">
          {caveats.map((c, i) => (
            <div key={i} className="text-[12px] text-progress leading-relaxed flex gap-2">
              <span className="mt-1.5 w-1 h-1 rounded-full bg-progress shrink-0" />
              {c}
            </div>
          ))}
        </div>
      )}

      {/* WHAT CHANGED */}
      <Section icon={FileDiff} label="WHAT CHANGED">
        <div className="text-[14.5px] leading-snug text-text font-medium">{analysis.what_changed}</div>
        {changed_files?.length > 0 && (
          <div className="mt-2 flex flex-col gap-1">
            {changed_files.map((f) => (
              <div key={f.filename} className="flex items-center gap-2 font-mono text-[11.5px]">
                <span className={f.additions > f.deletions ? "text-healthy" : "text-critical"}>
                  +{f.additions}/−{f.deletions}
                </span>
                <span className="text-muted truncate">{f.filename}</span>
              </div>
            ))}
          </div>
        )}
      </Section>

      {/* WHAT BROKE */}
      {analysis.what_broke && (
        <Section icon={FlaskConical} label="WHAT BROKE">
          <div className="text-[14.5px] leading-snug text-critical">{analysis.what_broke}</div>
          {ci?.failing_checks?.length > 0 && (
            <div className="mt-2 flex flex-col gap-1">
              {ci.failing_checks.map((c) => (
                <a
                  key={c.name}
                  href={c.details_url || repo?.url}
                  target="_blank"
                  rel="noreferrer"
                  className="flex items-center gap-2 font-mono text-[11.5px] text-critical hover:underline"
                >
                  <span className="w-1 h-1 rounded-full bg-critical shrink-0" />
                  {c.name}
                  {c.title && <span className="text-muted2">— {c.title}</span>}
                </a>
              ))}
            </div>
          )}
          {health && !health.ok && (
            <div className="mt-2 font-mono text-[11.5px] text-critical">
              health check {health.url} → {health.reachable ? `HTTP ${health.status_code}` : "unreachable"}
              {health.detail && <span className="text-muted2"> ({health.detail})</span>}
            </div>
          )}
        </Section>
      )}

      {/* WHY */}
      <Section icon={Lightbulb} label="WHY">
        <div className="text-[14.5px] leading-relaxed text-muted">{analysis.why}</div>
      </Section>

      {/* EVIDENCE */}
      {analysis.evidence?.length > 0 && (
        <Section icon={FileText} label="EVIDENCE">
          <ul className="flex flex-col gap-2">
            {analysis.evidence.map((e, i) => (
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
        </Section>
      )}

      {/* HOW TO FIX */}
      <div className="border-t border-white/[0.07] pt-6 flex flex-col gap-4">
        <Section icon={Wrench} label="HOW TO FIX">
          <div className="rounded-xl border border-healthy/25 bg-healthyDim px-4 py-3.5 text-[14px] leading-relaxed text-text">
            {analysis.how_to_fix}
          </div>
        </Section>

        <AnimatePresence mode="wait">
          {analyzing ? (
            <motion.div
              key="analyzing"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              className="w-full py-3.5 rounded-xl font-mono text-sm text-progress bg-progressDim border border-progress/20 flex items-center justify-center gap-2"
            >
              <Loader2 size={15} className="animate-spin" />
              Running fire drill…
            </motion.div>
          ) : (
            <motion.button
              key="reset"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              whileTap={{ scale: 0.98 }}
              onClick={onReset}
              className="w-full py-2.5 rounded-xl font-mono text-xs text-muted2 hover:text-muted border border-white/[0.08] flex items-center justify-center gap-1.5 transition-colors"
            >
              <RotateCcw size={12} />
              run another fire drill
            </motion.button>
          )}
        </AnimatePresence>
      </div>
    </motion.div>
  );
}
