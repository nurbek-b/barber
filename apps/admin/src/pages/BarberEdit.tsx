import { todayKey, addDaysKey } from "@barber/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Camera, Trash2, TriangleAlert } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useParams } from "react-router-dom";
import { toast } from "sonner";

import { FileButton } from "@/components/FileButton";
import { MoneyInput } from "@/components/MoneyInput";
import {
  Badge,
  Button,
  Card,
  CardContent,
  Field,
  Input,
  NativeSelect,
  Skeleton,
  Switch,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  Textarea,
} from "@/components/ui";
import { PageHeader } from "@/features/Layout";
import { keys, pickName, useServicesList } from "@/features/queries";
import { ReviewsTab, WorksTab } from "@/features/BarberWorks";
import { ScheduleEditor, overlappingDays, type Interval } from "@/features/ScheduleEditor";
import { ADMIN, api, call, errorMessage } from "@/lib/api";
import { useAuth, useCan } from "@/lib/auth";
import { useFormat } from "@/lib/format";

const hhmm = (value: string) => value.slice(0, 5);

export default function BarberEdit() {
  const { barberId = "" } = useParams();
  const { t } = useTranslation();
  const can = useCan();
  const writable = can("barbers:write");
  const [tab, setTab] = useState("profile");
  const barber = useQuery({
    queryKey: keys.barber(barberId),
    queryFn: () =>
      call(api.GET(`${ADMIN}/barbers/{barber_id}`, { params: { path: { barber_id: barberId } } })),
  });
  if (barber.isPending) return <Skeleton className="h-96" />;
  if (barber.isError) return <p className="text-destructive">{errorMessage(barber.error)}</p>;
  return (
    <div>
      <PageHeader title={barber.data.name} />
      {!barber.data.has_schedule && (
        <div
          role="alert"
          className="mb-4 flex flex-wrap items-center gap-3 rounded-md border border-amber-500/40 bg-amber-500/10 p-3 text-sm"
        >
          <TriangleAlert className="h-4 w-4 shrink-0 text-amber-600" />
          <span className="flex-1">{t("barbers.noScheduleHint")}</span>
          {tab !== "schedule" && (
            <Button size="sm" variant="outline" onClick={() => setTab("schedule")}>
              {t("barbers.setSchedule")}
            </Button>
          )}
        </div>
      )}
      <Tabs value={tab} onValueChange={setTab} className="space-y-4">
        <TabsList>
          <TabsTrigger value="profile">{t("barbers.profile")}</TabsTrigger>
          <TabsTrigger value="services">{t("barbers.services")}</TabsTrigger>
          <TabsTrigger value="schedule">{t("barbers.schedule")}</TabsTrigger>
          <TabsTrigger value="exceptions">{t("barbers.exceptions")}</TabsTrigger>
          <TabsTrigger value="works">{t("barbers.works")}</TabsTrigger>
          {can("barbers:read") && <TabsTrigger value="reviews">{t("barbers.reviews")}</TabsTrigger>}
        </TabsList>
        <TabsContent value="profile">
          <ProfileTab barberId={barberId} writable={writable} />
        </TabsContent>
        <TabsContent value="services">
          <ServicesTab barberId={barberId} writable={writable} />
        </TabsContent>
        <TabsContent value="schedule">
          <ScheduleTab barberId={barberId} writable={writable} />
        </TabsContent>
        <TabsContent value="exceptions">
          <ExceptionsTab barberId={barberId} writable={writable} />
        </TabsContent>
        <TabsContent value="works">
          <WorksTab barber={barber.data} writable={writable} />
        </TabsContent>
        <TabsContent value="reviews">
          <ReviewsTab barberId={barberId} />
        </TabsContent>
      </Tabs>
    </div>
  );
}

function useBarber(barberId: string) {
  return useQuery({
    queryKey: keys.barber(barberId),
    queryFn: () =>
      call(api.GET(`${ADMIN}/barbers/{barber_id}`, { params: { path: { barber_id: barberId } } })),
  });
}

/** "37.5" -> 3750 basis points, clamped to 0..100 %. */
function percentToBp(value: string): number {
  const number = Number(value.replace(",", "."));
  if (!Number.isFinite(number)) return 0;
  return Math.round(Math.min(100, Math.max(0, number)) * 100);
}

function ProfileTab({ barberId, writable }: { barberId: string; writable: boolean }) {
  const { t } = useTranslation();
  const can = useCan();
  const client = useQueryClient();
  const barber = useBarber(barberId).data!;
  const [name, setName] = useState(barber.name);
  const [spec, setSpec] = useState(barber.specialization_i18n);
  const [bio, setBio] = useState(barber.bio_i18n);
  const { me } = useAuth();
  const isOwner = me.role === "owner";
  const [commission, setCommission] = useState(String(barber.commission_bp / 100));
  const [sortOrder, setSortOrder] = useState(String(barber.sort_order));
  const [active, setActive] = useState(barber.is_active);
  const [online, setOnline] = useState(barber.is_bookable_online);
  const [link, setLink] = useState<string | null>(null);

  const refresh = () => void client.invalidateQueries({ queryKey: keys.barbers });
  const save = useMutation({
    mutationFn: () =>
      call(
        api.PATCH(`${ADMIN}/barbers/{barber_id}`, {
          params: { path: { barber_id: barberId } },
          body: {
            name,
            specialization_i18n: spec,
            bio_i18n: bio,
            sort_order: Number(sortOrder) || 0,
            is_active: active,
            is_bookable_online: online,
            ...(isOwner ? { commission_bp: percentToBp(commission) } : {}),
          },
        }),
      ),
    onSuccess: () => {
      toast.success(t("common.saved"));
      refresh();
    },
    onError: (error) => toast.error(errorMessage(error)),
  });
  const upload = useMutation({
    mutationFn: async (file: File) => {
      const form = new FormData();
      form.append("file", file);
      return call(
        api.POST(`${ADMIN}/barbers/{barber_id}/photo`, {
          params: { path: { barber_id: barberId } },
          body: form as never,
          bodySerializer: (body: unknown) => body as FormData,
        }),
      );
    },
    onSuccess: () => {
      toast.success(t("barbers.photoUploaded"));
      refresh();
    },
    onError: (error) => toast.error(errorMessage(error)),
  });
  const removePhoto = useMutation({
    mutationFn: () =>
      call(
        api.DELETE(`${ADMIN}/barbers/{barber_id}/photo`, {
          params: { path: { barber_id: barberId } },
        }),
      ),
    onSuccess: refresh,
    onError: (error) => toast.error(errorMessage(error)),
  });
  const telegram = useMutation({
    mutationFn: () =>
      call(
        api.GET(`${ADMIN}/barbers/{barber_id}/telegram-link`, {
          params: { path: { barber_id: barberId } },
        }),
      ),
    onSuccess: (data) => setLink(data.link),
    onError: (error) => toast.error(errorMessage(error)),
  });

  return (
    <Card>
      <CardContent className="grid gap-4 pt-5 md:grid-cols-2">
        <div className="space-y-3">
          <Field label={t("common.name")} htmlFor="b-name">
            <Input
              id="b-name"
              value={name}
              disabled={!writable}
              onChange={(e) => setName(e.target.value)}
            />
          </Field>
          {(["ru", "ky", "en"] as const).map((lang) => (
            <Field
              key={lang}
              label={`${t("barbers.specialization")} (${lang})`}
              htmlFor={`b-spec-${lang}`}
            >
              <Input
                id={`b-spec-${lang}`}
                value={spec[lang] ?? ""}
                disabled={!writable}
                onChange={(e) => setSpec({ ...spec, [lang]: e.target.value })}
              />
            </Field>
          ))}
          {(["ru", "ky", "en"] as const).map((lang) => (
            <Field key={lang} label={`${t("barbers.bio")} (${lang})`} htmlFor={`b-bio-${lang}`}>
              <Textarea
                id={`b-bio-${lang}`}
                value={bio[lang] ?? ""}
                disabled={!writable}
                onChange={(e) => setBio({ ...bio, [lang]: e.target.value })}
              />
            </Field>
          ))}
        </div>
        <div className="space-y-4">
          <div className="flex items-center gap-4 rounded-md border p-3">
            {barber.photo_url ? (
              <img
                src={barber.photo_url}
                alt={barber.name}
                className="h-24 w-24 shrink-0 rounded-full object-cover"
              />
            ) : (
              <div className="flex h-24 w-24 shrink-0 items-center justify-center rounded-full bg-muted text-muted-foreground">
                <Camera className="h-8 w-8" />
              </div>
            )}
            <div className="space-y-2">
              <div className="text-sm font-medium">{t("barbers.photo")}</div>
              {writable && (
                <div className="flex flex-wrap gap-2">
                  <FileButton
                    accept="image/jpeg,image/png,image/webp"
                    loading={upload.isPending}
                    onFile={(file) => upload.mutate(file)}
                  >
                    <Camera />
                    {barber.photo_url ? t("barbers.replacePhoto") : t("barbers.uploadPhoto")}
                  </FileButton>
                  {barber.photo_url && (
                    <Button
                      size="sm"
                      variant="ghost"
                      loading={removePhoto.isPending}
                      onClick={() => removePhoto.mutate()}
                    >
                      <Trash2 /> {t("barbers.removePhoto")}
                    </Button>
                  )}
                </div>
              )}
              <p className="text-xs text-muted-foreground">{t("barbers.photoHint")}</p>
            </div>
          </div>
          {(isOwner || can("finance:read")) && (
            <Field label={t("barbers.commission")} htmlFor="b-commission">
              <div className="flex items-center gap-2">
                <Input
                  id="b-commission"
                  type="number"
                  min={0}
                  max={100}
                  step={0.5}
                  className="w-28"
                  value={commission}
                  disabled={!isOwner}
                  onChange={(e) => setCommission(e.target.value)}
                />
                <span className="text-sm text-muted-foreground">%</span>
              </div>
              <p className="mt-1 text-xs text-muted-foreground">{t("barbers.commissionHint")}</p>
            </Field>
          )}
          <Field label={t("barbers.sortOrder")} htmlFor="b-sort">
            <Input
              id="b-sort"
              type="number"
              min={0}
              value={sortOrder}
              disabled={!writable}
              onChange={(e) => setSortOrder(e.target.value)}
            />
          </Field>
          <label className="flex items-center justify-between text-sm">
            {t("common.active")}
            <Switch checked={active} disabled={!writable} onCheckedChange={setActive} />
          </label>
          <label className="flex items-center justify-between text-sm">
            {t("barbers.online")}
            <Switch checked={online} disabled={!writable} onCheckedChange={setOnline} />
          </label>
          {writable && (
            <div className="space-y-2 rounded-md border p-3">
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium">{t("barbers.telegramLink")}</span>
                {barber.telegram_chat_id && <Badge variant="success">✓</Badge>}
              </div>
              <p className="text-xs text-muted-foreground">{t("barbers.telegramLinkHint")}</p>
              {link ? (
                <Input readOnly value={link} onFocus={(e) => e.target.select()} />
              ) : (
                <Button
                  size="sm"
                  variant="outline"
                  loading={telegram.isPending}
                  onClick={() => telegram.mutate()}
                >
                  {t("common.create")}
                </Button>
              )}
            </div>
          )}
          {writable && (
            <Button loading={save.isPending} onClick={() => save.mutate()}>
              {t("common.save")}
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

interface LinkState {
  enabled: boolean;
  price: number | null;
  duration: string;
}

function ServicesTab({ barberId, writable }: { barberId: string; writable: boolean }) {
  const { t, i18n } = useTranslation();
  const { money } = useFormat();
  const client = useQueryClient();
  const barber = useBarber(barberId).data!;
  const services = useServicesList(true);
  const [state, setState] = useState<Record<string, LinkState>>({});

  useEffect(() => {
    const next: Record<string, LinkState> = {};
    for (const link of barber.services) {
      next[link.service_id] = {
        enabled: link.is_active,
        price: link.price ?? null,
        duration: link.duration_min ? String(link.duration_min) : "",
      };
    }
    setState(next);
  }, [barber.services]);

  const save = useMutation({
    mutationFn: () =>
      call(
        api.PUT(`${ADMIN}/barbers/{barber_id}/services`, {
          params: { path: { barber_id: barberId } },
          body: {
            services: Object.entries(state)
              .filter(([, v]) => v.enabled)
              .map(([service_id, v]) => ({
                service_id,
                price: v.price,
                duration_min: v.duration ? Number(v.duration) : null,
                is_active: true,
              })),
          },
        }),
      ),
    onSuccess: () => {
      toast.success(t("common.saved"));
      void client.invalidateQueries({ queryKey: keys.barbers });
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  return (
    <Card>
      <CardContent className="space-y-2 pt-5">
        {services.data?.map((service) => {
          const row = state[service.id] ?? { enabled: false, price: null, duration: "" };
          const set = (patch: Partial<LinkState>) =>
            setState((s) => ({ ...s, [service.id]: { ...row, ...patch } }));
          return (
            <div
              key={service.id}
              className="flex flex-wrap items-center gap-3 border-b pb-2 last:border-0"
            >
              <label className="flex flex-1 items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={row.enabled}
                  disabled={!writable}
                  onChange={(e) => set({ enabled: e.target.checked })}
                />
                <span className="font-medium">{pickName(service.name_i18n, i18n.language)}</span>
                <span className="text-muted-foreground">
                  {money(service.base_price)} · {t("common.minutes", { n: service.duration_min })}
                </span>
              </label>
              <div className="w-32">
                <MoneyInput
                  allowEmpty
                  aria-label={t("barbers.priceOverride")}
                  placeholder={t("barbers.priceOverride")}
                  value={row.price}
                  onChange={(price) => set({ price })}
                />
              </div>
              <Input
                className="w-28"
                type="number"
                min={5}
                placeholder={t("barbers.durationOverride")}
                aria-label={t("barbers.durationOverride")}
                value={row.duration}
                disabled={!writable}
                onChange={(e) => set({ duration: e.target.value })}
              />
            </div>
          );
        })}
        {writable && (
          <Button loading={save.isPending} onClick={() => save.mutate()}>
            {t("common.save")}
          </Button>
        )}
      </CardContent>
    </Card>
  );
}

function ScheduleTab({ barberId, writable }: { barberId: string; writable: boolean }) {
  const { t } = useTranslation();
  const client = useQueryClient();
  const schedule = useQuery({
    queryKey: ["schedule", barberId],
    queryFn: () =>
      call(
        api.GET(`${ADMIN}/barbers/{barber_id}/schedule`, {
          params: { path: { barber_id: barberId } },
        }),
      ),
  });
  const [value, setValue] = useState<Interval[]>([]);
  useEffect(() => {
    if (schedule.data) {
      setValue(
        schedule.data.intervals.map((i) => ({
          weekday: i.weekday,
          start_time: hhmm(i.start_time),
          end_time: hhmm(i.end_time),
        })),
      );
    }
  }, [schedule.data]);
  const save = useMutation({
    mutationFn: () =>
      call(
        api.PUT(`${ADMIN}/barbers/{barber_id}/schedule`, {
          params: { path: { barber_id: barberId } },
          body: { intervals: value },
        }),
      ),
    onSuccess: (result) => {
      toast.success(t("common.saved"));
      if (result.conflicting_bookings.length)
        toast.warning(t("barbers.conflicts", { count: result.conflicting_bookings.length }));
      void client.invalidateQueries({ queryKey: ["schedule", barberId] });
      void client.invalidateQueries({ queryKey: ["calendar"] });
      void client.invalidateQueries({ queryKey: keys.barbers }); // has_schedule badge/warning
    },
    onError: (error) => toast.error(errorMessage(error)),
  });
  if (schedule.isPending) return <Skeleton className="h-64" />;
  return (
    <Card>
      <CardContent className="space-y-3 pt-5">
        <ScheduleEditor value={value} onChange={setValue} />
        {writable && (
          <Button
            disabled={overlappingDays(value).size > 0}
            loading={save.isPending}
            onClick={() => save.mutate()}
          >
            {t("common.save")}
          </Button>
        )}
      </CardContent>
    </Card>
  );
}

type Kind = "day_off" | "vacation" | "custom_hours";

function ExceptionsTab({ barberId, writable }: { barberId: string; writable: boolean }) {
  const { t } = useTranslation();
  const { tz } = useFormat();
  const client = useQueryClient();
  const today = todayKey(tz);
  const list = useQuery({
    queryKey: ["exceptions", barberId],
    queryFn: () =>
      call(
        api.GET(`${ADMIN}/barbers/{barber_id}/exceptions`, {
          params: {
            path: { barber_id: barberId },
            query: { date_from: addDaysKey(today, -30), date_to: addDaysKey(today, 365) },
          },
        }),
      ),
  });
  const [from, setFrom] = useState(today);
  const [to, setTo] = useState(today);
  const [kind, setKind] = useState<Kind>("day_off");
  const [start, setStart] = useState("10:00");
  const [end, setEnd] = useState("16:00");
  const [note, setNote] = useState("");
  const refresh = () => {
    void client.invalidateQueries({ queryKey: ["exceptions", barberId] });
    void client.invalidateQueries({ queryKey: ["calendar"] });
  };
  const create = useMutation({
    mutationFn: () =>
      call(
        api.POST(`${ADMIN}/barbers/{barber_id}/exceptions`, {
          params: { path: { barber_id: barberId } },
          body: {
            date_from: from,
            date_to: to,
            kind,
            note: note || null,
            intervals: kind === "custom_hours" ? [{ start, end }] : [],
          },
        }),
      ),
    onSuccess: (result) => {
      if (result.conflicting_bookings.length)
        toast.warning(t("barbers.conflicts", { count: result.conflicting_bookings.length }));
      refresh();
    },
    onError: (error) => toast.error(errorMessage(error)),
  });
  const remove = useMutation({
    mutationFn: (id: string) =>
      call(
        api.DELETE(`${ADMIN}/barbers/{barber_id}/exceptions/{exception_id}`, {
          params: { path: { barber_id: barberId, exception_id: id } },
        }),
      ),
    onSuccess: refresh,
  });

  return (
    <Card>
      <CardContent className="space-y-4 pt-5">
        {writable && (
          <div className="flex flex-wrap items-end gap-2">
            <Field label={t("common.from")} htmlFor="ex-from">
              <Input
                id="ex-from"
                type="date"
                value={from}
                onChange={(e) => setFrom(e.target.value)}
              />
            </Field>
            <Field label={t("common.to")} htmlFor="ex-to">
              <Input id="ex-to" type="date" value={to} onChange={(e) => setTo(e.target.value)} />
            </Field>
            <Field label={t("booking.status")} htmlFor="ex-kind">
              <NativeSelect
                id="ex-kind"
                value={kind}
                onChange={(e) => setKind(e.target.value as Kind)}
              >
                {(["day_off", "vacation", "custom_hours"] as const).map((k) => (
                  <option key={k} value={k}>
                    {t(`barbers.kind.${k}`)}
                  </option>
                ))}
              </NativeSelect>
            </Field>
            {kind === "custom_hours" && (
              <>
                <Input
                  type="time"
                  className="w-28"
                  value={start}
                  onChange={(e) => setStart(e.target.value)}
                  aria-label={t("booking.start")}
                />
                <Input
                  type="time"
                  className="w-28"
                  value={end}
                  onChange={(e) => setEnd(e.target.value)}
                  aria-label={t("booking.end")}
                />
              </>
            )}
            <Input
              className="w-48"
              placeholder={t("common.note")}
              value={note}
              onChange={(e) => setNote(e.target.value)}
              aria-label={t("common.note")}
            />
            <Button loading={create.isPending} onClick={() => create.mutate()}>
              {t("common.add")}
            </Button>
          </div>
        )}
        <div className="divide-y">
          {list.data?.map((item) => (
            <div key={item.id} className="flex items-center gap-3 py-2 text-sm">
              <span className="w-48">
                {item.date_from}
                {item.date_to !== item.date_from && ` — ${item.date_to}`}
              </span>
              <Badge variant="secondary">{t(`barbers.kind.${item.kind}`)}</Badge>
              <span>{item.intervals.map((i) => `${hhmm(i.start)}–${hhmm(i.end)}`).join(", ")}</span>
              <span className="flex-1 text-muted-foreground">{item.note}</span>
              {writable && (
                <Button
                  size="icon"
                  variant="ghost"
                  aria-label={t("common.delete")}
                  onClick={() => remove.mutate(item.id)}
                >
                  <Trash2 />
                </Button>
              )}
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
