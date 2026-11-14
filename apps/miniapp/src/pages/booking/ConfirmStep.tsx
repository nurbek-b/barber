import type { Slot } from "@barber/api-client";
import { formatDateTime, formatTime } from "@barber/ui";
import { useEffect, useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";

import {
  ApiError,
  newIdempotencyKey,
  placeHold,
  useCreateBooking,
  useMe,
  useReschedule,
  useSavePhone,
} from "../../api";
import { PriceSummary, bonusToSpend } from "../../components/PriceSummary";
import { Avatar, Card, Screen, useTimezone } from "../../components/ui";
import { useLang, useT } from "../../i18n";
import { barberParam, useBooking } from "../../store/booking";
import { haptic, requestSignedContact } from "../../telegram/sdk";
import { useBackButton, useMainButton } from "../../telegram/hooks";

function useCountdown(until: string | undefined): number {
  const [left, setLeft] = useState(() => (until ? Date.parse(until) - Date.now() : 0));
  useEffect(() => {
    if (!until) return;
    const tick = () => setLeft(Date.parse(until) - Date.now());
    tick();
    const id = window.setInterval(tick, 1000);
    return () => window.clearInterval(id);
  }, [until]);
  return Math.max(0, left);
}

export default function ConfirmStep() {
  const t = useT();
  const lang = useLang();
  const tz = useTimezone();
  const navigate = useNavigate();
  const me = useMe();
  const draft = useBooking();
  const create = useCreateBooking();
  const reschedule = useReschedule();
  const savePhone = useSavePhone();
  const [error, setError] = useState<string | null>(null);
  const [alternatives, setAlternatives] = useState<Slot[]>([]);
  const left = useCountdown(draft.hold?.expires_at);
  const expired = Boolean(draft.hold) && left <= 0;
  const isReschedule = Boolean(draft.rescheduleBookingId);
  const needsPhone = !isReschedule && me.data !== undefined && !me.data.phone;
  const busy = create.isPending || reschedule.isPending || savePhone.isPending;

  useBackButton();

  const submit = async () => {
    const hold = draft.hold;
    if (!hold) return;
    setError(null);
    try {
      if (isReschedule && draft.rescheduleBookingId) {
        await reschedule.mutateAsync({
          bookingId: draft.rescheduleBookingId,
          holdId: hold.hold_id,
        });
      } else {
        await create.mutateAsync({
          holdId: hold.hold_id,
          comment: draft.comment.trim() || null,
          bonusToSpend: bonusToSpend(hold.quote, draft.useBonus),
          idempotencyKey: draft.ensureIdempotencyKey(newIdempotencyKey),
        });
      }
      haptic.success();
      navigate("/book/done", { replace: true, state: { rescheduled: isReschedule } });
    } catch (caught) {
      haptic.error();
      if (caught instanceof ApiError) {
        if (caught.code === "slot_conflict") {
          setAlternatives((caught.details.alternatives as Slot[] | undefined) ?? []);
          draft.clearHold();
        }
        if (caught.code === "hold_expired") draft.clearHold();
        setError(caught.isNetwork ? t("error.network") : caught.message);
      } else {
        setError(t("error.generic"));
      }
    }
  };

  const sharePhone = async () => {
    const contact = await requestSignedContact();
    if (contact) {
      await savePhone.mutateAsync(contact).catch(() => setError(t("error.generic")));
    } else {
      // the bot also receives the contact: give it a moment, then refresh the profile
      window.setTimeout(() => void me.refetch(), 1500);
    }
  };

  const pickAlternative = async (slot: Slot) => {
    setError(null);
    try {
      const placed = await placeHold({
        barberId: barberParam(draft.barber),
        serviceIds: draft.serviceIds,
        startAt: slot.start_at,
        rescheduleBookingId: draft.rescheduleBookingId,
      });
      draft.setHold(slot, placed);
      setAlternatives([]);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : t("error.generic"));
    }
  };

  useMainButton({
    text: needsPhone
      ? t("confirm.sharePhone")
      : isReschedule
        ? t("button.reschedule")
        : t("button.book"),
    visible: Boolean(draft.hold) && !expired,
    enabled: !busy,
    loading: busy,
    onClick: () => void (needsPhone ? sharePhone() : submit()),
  });

  if (!draft.hold && alternatives.length === 0 && !error) {
    return <Navigate to="/book/time" replace />;
  }
  const hold = draft.hold;
  const minutes = Math.floor(left / 60_000);
  const seconds = Math.floor((left % 60_000) / 1000);

  return (
    <Screen
      title={t("step.confirm")}
      step={isReschedule ? 2 : 4}
      totalSteps={isReschedule ? 2 : 4}
      withMainButton
      back
    >
      <div className="space-y-3">
        {hold && (
          <>
            <Card className="flex items-center gap-3">
              <Avatar name={hold.barber.name} url={hold.barber.photo_url} />
              <div>
                <div className="text-sm text-hint">{t("confirm.barber")}</div>
                <div className="font-medium">{hold.barber.name}</div>
                <div className="mt-1 font-semibold">{formatDateTime(hold.start_at, tz, lang)}</div>
              </div>
            </Card>
            <Card>
              <PriceSummary
                quote={hold.quote}
                useBonus={draft.useBonus}
                onToggleBonus={draft.setUseBonus}
              />
            </Card>
            {!isReschedule && (
              <Card>
                <label className="block">
                  <span className="mb-1 block text-sm text-hint">{t("confirm.comment")}</span>
                  <textarea
                    value={draft.comment}
                    maxLength={500}
                    rows={2}
                    placeholder={t("confirm.commentPlaceholder")}
                    onChange={(event) => draft.setComment(event.target.value)}
                    className="w-full resize-none rounded-xl bg-bg-secondary p-3 outline-none"
                  />
                </label>
                <div className="mt-3 flex items-center justify-between text-sm">
                  <span className="text-hint">{t("confirm.phone")}</span>
                  <span>{me.data?.phone ?? "—"}</span>
                </div>
                {needsPhone && (
                  <p className="mt-2 text-xs text-hint">{t("confirm.phoneRequired")}</p>
                )}
              </Card>
            )}
            <p className={`text-center text-xs ${expired ? "text-destructive" : "text-hint"}`}>
              {expired
                ? t("confirm.expired")
                : t("confirm.expires", { time: `${minutes}:${String(seconds).padStart(2, "0")}` })}
            </p>
          </>
        )}
        {error && (
          <p
            className="rounded-xl bg-destructive/10 px-3 py-2 text-sm text-destructive"
            role="alert"
          >
            {error}
          </p>
        )}
        {alternatives.length > 0 && (
          <div>
            <p className="mb-2 text-sm text-hint">{t("confirm.alternatives")}</p>
            <div className="flex flex-wrap gap-2">
              {alternatives.map((slot) => (
                <button
                  key={slot.start_at}
                  type="button"
                  onClick={() => void pickAlternative(slot)}
                  className="rounded-xl bg-section px-4 py-2 font-medium tabular-nums"
                >
                  {formatTime(slot.start_at, tz)}
                </button>
              ))}
            </div>
          </div>
        )}
        {(expired || (!hold && alternatives.length === 0)) && (
          <button
            type="button"
            onClick={() => navigate("/book/time", { replace: true })}
            className="w-full rounded-xl bg-section py-3 font-medium text-link"
          >
            {t("step.time")}
          </button>
        )}
      </div>
    </Screen>
  );
}
