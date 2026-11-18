import type { Config } from "tailwindcss";

// Colors come from Telegram theme params (bound to CSS variables by the SDK),
// so the app follows the user's light/dark theme automatically.
// A function color so opacity modifiers (`bg-button/10`) work on CSS variables too.
const cssColor =
  (color: string) =>
  ({ opacityValue }: { opacityValue?: string }) => {
    // plain classes (`bg-button`) get Tailwind's own opacity variable: keep the bare color so
    // they render even where color-mix is unsupported; only explicit `/10` tints mix
    if (opacityValue === undefined || opacityValue.startsWith("var(")) return color;
    return `color-mix(in srgb, ${color} calc(${opacityValue} * 100%), transparent)`;
  };
const tg = (name: string, fallback: string) => cssColor(`var(--tg-theme-${name}, ${fallback})`);
// salon brand colors (set at runtime from the admin settings) win over the Telegram theme
const brand = (variable: string, name: string, fallback: string) =>
  cssColor(`var(${variable}, var(--tg-theme-${name}, ${fallback}))`);

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
        link: brand("--brand-ink", "link-color", "#2481cc"),
        accent: tg("accent-text-color", "#2481cc"),
        button: brand("--brand", "button-color", "#2481cc"),
        "button-text": brand("--brand-text", "button-text-color", "#ffffff"),
        // second brand color: bonuses and highlights; without it, the main color
        brand2: cssColor("var(--brand-2, var(--brand, var(--tg-theme-button-color, #2481cc)))"),
        "brand2-text": cssColor(
          "var(--brand-2-text, var(--brand-text, var(--tg-theme-button-text-color, #ffffff)))",
        ),
        "brand2-ink": cssColor(
          "var(--brand-2-ink, var(--brand-ink, var(--tg-theme-link-color, #2481cc)))",
        ),
        // semantic colors that keep their meaning in any brand
        gold: cssColor("#f5a524"),
        success: cssColor("#16a34a"),
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
