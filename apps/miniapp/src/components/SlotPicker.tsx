import type { AvailabilityDays, Slot } from "@barber/api-client";
import { dayOfMonth, formatTime, formatWeekdayNarrow } from "@barber/ui";

import { useLang, useT } from "../i18n";

export function DayStrip({
  days,
  selected,
  onSelect,
}: {
  days: AvailabilityDays["days"];
  selected: string | null;
  onSelect: (day: string) => void;
}) {
  const lang = useLang();
  return (
    <div className="-mx-4 flex gap-2 overflow-x-auto px-4 pb-2" role="listbox" aria-label="days">
      {days.map((day) => {
        const active = day.date === selected;
        const empty = day.slots_count === 0;
        return (
          <button
            key={day.date}
            type="button"
            role="option"
            aria-selected={active}
            disabled={empty}
            onClick={() => onSelect(day.date)}
            className={`flex w-14 shrink-0 flex-col items-center rounded-xl py-2 text-sm transition ${
              active ? "bg-button text-button-text" : "bg-section"
            } ${empty ? "opacity-40" : ""}`}
          >
            <span className="text-xs capitalize">{formatWeekdayNarrow(day.date, lang)}</span>
            <span className="text-lg font-semibold">{dayOfMonth(day.date)}</span>
          </button>
        );
      })}
    </div>
  );
}

/** Grid of free start times. Times are shown in the salon timezone. */
export function SlotGrid({
  slots,
  timezone,
  selected,
  pending,
  onSelect,
}: {
  slots: Slot[];
  timezone: string;
  selected: string | null;
  pending?: string | null;
  onSelect: (slot: Slot) => void;
}) {
  const t = useT();
  if (slots.length === 0) {
    return <p className="py-8 text-center text-hint">{t("time.noSlots")}</p>;
  }
  return (
    <div className="grid grid-cols-4 gap-2" role="listbox" aria-label="slots">
      {slots.map((slot) => {
        const active = slot.start_at === selected;
        const loading = slot.start_at === pending;
        return (
          <button
            key={slot.start_at}
            type="button"
            role="option"
            aria-selected={active}
            disabled={Boolean(pending)}
            onClick={() => onSelect(slot)}
            className={`h-11 rounded-xl text-sm font-medium tabular-nums transition ${
              active ? "bg-button text-button-text" : "bg-section"
            } ${loading ? "animate-pulse" : ""}`}
          >
            {formatTime(slot.start_at, timezone)}
          </button>
        );
      })}
    </div>
  );
}
