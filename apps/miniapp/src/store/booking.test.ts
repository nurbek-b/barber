import type { Hold } from "@barber/api-client";
import { beforeEach, describe, expect, it } from "vitest";

import { translate } from "../i18n";
import { ANY_BARBER, barberParam, useBooking } from "./booking";

const hold = { hold_id: "h1" } as Hold;
const slot = { start_at: "2026-12-07T06:00:00Z", barber_ids: ["b1"] };

describe("booking store", () => {
  beforeEach(() => useBooking.getState().reset());

  it("changing the barber resets dependent choices", () => {
    const store = useBooking.getState();
    store.setBarber("b1");
    store.toggleService("s1");
    store.setDay("2026-12-07");
    useBooking.getState().setBarber("b2");
    const state = useBooking.getState();
    expect(state.serviceIds).toEqual([]);
    expect(state.day).toBeNull();
  });

  it("idempotency key is stable across retries and reset by a new hold", () => {
    const store = useBooking.getState();
    let n = 0;
    const make = () => `key-${++n}`;
    store.setHold(slot, hold);
    const first = useBooking.getState().ensureIdempotencyKey(make);
    const retry = useBooking.getState().ensureIdempotencyKey(make);
    expect(retry).toBe(first);
    useBooking.getState().setHold(slot, { ...hold, hold_id: "h2" });
    expect(useBooking.getState().ensureIdempotencyKey(make)).not.toBe(first);
  });

  it("toggles services and drops the hold", () => {
    const store = useBooking.getState();
    store.setHold(slot, hold);
    store.toggleService("s1");
    store.toggleService("s2");
    store.toggleService("s1");
    const state = useBooking.getState();
    expect(state.serviceIds).toEqual(["s2"]);
    expect(state.hold).toBeNull();
  });

  it("repeat and reschedule prefill the draft", () => {
    useBooking.getState().startRepeat(null, ["s1"]);
    expect(useBooking.getState().barber).toBe(ANY_BARBER);
    useBooking.getState().startReschedule("bk", "b1", ["s1"]);
    expect(useBooking.getState().rescheduleBookingId).toBe("bk");
    expect(barberParam(ANY_BARBER)).toBeNull();
    expect(barberParam("b1")).toBe("b1");
  });
});

describe("i18n", () => {
  it("interpolates and falls back", () => {
    expect(translate("ru", "step.of", { n: 2, total: 4 })).toBe("Шаг 2 из 4");
    expect(translate("en", "home.hello", { name: "Bek" })).toBe("Hi, Bek!");
    expect(translate("ky", "button.book")).toBe("Жазылуу");
  });
});
