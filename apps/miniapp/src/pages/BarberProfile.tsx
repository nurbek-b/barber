import type { Review } from "@barber/api-client";
import { formatDate } from "@barber/ui";
import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { useBarberProfile, useBarberReviews } from "../api";
import { Stars } from "../components/Stars";
import {
  Avatar,
  Card,
  ErrorState,
  Screen,
  Skeleton,
  SkeletonList,
  useTimezone,
} from "../components/ui";
import { pickI18n, useLang, useT } from "../i18n";
import { useBooking } from "../store/booking";
import { haptic } from "../telegram/sdk";
import { useBackButton, useMainButton } from "../telegram/hooks";

/** Barber page: bio, rating, works catalogue, reviews; the main button starts a booking. */
export default function BarberProfile() {
  const { barberId = "" } = useParams();
  const t = useT();
  const lang = useLang();
  const navigate = useNavigate();
  const profile = useBarberProfile(barberId);
  const reviews = useBarberReviews(barberId);
  const reset = useBooking((state) => state.reset);
  const setBarber = useBooking((state) => state.setBarber);
  const [viewer, setViewer] = useState<number | null>(null);

  useBackButton(() => (viewer !== null ? setViewer(null) : navigate(-1)));
  useMainButton({
    text: t("profile.book"),
    visible: Boolean(profile.data) && viewer === null,
    onClick: () => {
      haptic.tap();
      reset();
      setBarber(barberId);
      navigate("/book/services");
    },
  });

  if (profile.isError) {
    return (
      <Screen title={t("step.barber")} back>
        <ErrorState error={profile.error} onRetry={() => void profile.refetch()} />
      </Screen>
    );
  }
  const barber = profile.data;
  const items = reviews.data?.pages.flatMap((page) => page.items) ?? [];
  const bio = barber ? pickI18n(barber.bio_i18n, lang) : "";

  return (
    <Screen title={barber?.name ?? t("step.barber")} withMainButton back>
      {!barber && <Skeleton className="h-40" />}
      {barber && (
        <div className="space-y-5">
          <div className="flex items-center gap-4">
            <Avatar name={barber.name} url={barber.photo_url} size={88} />
            <div className="min-w-0">
              <div className="text-sm text-hint">{pickI18n(barber.specialization_i18n, lang)}</div>
              {barber.rating !== null && barber.rating !== undefined ? (
                <div className="mt-1 flex items-center gap-2">
                  <span className="text-2xl font-semibold tabular-nums">
                    {barber.rating.toFixed(1)}
                  </span>
                  <div className="leading-tight">
                    <Stars value={barber.rating} />
                    <div className="text-xs text-hint">
                      {t("profile.reviewsCount", { n: barber.rating_count })}
                    </div>
                  </div>
                </div>
              ) : (
                <div className="mt-1 text-sm text-hint">{t("barber.noRating")}</div>
              )}
            </div>
          </div>

          {bio && <p className="whitespace-pre-line text-sm leading-relaxed">{bio}</p>}

          {barber.portfolio.length > 0 && (
            <section>
              <h2 className="mb-2 px-1 text-sm font-medium uppercase text-hint">
                {t("profile.works")}
              </h2>
              <div className="grid grid-cols-3 gap-1.5">
                {barber.portfolio.map((url, index) => (
                  <button
                    key={url}
                    type="button"
                    onClick={() => setViewer(index)}
                    className="overflow-hidden rounded-xl bg-section"
                  >
                    <img
                      src={url}
                      alt=""
                      loading="lazy"
                      className="aspect-square w-full object-cover"
                    />
                  </button>
                ))}
              </div>
            </section>
          )}

          <section>
            <h2 className="mb-2 px-1 text-sm font-medium uppercase text-hint">
              {t("profile.reviews")}
            </h2>
            {reviews.isPending && <SkeletonList rows={2} height="h-20" />}
            {reviews.isSuccess && items.length === 0 && (
              <p className="py-4 text-center text-sm text-hint">{t("profile.noReviews")}</p>
            )}
            <div className="space-y-2">
              {items.map((review) => (
                <ReviewCard key={review.booking_id} review={review} />
              ))}
            </div>
            {reviews.hasNextPage && (
              <button
                type="button"
                onClick={() => void reviews.fetchNextPage()}
                disabled={reviews.isFetchingNextPage}
                className="mt-3 w-full py-2 text-sm text-link"
              >
                {t("profile.showMore")}
              </button>
            )}
          </section>
        </div>
      )}

      {barber && viewer !== null && (
        <PhotoViewer photos={barber.portfolio} start={viewer} onClose={() => setViewer(null)} />
      )}
    </Screen>
  );
}

function ReviewCard({ review }: { review: Review }) {
  const lang = useLang();
  const tz = useTimezone();
  return (
    <Card className="space-y-1.5">
      <div className="flex items-center justify-between gap-2">
        <span className="font-medium">{review.author}</span>
        <Stars value={review.rating} />
      </div>
      {review.text && <p className="whitespace-pre-line text-sm">{review.text}</p>}
      <div className="text-xs text-hint">
        {[
          formatDate(review.created_at, tz, lang),
          review.services.map((name) => pickI18n(name, lang)).join(", "),
        ]
          .filter(Boolean)
          .join(" · ")}
      </div>
    </Card>
  );
}

/** Full-screen swipeable viewer; tap anywhere to close. */
function PhotoViewer({
  photos,
  start,
  onClose,
}: {
  photos: string[];
  start: number;
  onClose: () => void;
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center bg-black/95"
      role="dialog"
      aria-modal="true"
      onClick={onClose}
    >
      <div
        className="flex w-full snap-x snap-mandatory overflow-x-auto"
        ref={(node) => {
          if (node) node.scrollLeft = node.clientWidth * start;
        }}
      >
        {photos.map((url) => (
          <img
            key={url}
            src={url}
            alt=""
            className="max-h-[85vh] w-full shrink-0 snap-center object-contain"
          />
        ))}
      </div>
    </div>
  );
}
