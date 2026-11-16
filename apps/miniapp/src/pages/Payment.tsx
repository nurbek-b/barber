import { useNavigate, useParams } from "react-router-dom";

import { ApiError, useClaimPayment, usePaymentInfo } from "../api";
import { Card, ErrorState, Screen, Skeleton, useMoney } from "../components/ui";
import { useT } from "../i18n";
import { haptic, openLink } from "../telegram/sdk";
import { useBackButton, useMainButton } from "../telegram/hooks";

/** Pay a booking by the barber's (or salon's) bank QR, then tell the salon "I paid". */
export default function Payment() {
  const { bookingId = "" } = useParams();
  const t = useT();
  const navigate = useNavigate();
  const { money } = useMoney();
  const info = usePaymentInfo(bookingId);
  const claim = useClaimPayment();

  const data = info.data;
  const canClaim =
    Boolean(data?.qr_url) &&
    !data?.claimed &&
    data?.payment_status !== "paid" &&
    (data?.amount_left ?? 0) > 0;

  useBackButton(() => navigate("/bookings"));
  useMainButton({
    text: `${t("pay.iPaid")} · ${money(data?.amount_left ?? 0)}`,
    visible: canClaim,
    loading: claim.isPending,
    onClick: () =>
      data &&
      claim.mutate(
        { bookingId, amount: data.amount_left },
        { onSuccess: () => haptic.success(), onError: () => haptic.error() },
      ),
  });

  return (
    <Screen title={t("pay.title")} withMainButton={canClaim} back>
      {info.isPending && <Skeleton className="h-80" />}
      {info.isError && <ErrorState error={info.error} onRetry={() => void info.refetch()} />}
      {data && (
        <div className="space-y-4">
          {data.prepay_due > data.prepaid_amount && (
            <p className="rounded-xl bg-amber-500/15 px-3 py-2 text-sm">{t("pay.prepayWait")}</p>
          )}
          <Card className="space-y-2">
            <div className="flex justify-between text-sm">
              <span className="text-hint">{t("pay.total")}</span>
              <span className="tabular-nums">{money(data.total_due)}</span>
            </div>
            {data.prepaid_amount > 0 && (
              <div className="flex justify-between text-sm">
                <span className="text-hint">{t("pay.prepaid")}</span>
                <span className="tabular-nums">{money(data.prepaid_amount)}</span>
              </div>
            )}
            {data.amount_left > 0 && data.payment_status !== "paid" && (
              <div className="flex justify-between text-lg font-semibold">
                <span>{t("pay.amount")}</span>
                <span className="tabular-nums">{money(data.amount_left)}</span>
              </div>
            )}
          </Card>

          {data.payment_status === "paid" ? (
            <p className="py-6 text-center text-lg font-medium">✅ {t("pay.paid")}</p>
          ) : data.claimed ? (
            <p className="rounded-xl bg-section p-4 text-center">⏳ {t("pay.claimed")}</p>
          ) : !data.qr_url ? (
            <p className="py-6 text-center text-hint">{t("pay.noQr")}</p>
          ) : (
            <Card className="space-y-3 text-center">
              <img
                src={data.qr_url}
                alt="QR"
                className="mx-auto aspect-square w-full max-w-[280px] rounded-xl bg-white object-contain p-2"
              />
              {data.note && <p className="font-medium">{data.note}</p>}
              <p className="text-sm text-hint">{t("pay.howTo")}</p>
              <button
                type="button"
                onClick={() => openLink(new URL(data.qr_url!, window.location.href).href)}
                className="text-sm text-link"
              >
                {t("pay.saveQr")}
              </button>
            </Card>
          )}
          {claim.isError && (
            <p className="text-sm text-destructive" role="alert">
              {claim.error instanceof ApiError ? claim.error.message : t("error.generic")}
            </p>
          )}
        </div>
      )}
    </Screen>
  );
}
