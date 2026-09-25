import type { Config } from "tailwindcss";

/**
 * Ordin's design tokens.
 *
 * The register is an evidence registry, not a SaaS dashboard: deep ink chrome, warm
 * archival paper for the working surface, brass reserved for the few things that carry
 * authority (the seal, the focus ring, the committed state). Colour is spent on meaning
 * — verified, needs attention, refused — and nowhere else.
 *
 * Fonts are system stacks only. `next/font/google` fetches from Google's CDN, which
 * breaks the air-gapped demo path (invariant 11). Segoe UI Variable and Cascadia ship
 * with Windows 11; the fallbacks carry the rest.
 */
export default {
  content: ["./app/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: {
          950: "#070B16",
          900: "#0B1222",
          850: "#0F172B",
          800: "#141E36",
          700: "#1E2A47",
          600: "#2C3A5C",
          500: "#4A5877",
          // 4.5:1 on paper, paper-50, white and paper-200 - AA for body text.
          // #7481A0 measured 3.51:1 on paper and was used 77 times, all of it
          // text. The seven uses that sat on the dark sidebar moved to ink-300
          // first, because darkening this would have taken THOSE from 4.80:1 to
          // 3.36:1 - the same failure, on the other side of the page.
          400: "#5B6887",
          300: "#A3ADC4",
          200: "#CBD2E1",
          100: "#E6EAF2",
        },
        paper: {
          DEFAULT: "#F5F3EE",
          50: "#FBFAF7",
          100: "#F5F3EE",
          200: "#ECE8DF",
          300: "#DDD7CA",
          400: "#C3BAA8",
        },
        brass: {
          50: "#FBF6EC",
          100: "#F3E6C8",
          300: "#D8B46E",
          400: "#C89C4B",
          500: "#B08236",
          600: "#8E6727",
          700: "#6B4D1D",
        },
        verified: { 50: "#ECF7F2", 100: "#CFEBDF", 500: "#1F8A63", 600: "#15724F", 700: "#0F5B3F" },
        caution: { 50: "#FDF6E8", 100: "#F8E6BE", 500: "#C07A12", 600: "#9A5F0B", 700: "#744608" },
        danger: { 50: "#FCEFED", 100: "#F6D3CE", 500: "#C2412F", 600: "#A33322", 700: "#7E2517" },
        signal: { 50: "#EEF1FD", 100: "#D7DEFA", 500: "#4459D6", 600: "#3346B8", 700: "#263591" },
      },
      fontFamily: {
        sans: [
          '"Segoe UI Variable Text"', '"Segoe UI Variable"', '"Segoe UI"', "system-ui",
          "-apple-system", "BlinkMacSystemFont", '"Helvetica Neue"', "Arial", "sans-serif",
        ],
        display: [
          '"Segoe UI Variable Display"', '"Segoe UI Variable"', '"Segoe UI"', "system-ui",
          "-apple-system", "sans-serif",
        ],
        serif: [
          '"Iowan Old Style"', '"Palatino Linotype"', "Palatino", '"Book Antiqua"', "Georgia",
          "serif",
        ],
        mono: ['"Cascadia Code"', '"Cascadia Mono"', "ui-monospace", "Consolas", "monospace"],
      },
      boxShadow: {
        card: "0 1px 0 rgba(11,18,34,0.04), 0 1px 2px rgba(11,18,34,0.06)",
        lift: "0 1px 2px rgba(11,18,34,0.06), 0 8px 24px -12px rgba(11,18,34,0.22)",
        page: "0 2px 4px rgba(0,0,0,0.25), 0 24px 48px -16px rgba(0,0,0,0.55)",
        seal: "inset 0 0 0 1px rgba(216,180,110,0.35), 0 6px 20px -8px rgba(176,130,54,0.55)",
      },
      borderRadius: { xl: "0.875rem", "2xl": "1.125rem" },
      letterSpacing: { eyebrow: "0.14em" },
      keyframes: {
        rise: { "0%": { opacity: "0", transform: "translateY(6px)" }, "100%": { opacity: "1", transform: "none" } },
        pulseRing: { "0%": { boxShadow: "0 0 0 0 rgba(200,156,75,0.55)" }, "100%": { boxShadow: "0 0 0 10px rgba(200,156,75,0)" } },
        sweep: { "0%": { opacity: "0.2" }, "50%": { opacity: "0.55" }, "100%": { opacity: "0.2" } },
      },
      animation: {
        rise: "rise 420ms cubic-bezier(0.2, 0.7, 0.2, 1) both",
        "pulse-ring": "pulseRing 1.6s ease-out infinite",
        sweep: "sweep 2.4s ease-in-out infinite",
      },
    },
  },
  plugins: [],
} satisfies Config;
