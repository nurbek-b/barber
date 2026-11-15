import { formatDateTime } from "@barber/ui";
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { ApiError, useBookingDetails, useSubmitReview } from "../api";
import { StarInput } from "../components/Stars";
import { Avatar, Card, ErrorState, Screen, Skeleton, useTimezone } from "../components/ui";
import { pickI18n, useLang, useT } from "../i18n";
import { haptic } from "../telegram/sdk";
import { useBackButton, useMainButton } from "../telegram/hooks";

export default function ReviewForm() {
  const { bookingId = "" } = useParams();
  const t = useT();
  const lang = useLang();
  const tz = useTimezone();
  const navigate = useNavigate();
  const booking = useBookingDetails(bookingId);
  const submit = useSubmitReview();
  const [rating, setRating] = useState(0);
  const [text, setText] = useState("");
  const [done, setDone] = useState(false);

  // editing an existing review starts from what was sent
  useEffect(() => {
    if (booking.data?.rating) {
      setRating(booking.data.rating);
      setText(booking.data.review_text ?? "");
    }
  }, [booking.data]);

  useBackButton(() => navigate("/bookings"));
  useMainButton({
    text: t("review.send"),
    visible: Boolean(booking.data?.can_review) && !done,
    enabled: rating > 0,
    loading: submit.isPending,
    onClick: () =>
      submit.mutate(
        { bookingId, rating, text },
        {
          onSuccess: () => {
            haptic.success();
            setDone(true);
          },
          onError: () => haptic.error(),
        },
      ),
  });

  const data = booking.data;
  return (
    <Screen title={t("review.title")} withMainButton back>
      {booking.isPending && <Skeleton className="h-40" />}
      {booking.isError && (
        <ErrorState error={booking.error} onRetry={() => void booking.refetch()} />
      )}
      {data && (
        <div className="space-y-4">
          <Card className="flex items-center gap-3">
            <Avatar name={data.barber.name} url={data.barber.photo_url} size={44} />
            <div className="min-w-0">
              <div className="font-medium">{data.barber.name}</div>
              <div className="truncate text-sm text-hint">
                {formatDateTime(data.start_at, tz, lang)} ·{" "}
                {data.services.map((s) => pickI18n(s.name_i18n, lang)).join(", ")}
              </div>
            </div>
          </Card>

          {done ? (
            <div className="space-y-3 py-6 text-center">
              <div className="text-4xl">🙏</div>
              <p className="font-medium">{t("review.thanks")}</p>
              <button
                type="button"
                onClick={() => navigate(`/barber/${data.barber.id}`)}
                className="text-sm text-link"
              >
                {t("profile.reviews")} →
              </button>
            </div>
          ) : data.can_review ? (
            <>
              <p className="text-center font-medium">{t("review.rate")}</p>
              <StarInput
                value={rating}
                onChange={(n) => {
                  haptic.select();
                  setRating(n);
                }}
              />
              <textarea
                value={text}
                maxLength={1000}
                rows={4}
                placeholder={t("review.text")}
                onChange={(e) => setText(e.target.value)}
                className="w-full rounded-xl bg-section p-3 text-sm outline-none ring-button focus:ring-2"
              />
              {submit.isError && (
                <p className="text-sm text-destructive" role="alert">
                  {submit.error instanceof ApiError ? submit.error.message : t("error.generic")}
                </p>
              )}
            </>
          ) : (
            <p className="py-6 text-center text-hint">{t("review.unavailable")}</p>
          )}
        </div>
      )}
    </Screen>
  );
}
