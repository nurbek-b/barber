import { describe, expect, it } from "vitest";

import {
  addDaysKey,
  clampBonus,
  computeTotals,
  dayKey,
  formatDayShort,
  formatMoney,
  formatMoneyRange,
  formatTime,
  parseMoneyInput,
  percentOf,
  weekday,
} from "./index";

const NB = " ";

describe("money", () => {
  it("formats minor units without floats", () => {
    expect(formatMoney(150_000)).toBe(`1${NB}500${NB}сом`);
    expect(formatMoney(150_050)).toBe(`1${NB}500,50${NB}сом`);
    expect(formatMoney(5)).toBe(`0,05${NB}сом`);
    expect(formatMoney(-20_000)).toBe(`-200${NB}сом`);
    expect(formatMoney(123_456_789_012, "KGS")).toBe(`1${NB}234${NB}567${NB}890,12${NB}сом`);
    expect(formatMoney(1000, "USD", "en")).toBe(`10${NB}USD`);
  });

  it("rejects non-integers", () => {
    expect(() => formatMoney(10.5)).toThrow(TypeError);
  });

  it("formats ranges", () => {
    expect(formatMoneyRange(80_000, 80_000)).toBe(`800${NB}сом`);
    expect(formatMoneyRange(80_000, 120_000)).toBe(`800${NB}–${NB}1${NB}200${NB}сом`);
  });

  it.each([
    ["1 234,5", 123_450],
    ["1234.56", 123_456],
    ["12", 1_200],
    ["0,07", 7],
    [" 500 ", 50_000],
  ])("parses %s", (input, expected) => {
    expect(parseMoneyInput(input)).toBe(expected);
  });

  it.each(["", "abc", "1,234", "1.2.3", "-5", "1e3"])("rejects %s", (input) => {
    expect(parseMoneyInput(input)).toBeNull();
  });
});

describe("pricing", () => {
  it("clamps bonuses", () => {
    expect(clampBonus(50_000, 30_000)).toBe(30_000);
    expect(clampBonus(-1, 30_000)).toBe(0);
    expect(clampBonus(10.9, 30_000)).toBe(10);
  });

  it("computes totals", () => {
    expect(computeTotals(150_000, 45_000, 100_000)).toEqual({
      subtotal: 150_000,
      bonusSpent: 45_000,
      totalDue: 105_000,
      maxBonus: 45_000,
    });
    expect(computeTotals(10_000, 45_000, 100_000).totalDue).toBe(0);
    // promo discount first, bonuses on what is left
    expect(computeTotals(150_000, 45_000, 100_000, 30_000)).toEqual({
      subtotal: 150_000,
      bonusSpent: 45_000,
      totalDue: 75_000,
      maxBonus: 45_000,
    });
    expect(computeTotals(150_000, 45_000, 100_000, 140_000).totalDue).toBe(0);
  });

  it("percent rounds down like the backend", () => {
    expect(percentOf(123_456, 500)).toBe(6_172);
  });
});

describe("dates", () => {
  const tz = "Asia/Bishkek";

  it("shows times in the salon timezone", () => {
    expect(formatTime("2026-12-07T06:00:00Z", tz)).toBe("12:00");
    expect(dayKey("2026-12-07T20:00:00Z", tz)).toBe("2026-12-08");
  });

  it("formats days", () => {
    expect(formatDayShort("2026-12-07", "ru")).toBe("пн, 7 дек.");
    expect(formatDayShort("2026-12-07", "en")).toBe("Mon 7 Dec");
    expect(formatDayShort("2026-12-07", "ky")).toContain("7");
    expect(addDaysKey("2026-12-31", 1)).toBe("2027-01-01");
    expect(weekday("2026-12-07")).toBe(0);
    expect(weekday("2026-12-13")).toBe(6);
  });

  it("handles DST zones", () => {
    expect(addDaysKey("2026-03-28", 1)).toBe("2026-03-29");
    expect(dayKey("2026-03-28T23:30:00Z", "Europe/Berlin")).toBe("2026-03-29");
    expect(formatTime("2026-03-29T01:30:00Z", "Europe/Berlin")).toBe("03:30");
  });
});
