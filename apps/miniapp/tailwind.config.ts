import type { Config } from "tailwindcss";

// Colors come from Telegram theme params (bound to CSS variables by the SDK),
// so the app follows the user's light/dark theme automatically.
const tg = (name: string, fallback: string) => `var(--tg-theme-${name}, ${fallback})`;

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: tg("bg-color", "#ffffff"),
        "bg-secondary": tg("secondary-bg-color", "#f1f1f4"),
        section: tg("section-bg-color", "#ffffff"),
        text: tg("text-color", "#111111"),
        hint: tg("hint-color", "#8a8a8f"),
        link: tg("link-color", "#2481cc"),
        accent: tg("accent-text-color", "#2481cc"),
        button: tg("button-color", "#2481cc"),
        "button-text": tg("button-text-color", "#ffffff"),
        destructive: tg("destructive-text-color", "#e53935"),
        separator: tg("section-separator-color", "#e3e3e6"),
      },
      spacing: {
        "safe-top": "var(--safe-top)",
        "safe-bottom": "var(--safe-bottom)",
      },
    },
  },
  plugins: [],
} satisfies Config;
