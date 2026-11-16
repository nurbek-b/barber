import type { Config } from "tailwindcss";

const v = (name: string) => `rgb(var(--${name}) / <alpha-value>)`;

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: v("bg"),
        card: v("card"),
        text: v("text"),
        hint: v("hint"),
        brand: v("brand"),
        "brand-text": v("brand-text"),
        line: v("line"),
        danger: v("danger"),
      },
    },
  },
  plugins: [],
} satisfies Config;
