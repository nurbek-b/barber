import type { AdminBooking } from "@barber/api-client";
import { formatTime } from "@barber/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { MoneyInput } from "@/components/MoneyInput";
import {
  Badge,
  Button,
  Dialog,
  DialogContent,
  Field,
  Input,
  NativeSelect,
  Switch,
  Textarea,
} from "@/components/ui";
import { ADMIN, api, call, errorMessage } from "@/lib/api";
import { useCan } from "@/lib/auth";
import { useFormat } from "@/lib/format";
import { fromWallClock, toWallClock, wallDayKey } from "@/lib/zoned";

import { BookingPayments, PaymentBadge } from "./Payments";
import { BookingVouchers } from "./Vouchers";
import { pickName, STATUS_VARIANT, useBarbersList } from "./queries";

export function invalidateBookings(client: ReturnType<typeof useQueryClient>): void {
  for (const key of [["calendar"], ["bookings"], ["dashboard"], ["clients"], ["finance"]]) {
    void client.invalidateQueries({ queryKey: key });
  }
}

type PaymentMethod = "cash" | "card" | "transfer" | "mixed";

// ---------------------------------------------------------------------------
// create
// ---------------------------------------------------------------------------

export interface CreateDefaults {
  barberId?: string;
  start?: Date; // UTC instant
}

export function CreateBookingDialog({
  open,
  onOpenChange,
  defaults,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  defaults: CreateDefaults;
}) {
  const { t, i18n } = useTranslation();
  const { tz, money } = useFormat();
  const client = useQueryClient();
  const barbers = useBarbersList(true);

  const [mode, setMode] = useState<"existing" | "new">("existing");
  const [search, setSearch] = useState("");
  const [clientId, setClientId] = useState<string | null>(null);
  const [clientLabel, setClientLabel] = useState("");
  const [newName, setNewName] = useState("");
  const [newPhone, setNewPhone] = useState("");
  const [barberId, setBarberId] = useState("");
  const [serviceIds, setServiceIds] = useState<string[]>([]);
  const [day, setDay] = useState("");
  const [time, setTime] = useState("");
  const [ignoreSchedule, setIgnoreSchedule] = useState(false);
  const [notify, setNotify] = useState(true);
  const [comment, setComment] = useState("");

  useEffect(() => {
    if (!open) return;
    const wall = defaults.start ? toWallClock(defaults.start, tz) : null;
    setBarberId(defaults.barberId ?? "");
    setDay(wall ? wallDayKey(wall) : "");
    setTime(
      wall
        ? `${String(wall.getHours()).padStart(2, "0")}:${String(wall.getMinutes()).padStart(2, "0")}`
        : "",
    );
    setServiceIds([]);
    setClientId(null);
    setClientLabel("");
    setSearch("");
    setComment("");
    setIgnoreSchedule(false);
  }, [open, defaults, tz]);

  const barber = useQuery({
    queryKey: ["barbers", barberId],
    enabled: Boolean(barberId),
    queryFn: () =>
      call(api.GET(`${ADMIN}/barbers/{barber_id}`, { params: { path: { barber_id: barberId } } })),
  });
  const services = useQuery({
    queryKey: ["services", { onlyActive: true }],
    queryFn: () =>
      call(api.GET(`${ADMIN}/services`, { params: { query: { only_active: true, limit: 500 } } })),
    select: (page) => page.items,
  });
  const offered = useMemo(() => {
    const links = new Map(
      (barber.data?.services ?? []).filter((l) => l.is_active).map((l) => [l.service_id, l]),
    );
    return (services.data ?? [])
      .filter((s) => links.has(s.id))
      .map((s) => ({ service: s, link: links.get(s.id)! }));
  }, [barber.data, services.data]);

  const clients = useQuery({
    queryKey: ["clients", "search", search],
    enabled: mode === "existing" && search.trim().length >= 2 && !clientId,
    queryFn: () =>
      call(api.GET(`${ADMIN}/clients`, { params: { query: { q: search, limit: 8 } } })),
  });
  const slots = useQuery({
    queryKey: ["admin-slots", barberId, serviceIds, day],
    enabled: Boolean(barberId && day && serviceIds.length),
    queryFn: () =>
      call(
        api.GET(`${ADMIN}/availability/slots`, {
          params: { query: { date: day, barber_id: barberId, service_ids: serviceIds } },
        }),
      ),
  });

  const create = useMutation({
    mutationFn: () => {
      const [h, m] = time.split(":").map(Number);
      const [y, mo, d] = day.split("-").map(Number);
      const start = fromWallClock(new Date(y!, mo! - 1, d!, h!, m!), tz);
      return call(
        api.POST(`${ADMIN}/bookings`, {
          body: {
            client_id: mode === "existing" ? clientId : null,
            client: mode === "new" ? { name: newName, phone: newPhone } : null,
            barber_id: barberId,
            service_ids: serviceIds,
            start_at: start.toISOString(),
            status: "confirmed",
            comment: comment || null,
            ignore_schedule: ignoreSchedule,
            notify_client: notify,
          },
        }),
      );
    },
    onSuccess: () => {
      toast.success(t("booking.created"));
      invalidateBookings(client);
      onOpenChange(false);
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const total = offered
    .filter((o) => serviceIds.includes(o.service.id))
    .reduce((sum, o) => sum + o.link.effective_price, 0);
  const valid =
    barberId &&
    serviceIds.length &&
    day &&
    /^\d{2}:\d{2}$/.test(time) &&
    (mode === "existing" ? clientId : newName.trim() && newPhone.trim().length >= 7);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent title={t("calendar.newBooking")} className="max-w-2xl">
        <div className="grid gap-4 md:grid-cols-2">
          <div className="space-y-3">
            <div className="flex gap-2">
              {(["existing", "new"] as const).map((value) => (
                <Button
                  key={value}
                  type="button"
                  size="sm"
                  variant={mode === value ? "default" : "outline"}
                  onClick={() => setMode(value)}
                >
                  {t(value === "existing" ? "booking.existingClient" : "booking.newClient")}
                </Button>
              ))}
            </div>
            {mode === "existing" ? (
              clientId ? (
                <div className="flex items-center justify-between rounded-md border p-2 text-sm">
                  <span>{clientLabel}</span>
                  <Button size="sm" variant="ghost" onClick={() => setClientId(null)}>
                    ✕
                  </Button>
                </div>
              ) : (
                <div className="space-y-1">
                  <Input
                    placeholder={t("booking.searchClient")}
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    aria-label={t("booking.searchClient")}
                  />
                  {clients.data?.items.map((item) => (
                    <button
                      key={item.id}
                      type="button"
                      className="block w-full rounded px-2 py-1 text-left text-sm hover:bg-accent"
                      onClick={() => {
                        setClientId(item.id);
                        setClientLabel(`${item.name} ${item.phone ?? ""}`);
                      }}
                    >
                      {item.name} <span className="text-muted-foreground">{item.phone}</span>
                    </button>
                  ))}
                </div>
              )
            ) : (
              <>
                <Field label={t("common.name")} htmlFor="new-name">
                  <Input
                    id="new-name"
                    value={newName}
                    onChange={(e) => setNewName(e.target.value)}
                  />
                </Field>
                <Field label={t("common.phone")} htmlFor="new-phone">
                  <Input
                    id="new-phone"
                    value={newPhone}
                    onChange={(e) => setNewPhone(e.target.value)}
                    placeholder="+996"
                  />
                </Field>
              </>
            )}
            <Field label={t("booking.barber")} htmlFor="barber">
              <NativeSelect
                id="barber"
                value={barberId}
                onChange={(e) => {
                  setBarberId(e.target.value);
                  setServiceIds([]);
                }}
              >
                <option value="">—</option>
                {barbers.data?.map((b) => (
                  <option key={b.id} value={b.id}>
                    {b.name}
                  </option>
                ))}
              </NativeSelect>
            </Field>
            <Field label={t("booking.services")}>
              <div className="max-h-44 space-y-1 overflow-y-auto rounded-md border p-2">
                {offered.map(({ service, link }) => (
                  <label
                    key={service.id}
                    className="flex items-center justify-between gap-2 text-sm"
                  >
                    <span className="flex items-center gap-2">
                      <input
                        type="checkbox"
                        checked={serviceIds.includes(service.id)}
                        onChange={() =>
                          setServiceIds((ids) =>
                            ids.includes(service.id)
                              ? ids.filter((i) => i !== service.id)
                              : [...ids, service.id],
                          )
                        }
                      />
                      {pickName(service.name_i18n, i18n.language)}
                    </span>
                    <span className="text-muted-foreground">{money(link.effective_price)}</span>
                  </label>
                ))}
                {!offered.length && (
                  <p className="text-sm text-muted-foreground">{t("booking.pickSlot")}</p>
                )}
              </div>
            </Field>
          </div>
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-2">
              <Field label={t("booking.date")} htmlFor="day">
                <Input id="day" type="date" value={day} onChange={(e) => setDay(e.target.value)} />
              </Field>
              <Field label={t("booking.time")} htmlFor="time">
                <Input
                  id="time"
                  type="time"
                  step={300}
                  value={time}
                  onChange={(e) => setTime(e.target.value)}
                />
              </Field>
            </div>
            <Field label={t("booking.slots")}>
              <div className="flex max-h-32 flex-wrap gap-1 overflow-y-auto">
                {slots.data?.slots.map((slot) => {
                  const label = formatTime(slot.start_at, tz);
                  return (
                    <Button
                      key={slot.start_at}
                      type="button"
                      size="sm"
                      variant={label === time ? "default" : "outline"}
                      onClick={() => setTime(label)}
                    >
                      {label}
                    </Button>
                  );
                })}
                {slots.data && !slots.data.slots.length && (
                  <span className="text-sm text-muted-foreground">—</span>
                )}
              </div>
            </Field>
            <label className="flex items-center justify-between text-sm">
              {t("booking.ignoreSchedule")}
              <Switch checked={ignoreSchedule} onCheckedChange={setIgnoreSchedule} />
            </label>
            <label className="flex items-center justify-between text-sm">
              {t("booking.notifyClient")}
              <Switch checked={notify} onCheckedChange={setNotify} />
            </label>
            <Field label={t("common.comment")} htmlFor="comment">
              <Textarea id="comment" value={comment} onChange={(e) => setComment(e.target.value)} />
            </Field>
            <div className="flex items-center justify-between font-medium">
              <span>{t("booking.subtotal")}</span>
              <span>{money(total)}</span>
            </div>
          </div>
        </div>
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("common.cancel")}
          </Button>
          <Button disabled={!valid} loading={create.isPending} onClick={() => create.mutate()}>
            {t("common.create")}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// details / status / edit
// ---------------------------------------------------------------------------

export function BookingDetailsDialog({
  booking,
  onClose,
}: {
  booking: AdminBooking | null;
  onClose: () => void;
}) {
  const { t, i18n } = useTranslation();
  const { money, dateTime } = useFormat();
  const can = useCan();
  const client = useQueryClient();
  const [method, setMethod] = useState<PaymentMethod>("cash");
  const [paid, setPaid] = useState<number | null>(null);
  const [reason, setReason] = useState("");
  const [prices, setPrices] = useState<Record<string, number | null>>({});
  const [note, setNote] = useState("");

  useEffect(() => {
    if (!booking) return;
    // certificates / subscription visits are not money paid today; a no-show got its bonuses
    // and vouchers back, so "the client came" is paid in full
    setPaid(
      booking.status === "no_show"
        ? booking.subtotal - (booking.discount ?? 0)
        : Math.max(0, booking.total_due - (booking.voucher_amount ?? 0)),
    );
    setMethod((booking.payment_method as PaymentMethod | null) ?? "cash");
    setReason("");
    setNote(booking.admin_note ?? "");
    setPrices(Object.fromEntries(booking.services.map((s) => [s.service_id ?? "", s.price])));
  }, [booking]);

  const status = useMutation({
    mutationFn: (next: "confirmed" | "completed" | "cancelled" | "no_show") =>
      call(
        api.POST(`${ADMIN}/bookings/{booking_id}/status`, {
          params: { path: { booking_id: booking!.id } },
          body: {
            version: booking!.version,
            status: next,
            reason: next === "cancelled" ? reason || null : null,
            payment_method: next === "completed" ? method : null,
            paid_amount: next === "completed" ? paid : null,
          },
        }),
      ),
    onSuccess: (_data, next) => {
      toast.success(
        next === "no_show" && booking?.status === "no_show"
          ? t("booking.noShowConfirmed")
          : t("booking.updated"),
      );
      invalidateBookings(client);
      onClose();
    },
    onError: (error) => toast.error(errorMessage(error)),
  });
  const patch = useMutation({
    mutationFn: () =>
      call(
        api.PATCH(`${ADMIN}/bookings/{booking_id}`, {
          params: { path: { booking_id: booking!.id } },
          body: {
            version: booking!.version,
            admin_note: note || null,
            services: booking!.services
              .filter((s) => s.service_id)
              .map((s) => ({ service_id: s.service_id!, price: prices[s.service_id!] ?? null })),
          },
        }),
      ),
    onSuccess: () => {
      toast.success(t("booking.updated"));
      invalidateBookings(client);
      onClose();
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  if (!booking) return null;
  const active = booking.status === "pending" || booking.status === "confirmed";
  const canWrite = can("bookings:write");
  const canStatus = canWrite || can("bookings:status_own");
  const started = new Date(booking.start_at).getTime() <= Date.now();
  const noShow = booking.status === "no_show";
  const autoNoShow = noShow && booking.no_show_auto;

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent
        title={`${t("booking.title")} · ${dateTime(booking.start_at)}`}
        className="max-w-xl"
      >
        <div className="space-y-3 text-sm">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={STATUS_VARIANT[booking.status]}>{t(`status.${booking.status}`)}</Badge>
            {booking.client_confirmed_at && (
              <Badge variant="success">✓ {t("booking.clientConfirmed")}</Badge>
            )}
            {autoNoShow && <Badge variant="warning">⚠ {t("booking.autoNoShow")}</Badge>}
            <PaymentBadge state={booking.payment_status} />
            <span className="text-muted-foreground">{booking.source}</span>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div>
              <div className="text-muted-foreground">{t("booking.client")}</div>
              <div className="font-medium">{booking.client?.name ?? "—"}</div>
              <div>{booking.client?.phone}</div>
            </div>
            <div>
              <div className="text-muted-foreground">{t("booking.barber")}</div>
              <div className="font-medium">{booking.barber.name}</div>
            </div>
          </div>
          <div className="space-y-1 rounded-md border p-3">
            {booking.services.map((line) => (
              <div
                key={line.service_id ?? pickName(line.name_i18n, "ru")}
                className="flex items-center justify-between gap-2"
              >
                <span>
                  {pickName(line.name_i18n, i18n.language)} ·{" "}
                  {t("common.minutes", { n: line.duration_min })}
                </span>
                {canWrite && active && line.service_id ? (
                  <div className="w-32">
                    <MoneyInput
                      aria-label={t("booking.priceOverride")}
                      value={prices[line.service_id] ?? null}
                      onChange={(value) => setPrices((p) => ({ ...p, [line.service_id!]: value }))}
                    />
                  </div>
                ) : (
                  <span>{money(line.price)}</span>
                )}
              </div>
            ))}
            <div className="flex justify-between border-t pt-1">
              <span>{t("booking.subtotal")}</span>
              <span>{money(booking.subtotal)}</span>
            </div>
            {booking.bonus_spent > 0 && (
              <div className="flex justify-between text-primary">
                <span>{t("booking.bonusSpent")}</span>
                <span>−{money(booking.bonus_spent)}</span>
              </div>
            )}
            <div className="flex justify-between font-semibold">
              <span>{t("booking.totalDue")}</span>
              <span>{money(booking.total_due)}</span>
            </div>
            {booking.paid_amount !== null && booking.paid_amount !== undefined && (
              <div className="flex justify-between">
                <span>{t("booking.paid")}</span>
                <span>
                  {money(booking.paid_amount)} ·{" "}
                  {booking.payment_method && t(`payment.${booking.payment_method}`)}
                </span>
              </div>
            )}
          </div>
          {canWrite && booking.kind === "appointment" && <BookingPayments booking={booking} />}
          {canWrite && booking.kind === "appointment" && <BookingVouchers booking={booking} />}
          {booking.comment && <p className="rounded-md bg-muted p-2">💬 {booking.comment}</p>}
          {canWrite && (
            <Field label={t("booking.adminNote")} htmlFor="note">
              <Textarea id="note" value={note} onChange={(e) => setNote(e.target.value)} />
            </Field>
          )}
          {canWrite && active && (
            <Button
              variant="outline"
              size="sm"
              loading={patch.isPending}
              onClick={() => patch.mutate()}
            >
              {t("common.save")}
            </Button>
          )}

          {canStatus && ((booking.status === "confirmed" && started) || noShow) && (
            <div className="space-y-2 rounded-md border p-3">
              {autoNoShow && (
                <p className="text-sm text-muted-foreground">{t("booking.autoNoShowHint")}</p>
              )}
              <div className="grid grid-cols-2 gap-2">
                <Field label={t("booking.paymentMethod")} htmlFor="method">
                  <NativeSelect
                    id="method"
                    value={method}
                    onChange={(e) => setMethod(e.target.value as PaymentMethod)}
                  >
                    {(["cash", "card", "transfer", "mixed"] as const).map((m) => (
                      <option key={m} value={m}>
                        {t(`payment.${m}`)}
                      </option>
                    ))}
                  </NativeSelect>
                </Field>
                <Field label={t("booking.paid")} htmlFor="paid">
                  <MoneyInput id="paid" value={paid} onChange={setPaid} />
                </Field>
              </div>
              <div className="flex gap-2">
                <Button
                  disabled={paid === null}
                  loading={status.isPending}
                  onClick={() => status.mutate("completed")}
                >
                  {noShow ? t("booking.came") : t("booking.complete")}
                </Button>
                {(!noShow || autoNoShow) && (
                  <Button
                    variant="outline"
                    loading={status.isPending}
                    onClick={() => status.mutate("no_show")}
                  >
                    {noShow ? t("booking.didNotCome") : t("booking.noShow")}
                  </Button>
                )}
              </div>
            </div>
          )}
          {canWrite && booking.status === "pending" && (
            <Button onClick={() => status.mutate("confirmed")}>{t("booking.confirm")}</Button>
          )}
          {canWrite && active && (
            <div className="flex items-end gap-2">
              <div className="flex-1">
                <Field label={t("booking.cancelReason")} htmlFor="reason">
                  <Input id="reason" value={reason} onChange={(e) => setReason(e.target.value)} />
                </Field>
              </div>
              <Button variant="destructive" onClick={() => status.mutate("cancelled")}>
                {t("booking.cancelBooking")}
              </Button>
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
