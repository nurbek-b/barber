import type { AdminBooking } from "@barber/api-client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { MoneyInput } from "@/components/MoneyInput";
import { Button, Input, NativeSelect } from "@/components/ui";
import { ADMIN, api, call, errorMessage } from "@/lib/api";
import { useFormat } from "@/lib/format";

import { invalidateBookings } from "./BookingDialogs";

/** Apply a gift certificate or a subscription visit to an open booking; undo either. */
export function BookingVouchers({ booking }: { booking: AdminBooking }) {
  const { t } = useTranslation();
  const { money } = useFormat();
  const client = useQueryClient();
  const key = ["vouchers", booking.id];
  const [code, setCode] = useState("");
  const [amount, setAmount] = useState<number | null>(null);
  const [subId, setSubId] = useState("");
  const open = booking.status === "pending" || booking.status === "confirmed";

  const uses = useQuery({
    queryKey: key,
    queryFn: () =>
      call(
        api.GET(`${ADMIN}/bookings/{booking_id}/vouchers`, {
          params: { path: { booking_id: booking.id } },
        }),
      ),
  });
  const subs = useQuery({
    queryKey: ["subscriptions", booking.client?.id],
    enabled: Boolean(booking.client?.id) && open,
    queryFn: () =>
      call(
        api.GET(`${ADMIN}/subscriptions`, {
          params: { query: { client_id: booking.client!.id } },
        }),
      ),
    select: (rows) => rows.filter((s) => s.state === "active"),
  });
  const done = () => {
    void client.invalidateQueries({ queryKey: key });
    void client.invalidateQueries({ queryKey: ["subscriptions"] });
    void client.invalidateQueries({ queryKey: ["certificates"] });
    invalidateBookings(client);
  };
  const onError = (error: unknown) => toast.error(errorMessage(error));
  const applyCert = useMutation({
    mutationFn: () =>
      call(
        api.POST(`${ADMIN}/bookings/{booking_id}/vouchers/certificate`, {
          params: { path: { booking_id: booking.id } },
          body: { code: code.trim(), amount },
        }),
      ),
    onSuccess: () => {
      setCode("");
      setAmount(null);
      done();
    },
    onError,
  });
  const applySub = useMutation({
    mutationFn: (id: string) =>
      call(
        api.POST(`${ADMIN}/bookings/{booking_id}/vouchers/subscription`, {
          params: { path: { booking_id: booking.id } },
          body: { subscription_id: id },
        }),
      ),
    onSuccess: done,
    onError,
  });
  const undo = useMutation({
    mutationFn: (id: string) =>
      call(api.DELETE(`${ADMIN}/vouchers/{use_id}`, { params: { path: { use_id: id } } })),
    onSuccess: done,
    onError,
  });

  const rows = uses.data ?? [];
  if (!open && rows.length === 0) return null;
  const active = subs.data ?? [];
  const chosen = subId || active[0]?.id || "";

  return (
    <div className="space-y-2 rounded-md border p-3">
      <span className="font-medium">{t("vouchers.onBooking")}</span>
      {rows.map((use) => (
        <div key={use.id} className="flex items-center justify-between gap-2 text-sm">
          <span>
            {use.kind === "certificate" ? "🎁" : "🎟"} {use.label} · {t("vouchers.covered")}{" "}
            {money(use.amount)}
          </span>
          {open && (
            <Button
              size="sm"
              variant="ghost"
              loading={undo.isPending && undo.variables === use.id}
              onClick={() => undo.mutate(use.id)}
            >
              {t("vouchers.undo")}
            </Button>
          )}
        </div>
      ))}
      {open && (
        <div className="flex flex-wrap items-end gap-2">
          <Input
            aria-label={t("vouchers.applyCode")}
            placeholder="GIFT-XXXX-XXXX"
            className="w-44 font-mono"
            value={code}
            onChange={(e) => setCode(e.target.value)}
          />
          <div className="w-32">
            <MoneyInput
              aria-label={t("vouchers.amount")}
              placeholder={t("vouchers.balance")}
              value={amount}
              onChange={setAmount}
              allowEmpty
            />
          </div>
          <Button
            size="sm"
            variant="outline"
            disabled={code.trim().length < 4}
            loading={applyCert.isPending}
            onClick={() => applyCert.mutate()}
          >
            {t("vouchers.apply")}
          </Button>
        </div>
      )}
      {open && active.length > 0 && (
        <div className="flex flex-wrap items-end gap-2">
          <NativeSelect
            aria-label={t("vouchers.plan")}
            className="w-56"
            value={chosen}
            onChange={(e) => setSubId(e.target.value)}
          >
            {active.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name} · {s.visits_left}/{s.visits_total}
              </option>
            ))}
          </NativeSelect>
          <Button
            size="sm"
            variant="outline"
            loading={applySub.isPending}
            onClick={() => applySub.mutate(chosen)}
          >
            {t("vouchers.applySub")}
          </Button>
        </div>
      )}
    </div>
  );
}
