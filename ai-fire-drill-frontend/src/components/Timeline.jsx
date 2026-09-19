const STEPS = [
  "Incident detected",
  "Application logs collected",
  "Deployment checked",
  "Database checked",
  "Errors correlated",
  "Root cause identified",
];

// activeCount: how many steps are complete. -1 means the timeline hasn't started.
export default function Timeline({ activeCount, running }) {
  if (activeCount < 0) return null;

  return (
    <div className="border border-line bg-panel rounded-sm p-6">
      <div className="text-xs tracking-wide text-muted font-mono mb-4">INVESTIGATION TIMELINE</div>
      <ul className="flex flex-col gap-3">
        {STEPS.map((step, i) => {
          const done = i < activeCount;
          const isCurrent = i === activeCount && running;
          return (
            <li key={step} className="flex items-center gap-3 font-mono text-sm">
              <span
                className={`w-4 h-4 flex items-center justify-center rounded-sm border text-[10px]
                  ${
                    done
                      ? "border-healthy text-healthy"
                      : isCurrent
                      ? "border-progress text-progress"
                      : "border-line text-muted"
                  }`}
              >
                {done ? "✓" : isCurrent ? "•" : ""}
              </span>
              <span className={done ? "text-text" : isCurrent ? "text-progress" : "text-muted"}>
                {step}
                {isCurrent && <span className="animate-pulse">…</span>}
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
