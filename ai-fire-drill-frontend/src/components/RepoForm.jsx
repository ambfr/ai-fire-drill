import { useState } from "react";
import { motion } from "framer-motion";
import { Search, Loader2, GitBranch, Activity, Zap } from "lucide-react";

export default function RepoForm({ onSubmit, running }) {
  const [repoUrl, setRepoUrl] = useState("");
  const [branch, setBranch] = useState("main");
  const [healthUrl, setHealthUrl] = useState("");

  const submit = (e) => {
    e.preventDefault();
    if (!repoUrl.trim() || running) return;
    onSubmit({ repoUrl: repoUrl.trim(), branch: branch.trim() || "main", healthUrl: healthUrl.trim() || null });
  };

  return (
    <div className="glass shadow-panel rounded-2xl p-7 flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-muted">
          <Search size={13} />
          <span className="text-[11px] tracking-[0.14em] font-mono">REPOSITORY</span>
        </div>
        <span className="text-[11px] text-muted2 font-mono">commit fire drill</span>
      </div>

      <form onSubmit={submit} className="flex flex-col gap-4">
        <label className="flex flex-col gap-1.5">
          <span className="text-[10px] tracking-wide text-muted2 font-mono">GITHUB REPO URL</span>
          <input
            type="text"
            value={repoUrl}
            onChange={(e) => setRepoUrl(e.target.value)}
            placeholder="https://github.com/owner/repo"
            spellCheck={false}
            className="w-full bg-white/[0.03] border border-white/[0.08] rounded-xl px-3.5 py-3 font-mono text-sm text-text placeholder:text-muted2 focus:outline-none focus:border-progress/50 transition-colors"
          />
        </label>

        <label className="flex flex-col gap-1.5">
          <span className="text-[10px] tracking-wide text-muted2 font-mono flex items-center gap-1.5">
            <GitBranch size={11} />
            BRANCH
          </span>
          <input
            type="text"
            value={branch}
            onChange={(e) => setBranch(e.target.value)}
            placeholder="main"
            spellCheck={false}
            className="w-full bg-white/[0.03] border border-white/[0.08] rounded-xl px-3.5 py-3 font-mono text-sm text-text placeholder:text-muted2 focus:outline-none focus:border-progress/50 transition-colors"
          />
        </label>

        <label className="flex flex-col gap-1.5">
          <span className="text-[10px] tracking-wide text-muted2 font-mono flex items-center gap-1.5">
            <Activity size={11} />
            HEALTH URL (OPTIONAL)
          </span>
          <input
            type="text"
            value={healthUrl}
            onChange={(e) => setHealthUrl(e.target.value)}
            placeholder="https://your-app.example.com/health"
            spellCheck={false}
            className="w-full bg-white/[0.03] border border-white/[0.08] rounded-xl px-3.5 py-3 font-mono text-sm text-text placeholder:text-muted2 focus:outline-none focus:border-progress/50 transition-colors"
          />
        </label>

        <motion.button
          type="submit"
          disabled={running || !repoUrl.trim()}
          whileTap={running || !repoUrl.trim() ? {} : { scale: 0.98 }}
          className={`w-full py-4 rounded-xl font-semibold text-[15px] tracking-tight transition-all flex items-center justify-center gap-2
            ${
              running || !repoUrl.trim()
                ? "bg-white/5 text-muted2 cursor-not-allowed"
                : "bg-gradient-to-b from-[#FB7B7B] to-[#F04747] text-[#2A0808] shadow-glowRed hover:brightness-105"
            }`}
        >
          {running ? (
            <>
              <Loader2 size={16} className="animate-spin" />
              Analyzing…
            </>
          ) : (
            <>
              <Zap size={16} strokeWidth={2.5} />
              Analyze Latest Commit · Run Fire Drill
            </>
          )}
        </motion.button>
      </form>
    </div>
  );
}
