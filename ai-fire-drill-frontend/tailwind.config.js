/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        bg: "#0A0E0F",
        panel: "#12181A",
        panel2: "#161D1F",
        line: "#1E2628",
        healthy: "#3DDC84",
        critical: "#FF5C5C",
        progress: "#F5A623",
        text: "#E8EEEF",
        muted: "#6B7B7E",
      },
      fontFamily: {
        sans: ["IBM Plex Sans", "sans-serif"],
        mono: ["IBM Plex Mono", "monospace"],
      },
      keyframes: {
        blink: { "0%, 100%": { opacity: 1 }, "50%": { opacity: 0.3 } },
        sweep: { "0%": { transform: "translateX(-100%)" }, "100%": { transform: "translateX(100%)" } },
        pulseBorder: {
          "0%, 100%": { boxShadow: "0 0 0 0 rgba(255,92,92,0.0)" },
          "50%": { boxShadow: "0 0 0 4px rgba(255,92,92,0.12)" },
        },
      },
      animation: {
        blink: "blink 1.4s ease-in-out infinite",
        sweep: "sweep 1.8s linear infinite",
        pulseBorder: "pulseBorder 1.6s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};
