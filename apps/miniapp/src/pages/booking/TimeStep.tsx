import type { Slot } from "@barber/api-client";
import { formatDayLong } from "@barber/ui";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { ApiError, keys, placeHold, releaseHold, useDays, useSlots } from "../../api";
import { DayStrip, SlotGrid } from "../../components/SlotPicker";
import { ErrorState, Screen, Skeleton, SkeletonList, useTimezone } from "../../components/ui";
import { useLang, useT } from "../../i18n";
import { ANY_BARBER, barberParam, useBooking } from "../../store/booking";
import { haptic } from "../../telegram/sdk";
import { useBackButton } from "../../telegram/hooks";

export default function TimeStep() {
  const t = useT();
  const lang = useLang();
  const tz = useTimezone();
  const navigate = useNavigate();
  const client = useQueryClient();
  const { barber, serviceIds, day, hold, rescheduleBookingId, setDay, setHold, clearHold } =
    useBooking();
  const barberId = barberParam(barber);
  const days = useDays(barberId, serviceIds);
  const slots = useSlots(barberId, serviceIds, day);
  const [pending, setPending] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useBackButton();

  // a previous hold is released when the user comes back to pick another time
  useEffect(() => {
    if (hold) {
      void releaseHold(hold.hold_id).catch(() => undefined);
      clearHold();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // pick the first day with free time
  useEffect(() => {
    if (!day && days.data) {
      const first = days.data.days.find((item) => item.slots_count > 0);
      if (first) setDay(first.date);
    }
  }, [day, days.data, setDay]);

  const choose = async (slot: Slot) => {
    haptic.tap();
    setPending(slot.start_at);
    setNotice(null);
    try {
      const placed = await placeHold({
        barberId,
        serviceIds,
        startAt: slot.start_at,
        rescheduleBookingId,
      });
      setHold(slot, placed);
      navigate("/book/confirm");
    } catch (error) {
      haptic.error();
      if (error instanceof ApiError && error.code === "slot_conflict") {
        setNotice(t("time.taken"));
        void client.invalidateQueries({ queryKey: keys.slots(barberId, serviceIds, day ?? "") });
        void client.invalidateQueries({ queryKey: keys.days(barberId, serviceIds) });
      } else {
        setNotice(error instanceof ApiError ? error.message : t("error.generic"));
      }
    } finally {
      setPending(null);
    }
  };

  const noFreeDays = Boolean(days.data && !days.data.days.some((item) => item.slots_count > 0));
  const step = rescheduleBookingId ? 1 : 3;
  const total = rescheduleBookingId ? 2 : 4;

  return (
    <Screen title={t("step.time")} step={step} totalSteps={total} back>
      {days.isPending && <Skeleton className="mb-4 h-16" />}
      {days.isError && <ErrorState error={days.error} onRetry={() => void days.refetch()} />}
      {noFreeDays && days.data && (
        <div className="space-y-3 py-8 text-center" role="status">
          <p className="text-hint">
            {t(barber === ANY_BARBER ? "time.noFreeDaysAny" : "time.noFreeDays", {
              days: days.data.days.length,
            })}
          </p>
          {barber !== ANY_BARBER && !rescheduleBookingId && (
            <button
              type="button"
              className="rounded-xl bg-button px-4 py-2 text-sm font-medium text-button-text"
              onClick={() => navigate("/book/barber")}
            >
              {t("time.otherBarber")}
            </button>
          )}
        </div>
      )}
      {days.data && !noFreeDays && (
        <DayStrip days={days.data.days} selected={day} onSelect={setDay} />
      )}

      {day && (
        <h2 className="mb-3 mt-4 font-medium first-letter:uppercase">{formatDayLong(day, lang)}</h2>
      )}
      {notice && (
        <p
          className="mb-3 rounded-xl bg-destructive/10 px-3 py-2 text-sm text-destructive"
          role="status"
        >
          {notice}
        </p>
      )}
      {day && slots.isPending && <SkeletonList rows={3} height="h-11" />}
      {slots.isError && <ErrorState error={slots.error} onRetry={() => void slots.refetch()} />}
      {slots.data && (
        <SlotGrid
          slots={slots.data.slots}
          timezone={tz}
          selected={null}
          pending={pending}
          onSelect={(slot) => void choose(slot)}
        />
      )}
      {!day && days.data && !noFreeDays && (
        <p className="py-8 text-center text-hint">{t("time.pickDay")}</p>
      )}
    </Screen>
  );
}
