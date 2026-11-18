import type { AdminBooking } from "@barber/api-client";
import { todayKey } from "@barber/ui";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { Plus } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { DataTable } from "@/components/DataTable";
import { Badge, Button, Input, NativeSelect } from "@/components/ui";
import { BookingCard } from "@/features/BookingCard";
import { BookingDetailsDialog, CreateBookingDialog } from "@/features/BookingDialogs";
import { PageHeader } from "@/features/Layout";
import { pickName, STATUS_VARIANT, useBarbersList } from "@/features/queries";
import { PaymentBadge } from "@/features/Payments";
import { ADMIN, api, call } from "@/lib/api";
import { useCan } from "@/lib/auth";
import { useFormat } from "@/lib/format";
import { cn } from "@/lib/utils";

const PAGE = 25;
const STATUSES = ["pending", "confirmed", "completed", "cancelled", "no_show"] as const;
type Status = (typeof STATUSES)[number];
const RANGES = ["upcoming", "today", "past", "period"] as const;
type Range = (typeof RANGES)[number];

export default function Bookings() {
  const { t, i18n } = useTranslation();
  const { money, dateTime, tz } = useFormat();
  const can = useCan();
  const barbers = useBarbersList();
  const [page, setPage] = useState(0);
  const [range, setRange] = useState<Range>("upcoming");
  const [periodFrom, setFrom] = useState(() => todayKey(tz));
  const [periodTo, setTo] = useState(() => todayKey(tz));
  const today = todayKey(tz);
  // upcoming: from today on; past: up to today, newest first
  const from = range === "period" ? periodFrom : range === "past" ? "" : today;
  const to = range === "period" ? periodTo : range === "upcoming" ? "" : today;
  const newestFirst = range === "past";
  const [barberId, setBarberId] = useState("");
  const [status, setStatus] = useState<Status | "">("");
  const [selected, setSelected] = useState<AdminBooking | null>(null);
  const [creating, setCreating] = useState(false);

  const query = useQuery({
    queryKey: ["bookings", { page, from, to, newestFirst, barberId, status }],
    placeholderData: keepPreviousData,
    queryFn: () =>
      call(
        api.GET(`${ADMIN}/bookings`, {
          params: {
            query: {
              date_from: from || undefined,
              date_to: to || undefined,
              barber_id: barberId ? [barberId] : undefined,
              status: status ? [status] : undefined,
              limit: PAGE,
              offset: page * PAGE,
              newest_first: newestFirst || undefined,
            },
          },
        }),
      ),
  });

  const columns = useMemo<ColumnDef<AdminBooking, unknown>[]>(
    () => [
      { header: t("booking.start"), cell: ({ row }) => dateTime(row.original.start_at) },
      {
        header: t("booking.client"),
        cell: ({ row }) => (
          <div>
            <div>{row.original.client?.name ?? "—"}</div>
            <div className="text-xs text-muted-foreground">{row.original.client?.phone}</div>
          </div>
        ),
      },
      { header: t("booking.barber"), cell: ({ row }) => row.original.barber.name },
      {
        header: t("booking.services"),
        cell: ({ row }) =>
          row.original.services.map((s) => pickName(s.name_i18n, i18n.language)).join(", "),
      },
      {
        header: t("booking.status"),
        cell: ({ row }) => (
          <div className="flex flex-wrap gap-1">
            <Badge variant={STATUS_VARIANT[row.original.status]}>
              {t(`status.${row.original.status}`)}
            </Badge>
            <PaymentBadge state={row.original.payment_status} />
          </div>
        ),
      },
      {
        header: t("booking.totalDue"),
        cell: ({ row }) => <span className="tabular-nums">{money(row.original.total_due)}</span>,
      },
    ],
    [t, i18n.language, dateTime, money],
  );

  const reset = () => setPage(0);
  return (
    <div>
      <PageHeader
        title={t("nav.bookings")}
        actions={
          can("bookings:write") && (
            <Button onClick={() => setCreating(true)}>
              <Plus /> {t("calendar.newBooking")}
            </Button>
          )
        }
      />
      <div className="mb-3 grid grid-cols-2 gap-1 rounded-lg border bg-card p-1 sm:flex sm:w-fit">
        {RANGES.map((item) => (
          <button
            key={item}
            type="button"
            onClick={() => {
              setRange(item);
              reset();
            }}
            className={cn(
              "rounded-md px-3 py-1.5 text-sm transition-colors",
              range === item
                ? "bg-primary text-primary-foreground"
                : "text-muted-foreground hover:bg-accent",
            )}
          >
            {t(item === "today" ? "calendar.today" : `calendar.${item}`)}
          </button>
        ))}
      </div>
      <div className="mb-4 grid grid-cols-2 gap-2 sm:flex sm:flex-wrap">
        {range === "period" && (
          <>
            <Input
              type="date"
              className="sm:w-40"
              value={periodFrom}
              onChange={(e) => {
                setFrom(e.target.value);
                reset();
              }}
              aria-label={t("common.from")}
            />
            <Input
              type="date"
              className="sm:w-40"
              value={periodTo}
              onChange={(e) => {
                setTo(e.target.value);
                reset();
              }}
              aria-label={t("common.to")}
            />
          </>
        )}
        <NativeSelect
          className="sm:w-48"
          value={barberId}
          onChange={(e) => {
            setBarberId(e.target.value);
            reset();
          }}
          aria-label={t("booking.barber")}
        >
          <option value="">{t("common.all")}</option>
          {barbers.data?.map((b) => (
            <option key={b.id} value={b.id}>
              {b.name}
            </option>
          ))}
        </NativeSelect>
        <NativeSelect
          className="sm:w-44"
          value={status}
          onChange={(e) => {
            setStatus(e.target.value as Status | "");
            reset();
          }}
          aria-label={t("booking.status")}
        >
          <option value="">{t("common.all")}</option>
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {t(`status.${s}`)}
            </option>
          ))}
        </NativeSelect>
      </div>
      <DataTable
        columns={columns}
        data={query.data?.items ?? []}
        total={query.data?.total ?? 0}
        page={page}
        pageSize={PAGE}
        onPageChange={setPage}
        loading={query.isPending}
        onRowClick={setSelected}
        mobileCard={(booking) => (
          <BookingCard booking={booking} onClick={() => setSelected(booking)} />
        )}
      />
      <BookingDetailsDialog booking={selected} onClose={() => setSelected(null)} />
      {creating && <CreateBookingDialog open onOpenChange={setCreating} defaults={{}} />}
    </div>
  );
}
