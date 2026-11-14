import type { BonusSummary, Quote, Slot } from "@barber/api-client";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { LevelProgress } from "../pages/Bonus";
import { renderWithProviders } from "../test-utils";
import { PriceSummary, bonusToSpend } from "./PriceSummary";
import { DayStrip, SlotGrid } from "./SlotPicker";

const NB = " ";

const slots: Slot[] = [
  { start_at: "2026-12-07T04:00:00Z", barber_ids: ["a"] },
  { start_at: "2026-12-07T04:15:00Z", barber_ids: ["a", "b"] },
  { start_at: "2026-12-07T06:30:00Z", barber_ids: ["b"] },
];

describe("SlotGrid", () => {
  it("shows times in the salon timezone and reports the chosen slot", async () => {
    const onSelect = vi.fn();
    renderWithProviders(
      <SlotGrid slots={slots} timezone="Asia/Bishkek" selected={null} onSelect={onSelect} />,
    );
    const options = screen.getAllByRole("option");
    expect(options.map((o) => o.textContent)).toEqual(["10:00", "10:15", "12:30"]);
    await userEvent.click(screen.getByText("10:15"));
    expect(onSelect).toHaveBeenCalledWith(slots[1]);
  });

  it("disables all slots while a hold is being placed", () => {
    renderWithProviders(
      <SlotGrid
        slots={slots}
        timezone="Asia/Bishkek"
        selected={null}
        pending={slots[0]!.start_at}
        onSelect={() => undefined}
      />,
    );
    for (const option of screen.getAllByRole("option")) expect(option).toBeDisabled();
  });

  it("shows an empty state", () => {
    renderWithProviders(
      <SlotGrid slots={[]} timezone="UTC" selected={null} onSelect={() => undefined} />,
    );
    expect(screen.getByText("На этот день нет свободного времени")).toBeInTheDocument();
  });
});

describe("DayStrip", () => {
  it("disables days without free slots", async () => {
    const onSelect = vi.fn();
    renderWithProviders(
      <DayStrip
        days={[
          { date: "2026-12-07", slots_count: 5 },
          { date: "2026-12-08", slots_count: 0 },
        ]}
        selected="2026-12-07"
        onSelect={onSelect}
      />,
    );
    const [monday, tuesday] = screen.getAllByRole("option");
    expect(monday).toHaveAttribute("aria-selected", "true");
    expect(tuesday).toBeDisabled();
    await userEvent.click(monday!);
    expect(onSelect).toHaveBeenCalledWith("2026-12-07");
  });
});

const quote: Quote = {
  lines: [
    { service_id: "s1", name_i18n: { ru: "Стрижка" }, duration_min: 60, price: 100_000 },
    { service_id: "s2", name_i18n: { ru: "Борода", en: "Beard" }, duration_min: 30, price: 50_000 },
  ],
  subtotal: 150_000,
  duration_min: 90,
  bonus_balance: 60_000,
  max_bonus_spend: 45_000,
};

function Harness({ value }: { value: Quote }) {
  const [useBonus, setUseBonus] = useState(false);
  return <PriceSummary quote={value} useBonus={useBonus} onToggleBonus={setUseBonus} />;
}

describe("PriceSummary", () => {
  it("computes the amount to pay with and without bonuses", async () => {
    renderWithProviders(<Harness value={quote} />);
    expect(screen.getByTestId("subtotal").textContent).toBe(`1${NB}500${NB}сом`);
    expect(screen.getByTestId("total-due").textContent).toBe(`1${NB}500${NB}сом`);

    await userEvent.click(screen.getByRole("switch"));
    expect(screen.getByTestId("bonus-spent").textContent).toBe(`−450${NB}сом`);
    expect(screen.getByTestId("total-due").textContent).toBe(`1${NB}050${NB}сом`);

    await userEvent.click(screen.getByRole("switch"));
    expect(screen.queryByTestId("bonus-spent")).not.toBeInTheDocument();
  });

  it("disables the switch without bonuses", () => {
    renderWithProviders(<Harness value={{ ...quote, bonus_balance: 0, max_bonus_spend: 0 }} />);
    expect(screen.getByRole("switch")).toBeDisabled();
    expect(screen.getByText("Бонусов пока нет")).toBeInTheDocument();
  });

  it("localizes service names", () => {
    renderWithProviders(<Harness value={quote} />, "en");
    expect(screen.getByText("Beard")).toBeInTheDocument();
    expect(screen.getByText("Стрижка")).toBeInTheDocument(); // ru fallback
  });

  it("bonusToSpend never exceeds the limit", () => {
    expect(bonusToSpend(quote, true)).toBe(45_000);
    expect(bonusToSpend(quote, false)).toBe(0);
    expect(bonusToSpend({ ...quote, subtotal: 10_000 }, true)).toBe(10_000);
  });
});

const summary: BonusSummary = {
  enabled: true,
  balance: 10_000,
  level: {
    id: "l1",
    name_i18n: { ru: "Бронза" },
    min_visits: 0,
    min_spent: 0,
    cashback_bp: 300,
    color: null,
    sort_order: 0,
  },
  next_level: {
    id: "l2",
    name_i18n: { ru: "Серебро" },
    min_visits: 5,
    min_spent: 1_000_000,
    cashback_bp: 500,
    color: null,
    sort_order: 1,
  },
  visits_left: 1,
  spent_left: 900_000,
  level_rule: "any",
  cashback_bp: 300,
  max_spend_bp: 3000,
  expiring: [],
};

describe("LevelProgress", () => {
  it("with rule 'any' the closer goal wins", () => {
    renderWithProviders(<LevelProgress summary={summary} />);
    expect(screen.getByTestId("level-bar")).toHaveStyle({ width: "80%" });
    expect(screen.getByText(/1 визитов или 9/)).toBeInTheDocument();
  });

  it("with rule 'all' the farther goal wins", () => {
    renderWithProviders(<LevelProgress summary={{ ...summary, level_rule: "all" }} />);
    expect(screen.getByTestId("level-bar")).toHaveStyle({ width: "10%" });
  });

  it("top level", () => {
    renderWithProviders(<LevelProgress summary={{ ...summary, next_level: null }} />);
    expect(screen.getByText("У вас максимальный уровень")).toBeInTheDocument();
  });
});
