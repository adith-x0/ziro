import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        background: "var(--background)",
        foreground: "var(--foreground)",
        nexus: {
          dark: "#0b0f19",
          card: "#111827",
          border: "#1f2937",
          primary: "#3b82f6",
          accent: "#06b6d4",
          danger: "#ef4444",
          warning: "#f59e0b",
          success: "#10b981",
        },
      },
    },
  },
  plugins: [],
};
export default config;
