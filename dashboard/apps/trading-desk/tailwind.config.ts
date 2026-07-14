import type { Config } from "tailwindcss";

export default {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
  ],
  theme: {
    screens: {
      sm: "640px",
      md: "768px",
      lg: "1024px",
      xl: "1280px",
      "2xl": "1920px",
      "3xl": "2560px",
    },
    extend: {
      colors: {
        // JARVIS TRADER color palette — dark trading terminal aesthetic
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        card: {
          DEFAULT: "hsl(var(--card))",
          foreground: "hsl(var(--card-foreground))",
        },
        border: "hsl(var(--border))",
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        },
        accent: {
          DEFAULT: "hsl(var(--accent))",
          foreground: "hsl(var(--accent-foreground))",
        },
        // Trading-specific
        bull: "#22c55e",    // green — price up / bullish
        bear: "#ef4444",    // red — price down / bearish
        warn: "#f59e0b",    // amber — warning / neutral
        info: "#3b82f6",    // blue — informational
        // Dark-panel idiom — collapses two near-identical raw-hex pairs
        // (#0a0a0a/#1a1a2e and #0d0d1a/#1a1a2e) duplicated across ~26 files
        // into one shared token set (see phase3-design-inventory.md §2).
        panel: "#0a0a0a",
        "panel-alt": "#0d0d1a",
        "panel-border": "#1a1a2e",
      },
      fontFamily: {
        mono: ["JetBrains Mono", "Fira Code", "monospace"],
        sans: ["Inter", "system-ui", "sans-serif"],
      },
    },
  },
  plugins: [],
} satisfies Config;
