import { Plus, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button, Input } from "@/components/ui";

export interface Interval {
  weekday: number;
  start_time: string; // "HH:MM"
  end_time: string;
}

const toMinutes = (value: string) => {
  const [h, m] = value.split(":").map(Number);
  return (h ?? 0) * 60 + (m ?? 0);
};

/**
 * Client-side mirror of the backend overlap check (overnight shifts wrap into the next day,
 * Sunday wraps into Monday). Returns the weekdays that have overlapping intervals.
 */
export function overlappingDays(intervals: Interval[]): Set<number> {
  const week = 7 * 1440;
  const ranges: [number, number, number][] = [];
  for (const item of intervals) {
    const start = item.weekday * 1440 + toMinutes(item.start_time);
    let length = toMinutes(item.end_time) - toMinutes(item.start_time);
    if (length <= 0) length += 1440;
    const end = start + length;
    if (end <= week) ranges.push([start, end, item.weekday]);
    else {
      ranges.push([start, week, item.weekday]);
      ranges.push([0, end - week, item.weekday]);
    }
  }
  ranges.sort((a, b) => a[0] - b[0]);
  const bad = new Set<number>();
  for (let i = 1; i < ranges.length; i += 1) {
    const prev = ranges[i - 1]!;
    const cur = ranges[i]!;
    if (cur[0] < prev[1]) {
      bad.add(prev[2]);
      bad.add(cur[2]);
    }
  }
  return bad;
}

export function ScheduleEditor({
  value,
  onChange,
}: {
  value: Interval[];
  onChange: (next: Interval[]) => void;
}) {
  const { t } = useTranslation();
  const weekdays = t("barbers.weekday", { returnObjects: true }) as string[];
  const bad = overlappingDays(value);

  const update = (index: number, patch: Partial<Interval>) =>
    onChange(value.map((item, i) => (i === index ? { ...item, ...patch } : item)));

  const fill = (days: number[]) =>
    onChange(days.map((weekday) => ({ weekday, start_time: "10:00", end_time: "20:00" })));

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2 pb-1">
        <span className="text-sm text-muted-foreground">{t("barbers.presets")}:</span>
        <Button
          type="button"
          size="sm"
          variant="secondary"
          onClick={() => fill([0, 1, 2, 3, 4, 5])}
        >
          {t("barbers.presetWeekdays")}
        </Button>
        <Button
          type="button"
          size="sm"
          variant="secondary"
          onClick={() => fill([0, 1, 2, 3, 4, 5, 6])}
        >
          {t("barbers.presetEveryDay")}
        </Button>
        <Button type="button" size="sm" variant="ghost" onClick={() => onChange([])}>
          {t("barbers.presetClear")}
        </Button>
      </div>
      {weekdays.map((label, weekday) => {
        const rows = value
          .map((item, index) => ({ item, index }))
          .filter(({ item }) => item.weekday === weekday);
        return (
          <div
            key={weekday}
            data-testid={`weekday-${weekday}`}
            className={`flex flex-wrap items-center gap-2 rounded-md border p-2 ${bad.has(weekday) ? "border-destructive" : ""}`}
          >
            <span className="w-10 font-medium">{label}</span>
            {rows.length === 0 && (
              <span className="text-sm text-muted-foreground">{t("barbers.dayOff")}</span>
            )}
            {rows.map(({ item, index }) => (
              <span key={index} className="flex items-center gap-1">
                <Input
                  type="time"
                  className="w-28"
                  value={item.start_time}
                  aria-label={`${label} start`}
                  onChange={(e) => update(index, { start_time: e.target.value })}
                />
                –
                <Input
                  type="time"
                  className="w-28"
                  value={item.end_time}
                  aria-label={`${label} end`}
                  onChange={(e) => update(index, { end_time: e.target.value })}
                />
                <Button
                  type="button"
                  size="icon"
                  variant="ghost"
                  aria-label={t("common.delete")}
                  onClick={() => onChange(value.filter((_, i) => i !== index))}
                >
                  <Trash2 />
                </Button>
              </span>
            ))}
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={() =>
                onChange([
                  ...value,
                  {
                    weekday,
                    start_time: rows.length ? "15:00" : "10:00",
                    end_time: rows.length ? "19:00" : "14:00",
                  },
                ])
              }
            >
              <Plus /> {t("barbers.addInterval")}
            </Button>
          </div>
        );
      })}
    </div>
  );
}
