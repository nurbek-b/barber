/**
 * Salon brand colors → the colors the UI actually paints, readable on the client's
 * light or dark Telegram background (WCAG contrast). Shared by the Mini App and the
 * admin preview so both show exactly the same result.
 */

export interface BrandColors {
  /** fills: main button, selected items */
  brand: string;
  /** text on `brand` */
  brandText: string;
  /** brand-colored text and icons on the page background */
  brandInk: string;
  /** second color: bonus chip, highlights */
  brand2: string;
  brand2Text: string;
  brand2Ink: string;
}

export const HEX_COLOR = /^#[0-9a-f]{6}$/i;

function rgb(hex: string): [number, number, number] {
  const value = Number.parseInt(hex.slice(1), 16);
  return [(value >> 16) & 255, (value >> 8) & 255, value & 255];
}

function toHex([r, g, b]: [number, number, number]): string {
  return `#${[r, g, b].map((c) => Math.round(c).toString(16).padStart(2, "0")).join("")}`;
}

/** WCAG relative luminance, 0 (black) … 1 (white). */
export function luminance(hex: string): number {
  const [r, g, b] = rgb(hex).map((c) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  }) as [number, number, number];
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/** WCAG contrast ratio, 1 … 21. */
export function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number];
  return (hi + 0.05) / (lo + 0.05);
}

function mix(a: string, b: string, weight: number): string {
  const [x, y] = [rgb(a), rgb(b)];
  return toHex([0, 1, 2].map((i) => x[i]! + (y[i]! - x[i]!) * weight) as [number, number, number]);
}

/** Black or white text, whichever reads better on `fill`. */
export function textOn(fill: string): string {
  return contrast(fill, "#ffffff") >= contrast(fill, "#111111") ? "#ffffff" : "#111111";
}

/** The color itself, darkened (light page) or lightened (dark page) until text contrast ≥ 4.5. */
export function inkOn(color: string, background: string): string {
  const target = luminance(background) > 0.4 ? "#000000" : "#ffffff";
  for (let step = 0; step <= 10; step += 1) {
    const candidate = mix(color, target, step / 10);
    if (contrast(candidate, background) >= 4.5) return candidate;
  }
  return target;
}

function hsl(hex: string): [number, number, number] {
  const [r, g, b] = rgb(hex).map((c) => c / 255) as [number, number, number];
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const l = (max + min) / 2;
  const d = max - min;
  if (d === 0) return [0, 0, l];
  const s = d / (1 - Math.abs(2 * l - 1));
  const h =
    max === r
      ? ((g - b) / d + (g < b ? 6 : 0)) * 60
      : max === g
        ? ((b - r) / d + 2) * 60
        : ((r - g) / d + 4) * 60;
  return [h, s, l];
}

function fromHsl(h: number, s: number, l: number): string {
  const k = (n: number) => (n + h / 30) % 12;
  const a = s * Math.min(l, 1 - l);
  const f = (n: number) => l - a * Math.max(-1, Math.min(k(n) - 3, 9 - k(n), 1));
  return toHex([f(0) * 255, f(8) * 255, f(4) * 255]);
}

export interface BrandSurfaces {
  /** page background (Telegram's secondary_bg) */
  page: string;
  /** cards and sections on the page */
  section: string;
  separator: string;
}

/**
 * The salon's background tone, made to fit the client's theme: on a light theme the tone
 * itself (kept light), with cards a bit lighter; on a dark theme a dark shade of the same hue.
 */
export function brandSurfaces(
  tone: string | null | undefined,
  telegramBackground: string,
): BrandSurfaces | null {
  if (!tone || !HEX_COLOR.test(tone) || !HEX_COLOR.test(telegramBackground)) return null;
  const [h, s, l] = hsl(tone);
  if (luminance(telegramBackground) > 0.4) {
    const page = fromHsl(h, s, Math.min(Math.max(l, 0.9), 0.97));
    return { page, section: mix(page, "#ffffff", 0.7), separator: mix(page, "#000000", 0.1) };
  }
  const muted = Math.min(s, 0.3);
  return {
    page: fromHsl(h, muted, 0.07),
    section: fromHsl(h, muted, 0.14),
    separator: fromHsl(h, muted, 0.22),
  };
}

/** The background brand-colored text sits on with the least contrast (for `brandColors`). */
export function inkBackground(surfaces: BrandSurfaces, dark: boolean): string {
  return dark ? surfaces.section : surfaces.page;
}

/** A fill that disappears into the background (graphite on a dark theme) is not used as one. */
const VISIBLE_FILL = 1.4;

export function brandColors(
  primary: string | null | undefined,
  secondary: string | null | undefined,
  background: string,
): BrandColors | null {
  if (!primary || !HEX_COLOR.test(primary) || !HEX_COLOR.test(background)) return null;
  const second = secondary && HEX_COLOR.test(secondary) ? secondary : primary;
  // on a background where the main color is invisible, the second color fills buttons
  const swap =
    contrast(primary, background) < VISIBLE_FILL && contrast(second, background) >= VISIBLE_FILL;
  const brand = swap ? second : primary;
  const brand2 =
    contrast(swap ? primary : second, background) < VISIBLE_FILL ? brand : swap ? primary : second;
  return {
    brand,
    brandText: textOn(brand),
    brandInk: inkOn(brand, background),
    brand2,
    brand2Text: textOn(brand2),
    brand2Ink: inkOn(brand2, background),
  };
}

/** Ready-made sets (main, second, background) offered in the admin. */
export const BRAND_PALETTES = [
  { id: "barbershop", colors: ["#C8A24A", "#7A1F2B", "#F6F1E7"] },
  { id: "earth", colors: ["#B85C38", "#6B7B3A", "#FAF6EE"] },
  { id: "scandi", colors: ["#6B8BA4", "#C8A97E", "#EEF1F4"] },
  { id: "contrast", colors: ["#2E3236", "#F2C230", "#F4F4F1"] },
  { id: "pastel", colors: ["#8E7CC3", "#E3A6B4", "#FBF5EA"] },
] as const;
