import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        background: "hsl(var(--background) / <alpha-value>)",
        surface: "hsl(var(--surface) / <alpha-value>)",
        elevated: "hsl(var(--elevated) / <alpha-value>)",
        border: "hsl(var(--border) / <alpha-value>)",
        muted: "hsl(var(--muted) / <alpha-value>)",
        foreground: "hsl(var(--foreground) / <alpha-value>)",
        accent: "hsl(var(--accent) / <alpha-value>)",
        accent2: "hsl(var(--accent-2) / <alpha-value>)",
        danger: "hsl(var(--danger) / <alpha-value>)",
        warning: "hsl(var(--warning) / <alpha-value>)",
        up: "hsl(var(--up) / <alpha-value>)",
        down: "hsl(var(--down) / <alpha-value>)",
      },
      fontFamily: {
        sans: ['"Inter"', "-apple-system", "BlinkMacSystemFont", '"Segoe UI"', "Roboto", "sans-serif"],
        mono: ['"JetBrains Mono"', "ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
    },
  },
  plugins: [],
};

export default config;
