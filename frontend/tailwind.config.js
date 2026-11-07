/** Design tokens from the approved ResearchMind mockups. */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        navy: { DEFAULT: "#0F1F2E", 2: "#1B3247", 3: "#28425A", line: "#22384C", text: "#D5DEE7", muted: "#93A4B5", soft: "#9FB0C0" },
        teal: { DEFAULT: "#0F766E", dark: "#115E59", ink: "#0B5F58", soft: "#E3F2EF", wash: "#F6FBFA", line: "#CFE5E1", bright: "#5EEAD4" },
        amber: { DEFAULT: "#B45309", ink: "#8A4106", deep: "#7A3A06", text: "#4A3A26", soft: "#FDF0DE", wash: "#FDF6EC", line: "#F3D9B1", dot: "#F2B66D" },
        ground: "#F4F6F8",
        line: "#E5E7EB",
        ink: { DEFAULT: "#111827", 2: "#374151", muted: "#4B5563" },
        chip: "#EEF2F5",
        blue: { soft: "#E4ECFB", ink: "#1E40AF" },
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        serif: ['"Source Serif 4"', "Georgia", "serif"],
      },
      borderRadius: { card: "14px" },
    },
  },
  plugins: [],
};
