import type { components } from "@barber/api-client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { MoneyInput } from "@/components/MoneyInput";
import {
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Field,
  Input,
  NativeSelect,
  Skeleton,
  Switch,
  Table,
  Td,
  Th,
} from "@/components/ui";
import { PageHeader } from "@/features/Layout";
import { keys, pickName, useLevels } from "@/features/queries";
import { ADMIN, api, call, errorMessage } from "@/lib/api";
import { useCan } from "@/lib/auth";
import { useFormat } from "@/lib/format";

type BonusSettings = components["schemas"]["BonusSettingsOut"];
type Level = components["schemas"]["LevelOut"];

/**
 * Percent fields reuse MoneyInput: a percentage with two decimals is exactly basis points
 * ("2,5" % → 250 bp), the same integer-of-hundredths model as money — no floats.
 */
function PercentInput({
  id,
  value,
  onChange,
  disabled,
}: {
  id: string;
  value: number;
  onChange: (v: number) => void;
  disabled: boolean;
}) {
  return disabled ? (
    <Input id={id} disabled value={(value / 100).toString()} />
  ) : (
    <MoneyInput id={id} value={value} onChange={(v) => v !== null && onChange(v)} />
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="flex items-center justify-between gap-4 text-sm">
      {label}
      {children}
    </label>
  );
}

export default function BonusPage() {
  const { t } = useTranslation();
  const can = useCan();
  const owner = can("bonus_settings:write");
  const client = useQueryClient();
  const settings = useQuery({
    queryKey: ["bonus-settings"],
    queryFn: () => call(api.GET(`${ADMIN}/settings/bonus`)),
  });
  const [form, setForm] = useState<BonusSettings | null>(null);
  useEffect(() => {
    if (settings.data) setForm(settings.data);
  }, [settings.data]);

  const save = useMutation({
    mutationFn: (value: BonusSettings) => call(api.PUT(`${ADMIN}/settings/bonus`, { body: value })),
    onSuccess: (data) => {
      client.setQueryData(["bonus-settings"], data);
      toast.success(t("common.saved"));
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  if (!form) return <Skeleton className="h-96" />;
  const set = <K extends keyof BonusSettings>(key: K, value: BonusSettings[K]) =>
    setForm({ ...form, [key]: value });
  const money = (
    key: "welcome_amount" | "birthday_amount" | "referrer_amount" | "referee_amount",
  ) => (
    <div className="w-32">
      <MoneyInput aria-label={key} value={form[key]} onChange={(v) => v !== null && set(key, v)} />
    </div>
  );

  return (
    <div className="space-y-4">
      <PageHeader
        title={t("bonus.title")}
        actions={
          owner && (
            <Button loading={save.isPending} onClick={() => save.mutate(form)}>
              {t("common.save")}
            </Button>
          )
        }
      />
      {!owner && <p className="text-sm text-muted-foreground">{t("bonus.ownerOnly")}</p>}
      <div className="grid gap-4 xl:grid-cols-2">
        <Card>
          <CardContent className="space-y-4 pt-5">
            <Row label={t("bonus.enabled")}>
              <Switch
                checked={form.enabled}
                disabled={!owner}
                onCheckedChange={(v) => set("enabled", v)}
              />
            </Row>
            <div className="grid grid-cols-2 gap-3">
              <Field label={t("bonus.baseCashback")} htmlFor="cashback">
                <PercentInput
                  id="cashback"
                  value={form.base_cashback_bp}
                  disabled={!owner}
                  onChange={(v) => set("base_cashback_bp", v)}
                />
              </Field>
              <Field label={t("bonus.maxSpend")} htmlFor="maxspend">
                <PercentInput
                  id="maxspend"
                  value={form.max_spend_bp}
                  disabled={!owner}
                  onChange={(v) => set("max_spend_bp", v)}
                />
              </Field>
            </div>
            <Field label={t("bonus.lifetime")} htmlFor="lifetime">
              <Input
                id="lifetime"
                type="number"
                min={1}
                value={form.lifetime_days ?? ""}
                disabled={!owner}
                onChange={(e) =>
                  set("lifetime_days", e.target.value ? Number(e.target.value) : null)
                }
              />
            </Field>
            <Field label={t("bonus.warning")} htmlFor="warning">
              <Input
                id="warning"
                type="number"
                min={0}
                value={form.expiry_warning_days}
                disabled={!owner}
                onChange={(e) => set("expiry_warning_days", Number(e.target.value))}
              />
            </Field>
            <Field label={t("bonus.levelRule")} htmlFor="rule">
              <NativeSelect
                id="rule"
                value={form.level_rule}
                disabled={!owner}
                onChange={(e) => set("level_rule", e.target.value as "any" | "all")}
              >
                <option value="any">{t("bonus.ruleAny")}</option>
                <option value="all">{t("bonus.ruleAll")}</option>
              </NativeSelect>
            </Field>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="space-y-4 pt-5">
            <Row label={t("bonus.welcome")}>
              <span className="flex items-center gap-2">
                {money("welcome_amount")}
                <Switch
                  checked={form.welcome_enabled}
                  disabled={!owner}
                  onCheckedChange={(v) => set("welcome_enabled", v)}
                />
              </span>
            </Row>
            <Row label={t("bonus.birthday")}>
              <span className="flex items-center gap-2">
                {money("birthday_amount")}
                <Switch
                  checked={form.birthday_enabled}
                  disabled={!owner}
                  onCheckedChange={(v) => set("birthday_enabled", v)}
                />
              </span>
            </Row>
            <Field label={t("bonus.birthdayBefore")} htmlFor="bday-before">
              <Input
                id="bday-before"
                type="number"
                min={0}
                max={30}
                value={form.birthday_days_before}
                disabled={!owner}
                onChange={(e) => set("birthday_days_before", Number(e.target.value))}
              />
            </Field>
            <Row label={t("bonus.referral")}>
              <Switch
                checked={form.referral_enabled}
                disabled={!owner}
                onCheckedChange={(v) => set("referral_enabled", v)}
              />
            </Row>
            <Row label={t("bonus.referrer")}>{money("referrer_amount")}</Row>
            <Row label={t("bonus.referee")}>{money("referee_amount")}</Row>
          </CardContent>
        </Card>
      </div>
      <Levels owner={owner} />
    </div>
  );
}

function Levels({ owner }: { owner: boolean }) {
  const { t, i18n } = useTranslation();
  const { money } = useFormat();
  const client = useQueryClient();
  const levels = useLevels();
  const blank = { name: "", min_visits: 0, min_spent: 0, cashback_bp: 500 };
  const [draft, setDraft] = useState(blank);
  const refresh = () => void client.invalidateQueries({ queryKey: keys.levels });
  const create = useMutation({
    mutationFn: () =>
      call(
        api.POST(`${ADMIN}/loyalty-levels`, {
          body: {
            name_i18n: { ru: draft.name },
            min_visits: draft.min_visits,
            min_spent: draft.min_spent,
            cashback_bp: draft.cashback_bp,
            sort_order: levels.data?.length ?? 0,
            color: null,
          },
        }),
      ),
    onSuccess: () => {
      setDraft(blank);
      refresh();
    },
    onError: (error) => toast.error(errorMessage(error)),
  });
  const remove = useMutation({
    mutationFn: (level: Level) =>
      call(
        api.DELETE(`${ADMIN}/loyalty-levels/{level_id}`, {
          params: { path: { level_id: level.id } },
        }),
      ),
    onSuccess: refresh,
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("bonus.levels")}</CardTitle>
      </CardHeader>
      <CardContent>
        <Table>
          <thead className="border-b">
            <tr>
              <Th>{t("common.name")}</Th>
              <Th>{t("bonus.minVisits")}</Th>
              <Th>{t("bonus.minSpent")}</Th>
              <Th>{t("bonus.cashback")}</Th>
              <Th />
            </tr>
          </thead>
          <tbody>
            {levels.data?.map((level) => (
              <tr key={level.id} className="border-b">
                <Td className="font-medium">{pickName(level.name_i18n, i18n.language)}</Td>
                <Td>{level.min_visits}</Td>
                <Td className="tabular-nums">{money(level.min_spent)}</Td>
                <Td>{level.cashback_bp / 100}%</Td>
                <Td>
                  {owner && (
                    <Button
                      size="icon"
                      variant="ghost"
                      aria-label={t("common.delete")}
                      onClick={() => remove.mutate(level)}
                    >
                      <Trash2 />
                    </Button>
                  )}
                </Td>
              </tr>
            ))}
            {owner && (
              <tr>
                <Td>
                  <Input
                    aria-label={t("bonus.newLevel")}
                    placeholder={t("bonus.newLevel")}
                    value={draft.name}
                    onChange={(e) => setDraft({ ...draft, name: e.target.value })}
                  />
                </Td>
                <Td>
                  <Input
                    aria-label={t("bonus.minVisits")}
                    type="number"
                    min={0}
                    value={draft.min_visits}
                    onChange={(e) => setDraft({ ...draft, min_visits: Number(e.target.value) })}
                  />
                </Td>
                <Td>
                  <MoneyInput
                    aria-label={t("bonus.minSpent")}
                    value={draft.min_spent}
                    onChange={(v) => v !== null && setDraft({ ...draft, min_spent: v })}
                  />
                </Td>
                <Td>
                  <MoneyInput
                    aria-label={t("bonus.cashback")}
                    value={draft.cashback_bp}
                    onChange={(v) => v !== null && setDraft({ ...draft, cashback_bp: v })}
                  />
                </Td>
                <Td>
                  <Button
                    size="sm"
                    disabled={!draft.name.trim()}
                    loading={create.isPending}
                    onClick={() => create.mutate()}
                  >
                    {t("common.add")}
                  </Button>
                </Td>
              </tr>
            )}
          </tbody>
        </Table>
      </CardContent>
    </Card>
  );
}
