import { useNavigate, useParams } from "react-router-dom";

import { ApiError, useMyOrders, useOrderAction, useOrderPayment } from "../api";
import { Card, ErrorState, Screen, Skeleton, useMoney } from "../components/ui";
import { pickI18n, useLang, useT, type MessageKey } from "../i18n";
import { haptic, openLink } from "../telegram/sdk";
import { useBackButton, useMainButton } from "../telegram/hooks";
import { ORDER_STYLE } from "../orderStyle";

/** One order: items, status, the salon QR and "I paid". */
export default function Order() {
  const { orderId = "" } = useParams();
  const t = useT();
  const lang = useLang();
  const navigate = useNavigate();
  const { money } = useMoney();
  const payment = useOrderPayment(orderId);
  const orders = useMyOrders();
  const claim = useOrderAction("payment");
  const cancel = useOrderAction("cancel");
  const order = orders.data?.find((o) => o.id === orderId);
  const data = payment.data;
  const canClaim = data?.status === "new" && Boolean(data.qr_url) && data.amount_left > 0;

  useBackButton(() => navigate("/shop"));
  useMainButton({
    text: `${t("pay.iPaid")} · ${money(data?.amount_left ?? 0)}`,
    visible: canClaim,
    loading: claim.isPending,
    onClick: () =>
      claim.mutate(orderId, { onSuccess: () => haptic.success(), onError: () => haptic.error() }),
  });

  const error = claim.error ?? cancel.error;
  return (
    <Screen
      title={order ? t("shop.order_n", { n: order.number }) : t("shop.title")}
      withMainButton={canClaim}
      back
    >
      {(payment.isPending || orders.isPending) && <Skeleton className="h-60" />}
      {payment.isError && (
        <ErrorState error={payment.error} onRetry={() => void payment.refetch()} />
      )}
      {data && order && (
        <div className="space-y-4">
          <Card className="space-y-2">
            <div className="flex justify-end">
              <span
                className={`rounded-full px-2 py-0.5 text-xs ${ORDER_STYLE[data.status] ?? ""}`}
              >
                {t(`shop.status.${data.status}` as MessageKey)}
              </span>
            </div>
            {order.items.map((line) => (
              <div
                key={`${line.product_id}-${line.price}`}
                className="flex justify-between text-sm"
              >
                <span>
                  {pickI18n(line.name_i18n, lang)} × {line.quantity}
                </span>
                <span className="tabular-nums">{money(line.price * line.quantity)}</span>
              </div>
            ))}
            <div className="flex justify-between border-t border-bg-secondary pt-2 font-semibold">
              <span>{t("pay.amount")}</span>
              <span className="tabular-nums">{money(data.total)}</span>
            </div>
          </Card>

          {data.status === "payment_claimed" && (
            <p className="rounded-xl bg-section p-4 text-center">⏳ {t("pay.claimed")}</p>
          )}
          {(data.status === "paid" || data.status === "ready") && (
            <p className="rounded-xl bg-section p-4 text-center">✅ {t("shop.pickup")}</p>
          )}
          {data.status === "new" &&
            (data.qr_url ? (
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
            ) : (
              <p className="py-6 text-center text-hint">{t("pay.noQr")}</p>
            ))}
          {data.status === "new" && (
            <button
              type="button"
              onClick={() => cancel.mutate(orderId)}
              disabled={cancel.isPending}
              className="w-full py-3 text-sm text-destructive"
            >
              {t("shop.cancel")}
            </button>
          )}
          {error && (
            <p className="text-sm text-destructive" role="alert">
              {error instanceof ApiError ? error.message : t("error.generic")}
            </p>
          )}
        </div>
      )}
    </Screen>
  );
}
