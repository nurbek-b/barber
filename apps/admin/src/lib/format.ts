import { formatMoney, formatTime, localeTag } from "@barber/ui";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { ADMIN, api, call } from "./api";

export const salonKey = ["settings", "salon"] as const;

/** Salon settings (timezone, currency) used for all formatting. */
export function useSalonSettings() {
  return useQuery({
    queryKey: salonKey,
    queryFn: () => call(api.GET(`${ADMIN}/settings/salon`)),
    staleTime: 10 * 60_000,
  });
}

export function useFormat() {
  const { i18n } = useTranslation();
  const salon = useSalonSettings().data;
  const tz = salon?.timezone ?? "Asia/Bishkek";
  const currency = salon?.currency ?? "KGS";
  const lang = i18n.language;
  const dateTime = new Intl.DateTimeFormat(localeTag(lang), {
    timeZone: tz,
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  });
  const dateOnly = new Intl.DateTimeFormat(localeTag(lang), {
    timeZone: tz,
    day: "numeric",
    month: "short",
    year: "numeric",
  });
  return {
    tz,
    currency,
    money: (amount: number) => formatMoney(amount, currency, lang),
    time: (iso: string) => formatTime(iso, tz),
    dateTime: (iso: string) => dateTime.format(new Date(iso)),
    date: (iso: string) => dateOnly.format(new Date(iso)),
  };
}

/** Minor units → editable major string without floats: 150050 → "1500.50". */
export function toMajorInput(amount: number | null | undefined): string {
  if (amount === null || amount === undefined) return "";
  const major = Math.trunc(amount / 100);
  const minor = Math.abs(amount % 100);
  return minor ? `${major}.${String(minor).padStart(2, "0")}` : String(major);
}
