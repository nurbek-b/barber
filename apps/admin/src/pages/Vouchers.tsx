import type { components } from "@barber/api-client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

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
  NativeSelect,
  Switch,
  Table,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  Td,
  Th,
} from "@/components/ui";
import { PageHeader } from "@/features/Layout";
import { pickName, useServicesList } from "@/features/queries";
import { ADMIN, api, call, errorMessage } from "@/lib/api";
import { Can } from "@/lib/auth";
import { useFormat } from "@/lib/format";

type Certificate = components["schemas"]["CertificateOut"];
type Plan = components["schemas"]["PlanOut"];
type State = Certificate["state"];
type Method = "cash" | "card" | "transfer";

const STATE_VARIANT = {
  active: "success",
  used: "secondary",
  expired: "warning",
  cancelled: "destructive",
} as const;

function StateBadge({ state }: { state: State }) {
  const { t } = useTranslation();
  return <Badge variant={STATE_VARIANT[state]}>{t(`vouchers.state_${state}`)}</Badge>;
}

function MethodSelect({ value, onChange }: { value: Method; onChange: (m: Method) => void }) {
  const { t } = useTranslation();
  return (
    <NativeSelect
      aria-label={t("vouchers.method")}
      value={value}
      onChange={(e) => onChange(e.target.value as Method)}
    >
      {(["cash", "card", "transfer"] as const).map((m) => (
        <option key={m} value={m}>
          {t(`payment.${m}`)}
        </option>
      ))}
    </NativeSelect>
  );
}

export default function VouchersPage() {
  const { t } = useTranslation();
  return (
    <div>
      <PageHeader title={t("nav.vouchers")} />
      <Tabs defaultValue="certificates" className="space-y-4">
        <TabsList>
          <TabsTrigger value="certificates">{t("vouchers.certificates")}</TabsTrigger>
          <TabsTrigger value="subscriptions">{t("vouchers.subscriptions")}</TabsTrigger>
          <TabsTrigger value="plans">{t("vouchers.plans")}</TabsTrigger>
        </TabsList>
        <TabsContent value="certificates">
          <Certificates />
        </TabsContent>
        <TabsContent value="subscriptions">
          <Subscriptions />
        </TabsContent>
        <TabsContent value="plans">
          <Plans />
        </TabsContent>
      </Tabs>
    </div>
  );
}

// ---------------------------------------------------------------------------
// certificates
// ---------------------------------------------------------------------------

function Certificates() {
  const { t } = useTranslation();
  const { money, dateTime } = useFormat();
  const client = useQueryClient();
  const [selling, setSelling] = useState(false);
  const list = useQuery({
    queryKey: ["certificates"],
    queryFn: () => call(api.GET(`${ADMIN}/certificates`)),
  });
  const cancel = useMutation({
    mutationFn: (id: string) =>
      call(
        api.POST(`${ADMIN}/certificates/{cert_id}/cancel`, { params: { path: { cert_id: id } } }),
      ),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["certificates"] }),
    onError: (error) => toast.error(errorMessage(error)),
  });
  const copy = (code: string) => {
    void navigator.clipboard?.writeText(code);
    toast.success(code);
  };

  return (
    <Card>
      <CardContent className="space-y-4 pt-5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-sm text-muted-foreground">{t("vouchers.publicCheck")}</p>
          <Can perm="clients:write">
            <Button onClick={() => setSelling(true)}>{t("vouchers.sellCertificate")}</Button>
          </Can>
        </div>
        {list.data?.length === 0 && (
          <p className="text-sm text-muted-foreground">{t("vouchers.empty")}</p>
        )}
        {Boolean(list.data?.length) && (
          <div className="overflow-x-auto">
            <Table>
              <thead className="border-b">
                <tr>
                  <Th>{t("vouchers.code")}</Th>
                  <Th>{t("vouchers.amount")}</Th>
                  <Th>{t("vouchers.balance")}</Th>
                  <Th>{t("vouchers.recipient")}</Th>
                  <Th>{t("vouchers.expires")}</Th>
                  <Th>{t("vouchers.sold")}</Th>
                  <Th />
                </tr>
              </thead>
              <tbody>
                {list.data?.map((cert) => (
                  <tr key={cert.id} className="border-b last:border-0">
                    <Td>
                      <button
                        type="button"
                        className="inline-flex items-center gap-1 font-mono"
                        title={t("vouchers.copy")}
                        onClick={() => copy(cert.code)}
                      >
                        {cert.code} <Copy className="h-3 w-3" />
                      </button>
                      <div className="mt-1">
                        <StateBadge state={cert.state} />
                      </div>
                    </Td>
                    <Td className="tabular-nums">{money(cert.amount)}</Td>
                    <Td className="tabular-nums font-medium">{money(cert.balance)}</Td>
                    <Td>
                      {cert.recipient_name ?? "—"}
                      {cert.buyer_name && (
                        <div className="text-xs text-muted-foreground">{cert.buyer_name}</div>
                      )}
                    </Td>
                    <Td>{cert.expires_on ?? t("vouchers.noExpiry")}</Td>
                    <Td className="text-xs">{dateTime(cert.sold_at)}</Td>
                    <Td className="text-right">
                      {cert.state === "active" && (
                        <Can perm="clients:write">
                          <Button
                            size="sm"
                            variant="ghost"
                            loading={cancel.isPending && cancel.variables === cert.id}
                            onClick={() => cancel.mutate(cert.id)}
                          >
                            {t("vouchers.cancel")}
                          </Button>
                        </Can>
                      )}
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </div>
        )}
      </CardContent>
      {selling && <SellCertificate onClose={() => setSelling(false)} />}
    </Card>
  );
}

function SellCertificate({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation();
  const client = useQueryClient();
  const [amount, setAmount] = useState<number | null>(null);
  const [expires, setExpires] = useState("");
  const [recipient, setRecipient] = useState("");
  const [buyer, setBuyer] = useState("");
  const [method, setMethod] = useState<Method>("cash");
  const sell = useMutation({
    mutationFn: () =>
      call(
        api.POST(`${ADMIN}/certificates`, {
          body: {
            amount: amount!,
            expires_on: expires || null,
            recipient_name: recipient || null,
            buyer_name: buyer || null,
            payment_method: method,
          },
        }),
      ),
    onSuccess: (cert) => {
      toast.success(t("vouchers.soldToast", { code: cert.code }), { duration: 15_000 });
      void client.invalidateQueries({ queryKey: ["certificates"] });
      onClose();
    },
    onError: (error) => toast.error(errorMessage(error)),
  });
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent title={t("vouchers.sellCertificate")}>
        <div className="space-y-3">
          <Field label={t("vouchers.amount")} htmlFor="cert-amount">
            <MoneyInput id="cert-amount" value={amount} onChange={setAmount} />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label={t("vouchers.recipient")} htmlFor="cert-recipient">
              <Input
                id="cert-recipient"
                value={recipient}
                onChange={(e) => setRecipient(e.target.value)}
              />
            </Field>
            <Field label={t("vouchers.buyer")} htmlFor="cert-buyer">
              <Input id="cert-buyer" value={buyer} onChange={(e) => setBuyer(e.target.value)} />
            </Field>
            <Field label={t("vouchers.expires")} htmlFor="cert-expires">
              <Input
                id="cert-expires"
                type="date"
                value={expires}
                onChange={(e) => setExpires(e.target.value)}
              />
            </Field>
            <Field label={t("vouchers.method")} htmlFor="cert-method">
              <MethodSelect value={method} onChange={setMethod} />
            </Field>
          </div>
          <Button disabled={!amount} loading={sell.isPending} onClick={() => sell.mutate()}>
            {t("vouchers.sell")}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// sold subscriptions
// ---------------------------------------------------------------------------

function Subscriptions() {
  const { t } = useTranslation();
  const { money } = useFormat();
  const client = useQueryClient();
  const [selling, setSelling] = useState(false);
  const list = useQuery({
    queryKey: ["subscriptions"],
    queryFn: () => call(api.GET(`${ADMIN}/subscriptions`)),
  });
  const cancel = useMutation({
    mutationFn: (id: string) =>
      call(
        api.POST(`${ADMIN}/subscriptions/{sub_id}/cancel`, { params: { path: { sub_id: id } } }),
      ),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["subscriptions"] }),
    onError: (error) => toast.error(errorMessage(error)),
  });
  return (
    <Card>
      <CardContent className="space-y-4 pt-5">
        <div className="flex justify-end">
          <Can perm="clients:write">
            <Button onClick={() => setSelling(true)}>{t("vouchers.sellSubscription")}</Button>
          </Can>
        </div>
        {list.data?.length === 0 && (
          <p className="text-sm text-muted-foreground">{t("vouchers.empty")}</p>
        )}
        {Boolean(list.data?.length) && (
          <div className="overflow-x-auto">
            <Table>
              <thead className="border-b">
                <tr>
                  <Th>{t("vouchers.client")}</Th>
                  <Th>{t("vouchers.plan")}</Th>
                  <Th>{t("vouchers.visitsLeft")}</Th>
                  <Th>{t("vouchers.price")}</Th>
                  <Th>{t("vouchers.expires")}</Th>
                  <Th />
                </tr>
              </thead>
              <tbody>
                {list.data?.map((sub) => (
                  <tr key={sub.id} className="border-b last:border-0">
                    <Td className="font-medium">{sub.client_name}</Td>
                    <Td>
                      {sub.name}
                      <div className="mt-1">
                        <StateBadge state={sub.state} />
                      </div>
                    </Td>
                    <Td className="tabular-nums">
                      {sub.visits_left} / {sub.visits_total}
                    </Td>
                    <Td className="tabular-nums">{money(sub.price)}</Td>
                    <Td>{sub.expires_on}</Td>
                    <Td className="text-right">
                      {sub.state === "active" && (
                        <Can perm="clients:write">
                          <Button
                            size="sm"
                            variant="ghost"
                            loading={cancel.isPending && cancel.variables === sub.id}
                            onClick={() => cancel.mutate(sub.id)}
                          >
                            {t("vouchers.cancel")}
                          </Button>
                        </Can>
                      )}
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </div>
        )}
      </CardContent>
      {selling && <SellSubscription onClose={() => setSelling(false)} />}
    </Card>
  );
}

function SellSubscription({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation();
  const { money, date } = useFormat();
  const period = usePeriodLabel();
  const [creatingPlan, setCreatingPlan] = useState(false);
  const client = useQueryClient();
  const [search, setSearch] = useState("");
  const [picked, setPicked] = useState<{ id: string; name: string } | null>(null);
  const [planId, setPlanId] = useState("");
  const [method, setMethod] = useState<Method>("cash");
  const plans = useQuery({
    queryKey: ["plans"],
    queryFn: () => call(api.GET(`${ADMIN}/subscription-plans`)),
  });
  const found = useQuery({
    queryKey: ["clients", "search", search],
    enabled: search.trim().length >= 2 && !picked,
    queryFn: () =>
      call(api.GET(`${ADMIN}/clients`, { params: { query: { q: search, limit: 8 } } })),
  });
  const active = (plans.data ?? []).filter((plan) => plan.is_active);
  const chosen = active.find((plan) => plan.id === planId) ?? active[0];
  const sell = useMutation({
    mutationFn: () =>
      call(
        api.POST(`${ADMIN}/subscriptions`, {
          body: {
            client_id: picked!.id,
            plan_id: chosen!.id,
            payment_method: method,
          },
        }),
      ),
    onSuccess: () => {
      toast.success(t("common.saved"));
      void client.invalidateQueries({ queryKey: ["subscriptions"] });
      onClose();
    },
    onError: (error) => toast.error(errorMessage(error)),
  });
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent title={t("vouchers.sellSubscription")}>
        <div className="space-y-3">
          <Field label={t("vouchers.client")} htmlFor="sub-client">
            {picked ? (
              <div className="flex items-center justify-between rounded-md border px-3 py-2 text-sm">
                {picked.name}
                <Button size="sm" variant="ghost" onClick={() => setPicked(null)}>
                  ✕
                </Button>
              </div>
            ) : (
              <>
                <Input
                  id="sub-client"
                  placeholder={t("vouchers.searchClient")}
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                />
                <div className="mt-1 divide-y rounded-md border empty:hidden">
                  {found.data?.items.map((row) => (
                    <button
                      key={row.id}
                      type="button"
                      className="block w-full px-3 py-2 text-left text-sm hover:bg-muted"
                      onClick={() => setPicked({ id: row.id, name: row.name })}
                    >
                      {row.name} <span className="text-muted-foreground">{row.phone}</span>
                    </button>
                  ))}
                </div>
              </>
            )}
          </Field>
          <Field label={t("vouchers.plan")} htmlFor="sub-plan">
            {plans.isSuccess && active.length === 0 ? (
              <div className="space-y-2 rounded-md border border-dashed p-3 text-sm">
                <p className="text-muted-foreground">{t("vouchers.noPlans")}</p>
                <Can perm="settings:write">
                  <Button size="sm" variant="outline" onClick={() => setCreatingPlan(true)}>
                    {t("vouchers.createPlan")}
                  </Button>
                </Can>
              </div>
            ) : (
              <>
                <NativeSelect
                  id="sub-plan"
                  value={chosen?.id ?? ""}
                  onChange={(e) => setPlanId(e.target.value)}
                  disabled={plans.isPending}
                >
                  {active.map((plan) => (
                    <option key={plan.id} value={plan.id}>
                      {plan.name} — {money(plan.price)} · {period(plan.valid_days)}
                    </option>
                  ))}
                </NativeSelect>
                {chosen && (
                  <div className="mt-2 grid grid-cols-3 gap-2 rounded-md bg-muted/50 p-2 text-center text-sm">
                    <div>
                      <div className="font-semibold tabular-nums">{money(chosen.price)}</div>
                      <div className="text-xs text-muted-foreground">{t("vouchers.price")}</div>
                    </div>
                    <div>
                      <div className="font-semibold tabular-nums">{chosen.visits}</div>
                      <div className="text-xs text-muted-foreground">{t("vouchers.visits")}</div>
                    </div>
                    <div>
                      <div className="font-semibold">{period(chosen.valid_days)}</div>
                      <div className="text-xs text-muted-foreground">
                        {t("vouchers.validUntil", {
                          date: date(
                            new Date(Date.now() + chosen.valid_days * 86_400_000).toISOString(),
                          ),
                        })}
                      </div>
                    </div>
                  </div>
                )}
              </>
            )}
          </Field>
          <Field label={t("vouchers.method")} htmlFor="sub-method">
            <MethodSelect value={method} onChange={setMethod} />
          </Field>
          <Button
            disabled={!picked || active.length === 0}
            loading={sell.isPending}
            onClick={() => sell.mutate()}
          >
            {t("vouchers.sell")}
            {chosen && ` · ${money(chosen.price)}`}
          </Button>
        </div>
        {creatingPlan && (
          <PlanDialog
            plan={null}
            onClose={() => setCreatingPlan(false)}
            onSaved={(plan) => setPlanId(plan.id)}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// plans
// ---------------------------------------------------------------------------

/** Preset periods in days; anything else is shown as a number of days. */
const PERIODS = [
  { days: 30, key: "vouchers.month1" },
  { days: 90, key: "vouchers.month3" },
  { days: 180, key: "vouchers.month6" },
  { days: 365, key: "vouchers.year1" },
] as const;

function usePeriodLabel() {
  const { t } = useTranslation();
  return (days: number) => {
    const preset = PERIODS.find((p) => p.days === days);
    return preset ? t(preset.key) : t("vouchers.daysN", { n: days });
  };
}

const EMPTY_PLAN = {
  name: "",
  service_ids: [],
  visits: 5,
  price: 0,
  valid_days: 90,
  is_active: true,
};

function Plans() {
  const { t, i18n } = useTranslation();
  const { money } = useFormat();
  const period = usePeriodLabel();
  const services = useServicesList(true);
  const [editing, setEditing] = useState<Plan | "new" | null>(null);
  const plans = useQuery({
    queryKey: ["plans"],
    queryFn: () => call(api.GET(`${ADMIN}/subscription-plans`)),
  });
  const names = new Map(
    (services.data ?? []).map((s) => [s.id, pickName(s.name_i18n, i18n.language)]),
  );
  return (
    <Card>
      <CardContent className="space-y-4 pt-5">
        <div className="flex justify-end">
          <Can perm="settings:write">
            <Button onClick={() => setEditing("new")}>{t("common.create")}</Button>
          </Can>
        </div>
        {plans.data?.length === 0 && (
          <p className="text-sm text-muted-foreground">{t("vouchers.empty")}</p>
        )}
        <div className="divide-y">
          {plans.data?.map((plan) => (
            <div key={plan.id} className="flex flex-wrap items-center justify-between gap-2 py-3">
              <div>
                <div className="font-medium">
                  {plan.name}{" "}
                  {!plan.is_active && (
                    <Badge variant="secondary">{t("vouchers.state_cancelled")}</Badge>
                  )}
                </div>
                <div className="text-sm text-muted-foreground">
                  {money(plan.price)} · {t("vouchers.visitsN", { n: plan.visits })} ·{" "}
                  {period(plan.valid_days)}
                  {(plan.service_ids?.length ?? 0) > 0 &&
                    ` · ${(plan.service_ids ?? []).map((id) => names.get(id) ?? "?").join(", ")}`}
                </div>
              </div>
              <Can perm="settings:write">
                <Button size="sm" variant="outline" onClick={() => setEditing(plan)}>
                  {t("common.edit")}
                </Button>
              </Can>
            </div>
          ))}
        </div>
      </CardContent>
      {editing && (
        <PlanDialog plan={editing === "new" ? null : editing} onClose={() => setEditing(null)} />
      )}
    </Card>
  );
}

function PlanDialog({
  plan,
  onClose,
  onSaved,
}: {
  plan: Plan | null;
  onClose: () => void;
  onSaved?: (plan: Plan) => void;
}) {
  const { t, i18n } = useTranslation();
  const client = useQueryClient();
  const services = useServicesList(true);
  const [form, setForm] = useState({
    name: plan?.name ?? EMPTY_PLAN.name,
    service_ids: plan?.service_ids ?? ([] as string[]),
    visits: plan?.visits ?? EMPTY_PLAN.visits,
    price: plan?.price ?? EMPTY_PLAN.price,
    valid_days: plan?.valid_days ?? EMPTY_PLAN.valid_days,
    is_active: plan?.is_active ?? true,
  });
  const [customPeriod, setCustomPeriod] = useState(
    () => !PERIODS.some((p) => p.days === form.valid_days),
  );
  const save = useMutation({
    mutationFn: () =>
      plan
        ? call(
            api.PUT(`${ADMIN}/subscription-plans/{plan_id}`, {
              params: { path: { plan_id: plan.id } },
              body: form,
            }),
          )
        : call(api.POST(`${ADMIN}/subscription-plans`, { body: form })),
    onSuccess: (saved) => {
      toast.success(t("common.saved"));
      void client.invalidateQueries({ queryKey: ["plans"] });
      onSaved?.(saved);
      onClose();
    },
    onError: (error) => toast.error(errorMessage(error)),
  });
  const toggle = (id: string) =>
    setForm((f) => ({
      ...f,
      service_ids: f.service_ids.includes(id)
        ? f.service_ids.filter((x) => x !== id)
        : [...f.service_ids, id],
    }));
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent title={plan?.name ?? t("vouchers.createPlan")}>
        <div className="space-y-3">
          <Field label={t("vouchers.planName")} htmlFor="plan-name">
            <Input
              id="plan-name"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
            />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label={t("vouchers.price")} htmlFor="plan-price">
              <MoneyInput
                id="plan-price"
                value={form.price || null}
                onChange={(v) => setForm({ ...form, price: v ?? 0 })}
              />
            </Field>
            <Field label={t("vouchers.visits")} htmlFor="plan-visits">
              <Input
                id="plan-visits"
                type="number"
                min={1}
                max={100}
                value={form.visits}
                onChange={(e) => setForm({ ...form, visits: Number(e.target.value) })}
              />
            </Field>
          </div>
          <Field label={t("vouchers.period")} htmlFor="plan-period">
            <div
              id="plan-period"
              className="grid grid-cols-2 gap-2 sm:grid-cols-4"
              role="radiogroup"
            >
              {PERIODS.map((p) => {
                const on = !customPeriod && form.valid_days === p.days;
                return (
                  <button
                    key={p.days}
                    type="button"
                    role="radio"
                    aria-checked={on}
                    onClick={() => {
                      setCustomPeriod(false);
                      setForm({ ...form, valid_days: p.days });
                    }}
                    className={`min-h-10 rounded-md border px-2 text-sm transition-colors ${on ? "border-primary bg-primary/10 font-medium text-primary" : "hover:bg-accent"}`}
                  >
                    {t(p.key)}
                  </button>
                );
              })}
              <button
                type="button"
                role="radio"
                aria-checked={customPeriod}
                onClick={() => setCustomPeriod(true)}
                className={`col-span-2 min-h-10 rounded-md border px-2 text-sm transition-colors sm:col-span-4 ${customPeriod ? "border-primary bg-primary/10 font-medium text-primary" : "hover:bg-accent"}`}
              >
                {t("vouchers.otherPeriod")}
              </button>
            </div>
            {customPeriod && (
              <Input
                id="plan-days"
                className="mt-2"
                type="number"
                min={1}
                max={1000}
                aria-label={t("vouchers.validDays")}
                placeholder={t("vouchers.validDays")}
                value={form.valid_days}
                onChange={(e) => setForm({ ...form, valid_days: Number(e.target.value) })}
              />
            )}
          </Field>
          <Field label={t("vouchers.services")} htmlFor="plan-services">
            <div id="plan-services" className="flex flex-wrap gap-2">
              {services.data?.map((s) => (
                <button
                  key={s.id}
                  type="button"
                  onClick={() => toggle(s.id)}
                  className={`rounded-full border px-3 py-1 text-sm ${form.service_ids.includes(s.id) ? "border-primary bg-primary/10 text-primary" : ""}`}
                >
                  {pickName(s.name_i18n, i18n.language)}
                </button>
              ))}
            </div>
          </Field>
          <label className="flex items-center justify-between text-sm">
            {t("vouchers.active")}
            <Switch
              checked={form.is_active}
              onCheckedChange={(v) => setForm({ ...form, is_active: v })}
            />
          </label>
          <Button
            disabled={!form.name.trim() || form.price <= 0}
            loading={save.isPending}
            onClick={() => save.mutate()}
          >
            {t("common.save")}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
