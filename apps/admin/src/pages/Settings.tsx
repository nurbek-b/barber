import type { components } from "@barber/api-client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import {
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
import { BrandColorsCard } from "@/features/BrandColors";
import { BrandingCard } from "@/features/Branding";
import { PageHeader } from "@/features/Layout";
import { PaymentSettingsCard } from "@/features/Payments";
import { ADMIN, api, call, errorMessage } from "@/lib/api";
import { useCan } from "@/lib/auth";
import { salonKey, useSalonSettings } from "@/lib/format";

type Salon = components["schemas"]["SalonSettingsOut"];
type NumberKey =
  | "slot_step_min"
  | "buffer_min"
  | "min_lead_time_min"
  | "max_days_ahead"
  | "cancel_min_hours"
  | "reschedule_min_hours"
  | "max_active_bookings_per_client"
  | "revisit_after_days"
  | "auto_no_show_hours";

const TIMEZONES = ["Asia/Bishkek", "Asia/Almaty", "Asia/Tashkent", "Europe/Moscow", "UTC"];

export default function SettingsPage() {
  const { t } = useTranslation();
  const can = useCan();
  const writable = can("settings:write");
  const client = useQueryClient();
  const salon = useSalonSettings();
  const defaults = useQuery({
    queryKey: ["settings", "templates"],
    queryFn: () => call(api.GET(`${ADMIN}/settings/notification-templates`)),
  });
  const [form, setForm] = useState<Salon | null>(null);
  const [reminders, setReminders] = useState("");
  useEffect(() => {
    if (salon.data) {
      setForm(salon.data);
      setReminders(salon.data.reminder_offsets_min.join(", "));
    }
  }, [salon.data]);

  const save = useMutation({
    mutationFn: (value: Salon) =>
      call(
        api.PUT(`${ADMIN}/settings/salon`, {
          body: {
            ...value,
            reminder_offsets_min: reminders
              .split(",")
              .map((x) => Number(x.trim()))
              .filter((x) => Number.isInteger(x) && x > 0),
          },
        }),
      ),
    onSuccess: (data) => {
      client.setQueryData(salonKey, data);
      toast.success(t("common.saved"));
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  if (!form) return <Skeleton className="h-96" />;
  // functional update: several fields may change in one click (a color palette)
  const set = <K extends keyof Salon>(key: K, value: Salon[K]) =>
    setForm((current) => (current ? { ...current, [key]: value } : current));
  const number = (key: NumberKey, label: string) => (
    <Field label={label} htmlFor={key}>
      <Input
        id={key}
        type="number"
        min={0}
        value={form[key]}
        disabled={!writable}
        onChange={(e) => set(key, Number(e.target.value))}
      />
    </Field>
  );
  const templateText = (key: string, lang: string) =>
    form.notification_templates[key]?.[lang] ?? "";
  const setTemplate = (key: string, lang: string, text: string) =>
    set("notification_templates", {
      ...form.notification_templates,
      [key]: { ...(form.notification_templates[key] ?? {}), [lang]: text },
    });

  return (
    <div>
      <PageHeader
        title={t("nav.settings")}
        actions={
          writable && (
            <Button loading={save.isPending} onClick={() => save.mutate(form)}>
              {t("common.save")}
            </Button>
          )
        }
      />
      <Tabs defaultValue="salon" className="space-y-4">
        <TabsList>
          <TabsTrigger value="salon">{t("settings.salon")}</TabsTrigger>
          <TabsTrigger value="branding">{t("settings.branding")}</TabsTrigger>
          <TabsTrigger value="booking">{t("settings.booking")}</TabsTrigger>
          <TabsTrigger value="payments">{t("pay.settingsTitle")}</TabsTrigger>
          <TabsTrigger value="notifications">{t("settings.notifications")}</TabsTrigger>
          <TabsTrigger value="templates">{t("settings.templates")}</TabsTrigger>
        </TabsList>
        <TabsContent value="payments">
          {salon.data && (
            <PaymentSettingsCard salon={salon.data} form={form} writable={writable} set={set} />
          )}
        </TabsContent>
        <TabsContent value="branding">
          <BrandColorsCard form={form} set={set} writable={writable} />
          {salon.data && <BrandingCard salon={salon.data} writable={writable} />}
        </TabsContent>
        <TabsContent value="salon">
          <Card>
            <CardContent className="grid gap-4 pt-5 md:grid-cols-2">
              <Field label={t("settings.name")} htmlFor="name">
                <Input
                  id="name"
                  value={form.name}
                  disabled={!writable}
                  onChange={(e) => set("name", e.target.value)}
                />
              </Field>
              <Field label={t("settings.timezone")} htmlFor="tz">
                <NativeSelect
                  id="tz"
                  value={form.timezone}
                  disabled={!writable}
                  onChange={(e) => set("timezone", e.target.value)}
                >
                  {[...new Set([form.timezone, ...TIMEZONES])].map((tz) => (
                    <option key={tz} value={tz}>
                      {tz}
                    </option>
                  ))}
                </NativeSelect>
              </Field>
              <Field label={t("settings.currency")} htmlFor="currency">
                <Input
                  id="currency"
                  value={form.currency}
                  maxLength={3}
                  disabled={!writable}
                  onChange={(e) => set("currency", e.target.value.toUpperCase())}
                />
              </Field>
              <Field label={t("settings.defaultLanguage")} htmlFor="lang">
                <NativeSelect
                  id="lang"
                  value={form.default_language}
                  disabled={!writable}
                  onChange={(e) => set("default_language", e.target.value)}
                >
                  <option value="ru">Русский</option>
                  <option value="ky">Кыргызча</option>
                  <option value="en">English</option>
                </NativeSelect>
              </Field>
              <Field label={t("settings.address")} htmlFor="address">
                <Input
                  id="address"
                  value={form.contacts.address ?? ""}
                  disabled={!writable}
                  onChange={(e) => set("contacts", { ...form.contacts, address: e.target.value })}
                />
              </Field>
              <Field label={t("common.phone")} htmlFor="salon-phone">
                <Input
                  id="salon-phone"
                  value={form.contacts.phone ?? ""}
                  disabled={!writable}
                  onChange={(e) => set("contacts", { ...form.contacts, phone: e.target.value })}
                />
              </Field>
              <Field label={t("settings.review2gis")} htmlFor="review-2gis">
                <Input
                  id="review-2gis"
                  type="url"
                  placeholder="https://2gis.kg/bishkek/firm/…"
                  value={form.review_links?.["2gis"] ?? ""}
                  disabled={!writable}
                  onChange={(e) =>
                    set("review_links", { ...form.review_links, "2gis": e.target.value })
                  }
                />
              </Field>
              <Field label={t("settings.reviewGoogle")} htmlFor="review-google">
                <Input
                  id="review-google"
                  type="url"
                  placeholder="https://g.page/r/…/review"
                  value={form.review_links?.google ?? ""}
                  disabled={!writable}
                  onChange={(e) =>
                    set("review_links", { ...form.review_links, google: e.target.value })
                  }
                />
              </Field>
              <p className="text-sm text-muted-foreground md:col-span-full">
                {t("settings.reviewLinksHint")}
              </p>
            </CardContent>
          </Card>
        </TabsContent>
        <TabsContent value="booking">
          <Card>
            <CardContent className="grid gap-4 pt-5 md:grid-cols-3">
              {number("slot_step_min", t("settings.slotStep"))}
              {number("buffer_min", t("settings.buffer"))}
              {number("min_lead_time_min", t("settings.leadTime"))}
              {number("max_days_ahead", t("settings.daysAhead"))}
              {number("cancel_min_hours", t("settings.cancelHours"))}
              {number("reschedule_min_hours", t("settings.rescheduleHours"))}
              {number("max_active_bookings_per_client", t("settings.maxActive"))}
              <div>
                {number("revisit_after_days", t("settings.revisitDays"))}
                <p className="mt-1 text-xs text-muted-foreground">{t("settings.revisitHint")}</p>
              </div>
              <div>
                {number("auto_no_show_hours", t("settings.autoNoShow"))}
                <p className="mt-1 text-xs text-muted-foreground">{t("settings.autoNoShowHint")}</p>
              </div>
            </CardContent>
          </Card>
        </TabsContent>
        <TabsContent value="notifications">
          <Card>
            <CardContent className="grid gap-4 pt-5 md:grid-cols-2">
              <Field
                label={t("settings.reminders")}
                hint={t("settings.remindersHint")}
                htmlFor="reminders"
              >
                <Input
                  id="reminders"
                  value={reminders}
                  disabled={!writable}
                  onChange={(e) => setReminders(e.target.value)}
                />
              </Field>
              <Field
                label={t("settings.adminChat")}
                hint={t("settings.adminChatHint")}
                htmlFor="chat"
              >
                <Input
                  id="chat"
                  value={form.admin_chat_id ?? ""}
                  disabled={!writable}
                  onChange={(e) =>
                    set(
                      "admin_chat_id",
                      /^-?\d+$/.test(e.target.value) ? Number(e.target.value) : null,
                    )
                  }
                />
              </Field>
              <label className="flex items-center justify-between text-sm">
                {t("settings.notifyBarbers")}
                <Switch
                  checked={form.notify_barbers}
                  disabled={!writable}
                  onCheckedChange={(v) => set("notify_barbers", v)}
                />
              </label>
            </CardContent>
          </Card>
        </TabsContent>
        <TabsContent value="templates">
          <Card>
            <CardContent className="space-y-4 pt-5">
              <p className="text-sm text-muted-foreground">{t("settings.templateHint")}</p>
              {Object.entries(defaults.data?.templates ?? {}).map(([key, variants]) => (
                <div key={key} className="space-y-2 rounded-md border p-3">
                  <div className="font-mono text-xs">{key}</div>
                  <div className="grid gap-2 md:grid-cols-3">
                    {(["ru", "ky", "en"] as const).map((lang) => (
                      <Textarea
                        key={lang}
                        aria-label={`${key} ${lang}`}
                        placeholder={variants[lang]}
                        value={templateText(key, lang)}
                        disabled={!writable}
                        onChange={(e) => setTemplate(key, lang, e.target.value)}
                        className="text-xs"
                      />
                    ))}
                  </div>
                </div>
              ))}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
