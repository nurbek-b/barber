import type { AdminBooking, components } from "@barber/api-client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ImagePlus, Trash2 } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { FileButton } from "@/components/FileButton";
import { MoneyInput } from "@/components/MoneyInput";
import { Badge, Button, Card, CardContent, Field, Input, NativeSelect } from "@/components/ui";
import { ADMIN, api, call, errorMessage } from "@/lib/api";
import { salonKey, useFormat } from "@/lib/format";

import { invalidateBookings } from "./BookingDialogs";

type Salon = components["schemas"]["SalonSettingsOut"];
type Payment = components["schemas"]["PaymentOut"];
type Method = Payment["method"];
export type PaymentState = AdminBooking["payment_status"];

const IMAGES = "image/jpeg,image/png,image/webp";
const multipart = { bodySerializer: (body: unknown) => body as FormData };

function formOf(file: File): FormData {
  const form = new FormData();
  form.append("file", file);
  return form;
}

export const PAYMENT_VARIANT = {
  unpaid: "outline",
  claimed: "warning",
  partial: "default",
  paid: "success",
} as const;

export function PaymentBadge({ state }: { state: PaymentState | undefined }) {
  const { t } = useTranslation();
  if (!state || state === "unpaid") return null;
  return <Badge variant={PAYMENT_VARIANT[state]}>💳 {t(`pay.${state}`)}</Badge>;
}

const ROW_LABEL = {
  claimed: "pay.rowClaimed",
  confirmed: "pay.rowConfirmed",
  rejected: "pay.rowRejected",
} as const;

/** Payments of a booking: client "I paid" claims to check, deposits the salon received. */
export function BookingPayments({ booking }: { booking: AdminBooking }) {
  const { t } = useTranslation();
  const { money, dateTime } = useFormat();
  const client = useQueryClient();
  const key = ["payments", booking.id];
  const payments = useQuery({
    queryKey: key,
    queryFn: () =>
      call(
        api.GET(`${ADMIN}/bookings/{booking_id}/payments`, {
          params: { path: { booking_id: booking.id } },
        }),
      ),
  });
  const [received, setReceived] = useState<Record<string, number | null>>({});
  const [amount, setAmount] = useState<number | null>(null);
  const [method, setMethod] = useState<Method>("transfer");

  const done = (message: string) => () => {
    toast.success(message);
    void client.invalidateQueries({ queryKey: key });
    invalidateBookings(client);
  };
  const onError = (error: unknown) => toast.error(errorMessage(error));
  const confirm = useMutation({
    mutationFn: (payment: Payment) =>
      call(
        api.POST(`${ADMIN}/payments/{payment_id}/confirm`, {
          params: { path: { payment_id: payment.id } },
          body: { amount: received[payment.id] ?? null },
        }),
      ),
    onSuccess: done(t("pay.saved")),
    onError,
  });
  const reject = useMutation({
    mutationFn: (payment: Payment) =>
      call(
        api.POST(`${ADMIN}/payments/{payment_id}/reject`, {
          params: { path: { payment_id: payment.id } },
        }),
      ),
    onSuccess: done(t("pay.rejected")),
    onError,
  });
  const add = useMutation({
    mutationFn: () =>
      call(
        api.POST(`${ADMIN}/bookings/{booking_id}/payments`, {
          params: { path: { booking_id: booking.id } },
          body: { amount: amount!, method },
        }),
      ),
    onSuccess: () => {
      setAmount(null);
      done(t("pay.saved"))();
    },
    onError,
  });

  const rows = payments.data ?? [];
  // from the list, not the booking prop: it stays fresh while the dialog is open
  const prepaid = rows
    .filter((p) => p.status === "confirmed")
    .reduce((sum, p) => sum + p.amount, 0);
  const open = booking.status === "pending" || booking.status === "confirmed";
  if (!open && rows.length === 0) return null;

  return (
    <div className="space-y-2 rounded-md border p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-medium">{t("pay.title")}</span>
        {booking.prepay_due > 0 && (
          <Badge variant={prepaid >= booking.prepay_due ? "success" : "warning"}>
            {t("pay.prepayDue")}: {money(booking.prepay_due)}
          </Badge>
        )}
      </div>
      <div className="flex justify-between text-muted-foreground">
        <span>{t("pay.prepaid")}</span>
        <span>
          {money(prepaid)} · {t("pay.left")} {money(Math.max(0, booking.total_due - prepaid))}
        </span>
      </div>
      {payments.isSuccess && rows.length === 0 && (
        <p className="text-muted-foreground">{t("pay.none")}</p>
      )}
      {rows.map((payment) => (
        <div key={payment.id} className="space-y-2 rounded-md bg-muted/50 p-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span>
              {money(payment.amount)} · {t(`payment.${payment.method}`)}
              {payment.note ? ` · ${payment.note}` : ""}
            </span>
            <Badge
              variant={
                payment.status === "confirmed"
                  ? "success"
                  : payment.status === "claimed"
                    ? "warning"
                    : "destructive"
              }
            >
              {t(ROW_LABEL[payment.status])}
            </Badge>
          </div>
          <div className="text-xs text-muted-foreground">{dateTime(payment.created_at)}</div>
          {payment.status === "claimed" && (
            <div className="flex flex-wrap items-end gap-2">
              <div className="w-36">
                <MoneyInput
                  aria-label={t("pay.received")}
                  value={received[payment.id] ?? payment.amount}
                  onChange={(value) => setReceived((r) => ({ ...r, [payment.id]: value }))}
                />
              </div>
              <Button size="sm" loading={confirm.isPending} onClick={() => confirm.mutate(payment)}>
                ✓ {t("pay.confirm")}
              </Button>
              <Button
                size="sm"
                variant="outline"
                loading={reject.isPending}
                onClick={() => reject.mutate(payment)}
              >
                {t("pay.reject")}
              </Button>
            </div>
          )}
        </div>
      ))}
      {open && (
        <div className="flex flex-wrap items-end gap-2 border-t pt-2">
          <div className="w-36">
            <MoneyInput aria-label={t("pay.amount")} value={amount} onChange={setAmount} />
          </div>
          <NativeSelect
            aria-label={t("booking.paymentMethod")}
            value={method}
            onChange={(e) => setMethod(e.target.value as Method)}
            className="w-36"
          >
            {(["transfer", "cash", "card"] as const).map((m) => (
              <option key={m} value={m}>
                {t(`payment.${m}`)}
              </option>
            ))}
          </NativeSelect>
          <Button
            size="sm"
            variant="outline"
            disabled={!amount}
            loading={add.isPending}
            onClick={() => add.mutate()}
          >
            {t("pay.add")}
          </Button>
        </div>
      )}
    </div>
  );
}

/** A QR image with upload / remove buttons (salon or barber). */
export function QrUpload({
  url,
  label,
  writable,
  uploading,
  removing,
  onUpload,
  onRemove,
}: {
  url: string | null | undefined;
  label: string;
  writable: boolean;
  uploading: boolean;
  removing: boolean;
  onUpload: (file: File) => void;
  onRemove: () => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-wrap items-center gap-4">
      {url ? (
        <img
          src={url}
          alt={label}
          className="h-32 w-32 rounded-xl border bg-white object-contain p-1"
        />
      ) : (
        <div className="flex h-32 w-32 items-center justify-center rounded-xl border border-dashed text-muted-foreground">
          <ImagePlus className="h-6 w-6" />
        </div>
      )}
      {writable && (
        <div className="flex flex-wrap gap-2">
          <FileButton accept={IMAGES} loading={uploading} onFile={onUpload}>
            {t("pay.upload")}
          </FileButton>
          {url && (
            <Button variant="outline" size="sm" loading={removing} onClick={onRemove}>
              <Trash2 />
              {t("pay.remove")}
            </Button>
          )}
        </div>
      )}
    </div>
  );
}

/** Settings card: the salon QR, the hint next to it and the prepayment rules. */
export function PaymentSettingsCard({
  salon,
  form,
  writable,
  set,
}: {
  salon: Salon;
  form: Salon;
  writable: boolean;
  set: <K extends keyof Salon>(key: K, value: Salon[K]) => void;
}) {
  const { t } = useTranslation();
  const client = useQueryClient();
  // only the QR fields: an upload must not overwrite unsaved edits in the form
  const onSuccess = (data: Salon) =>
    client.setQueryData<Salon>(salonKey, (old) =>
      old ? { ...old, payment_qr_url: data.payment_qr_url } : data,
    );
  const onError = (error: unknown) => toast.error(errorMessage(error));
  const upload = useMutation({
    mutationFn: (file: File) =>
      call(
        api.POST(`${ADMIN}/settings/salon/payment-qr`, {
          body: formOf(file) as never,
          ...multipart,
        }),
      ),
    onSuccess,
    onError,
  });
  const remove = useMutation({
    mutationFn: () => call(api.DELETE(`${ADMIN}/settings/salon/payment-qr`)),
    onSuccess,
    onError,
  });
  const int = (
    key: "prepay_percent" | "prepay_after_no_shows" | "prepay_timeout_min",
    label: string,
  ) => (
    <Field label={label} htmlFor={key}>
      <Input
        id={key}
        type="number"
        min={0}
        value={form[key] ?? 0}
        disabled={!writable}
        onChange={(e) => set(key, Number(e.target.value))}
      />
    </Field>
  );

  return (
    <Card>
      <CardContent className="space-y-5 pt-5">
        <p className="text-sm text-muted-foreground">{t("pay.qrHint")}</p>
        <section className="space-y-2">
          <h3 className="font-medium">{t("pay.salonQr")}</h3>
          <QrUpload
            url={salon.payment_qr_url}
            label={t("pay.salonQr")}
            writable={writable}
            uploading={upload.isPending}
            removing={remove.isPending}
            onUpload={(file) => upload.mutate(file)}
            onRemove={() => remove.mutate()}
          />
        </section>
        <Field label={t("pay.note")} htmlFor="payment-note">
          <Input
            id="payment-note"
            maxLength={300}
            value={form.payment_note ?? ""}
            disabled={!writable}
            onChange={(e) => set("payment_note", e.target.value || null)}
          />
        </Field>
        <div className="grid gap-4 md:grid-cols-3">
          {int("prepay_percent", t("pay.percent"))}
          {int("prepay_after_no_shows", t("pay.after"))}
          {int("prepay_timeout_min", t("pay.timeout"))}
        </div>
      </CardContent>
    </Card>
  );
}

/** The barber's own bank QR, uploaded by the owner. */
export function BarberQr({
  barberId,
  url,
  writable,
  onChanged,
}: {
  barberId: string;
  url: string | null | undefined;
  writable: boolean;
  onChanged: () => void;
}) {
  const { t } = useTranslation();
  const onError = (error: unknown) => toast.error(errorMessage(error));
  const upload = useMutation({
    mutationFn: (file: File) =>
      call(
        api.POST(`${ADMIN}/barbers/{barber_id}/payment-qr`, {
          params: { path: { barber_id: barberId } },
          body: formOf(file) as never,
          ...multipart,
        }),
      ),
    onSuccess: onChanged,
    onError,
  });
  const remove = useMutation({
    mutationFn: () =>
      call(
        api.DELETE(`${ADMIN}/barbers/{barber_id}/payment-qr`, {
          params: { path: { barber_id: barberId } },
        }),
      ),
    onSuccess: onChanged,
    onError,
  });
  return (
    <div className="space-y-2 rounded-md border p-3">
      <div className="text-sm font-medium">{t("pay.barberQr")}</div>
      <QrUpload
        url={url}
        label={t("pay.barberQr")}
        writable={writable}
        uploading={upload.isPending}
        removing={remove.isPending}
        onUpload={(file) => upload.mutate(file)}
        onRemove={() => remove.mutate()}
      />
      <p className="text-xs text-muted-foreground">{t("pay.barberQrHint")}</p>
    </div>
  );
}
