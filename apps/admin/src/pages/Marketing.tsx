import type { components } from "@barber/api-client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Send } from "lucide-react";
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
  Skeleton,
  Switch,
  Table,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  Td,
  Textarea,
  Th,
} from "@/components/ui";
import { PageHeader } from "@/features/Layout";
import { ADMIN, api, call, errorMessage } from "@/lib/api";
import { useCan } from "@/lib/auth";
import { useFormat } from "@/lib/format";

type Promo = components["schemas"]["PromoCodeOut"];
type SegmentKind = components["schemas"]["SegmentIn"]["kind"];
const promoKey = ["promo-codes"] as const;

export default function Marketing() {
  const { t } = useTranslation();
  const can = useCan();
  return (
    <div>
      <PageHeader title={t("marketing.title")} />
      <Tabs defaultValue={can("clients:write") ? "broadcasts" : "promo"} className="space-y-4">
        <TabsList>
          {can("clients:write") && (
            <TabsTrigger value="broadcasts">{t("marketing.broadcasts")}</TabsTrigger>
          )}
          <TabsTrigger value="promo">{t("marketing.promo")}</TabsTrigger>
        </TabsList>
        <TabsContent value="broadcasts">
          <Broadcasts />
        </TabsContent>
        <TabsContent value="promo">
          <PromoCodes writable={can("settings:write")} />
        </TabsContent>
      </Tabs>
    </div>
  );
}

function usePromoCodes() {
  return useQuery({ queryKey: promoKey, queryFn: () => call(api.GET(`${ADMIN}/promo-codes`)) });
}

function promoValue(promo: Promo, money: (n: number) => string): string {
  return promo.kind === "percent" ? `${promo.value / 100}%` : money(promo.value);
}

function PromoCodes({ writable }: { writable: boolean }) {
  const { t } = useTranslation();
  const { money } = useFormat();
  const client = useQueryClient();
  const codes = usePromoCodes();
  const [creating, setCreating] = useState(false);
  const toggle = useMutation({
    mutationFn: (promo: Promo) =>
      call(
        api.PATCH(`${ADMIN}/promo-codes/{promo_id}`, {
          params: { path: { promo_id: promo.id } },
          body: { is_active: !promo.is_active },
        }),
      ),
    onSuccess: () => void client.invalidateQueries({ queryKey: promoKey }),
    onError: (error) => toast.error(errorMessage(error)),
  });

  if (codes.isPending) return <Skeleton className="h-40" />;
  return (
    <Card>
      <CardContent className="space-y-3 pt-5">
        {writable && (
          <Button onClick={() => setCreating(true)}>
            <Plus /> {t("marketing.newPromo")}
          </Button>
        )}
        {codes.data?.length === 0 && (
          <p className="py-6 text-center text-sm text-muted-foreground">{t("marketing.noPromo")}</p>
        )}
        {Boolean(codes.data?.length) && (
          <Table>
            <thead className="border-b">
              <tr>
                <Th>{t("marketing.code")}</Th>
                <Th>{t("marketing.value")}</Th>
                <Th>{t("marketing.validTo")}</Th>
                <Th>{t("marketing.uses")}</Th>
                <Th>{t("marketing.active")}</Th>
              </tr>
            </thead>
            <tbody>
              {codes.data?.map((promo) => (
                <tr key={promo.id} className="border-b last:border-0">
                  <Td>
                    <div className="font-mono font-medium">{promo.code}</div>
                    {promo.description && (
                      <div className="text-xs text-muted-foreground">{promo.description}</div>
                    )}
                    {promo.first_visit_only && (
                      <Badge variant="secondary">{t("marketing.firstVisit")}</Badge>
                    )}
                  </Td>
                  <Td className="tabular-nums">{promoValue(promo, money)}</Td>
                  <Td>{promo.valid_to ?? "—"}</Td>
                  <Td className="tabular-nums">
                    {promo.uses}
                    {promo.max_uses ? ` / ${promo.max_uses}` : ""}
                  </Td>
                  <Td>
                    <Switch
                      checked={promo.is_active}
                      disabled={!writable || toggle.isPending}
                      onCheckedChange={() => toggle.mutate(promo)}
                    />
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
        <NewPromoDialog open={creating} onOpenChange={setCreating} />
      </CardContent>
    </Card>
  );
}

function NewPromoDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
}) {
  const { t } = useTranslation();
  const client = useQueryClient();
  const [code, setCode] = useState("");
  const [kind, setKind] = useState<"percent" | "fixed">("percent");
  const [percent, setPercent] = useState("10");
  const [fixed, setFixed] = useState<number | null>(null);
  const [maxDiscount, setMaxDiscount] = useState<number | null>(null);
  const [minSubtotal, setMinSubtotal] = useState<number | null>(null);
  const [validTo, setValidTo] = useState("");
  const [maxUses, setMaxUses] = useState("");
  const [perClient, setPerClient] = useState("1");
  const [firstVisit, setFirstVisit] = useState(false);
  const [description, setDescription] = useState("");

  const create = useMutation({
    mutationFn: () =>
      call(
        api.POST(`${ADMIN}/promo-codes`, {
          body: {
            code: code.trim(),
            kind,
            value: kind === "percent" ? Math.round(Number(percent) * 100) : (fixed ?? 0),
            max_discount: kind === "percent" ? maxDiscount : null,
            min_subtotal: minSubtotal ?? 0,
            valid_to: validTo || null,
            max_uses: maxUses ? Number(maxUses) : null,
            max_uses_per_client: Number(perClient) || 1,
            first_visit_only: firstVisit,
            is_active: true,
            description: description.trim() || null,
          },
        }),
      ),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: promoKey });
      onOpenChange(false);
      setCode("");
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent title={t("marketing.newPromo")}>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label={t("marketing.code")} htmlFor="p-code">
            <Input
              id="p-code"
              value={code}
              maxLength={32}
              className="font-mono uppercase"
              placeholder="SPRING20"
              onChange={(e) => setCode(e.target.value.replace(/[^A-Za-z0-9_-]/g, ""))}
            />
          </Field>
          <Field label={t("marketing.kind")} htmlFor="p-kind">
            <NativeSelect
              id="p-kind"
              value={kind}
              onChange={(e) => setKind(e.target.value as "percent" | "fixed")}
            >
              <option value="percent">{t("marketing.percent")}</option>
              <option value="fixed">{t("marketing.fixed")}</option>
            </NativeSelect>
          </Field>
          {kind === "percent" ? (
            <>
              <Field label={t("marketing.valuePercent")} htmlFor="p-percent">
                <Input
                  id="p-percent"
                  type="number"
                  min={1}
                  max={100}
                  value={percent}
                  onChange={(e) => setPercent(e.target.value)}
                />
              </Field>
              <Field label={t("marketing.maxDiscount")} htmlFor="p-max">
                <MoneyInput id="p-max" value={maxDiscount} onChange={setMaxDiscount} />
              </Field>
            </>
          ) : (
            <Field label={t("marketing.valueFixed")} htmlFor="p-fixed">
              <MoneyInput id="p-fixed" value={fixed} onChange={setFixed} />
            </Field>
          )}
          <Field label={t("marketing.minSubtotal")} htmlFor="p-min">
            <MoneyInput id="p-min" value={minSubtotal} onChange={setMinSubtotal} />
          </Field>
          <Field label={t("marketing.validTo")} htmlFor="p-to">
            <Input
              id="p-to"
              type="date"
              value={validTo}
              onChange={(e) => setValidTo(e.target.value)}
            />
          </Field>
          <Field label={t("marketing.maxUses")} htmlFor="p-uses">
            <Input
              id="p-uses"
              type="number"
              min={1}
              value={maxUses}
              onChange={(e) => setMaxUses(e.target.value)}
            />
          </Field>
          <Field label={t("marketing.perClient")} htmlFor="p-per">
            <Input
              id="p-per"
              type="number"
              min={1}
              value={perClient}
              onChange={(e) => setPerClient(e.target.value)}
            />
          </Field>
          <Field label={t("marketing.description")} htmlFor="p-desc">
            <Input
              id="p-desc"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </Field>
          <label className="flex items-center justify-between gap-3 text-sm sm:col-span-2">
            {t("marketing.firstVisit")}
            <Switch checked={firstVisit} onCheckedChange={setFirstVisit} />
          </label>
        </div>
        <div className="flex justify-end">
          <Button
            disabled={code.trim().length < 3}
            loading={create.isPending}
            onClick={() => create.mutate()}
          >
            {t("common.create")}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function Broadcasts() {
  const { t } = useTranslation();
  const { dateTime } = useFormat();
  const client = useQueryClient();
  const codes = usePromoCodes();
  const history = useQuery({
    queryKey: ["broadcasts"],
    queryFn: () => call(api.GET(`${ADMIN}/broadcasts`)),
  });
  const [kind, setKind] = useState<SegmentKind>("inactive");
  const [days, setDays] = useState("45");
  const [tag, setTag] = useState("");
  const [texts, setTexts] = useState({ ru: "", ky: "", en: "" });
  const [promoId, setPromoId] = useState("");
  const [bookButton, setBookButton] = useState(true);
  const [count, setCount] = useState<number | null>(null);

  const segment = {
    kind,
    days: kind === "inactive" ? Number(days) || 1 : null,
    tag: kind === "tag" ? tag.trim() : null,
  };
  const preview = useMutation({
    mutationFn: () => call(api.POST(`${ADMIN}/broadcasts/preview`, { body: segment })),
    onSuccess: (data) => setCount(data.recipients),
    onError: (error) => toast.error(errorMessage(error)),
  });
  const send = useMutation({
    mutationFn: () =>
      call(
        api.POST(`${ADMIN}/broadcasts`, {
          body: { segment, texts, promo_code_id: promoId || null, book_button: bookButton },
        }),
      ),
    onSuccess: (data) => {
      toast.success(t("marketing.sent", { count: data.recipients }));
      setTexts({ ru: "", ky: "", en: "" });
      setCount(null);
      void client.invalidateQueries({ queryKey: ["broadcasts"] });
    },
    onError: (error) => toast.error(errorMessage(error)),
  });
  const reset = (next: () => void) => {
    next();
    setCount(null);
  };

  return (
    <div className="grid gap-4 xl:grid-cols-3">
      <Card className="xl:col-span-2">
        <CardContent className="space-y-4 pt-5">
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label={t("marketing.segment")} htmlFor="b-seg">
              <NativeSelect
                id="b-seg"
                value={kind}
                onChange={(e) => reset(() => setKind(e.target.value as SegmentKind))}
              >
                <option value="inactive">{t("marketing.segmentInactive")}</option>
                <option value="never_visited">{t("marketing.segmentNever")}</option>
                <option value="birthday_month">{t("marketing.segmentBirthday")}</option>
                <option value="tag">{t("marketing.segmentTag")}</option>
                <option value="all">{t("marketing.segmentAll")}</option>
              </NativeSelect>
            </Field>
            {kind === "inactive" && (
              <Field label={t("marketing.days")} htmlFor="b-days">
                <Input
                  id="b-days"
                  type="number"
                  min={1}
                  value={days}
                  onChange={(e) => reset(() => setDays(e.target.value))}
                />
              </Field>
            )}
            {kind === "tag" && (
              <Field label={t("marketing.tag")} htmlFor="b-tag">
                <Input
                  id="b-tag"
                  value={tag}
                  onChange={(e) => reset(() => setTag(e.target.value))}
                />
              </Field>
            )}
          </div>
          <div className="flex items-center gap-3">
            <Button variant="outline" loading={preview.isPending} onClick={() => preview.mutate()}>
              {t("marketing.countRecipients")}
            </Button>
            {count !== null && (
              <span className="text-sm font-medium">{t("marketing.recipients", { count })}</span>
            )}
          </div>

          {(["ru", "ky", "en"] as const).map((lang) => (
            <Field
              key={lang}
              label={t(
                lang === "ru"
                  ? "marketing.textRu"
                  : lang === "ky"
                    ? "marketing.textKy"
                    : "marketing.textEn",
              )}
              htmlFor={`b-text-${lang}`}
            >
              <Textarea
                id={`b-text-${lang}`}
                rows={3}
                maxLength={1000}
                value={texts[lang]}
                onChange={(e) => setTexts({ ...texts, [lang]: e.target.value })}
              />
            </Field>
          ))}
          <p className="text-xs text-muted-foreground">{t("marketing.textHint")}</p>

          <div className="grid gap-3 sm:grid-cols-2">
            <Field label={t("marketing.attachPromo")} htmlFor="b-promo">
              <NativeSelect
                id="b-promo"
                value={promoId}
                onChange={(e) => setPromoId(e.target.value)}
              >
                <option value="">{t("marketing.noPromoAttached")}</option>
                {codes.data
                  ?.filter((promo) => promo.is_active)
                  .map((promo) => (
                    <option key={promo.id} value={promo.id}>
                      {promo.code}
                    </option>
                  ))}
              </NativeSelect>
            </Field>
            <label className="flex items-center justify-between gap-3 self-end pb-2 text-sm">
              {t("marketing.bookButton")}
              <Switch checked={bookButton} onCheckedChange={setBookButton} />
            </label>
          </div>

          <Button
            disabled={!texts.ru.trim() || count === null || count === 0}
            loading={send.isPending}
            onClick={() => {
              if (window.confirm(t("marketing.confirmSend", { count: count ?? 0 }))) send.mutate();
            }}
          >
            <Send /> {t("marketing.send")}
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="space-y-3 pt-5">
          <h3 className="font-medium">{t("marketing.history")}</h3>
          {history.data?.length === 0 && (
            <p className="text-sm text-muted-foreground">{t("marketing.noBroadcasts")}</p>
          )}
          {history.data?.map((item) => (
            <div key={item.id} className="space-y-1 rounded-md border p-3 text-sm">
              <div className="flex justify-between gap-2 text-xs text-muted-foreground">
                <span>{dateTime(item.created_at)}</span>
                <span>{t("marketing.recipients", { count: item.recipients })}</span>
              </div>
              <p className="line-clamp-3 whitespace-pre-line">{item.texts.ru}</p>
              {item.promo_code && <Badge variant="secondary">🎁 {item.promo_code}</Badge>}
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}
