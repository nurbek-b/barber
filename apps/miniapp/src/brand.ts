import { brandColors } from "@barber/ui";
import { useEffect } from "react";

import { useSalon } from "./api";
import { setMainButtonColors } from "./telegram/sdk";

const VARS = {
  brand: "--brand",
  brandText: "--brand-text",
  brandInk: "--brand-ink",
  brand2: "--brand-2",
  brand2Text: "--brand-2-text",
  brand2Ink: "--brand-2-ink",
} as const;

function pageBackground(): string {
  const value = getComputedStyle(document.documentElement)
    .getPropertyValue("--tg-theme-bg-color")
    .trim()
    .toLowerCase();
  if (/^#[0-9a-f]{6}$/.test(value)) return value;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "#1c1c1d" : "#ffffff";
}

/**
 * Paints the Mini App in the salon's brand colors (set in the admin). Colors are adjusted to
 * the client's light or dark Telegram theme so text stays readable; no colors = Telegram's.
 */
export function useBrandTheme(): void {
  const salon = useSalon();
  const primary = salon.data?.brand_color ?? null;
  const secondary = salon.data?.brand_color_2 ?? null;
  useEffect(() => {
    const root = document.documentElement.style;
    const colors = brandColors(primary, secondary, pageBackground());
    for (const [key, name] of Object.entries(VARS)) {
      const value = colors?.[key as keyof typeof VARS];
      if (value) root.setProperty(name, value);
      else root.removeProperty(name);
    }
    setMainButtonColors(colors ? { background: colors.brand, text: colors.brandText } : null);
  }, [primary, secondary]);
}
