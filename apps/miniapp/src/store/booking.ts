/**
 * Booking flow state. Persisted in sessionStorage so BackButton and a WebView reload keep
 * the user's choices.
 */
import type { Hold, Slot } from "@barber/api-client";
import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

export const ANY_BARBER = "any";

export interface BookingDraft {
  /** barber id or ANY_BARBER; null = not chosen yet */
  barber: string | null;
  serviceIds: string[];
  day: string | null;
  slot: Slot | null;
  hold: Hold | null;
  comment: string;
  useBonus: boolean;
  /** one key per confirmation attempt: retries reuse it, a new hold resets it */
  idempotencyKey: string | null;
  /** set when the flow moves an existing booking */
  rescheduleBookingId: string | null;
}

interface BookingStore extends BookingDraft {
  setBarber(barber: string): void;
  toggleService(serviceId: string): void;
  setDay(day: string): void;
  setHold(slot: Slot, hold: Hold): void;
  clearHold(): void;
  setComment(comment: string): void;
  setUseBonus(value: boolean): void;
  ensureIdempotencyKey(make: () => string): string;
  startRepeat(barber: string | null, serviceIds: string[]): void;
  startReschedule(bookingId: string, barberId: string, serviceIds: string[]): void;
  reset(): void;
}

const initial: BookingDraft = {
  barber: null,
  serviceIds: [],
  day: null,
  slot: null,
  hold: null,
  comment: "",
  useBonus: false,
  idempotencyKey: null,
  rescheduleBookingId: null,
};

export const useBooking = create<BookingStore>()(
  persist(
    (set, get) => ({
      ...initial,
      setBarber: (barber) =>
        set((state) =>
          state.barber === barber
            ? state
            : // services/prices depend on the barber: start the rest over
              { barber, serviceIds: [], day: null, slot: null, hold: null, idempotencyKey: null },
        ),
      toggleService: (serviceId) =>
        set((state) => ({
          serviceIds: state.serviceIds.includes(serviceId)
            ? state.serviceIds.filter((id) => id !== serviceId)
            : [...state.serviceIds, serviceId],
          slot: null,
          hold: null,
          idempotencyKey: null,
        })),
      setDay: (day) => set({ day, slot: null }),
      setHold: (slot, hold) => set({ slot, hold, idempotencyKey: null }),
      clearHold: () => set({ slot: null, hold: null, idempotencyKey: null }),
      setComment: (comment) => set({ comment }),
      setUseBonus: (useBonus) => set({ useBonus }),
      ensureIdempotencyKey: (make) => {
        const existing = get().idempotencyKey;
        if (existing) return existing;
        const key = make();
        set({ idempotencyKey: key });
        return key;
      },
      startRepeat: (barber, serviceIds) =>
        set({ ...initial, barber: barber ?? ANY_BARBER, serviceIds }),
      startReschedule: (bookingId, barberId, serviceIds) =>
        set({ ...initial, barber: barberId, serviceIds, rescheduleBookingId: bookingId }),
      reset: () => set(initial),
    }),
    {
      name: "booking-draft",
      storage: createJSONStorage(() => sessionStorage),
      version: 1,
    },
  ),
);

export function barberParam(barber: string | null): string | null {
  return barber && barber !== ANY_BARBER ? barber : null;
}
