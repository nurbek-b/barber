/**
 * react-big-calendar renders in the browser timezone. To show the *salon* timezone we hand it
 * "wall-clock" Dates: a Date whose local fields equal the salon-local fields of the instant.
 * After a drag we convert back. Works for any browser timezone, including DST zones.
 */

function partsIn(instant: Date, tz: string): Record<string, number> {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: tz,
    hourCycle: "h23",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).formatToParts(instant);
  const out: Record<string, number> = {};
  for (const part of parts) if (part.type !== "literal") out[part.type] = Number(part.value);
  return out;
}

/** UTC instant → Date whose local fields show the salon wall clock. */
export function toWallClock(iso: string | Date, tz: string): Date {
  const p = partsIn(typeof iso === "string" ? new Date(iso) : iso, tz);
  return new Date(p.year!, p.month! - 1, p.day!, p.hour!, p.minute!, p.second!);
}

/** Offset of `tz` at `instant`, in minutes (local = UTC + offset). */
function offsetMinutes(instant: Date, tz: string): number {
  const p = partsIn(instant, tz);
  const asUtc = Date.UTC(p.year!, p.month! - 1, p.day!, p.hour!, p.minute!, p.second!);
  return Math.round((asUtc - instant.getTime()) / 60_000);
}

/** Wall-clock Date (local fields = salon time) → real UTC instant. */
export function fromWallClock(wall: Date, tz: string): Date {
  const naiveUtc = Date.UTC(
    wall.getFullYear(),
    wall.getMonth(),
    wall.getDate(),
    wall.getHours(),
    wall.getMinutes(),
    wall.getSeconds(),
  );
  // two passes settle DST transitions
  let guess = naiveUtc - offsetMinutes(new Date(naiveUtc), tz) * 60_000;
  guess = naiveUtc - offsetMinutes(new Date(guess), tz) * 60_000;
  return new Date(guess);
}

/** "YYYY-MM-DD" of a wall-clock Date. */
export function wallDayKey(wall: Date): string {
  const m = String(wall.getMonth() + 1).padStart(2, "0");
  const d = String(wall.getDate()).padStart(2, "0");
  return `${wall.getFullYear()}-${m}-${d}`;
}
