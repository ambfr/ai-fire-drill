import { useEffect, useRef } from "react";

// A terminal-style running log. Purely presentational — driven by the
// `events` array the state machine in App.jsx appends to. This is the
// piece that sells "mission control" more than any other single element.
export default function EventStream({ events }) {
  const bottomRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [events]);

  return (
    <div className="border border-line bg-[#0D1213] rounded-sm p-4 h-40 overflow-y-auto stream-scroll font-mono text-xs">
      {events.length === 0 && <div className="text-muted">waiting for events…</div>}
      {events.map((e, i) => (
        <div key={i} className="flex gap-3 py-0.5">
          <span className="text-muted shrink-0">{e.time}</span>
          <span
            className={
              e.level === "ERROR"
                ? "text-critical"
                : e.level === "OK"
                ? "text-healthy"
                : "text-muted"
            }
          >
            [{e.level}]
          </span>
          <span className="text-text">{e.message}</span>
        </div>
      ))}
      <div ref={bottomRef} />
    </div>
  );
}
