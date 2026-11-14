import type { Booking } from "@barber/api-client";
import { formatDateTime } from "@barber/ui";
import type { ReactNode } from "react";

import { pickI18n, useLang, useT, type MessageKey } from "../i18n";
import { Avatar, Card, useMoney, useTimezone } from "./ui";

const STATUS_STYLE: Record<string, string> = {
  confirmed: "bg-green-500/15 text-green-600",
  pending: "bg-amber-500/15 text-amber-600",
  completed: "bg-bg-secondary text-hint",
  cancelled: "bg-destructive/10 text-destructive",
  no_show: "bg-destructive/10 text-destructive",
};

export function BookingCard({ booking, actions }: { booking: Booking; actions?: ReactNode }) {
  const t = useT();
  const lang = useLang();
  const tz = useTimezone();
  const { money } = useMoney();
  return (
    <Card className="space-y-3" data-testid="booking-card">
      <div className="flex items-start gap-3">
        <Avatar name={booking.barber.name} url={booking.barber.photo_url} size={44} />
        <div className="min-w-0 flex-1">
          <div className="font-semibold">{formatDateTime(booking.start_at, tz, lang)}</div>
          <div className="text-sm text-hint">{booking.barber.name}</div>
        </div>
        <span className={`rounded-full px-2 py-0.5 text-xs ${STATUS_STYLE[booking.status] ?? ""}`}>
          {t(`status.${booking.status}` as MessageKey)}
        </span>
      </div>
      <div className="text-sm">
        {booking.services.map((service) => pickI18n(service.name_i18n, lang)).join(", ")}
      </div>
      <div className="flex justify-between text-sm">
        <span className="text-hint">{t("confirm.toPay")}</span>
        <span className="font-medium tabular-nums">{money(booking.total_due)}</span>
      </div>
      {actions}
    </Card>
  );
}
