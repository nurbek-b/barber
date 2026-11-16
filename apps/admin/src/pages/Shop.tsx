import type { components } from "@barber/api-client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ImagePlus } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { FileButton } from "@/components/FileButton";
import { MoneyInput } from "@/components/MoneyInput";
import {
  Badge,
  Button,
  Card,
  CardContent,
  Dialog,
  DialogContent,
  Field,
  Input,
  Switch,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui";
import { PageHeader } from "@/features/Layout";
import { pickName } from "@/features/queries";
import { ADMIN, api, call, errorMessage } from "@/lib/api";
import { Can, useCan } from "@/lib/auth";
import { useFormat } from "@/lib/format";

type Order = components["schemas"]["AdminOrderOut"];
type Product = components["schemas"]["ProductOut"];
type Status = Order["status"];

const STATUS_VARIANT = {
  new: "outline",
  payment_claimed: "warning",
  paid: "default",
  ready: "success",
  completed: "secondary",
  cancelled: "destructive",
} as const;
const STATUS_LABEL = {
  new: "shop.new",
  payment_claimed: "shop.payment_claimed",
  paid: "shop.paid",
  ready: "shop.readyStatus",
  completed: "shop.completed",
  cancelled: "shop.cancelled",
} as const;
const OPEN: Status[] = ["new", "payment_claimed", "paid", "ready"];

export default function ShopPage() {
  const { t } = useTranslation();
  return (
    <div>
      <PageHeader title={t("nav.shop")} />
      <p className="mb-4 text-sm text-muted-foreground">{t("shop.hint")}</p>
      <Tabs defaultValue="orders" className="space-y-4">
        <TabsList>
          <TabsTrigger value="orders">{t("shop.orders")}</TabsTrigger>
          <TabsTrigger value="products">{t("shop.products")}</TabsTrigger>
        </TabsList>
        <TabsContent value="orders">
          <Orders />
        </TabsContent>
        <TabsContent value="products">
          <Products />
        </TabsContent>
      </Tabs>
    </div>
  );
}

// ---------------------------------------------------------------------------
// orders
// ---------------------------------------------------------------------------

function Orders() {
  const { t, i18n } = useTranslation();
  const { money, dateTime } = useFormat();
  const can = useCan();
  const client = useQueryClient();
  const [onlyOpen, setOnlyOpen] = useState(true);
  const orders = useQuery({
    queryKey: ["admin-orders", onlyOpen],
    queryFn: () =>
      call(api.GET(`${ADMIN}/orders`, { params: { query: onlyOpen ? { status: OPEN } : {} } })),
    refetchInterval: 30_000,
  });
  const onError = (error: unknown) => toast.error(errorMessage(error));
  const refresh = () => void client.invalidateQueries({ queryKey: ["admin-orders"] });
  const setStatus = useMutation({
    mutationFn: (input: { order: Order; status: Exclude<Status, "new" | "payment_claimed"> }) =>
      call(
        api.POST(`${ADMIN}/orders/{order_id}/status`, {
          params: { path: { order_id: input.order.id } },
          body: { version: input.order.version, status: input.status },
        }),
      ),
    onSuccess: refresh,
    onError,
  });
  const reject = useMutation({
    mutationFn: (order: Order) =>
      call(
        api.POST(`${ADMIN}/orders/{order_id}/reject-payment`, {
          params: { path: { order_id: order.id } },
        }),
      ),
    onSuccess: refresh,
    onError,
  });
  const writable = can("bookings:write");
  const busy = setStatus.isPending || reject.isPending;

  return (
    <Card>
      <CardContent className="space-y-3 pt-5">
        <div className="flex gap-2">
          <Button
            size="sm"
            variant={onlyOpen ? "default" : "outline"}
            onClick={() => setOnlyOpen(true)}
          >
            {t("shop.open")}
          </Button>
          <Button
            size="sm"
            variant={onlyOpen ? "outline" : "default"}
            onClick={() => setOnlyOpen(false)}
          >
            {t("shop.all")}
          </Button>
        </div>
        {orders.data?.length === 0 && (
          <p className="text-sm text-muted-foreground">{t("shop.empty")}</p>
        )}
        <div className="divide-y">
          {orders.data?.map((order) => (
            <div key={order.id} className="space-y-2 py-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <span className="font-semibold">
                    {t("shop.number")}
                    {order.number}
                  </span>{" "}
                  · {order.client_name} {order.client_phone}
                  <div className="text-xs text-muted-foreground">{dateTime(order.created_at)}</div>
                </div>
                <Badge variant={STATUS_VARIANT[order.status]}>
                  {t(STATUS_LABEL[order.status])}
                </Badge>
              </div>
              <div className="text-sm">
                {order.items
                  .map((line) => `${pickName(line.name_i18n, i18n.language)} × ${line.quantity}`)
                  .join(", ")}{" "}
                · <span className="font-medium">{money(order.total)}</span>
              </div>
              {writable && (
                <div className="flex flex-wrap gap-2">
                  {order.status === "payment_claimed" && (
                    <>
                      <Button
                        size="sm"
                        disabled={busy}
                        onClick={() => setStatus.mutate({ order, status: "paid" })}
                      >
                        ✓ {t("shop.confirmPaid")}
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={busy}
                        onClick={() => reject.mutate(order)}
                      >
                        {t("shop.reject")}
                      </Button>
                    </>
                  )}
                  {order.status === "new" && (
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={busy}
                      onClick={() => setStatus.mutate({ order, status: "paid" })}
                    >
                      {t("shop.markPaid")}
                    </Button>
                  )}
                  {order.status === "paid" && (
                    <Button
                      size="sm"
                      disabled={busy}
                      onClick={() => setStatus.mutate({ order, status: "ready" })}
                    >
                      {t("shop.ready")}
                    </Button>
                  )}
                  {(order.status === "paid" || order.status === "ready") && (
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={busy}
                      onClick={() => setStatus.mutate({ order, status: "completed" })}
                    >
                      {t("shop.complete")}
                    </Button>
                  )}
                  {OPEN.includes(order.status) && (
                    <Button
                      size="sm"
                      variant="ghost"
                      disabled={busy}
                      onClick={() => setStatus.mutate({ order, status: "cancelled" })}
                    >
                      {t("shop.cancel")}
                    </Button>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// products
// ---------------------------------------------------------------------------

function Products() {
  const { t, i18n } = useTranslation();
  const { money } = useFormat();
  const [editing, setEditing] = useState<Product | "new" | null>(null);
  const products = useQuery({
    queryKey: ["admin-products"],
    queryFn: () => call(api.GET(`${ADMIN}/products`)),
  });
  return (
    <Card>
      <CardContent className="space-y-4 pt-5">
        <div className="flex justify-end">
          <Can perm="services:write">
            <Button onClick={() => setEditing("new")}>{t("shop.newProduct")}</Button>
          </Can>
        </div>
        {products.data?.length === 0 && (
          <p className="text-sm text-muted-foreground">{t("shop.empty")}</p>
        )}
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {products.data?.map((product) => (
            <button
              key={product.id}
              type="button"
              onClick={() => setEditing(product)}
              className="flex items-center gap-3 rounded-md border p-3 text-left hover:bg-muted"
            >
              {product.photo_url ? (
                <img src={product.photo_url} alt="" className="h-14 w-14 rounded-md object-cover" />
              ) : (
                <div className="flex h-14 w-14 items-center justify-center rounded-md bg-muted">
                  <ImagePlus className="h-5 w-5 text-muted-foreground" />
                </div>
              )}
              <div className="min-w-0">
                <div className="truncate font-medium">
                  {pickName(product.name_i18n, i18n.language)}
                </div>
                <div className="text-sm text-muted-foreground">
                  {money(product.price)}
                  {product.stock !== null && product.stock !== undefined && ` · ${product.stock}`}
                </div>
                {!product.is_active && <Badge variant="secondary">{t("shop.cancelled")}</Badge>}
              </div>
            </button>
          ))}
        </div>
      </CardContent>
      {editing && (
        <ProductDialog
          product={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
        />
      )}
    </Card>
  );
}

function ProductDialog({ product, onClose }: { product: Product | null; onClose: () => void }) {
  const { t } = useTranslation();
  const can = useCan();
  const writable = can("services:write");
  const client = useQueryClient();
  const [name, setName] = useState({
    ru: product?.name_i18n.ru ?? "",
    ky: product?.name_i18n.ky ?? "",
    en: product?.name_i18n.en ?? "",
  });
  const [price, setPrice] = useState<number | null>(product?.price ?? null);
  const [stock, setStock] = useState(product?.stock?.toString() ?? "");
  const [active, setActive] = useState(product?.is_active ?? true);
  const [current, setCurrent] = useState(product);
  const refresh = () => void client.invalidateQueries({ queryKey: ["admin-products"] });
  const save = useMutation({
    mutationFn: () => {
      const body = {
        name_i18n: Object.fromEntries(Object.entries(name).filter(([, v]) => v.trim())),
        price: price!,
        stock: stock.trim() === "" ? null : Number(stock),
        is_active: active,
        sort_order: current?.sort_order ?? 0,
      };
      return current
        ? call(
            api.PUT(`${ADMIN}/products/{product_id}`, {
              params: { path: { product_id: current.id } },
              body,
            }),
          )
        : call(api.POST(`${ADMIN}/products`, { body }));
    },
    onSuccess: (saved) => {
      toast.success(t("common.saved"));
      setCurrent(saved);
      refresh();
    },
    onError: (error) => toast.error(errorMessage(error)),
  });
  const photo = useMutation({
    mutationFn: (file: File) => {
      const form = new FormData();
      form.append("file", file);
      return call(
        api.POST(`${ADMIN}/products/{product_id}/photo`, {
          params: { path: { product_id: current!.id } },
          body: form as never,
          bodySerializer: (body: unknown) => body as FormData,
        }),
      );
    },
    onSuccess: (saved) => {
      setCurrent(saved);
      refresh();
    },
    onError: (error) => toast.error(errorMessage(error)),
  });
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent title={current ? pickName(current.name_i18n, "ru") : t("shop.newProduct")}>
        <div className="space-y-3">
          {(["ru", "ky", "en"] as const).map((lang) => (
            <Field key={lang} label={`${t("shop.name")} (${lang})`} htmlFor={`p-name-${lang}`}>
              <Input
                id={`p-name-${lang}`}
                value={name[lang]}
                disabled={!writable}
                onChange={(e) => setName({ ...name, [lang]: e.target.value })}
              />
            </Field>
          ))}
          <div className="grid grid-cols-2 gap-3">
            <Field label={t("shop.price")} htmlFor="p-price">
              <MoneyInput id="p-price" value={price} onChange={setPrice} />
            </Field>
            <Field label={t("shop.stock")} htmlFor="p-stock">
              <Input
                id="p-stock"
                type="number"
                min={0}
                value={stock}
                disabled={!writable}
                onChange={(e) => setStock(e.target.value)}
              />
            </Field>
          </div>
          <label className="flex items-center justify-between text-sm">
            {t("shop.active")}
            <Switch checked={active} disabled={!writable} onCheckedChange={setActive} />
          </label>
          {current && (
            <div className="flex items-center gap-3">
              {current.photo_url && (
                <img src={current.photo_url} alt="" className="h-16 w-16 rounded-md object-cover" />
              )}
              {writable && (
                <FileButton
                  accept="image/jpeg,image/png,image/webp"
                  variant="outline"
                  loading={photo.isPending}
                  onFile={(file) => photo.mutate(file)}
                >
                  <ImagePlus /> {t("shop.photo")}
                </FileButton>
              )}
            </div>
          )}
          {writable && (
            <Button
              disabled={!name.ru.trim() || !price}
              loading={save.isPending}
              onClick={() => save.mutate()}
            >
              {t("common.save")}
            </Button>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
