import { useEffect, useRef } from "react";
import { Terminal } from "lucide-react";

export default function EventStream({ events }) {
  const bottomRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [events]);

  return (
    <div className="rounded-2xl overflow-hidden border border-white/[0.08] shadow-panel">
      <div className="bg-white/[0.03] px-4 py-2.5 flex items-center gap-2 border-b border-white/[0.06]">
        <span className="w-2.5 h-2.5 rounded-full bg-critical/70" />
        <span className="w-2.5 h-2.5 rounded-full bg-progress/70" />
        <span className="w-2.5 h-2.5 rounded-full bg-healthy/70" />
        <div className="flex items-center gap-1.5 text-muted2 ml-2">
          <Terminal size={11} />
          <span className="text-[11px] font-mono tracking-wide">event stream</span>
        </div>
      </div>
      <div className="bg-console px-4 py-3 h-36 overflow-y-auto stream-scroll font-mono text-[12.5px]">
        {events.length === 0 && <div className="text-muted2">waiting for events…</div>}
        {events.map((e, i) => (
          <div key={i} className="flex gap-3 py-0.5">
            <span className="text-muted2 shrink-0 tabular">{e.time}</span>
            <span
              className={
                e.level === "ERROR" ? "text-critical" : e.level === "OK" ? "text-healthy" : "text-muted"
              }
            >
              {e.level}
            </span>
            <span className="text-muted">{e.message}</span>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
