import { brandColors, brandSurfaces, inkBackground, luminance } from "@barber/ui";
import { useEffect, useState } from "react";

import { useSalon } from "./api";
import { onThemeChange, setChromeColor, setMainButtonColors } from "./telegram/sdk";

const VARS = {
  brand: "--brand",
  brandText: "--brand-text",
  brandInk: "--brand-ink",
  brand2: "--brand-2",
  brand2Text: "--brand-2-text",
  brand2Ink: "--brand-2-ink",
  page: "--brand-page",
  section: "--brand-section",
  separator: "--brand-separator",
} as const;

function telegramBackground(): string {
  const value = getComputedStyle(document.documentElement)
    .getPropertyValue("--tg-theme-bg-color")
    .trim()
    .toLowerCase();
  if (/^#[0-9a-f]{6}$/.test(value)) return value;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "#1c1c1d" : "#ffffff";
}

/**
 * Paints the Mini App in the salon's brand colors and background tone (set in the admin).
 * Everything is adjusted to the client's light or dark Telegram theme so text stays readable;
 * nothing set = Telegram's own colors.
 */
export function useBrandTheme(): void {
  const salon = useSalon();
  const primary = salon.data?.brand_color ?? null;
  const secondary = salon.data?.brand_color_2 ?? null;
  const tone = salon.data?.brand_bg ?? null;
  const [themeTick, setThemeTick] = useState(0);
  useEffect(() => onThemeChange(() => setThemeTick((n) => n + 1)), []);

  useEffect(() => {
    const root = document.documentElement.style;
    const telegram = telegramBackground();
    const dark = luminance(telegram) <= 0.4;
    const surfaces = brandSurfaces(tone, telegram);
    const colors = brandColors(
      primary,
      secondary,
      surfaces ? inkBackground(surfaces, dark) : telegram,
    );
    const values: Partial<Record<keyof typeof VARS, string>> = { ...colors, ...surfaces };
    for (const [key, name] of Object.entries(VARS)) {
      const value = values[key as keyof typeof VARS];
      if (value) root.setProperty(name, value);
      else root.removeProperty(name);
    }
    setMainButtonColors(colors ? { background: colors.brand, text: colors.brandText } : null);
    setChromeColor(surfaces?.page ?? null);
  }, [primary, secondary, tone, themeTick]);
}
