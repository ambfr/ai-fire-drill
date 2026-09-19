export default function DiagnosisPanel({ diagnosis, phase, onAuthorize, onReset }) {
  if (!diagnosis) return null;

  const awaitingApproval = phase === "AWAITING_APPROVAL";
  const remediating = phase === "REMEDIATING" || phase === "VERIFYING";
  const resolved = phase === "RESOLVED";

  return (
    <div className="border border-line bg-panel rounded-sm p-6 flex flex-col gap-5">
      <div className="text-xs tracking-wide text-muted font-mono">AI DIAGNOSIS</div>

      <div>
        <div className="text-[10px] text-muted tracking-wide mb-1">ROOT CAUSE</div>
        <div className="text-base text-text">{diagnosis.root_cause}</div>
      </div>

      <div>
        <div className="text-[10px] text-muted tracking-wide mb-1">CONFIDENCE</div>
        <div className="flex items-center gap-2">
          <div className="flex-1 h-1.5 bg-line rounded-full overflow-hidden">
            <div
              className="h-full bg-progress"
              style={{ width: `${Math.round(diagnosis.confidence * 100)}%` }}
            />
          </div>
          <span className="font-mono text-sm text-progress">
            {Math.round(diagnosis.confidence * 100)}%
          </span>
        </div>
      </div>

      <div>
        <div className="text-[10px] text-muted tracking-wide mb-2">EVIDENCE</div>
        <ul className="flex flex-col gap-1.5">
          {diagnosis.evidence.map((e, i) => (
            <li key={i} className="text-sm text-text flex gap-2">
              <span className="text-muted">–</span>
              <span>{e}</span>
            </li>
          ))}
        </ul>
      </div>

      <div className="border-t border-line pt-4">
        <div className="text-[10px] text-muted tracking-wide mb-1">RECOMMENDATION</div>
        <div className="text-sm text-text mb-4">
          Rollback {diagnosis.rolled_back_from || "v17"} → {diagnosis.target_version}
        </div>

        {awaitingApproval && (
          <button
            onClick={onAuthorize}
            className="w-full py-3 rounded-sm font-semibold bg-healthy text-bg hover:brightness-110 active:scale-[0.99] transition"
          >
            AUTHORIZE ROLLBACK
          </button>
        )}

        {remediating && (
          <div className="w-full py-3 rounded-sm font-mono text-sm text-progress border border-progress/40 text-center animate-pulse">
            {phase === "REMEDIATING" ? "Executing rollback…" : "Verifying recovery…"}
          </div>
        )}

        {resolved && (
          <div className="flex flex-col gap-3">
            <div className="w-full py-3 rounded-sm font-semibold bg-healthy/10 text-healthy border border-healthy/40 text-center">
              ✓ INCIDENT RESOLVED
            </div>
            <button
              onClick={onReset}
              className="w-full py-2 rounded-sm font-mono text-xs text-muted hover:text-text border border-line transition"
            >
              reset demo
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
