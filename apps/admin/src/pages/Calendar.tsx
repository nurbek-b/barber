import type { AdminBooking } from "@barber/api-client";
import { addDaysKey } from "@barber/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { format, getDay, parse, startOfWeek } from "date-fns";
import { enUS, ru } from "date-fns/locale";
import { Plus } from "lucide-react";
import { useMemo, useState } from "react";
import { Calendar, dateFnsLocalizer, Views, type View } from "react-big-calendar";
import withDragAndDrop, {
  type EventInteractionArgs,
} from "react-big-calendar/lib/addons/dragAndDrop";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { Button, Dialog, DialogContent, Field, Input, NativeSelect } from "@/components/ui";
import {
  BookingDetailsDialog,
  CreateBookingDialog,
  invalidateBookings,
  type CreateDefaults,
} from "@/features/BookingDialogs";
import { PageHeader } from "@/features/Layout";
import { useBarbersList } from "@/features/queries";
import { ADMIN, ApiError, api, call, errorMessage } from "@/lib/api";
import { useCan } from "@/lib/auth";
import { useFormat } from "@/lib/format";
import { fromWallClock, toWallClock, wallDayKey } from "@/lib/zoned";

const localizer = dateFnsLocalizer({
  format,
  parse,
  startOfWeek: (date: Date) => startOfWeek(date, { weekStartsOn: 1 }),
  getDay,
  locales: { ru, en: enUS, ky: ru },
});

interface CalendarEvent {
  id: string;
  title: string;
  start: Date; // wall clock in the salon timezone
  end: Date;
  resourceId: string;
  booking: AdminBooking;
}

const DnDCalendar = withDragAndDrop<CalendarEvent, { id: string; title: string }>(Calendar);

const STATUS_COLOR: Record<string, string> = {
  pending: "#f59e0b",
  confirmed: "#3b82f6",
  completed: "#10b981",
  no_show: "#ef4444",
  cancelled: "#9ca3af",
  block: "#6b7280",
};

export default function CalendarPage() {
  const { t, i18n } = useTranslation();
  const { tz } = useFormat();
  const can = useCan();
  const client = useQueryClient();
  const barbers = useBarbersList(true);
  const [view, setView] = useState<View>(Views.DAY);
  const [cursor, setCursor] = useState<Date>(() => toWallClock(new Date(), tz));
  const [creating, setCreating] = useState<CreateDefaults | null>(null);
  const [selected, setSelected] = useState<AdminBooking | null>(null);
  const [blockOpen, setBlockOpen] = useState(false);

  const range = useMemo(() => {
    const day = wallDayKey(cursor);
    if (view === Views.WEEK) {
      const monday = startOfWeek(cursor, { weekStartsOn: 1 });
      const from = wallDayKey(monday);
      return { from, to: addDaysKey(from, 6) };
    }
    return { from: day, to: day };
  }, [cursor, view]);

  const calendar = useQuery({
    queryKey: ["calendar", range],
    queryFn: () =>
      call(
        api.GET(`${ADMIN}/calendar`, {
          params: { query: { date_from: range.from, date_to: range.to } },
        }),
      ),
  });

  const events: CalendarEvent[] = useMemo(
    () =>
      (calendar.data ?? []).map((booking) => ({
        id: booking.id,
        title:
          booking.kind === "block"
            ? `⛔ ${booking.admin_note ?? t("calendar.block")}`
            : `${booking.client?.name ?? ""} · ${booking.services.map((s) => s.name_i18n[i18n.language] ?? s.name_i18n.ru).join(", ")}`,
        start: toWallClock(booking.start_at, tz),
        end: toWallClock(booking.end_at, tz),
        resourceId: booking.barber.id,
        booking,
      })),
    [calendar.data, tz, t, i18n.language],
  );

  const move = useMutation({
    mutationFn: (args: { booking: AdminBooking; start: Date; barberId: string }) =>
      call(
        api.POST(`${ADMIN}/bookings/{booking_id}/move`, {
          params: { path: { booking_id: args.booking.id } },
          body: {
            version: args.booking.version,
            start_at: fromWallClock(args.start, tz).toISOString(),
            barber_id: args.barberId,
            ignore_schedule: false,
          },
        }),
      ),
    onMutate: async (args) => {
      // optimistic: show the event at the new place, roll back on 409/412
      const key = ["calendar", range];
      await client.cancelQueries({ queryKey: key });
      const previous = client.getQueryData<AdminBooking[]>(key);
      const duration =
        new Date(args.booking.end_at).getTime() - new Date(args.booking.start_at).getTime();
      const startUtc = fromWallClock(args.start, tz);
      client.setQueryData<AdminBooking[]>(key, (items) =>
        items?.map((item) =>
          item.id === args.booking.id
            ? {
                ...item,
                start_at: startUtc.toISOString(),
                end_at: new Date(startUtc.getTime() + duration).toISOString(),
                barber: { ...item.barber, id: args.barberId },
              }
            : item,
        ),
      );
      return { previous, key };
    },
    onError: (error, _args, context) => {
      if (context?.previous) client.setQueryData(context.key, context.previous);
      if (error instanceof ApiError && error.status === 409) toast.error(t("calendar.conflict"));
      else if (error instanceof ApiError && error.status === 412)
        toast.warning(t("calendar.stale"));
      else toast.error(errorMessage(error));
    },
    onSuccess: () => toast.success(t("calendar.moved")),
    onSettled: () => invalidateBookings(client),
  });

  const onDrop = ({ event, start, resourceId }: EventInteractionArgs<CalendarEvent>) => {
    if (!can("bookings:write")) return;
    const status = event.booking.status;
    if (status !== "pending" && status !== "confirmed") return;
    move.mutate({
      booking: event.booking,
      start: new Date(start),
      barberId: typeof resourceId === "string" ? resourceId : event.resourceId,
    });
  };

  const resources = (barbers.data ?? []).map((barber) => ({ id: barber.id, title: barber.name }));

  return (
    <div className="flex h-[calc(100vh-7rem)] flex-col">
      <PageHeader
        title={t("nav.calendar")}
        actions={
          can("bookings:write") && (
            <>
              <Button variant="outline" onClick={() => setBlockOpen(true)}>
                {t("calendar.newBlock")}
              </Button>
              <Button onClick={() => setCreating({ start: fromWallClock(cursor, tz) })}>
                <Plus /> {t("calendar.newBooking")}
              </Button>
            </>
          )
        }
      />
      <div className="min-h-0 flex-1 rounded-lg border bg-card p-2" data-testid="calendar">
        <DnDCalendar
          localizer={localizer}
          culture={i18n.language}
          events={events}
          resources={view === Views.DAY ? resources : undefined}
          resourceIdAccessor="id"
          resourceTitleAccessor="title"
          view={view}
          views={[Views.DAY, Views.WEEK]}
          onView={setView}
          date={cursor}
          onNavigate={setCursor}
          step={15}
          timeslots={4}
          min={new Date(1970, 0, 1, 8)}
          max={new Date(1970, 0, 1, 23)}
          selectable={can("bookings:write")}
          resizable={false}
          draggableAccessor={(event) =>
            can("bookings:write") && ["pending", "confirmed"].includes(event.booking.status)
          }
          onEventDrop={onDrop}
          onSelectEvent={(event) => setSelected(event.booking)}
          onSelectSlot={(slot) =>
            setCreating({
              start: fromWallClock(new Date(slot.start), tz),
              barberId: typeof slot.resourceId === "string" ? slot.resourceId : undefined,
            })
          }
          eventPropGetter={(event) => ({
            style: {
              backgroundColor:
                STATUS_COLOR[event.booking.kind === "block" ? "block" : event.booking.status] ??
                "#3b82f6",
            },
          })}
          messages={{
            day: t("calendar.day"),
            week: t("calendar.week"),
            today: t("calendar.today"),
            previous: "‹",
            next: "›",
          }}
        />
      </div>
      {creating && (
        <CreateBookingDialog
          open
          onOpenChange={(open) => !open && setCreating(null)}
          defaults={creating}
        />
      )}
      <BookingDetailsDialog booking={selected} onClose={() => setSelected(null)} />
      <BlockDialog open={blockOpen} onOpenChange={setBlockOpen} day={wallDayKey(cursor)} />
    </div>
  );
}

function BlockDialog({
  open,
  onOpenChange,
  day,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  day: string;
}) {
  const { t } = useTranslation();
  const { tz } = useFormat();
  const client = useQueryClient();
  const barbers = useBarbersList(true);
  const [barberId, setBarberId] = useState("");
  const [date, setDate] = useState(day);
  const [from, setFrom] = useState("13:00");
  const [to, setTo] = useState("14:00");
  const [note, setNote] = useState("");

  const toUtc = (time: string) => {
    const [y, m, d] = date.split("-").map(Number);
    const [h, mi] = time.split(":").map(Number);
    return fromWallClock(new Date(y!, m! - 1, d!, h!, mi!), tz).toISOString();
  };
  const create = useMutation({
    mutationFn: () =>
      call(
        api.POST(`${ADMIN}/blocks`, {
          body: {
            barber_id: barberId,
            start_at: toUtc(from),
            end_at: toUtc(to),
            comment: note || null,
          },
        }),
      ),
    onSuccess: () => {
      invalidateBookings(client);
      onOpenChange(false);
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent title={t("calendar.newBlock")}>
        <Field label={t("booking.barber")} htmlFor="block-barber">
          <NativeSelect
            id="block-barber"
            value={barberId}
            onChange={(e) => setBarberId(e.target.value)}
          >
            <option value="">—</option>
            {barbers.data?.map((b) => (
              <option key={b.id} value={b.id}>
                {b.name}
              </option>
            ))}
          </NativeSelect>
        </Field>
        <div className="grid grid-cols-3 gap-2">
          <Field label={t("booking.date")} htmlFor="block-date">
            <Input
              id="block-date"
              type="date"
              value={date}
              onChange={(e) => setDate(e.target.value)}
            />
          </Field>
          <Field label={t("booking.start")} htmlFor="block-from">
            <Input
              id="block-from"
              type="time"
              value={from}
              onChange={(e) => setFrom(e.target.value)}
            />
          </Field>
          <Field label={t("booking.end")} htmlFor="block-to">
            <Input id="block-to" type="time" value={to} onChange={(e) => setTo(e.target.value)} />
          </Field>
        </div>
        <Field label={t("common.comment")} htmlFor="block-note">
          <Input id="block-note" value={note} onChange={(e) => setNote(e.target.value)} />
        </Field>
        <div className="flex justify-end">
          <Button disabled={!barberId} loading={create.isPending} onClick={() => create.mutate()}>
            {t("common.create")}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
