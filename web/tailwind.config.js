/** Tailwind config for the Q-MigrateAI web app (compiled with the Tailwind standalone CLI). */
module.exports = {
  content: { relative: true, files: ["./static/index.html", "./src/**/*.ts"] },
  theme: {
    extend: {
      colors: {
        ink: { 0: "#0A0F1E", 1: "#0F172B", 2: "#16203A", 3: "#1C2846" },
        line: "#243152",
        mist: "#E4E9F5",
        fog: "#8B96B3",
        lattice: { DEFAULT: "#9B8CFF", strong: "#7B69F5", soft: "#262150" },
        risk: { critical: "#F0504A", high: "#F58A34", medium: "#E9C440", safe: "#3CCB7F" },
      },
      fontFamily: {
        display: ['"Space Grotesk"', "ui-sans-serif", "system-ui", "sans-serif"],
        sans: ['"IBM Plex Sans"', "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ['"IBM Plex Mono"', "ui-monospace", "SFMono-Regular", "monospace"],
      },
    },
  },
  plugins: [],
};
