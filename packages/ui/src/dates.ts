/**
 * Everything is displayed in the salon timezone (never the device timezone).
 * Instants travel as ISO strings in UTC; calendar days as "YYYY-MM-DD" keys.
 *
 * Implemented with the built-in Intl API (timeZone option) instead of date-fns-tz/dayjs:
 * zero bundle cost, and it ships the Kyrgyz locale that date-fns lacks.
 */

export type Lang = "ru" | "ky" | "en";

const LOCALE_TAG: Record<string, string> = { ru: "ru-RU", ky: "ky-KG", en: "en-GB" };

export function localeTag(lang: string): string {
  return LOCALE_TAG[lang] ?? "ru-RU";
}

const cache = new Map<string, Intl.DateTimeFormat>();

function formatter(
  lang: string,
  tz: string,
  options: Intl.DateTimeFormatOptions,
): Intl.DateTimeFormat {
  const key = `${lang}|${tz}|${JSON.stringify(options)}`;
  let value = cache.get(key);
  if (!value) {
    value = new Intl.DateTimeFormat(localeTag(lang), { timeZone: tz, ...options });
    cache.set(key, value);
  }
  return value;
}

function toDate(instant: string | Date): Date {
  return typeof instant === "string" ? new Date(instant) : instant;
}

/** "14:30" */
export function formatTime(instant: string | Date, tz: string): string {
  const parts = formatter("en", tz, {
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(toDate(instant));
  const hour = parts.find((p) => p.type === "hour")?.value ?? "00";
  const minute = parts.find((p) => p.type === "minute")?.value ?? "00";
  return `${hour}:${minute}`;
}

/** Local calendar day of an instant: "2026-12-07". */
export function dayKey(instant: string | Date, tz: string): string {
  const parts = formatter("en", tz, {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(toDate(instant));
  const get = (type: string) => parts.find((p) => p.type === type)?.value ?? "";
  return `${get("year")}-${get("month")}-${get("day")}`;
}

export function todayKey(tz: string, now: Date = new Date()): string {
  return dayKey(now, tz);
}

function parseDay(day: string): [number, number, number] {
  const [y, m, d] = day.split("-").map(Number) as [number, number, number];
  return [y, m, d];
}

/** Pure calendar arithmetic (no timezone involved). */
export function addDaysKey(day: string, days: number): string {
  const [y, m, d] = parseDay(day);
  const date = new Date(Date.UTC(y, m - 1, d + days));
  return date.toISOString().slice(0, 10);
}

/** A representative instant for formatting a calendar day: noon UTC of that day. */
function dayInstant(day: string): Date {
  const [y, m, d] = parseDay(day);
  return new Date(Date.UTC(y, m - 1, d, 12));
}

/** Weekday 0 = Monday … 6 = Sunday (same as the backend). */
export function weekday(day: string): number {
  return (dayInstant(day).getUTCDay() + 6) % 7;
}

/** "пн, 7 дек." */
export function formatDayShort(day: string, lang: string): string {
  return formatter(lang, "UTC", { weekday: "short", day: "numeric", month: "short" }).format(
    dayInstant(day),
  );
}

/** "понедельник, 7 декабря" */
export function formatDayLong(day: string, lang: string): string {
  return formatter(lang, "UTC", { weekday: "long", day: "numeric", month: "long" }).format(
    dayInstant(day),
  );
}

export function formatWeekdayNarrow(day: string, lang: string): string {
  return formatter(lang, "UTC", { weekday: "short" }).format(dayInstant(day));
}

export function dayOfMonth(day: string): number {
  return parseDay(day)[2];
}

/** "7 декабря, 14:30" */
export function formatDateTime(instant: string | Date, tz: string, lang: string): string {
  const date = formatter(lang, tz, { day: "numeric", month: "long" }).format(toDate(instant));
  return `${date}, ${formatTime(instant, tz)}`;
}

export function formatDate(instant: string | Date, tz: string, lang: string): string {
  return formatter(lang, tz, { day: "numeric", month: "long", year: "numeric" }).format(
    toDate(instant),
  );
}

export function isToday(day: string, tz: string, now: Date = new Date()): boolean {
  return todayKey(tz, now) === day;
}

export function hoursUntil(instant: string, now: Date = new Date()): number {
  return (new Date(instant).getTime() - now.getTime()) / 3_600_000;
}
