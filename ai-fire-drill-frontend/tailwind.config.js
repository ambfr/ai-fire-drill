/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        bg: "#08090B",
        panel: "rgba(255,255,255,0.035)",
        panelBorder: "rgba(255,255,255,0.08)",
        console: "#0C0E10",
        line: "rgba(255,255,255,0.08)",
        healthy: "#34D399",
        healthyDim: "#0F2A22",
        critical: "#F87171",
        criticalDim: "#2A1414",
        progress: "#FBBF24",
        progressDim: "#2A2312",
        text: "#F4F6F7",
        muted: "#7D8A8F",
        muted2: "#54605F",
      },
      fontFamily: {
        sans: ["IBM Plex Sans", "sans-serif"],
        mono: ["IBM Plex Mono", "monospace"],
      },
      boxShadow: {
        glowRed: "0 0 40px -8px rgba(248,113,113,0.35)",
        glowGreen: "0 0 40px -8px rgba(52,211,153,0.35)",
        glowAmber: "0 0 40px -8px rgba(251,191,36,0.35)",
        panel: "0 1px 0 0 rgba(255,255,255,0.04) inset, 0 8px 30px -12px rgba(0,0,0,0.6)",
      },
      keyframes: {
        blink: { "0%, 100%": { opacity: 1 }, "50%": { opacity: 0.35 } },
        pulseRing: {
          "0%": { transform: "scale(1)", opacity: 0.6 },
          "100%": { transform: "scale(2.4)", opacity: 0 },
        },
      },
      animation: {
        blink: "blink 1.6s ease-in-out infinite",
        pulseRing: "pulseRing 1.8s cubic-bezier(0.4,0,0.6,1) infinite",
      },
      backdropBlur: { xs: "2px" },
    },
  },
  plugins: [],
};
