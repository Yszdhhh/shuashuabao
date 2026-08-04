/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        darkBg: "#0b1220",
        cardBg: "#151c2c",
        cardBorder: "#243044",
        mutedText: "#8b9bb4",
        accentBlue: "#2563eb",
        accentBlueHover: "#1d4ed8",
        statusGreen: "#22c55e",
        statusRed: "#ef4444",
        statusYellow: "#f59e0b",
      }
    },
  },
  plugins: [],
}
