import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { ApiError, newIdempotencyKey, useMyOrders, usePlaceOrder, useProducts } from "../api";
import { Card, ErrorState, Screen, SkeletonList, useMoney } from "../components/ui";
import { pickI18n, useLang, useT, type MessageKey } from "../i18n";
import { ORDER_STYLE } from "../orderStyle";
import { haptic } from "../telegram/sdk";
import { useBackButton, useMainButton } from "../telegram/hooks";

/** Products of the salon with a simple cart; the order is paid by QR and picked up. */
export default function Shop() {
  const t = useT();
  const lang = useLang();
  const navigate = useNavigate();
  const { money } = useMoney();
  const products = useProducts();
  const orders = useMyOrders();
  const place = usePlaceOrder();
  const [cart, setCart] = useState<Record<string, number>>({});
  const key = useRef(newIdempotencyKey());
  const [error, setError] = useState<string | null>(null);

  const items = Object.entries(cart).filter(([, qty]) => qty > 0);
  const total = items.reduce((sum, [id, qty]) => {
    const product = products.data?.find((p) => p.id === id);
    return sum + (product ? product.price * qty : 0);
  }, 0);
  const change = (id: string, delta: number, max: number | null | undefined) => {
    haptic.select();
    setCart((c) => {
      const next = Math.max(0, Math.min((c[id] ?? 0) + delta, max ?? 99));
      return { ...c, [id]: next };
    });
  };

  useBackButton(() => navigate("/"));
  useMainButton({
    text: `${t("shop.order")} · ${money(total)}`,
    visible: items.length > 0,
    loading: place.isPending,
    onClick: () => {
      setError(null);
      place.mutate(
        {
          items: items.map(([product_id, quantity]) => ({ product_id, quantity })),
          idempotencyKey: key.current,
        },
        {
          onSuccess: (order) => {
            haptic.success();
            key.current = newIdempotencyKey();
            setCart({});
            navigate(`/order/${order.id}`);
          },
          onError: (caught) => {
            haptic.error();
            setError(caught instanceof ApiError ? caught.message : t("error.generic"));
          },
        },
      );
    },
  });

  const open = (orders.data ?? []).filter((o) => o.status !== "cancelled").slice(0, 5);

  return (
    <Screen title={t("shop.title")} withMainButton={items.length > 0} back>
      <div className="space-y-4">
        {error && (
          <p
            className="rounded-xl bg-destructive/10 px-3 py-2 text-sm text-destructive"
            role="alert"
          >
            {error}
          </p>
        )}
        {products.isPending && <SkeletonList rows={3} height="h-24" />}
        {products.isError && (
          <ErrorState error={products.error} onRetry={() => void products.refetch()} />
        )}
        {products.data?.length === 0 && (
          <p className="py-10 text-center text-hint">{t("shop.empty")}</p>
        )}
        <div className="grid grid-cols-2 gap-3">
          {products.data?.map((product) => {
            const qty = cart[product.id] ?? 0;
            return (
              <Card key={product.id} className="flex flex-col gap-2 p-3">
                {product.photo_url ? (
                  <img
                    src={product.photo_url}
                    alt=""
                    className="aspect-square w-full rounded-xl object-cover"
                    loading="lazy"
                  />
                ) : (
                  <div className="flex aspect-square w-full items-center justify-center rounded-xl bg-bg-secondary text-3xl">
                    🧴
                  </div>
                )}
                <div className="text-sm font-medium leading-tight">
                  {pickI18n(product.name_i18n, lang)}
                </div>
                {product.stock !== null && product.stock !== undefined && product.stock <= 5 && (
                  <div className="text-xs text-hint">{t("shop.left", { n: product.stock })}</div>
                )}
                <div className="mt-auto font-semibold tabular-nums">{money(product.price)}</div>
                <div className="flex items-center justify-end">
                  {qty === 0 ? (
                    <button
                      type="button"
                      aria-label="+"
                      onClick={() => change(product.id, 1, product.stock)}
                      className="h-8 w-8 rounded-full bg-button text-lg leading-none text-button-text"
                    >
                      +
                    </button>
                  ) : (
                    <span className="flex items-center gap-2">
                      <button
                        type="button"
                        aria-label="−"
                        onClick={() => change(product.id, -1, product.stock)}
                        className="h-8 w-8 rounded-full bg-bg-secondary text-lg leading-none"
                      >
                        −
                      </button>
                      <span className="w-4 text-center tabular-nums">{qty}</span>
                      <button
                        type="button"
                        aria-label="+"
                        onClick={() => change(product.id, 1, product.stock)}
                        className="h-8 w-8 rounded-full bg-button text-lg leading-none text-button-text"
                      >
                        +
                      </button>
                    </span>
                  )}
                </div>
              </Card>
            );
          })}
        </div>

        {open.length > 0 && (
          <section className="space-y-2">
            <h2 className="px-1 text-sm font-medium uppercase text-hint">{t("shop.myOrders")}</h2>
            {open.map((order) => (
              <button
                key={order.id}
                type="button"
                onClick={() => navigate(`/order/${order.id}`)}
                className="block w-full text-left"
              >
                <Card className="flex items-center justify-between gap-2">
                  <span>
                    <span className="font-medium">{t("shop.order_n", { n: order.number })}</span>
                    <span className="block text-sm text-hint">{money(order.total)}</span>
                  </span>
                  <span
                    className={`rounded-full px-2 py-0.5 text-xs ${ORDER_STYLE[order.status] ?? ""}`}
                  >
                    {t(`shop.status.${order.status}` as MessageKey)}
                  </span>
                </Card>
              </button>
            ))}
          </section>
        )}
      </div>
    </Screen>
  );
}
