import type { Config } from "tailwindcss";

// Colors come from Telegram theme params (bound to CSS variables by the SDK),
// so the app follows the user's light/dark theme automatically.
// A function color so opacity modifiers (`bg-button/10`) work on CSS variables too.
const tg =
  (name: string, fallback: string) =>
  ({ opacityValue }: { opacityValue?: string }) => {
    const color = `var(--tg-theme-${name}, ${fallback})`;
    // plain classes (`bg-button`) get Tailwind's own opacity variable: keep the bare color so
    // they render even where color-mix is unsupported; only explicit `/10` tints mix
    if (opacityValue === undefined || opacityValue.startsWith("var(")) return color;
    return `color-mix(in srgb, ${color} calc(${opacityValue} * 100%), transparent)`;
  };

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
