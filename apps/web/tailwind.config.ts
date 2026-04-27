import type { Config } from "tailwindcss";
import animate from "tailwindcss-animate";

/**
 * Design tokens for ShiftOps.
 *
 * Decisions:
 * - We expose tokens as CSS variables (in app/globals.css) and reference them
 *   in Tailwind via `hsl(var(--token))`. Reason: shadcn/ui assumes this shape,
 *   and it lets Telegram WebApp themeParams override us at runtime if we
 *   choose to map them later (`window.Telegram.WebApp.themeParams`).
 * - Dark mode is the *default*, not an opt-in: most HoReCa shifts run in
 *   low-light bars where pure white blasts the user's retina. Light mode is
 *   a future feature, not MVP.
 * - Spacing scale uses the standard 4px grid; we add `safe` utilities that
 *   honor the iOS notch / Android status bar inside Telegram Web App.
 */
const config: Config = {
  darkMode: "class",
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    container: {
      center: true,
      padding: "1rem",
      screens: {
        sm: "640px",
        md: "768px",
        lg: "1024px",
      },
    },
    extend: {
      colors: {
        background: "hsl(var(--bg))",
        surface: "hsl(var(--surface))",
        elevated: "hsl(var(--elevated))",
        border: "hsl(var(--border))",
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-fg))",
        },
        primary: {
          DEFAULT: "hsl(var(--primary))",
          foreground: "hsl(var(--primary-fg))",
        },
        success: {
          DEFAULT: "hsl(var(--success))",
          foreground: "hsl(var(--success-fg))",
        },
        warning: {
          DEFAULT: "hsl(var(--warning))",
          foreground: "hsl(var(--warning-fg))",
        },
        critical: {
          DEFAULT: "hsl(var(--critical))",
          foreground: "hsl(var(--critical-fg))",
        },
        foreground: "hsl(var(--fg))",
        ring: "hsl(var(--ring))",
      },
      borderRadius: {
        lg: "16px",
        md: "12px",
        sm: "8px",
      },
      fontFamily: {
        sans: [
          "Inter",
          "ui-sans-serif",
          "-apple-system",
          "BlinkMacSystemFont",
          "Segoe UI",
          "Roboto",
          "sans-serif",
        ],
      },
      fontSize: {
        // Sized for thumb-friendly bar use; we boost minimum to 14px.
        xs: ["13px", "16px"],
        sm: ["14px", "20px"],
        base: ["16px", "24px"],
        lg: ["18px", "26px"],
        xl: ["22px", "30px"],
        "2xl": ["28px", "36px"],
        "3xl": ["34px", "42px"],
      },
      spacing: {
        safe: "env(safe-area-inset-bottom)",
      },
      boxShadow: {
        card: "0 1px 0 rgba(255,255,255,0.04) inset, 0 8px 24px rgba(0,0,0,0.36)",
        glow: "0 0 0 4px hsl(var(--primary) / 0.18)",
      },
      keyframes: {
        "fade-in-up": {
          from: { opacity: "0", transform: "translateY(8px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
      },
      animation: {
        "fade-in-up": "fade-in-up 200ms ease-out",
      },
    },
  },
  plugins: [animate],
};

export default config;
