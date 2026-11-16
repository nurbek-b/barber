import type { Booking } from "@barber/api-client";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { ApiError, useBookings, useCancelBooking } from "../api";
import { BookingCard } from "../components/BookingCard";
import { Stars } from "../components/Stars";
import { ErrorState, Screen, SkeletonList } from "../components/ui";
import { useT } from "../i18n";
import { useBooking } from "../store/booking";
import { confirmDialog, haptic } from "../telegram/sdk";
import { useBackButton, useMainButton } from "../telegram/hooks";

export default function MyBookings() {
  const t = useT();
  const navigate = useNavigate();
  const [scope, setScope] = useState<"upcoming" | "past">("upcoming");
  const bookings = useBookings(scope);
  const cancel = useCancelBooking();
  const startReschedule = useBooking((state) => state.startReschedule);
  const [error, setError] = useState<string | null>(null);

  useBackButton(() => navigate("/"));
  useMainButton({ text: "", visible: false, onClick: () => undefined });

  const onCancel = async (booking: Booking) => {
    const ok = await confirmDialog(
      t("bookings.cancelConfirm"),
      t("bookings.cancelYes"),
      t("bookings.cancelNo"),
    );
    if (!ok) return;
    setError(null);
    try {
      await cancel.mutateAsync(booking.id);
      haptic.success();
    } catch (caught) {
      haptic.error();
      setError(caught instanceof ApiError ? caught.message : t("error.generic"));
    }
  };

  const onReschedule = (booking: Booking) => {
    const serviceIds = booking.services
      .map((service) => service.service_id)
      .filter((id): id is string => Boolean(id));
    startReschedule(booking.id, booking.barber.id, serviceIds);
    navigate("/book/time");
  };

  const items = bookings.data?.pages.flatMap((page) => page.items) ?? [];

  return (
    <Screen title={t("nav.bookings")}>
      <div className="mb-4 grid grid-cols-2 rounded-xl bg-bg-secondary p-1" role="tablist">
        {(["upcoming", "past"] as const).map((value) => (
          <button
            key={value}
            type="button"
            role="tab"
            aria-selected={scope === value}
            onClick={() => setScope(value)}
            className={`rounded-lg py-2 text-sm font-medium ${scope === value ? "bg-section shadow-sm" : "text-hint"}`}
          >
            {t(value === "upcoming" ? "bookings.upcoming" : "bookings.past")}
          </button>
        ))}
      </div>
      {error && (
        <p
          className="mb-3 rounded-xl bg-destructive/10 px-3 py-2 text-sm text-destructive"
          role="alert"
        >
          {error}
        </p>
      )}
      {bookings.isPending && <SkeletonList rows={3} height="h-36" />}
      {bookings.isError && (
        <ErrorState error={bookings.error} onRetry={() => void bookings.refetch()} />
      )}
      {bookings.isSuccess && items.length === 0 && (
        <p className="py-10 text-center text-hint">{t("bookings.empty")}</p>
      )}
      <div className="space-y-3">
        {items.map((booking) => (
          <BookingCard
            key={booking.id}
            booking={booking}
            actions={
              <>
                {scope === "upcoming" && booking.can_pay && (
                  <button
                    type="button"
                    onClick={() => navigate(`/pay/${booking.id}`)}
                    className="w-full rounded-xl bg-button py-2 text-sm font-medium text-button-text"
                  >
                    {t("pay.button")}
                  </button>
                )}
                {scope === "upcoming" && booking.status !== "cancelled" ? (
                  booking.can_cancel || booking.can_reschedule ? (
                    <div className="flex gap-2">
                      {booking.can_reschedule && (
                        <button
                          type="button"
                          onClick={() => onReschedule(booking)}
                          className="flex-1 rounded-xl bg-bg-secondary py-2 text-sm font-medium"
                        >
                          {t("button.reschedule")}
                        </button>
                      )}
                      {booking.can_cancel && (
                        <button
                          type="button"
                          onClick={() => void onCancel(booking)}
                          className="flex-1 rounded-xl bg-destructive/10 py-2 text-sm font-medium text-destructive"
                        >
                          {t("button.cancel")}
                        </button>
                      )}
                    </div>
                  ) : (
                    <p className="text-xs text-hint">{t("bookings.tooLate")}</p>
                  )
                ) : booking.status === "completed" && (booking.can_review || booking.rating) ? (
                  <div className="flex items-center justify-between gap-2">
                    {booking.rating ? <Stars value={booking.rating} /> : <span />}
                    {booking.can_review && (
                      <button
                        type="button"
                        onClick={() => navigate(`/review/${booking.id}`)}
                        className="rounded-xl bg-button/10 px-3 py-2 text-sm font-medium text-button"
                      >
                        {t(booking.rating ? "review.edit" : "review.leave")}
                      </button>
                    )}
                  </div>
                ) : null}
              </>
            }
          />
        ))}
      </div>
      {bookings.hasNextPage && (
        <button
          type="button"
          onClick={() => void bookings.fetchNextPage()}
          disabled={bookings.isFetchingNextPage}
          className="mt-4 w-full py-3 text-link"
        >
          {t("bookings.more")}
        </button>
      )}
    </Screen>
  );
}
