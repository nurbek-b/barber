import type { AdminBooking } from "@barber/api-client";
import { useTranslation } from "react-i18next";

import { Badge } from "@/components/ui";
import { useFormat } from "@/lib/format";
import { cn } from "@/lib/utils";

import { PaymentBadge } from "./Payments";
import { pickName, STATUS_VARIANT } from "./queries";

/** One booking as a tappable card: the phone replacement for a table row or calendar event. */
export function BookingCard({
  booking,
  onClick,
  timeOnly,
}: {
  booking: AdminBooking;
  onClick?: () => void;
  /** the day is already shown above the list */
  timeOnly?: boolean;
}) {
  const { t, i18n } = useTranslation();
  const { money, dateTime, time } = useFormat();
  const block = booking.kind === "block";
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex w-full flex-col gap-1.5 rounded-lg border bg-card p-3 text-left text-sm transition-colors active:bg-muted/60",
        block && "border-dashed bg-muted/40",
      )}
    >
      <div className="flex items-baseline justify-between gap-2">
        <span className="font-semibold tabular-nums">
          {timeOnly
            ? `${time(booking.start_at)}–${time(booking.end_at)}`
            : dateTime(booking.start_at)}
        </span>
        {!block && <span className="tabular-nums">{money(booking.total_due)}</span>}
      </div>
      {block ? (
        <div className="text-muted-foreground">
          ⛔ {booking.admin_note ?? t("calendar.block")} · {booking.barber.name}
        </div>
      ) : (
        <>
          <div>
            <span className="font-medium">
              {booking.client_confirmed_at ? "✓ " : ""}
              {booking.client?.name ?? "—"}
            </span>
            {booking.client?.phone && (
              <span className="ml-2 text-xs text-muted-foreground">{booking.client.phone}</span>
            )}
          </div>
          <div className="text-muted-foreground">
            {booking.barber.name} ·{" "}
            {booking.services.map((s) => pickName(s.name_i18n, i18n.language)).join(", ")}
          </div>
          <div className="flex flex-wrap gap-1">
            <Badge variant={STATUS_VARIANT[booking.status]}>{t(`status.${booking.status}`)}</Badge>
            <PaymentBadge state={booking.payment_status} />
          </div>
        </>
      )}
    </button>
  );
}
