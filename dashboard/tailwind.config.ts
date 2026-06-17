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
        // ── CSS variable-driven tokens (light/dark mode compatible) ──────────
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
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        popover: {
          DEFAULT: "hsl(var(--popover))",
          foreground: "hsl(var(--popover-foreground))",
        },
        secondary: {
          DEFAULT: "hsl(var(--secondary))",
          foreground: "hsl(var(--secondary-foreground))",
        },

        // ── JARVIS semantic signal tokens ────────────────────────────────────
        // Usage: text-signal-bull, bg-signal-bull/10, border-signal-bull/30
        signal: {
          bull:    "#00ff88",   // positive signal, approved, long, online
          bear:    "#ff4444",   // negative signal, rejected, short, error
          neutral: "#888888",   // flat / unknown / no data
          caution: "#ffaa00",   // warning, elevated risk, suspended
          info:    "#00ccff",   // informational, system messages, highlights
          halt:    "#ff6600",   // halted state (between caution and bear)
        },

        // ── JARVIS surface tokens ─────────────────────────────────────────────
        // Usage: bg-surface-base, bg-surface-card
        surface: {
          base:     "#050505",   // page background
          card:     "#0a0a0a",   // card background
          elevated: "#0d0d1a",   // elevated card, sub-sections, inner panels
          hover:    "#111125",   // hover states
          overlay:  "#000000cc", // modal overlays
        },

        // ── JARVIS border tokens ──────────────────────────────────────────────
        // Usage: border-edge-subtle, border-edge-active
        edge: {
          subtle:  "#1a1a2e",   // default card borders
          medium:  "#2a2a45",   // stronger borders, dividers
          active:  "#00ff8830", // active/selected state
          danger:  "#ff444430", // error state
          caution: "#ffaa0030", // warning state
        },

        // ── JARVIS text tokens ────────────────────────────────────────────────
        // Usage: text-ink-primary, text-ink-muted
        ink: {
          primary:  "#e0e0e0",  // primary labels, values
          secondary:"#888888",  // supporting text, labels
          muted:    "#555555",  // timestamps, metadata, footnotes
          disabled: "#333333",  // truly inactive, placeholder
          inverse:  "#050505",  // text on light backgrounds
        },

        // ── Legacy aliases (kept for backward compat) ─────────────────────────
        bull:  "#22c55e",
        bear:  "#ef4444",
        warn:  "#f59e0b",
        info:  "#3b82f6",
      },

      fontFamily: {
        mono: ["JetBrains Mono", "Fira Code", "monospace"],
        sans: ["Inter", "system-ui", "sans-serif"],
      },

      // ── Animation tokens ────────────────────────────────────────────────────
      keyframes: {
        "fade-in": {
          "0%": { opacity: "0", transform: "translateY(-4px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        "pulse-slow": {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: "0.4" },
        },
        "slide-in-right": {
          "0%": { transform: "translateX(100%)", opacity: "0" },
          "100%": { transform: "translateX(0)", opacity: "1" },
        },
      },
      animation: {
        "fade-in": "fade-in 0.15s ease-out",
        "pulse-slow": "pulse-slow 2s ease-in-out infinite",
        "slide-in-right": "slide-in-right 0.2s ease-out",
      },

      // ── Spacing tokens ───────────────────────────────────────────────────────
      spacing: {
        "widget-gap": "0.75rem",   // gap between widgets (12px)
        "section-gap": "1.5rem",   // gap between sections (24px)
      },

      // ── Border radius tokens ─────────────────────────────────────────────────
      borderRadius: {
        widget: "0.75rem",   // 12px — standard widget border radius
        card:   "1rem",      // 16px — outer card
        chip:   "0.375rem",  // 6px — badges, chips
      },
    },
  },
  plugins: [],
} satisfies Config;
