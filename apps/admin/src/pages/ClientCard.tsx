import type { AdminBooking } from "@barber/api-client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useParams } from "react-router-dom";
import { toast } from "sonner";

import { MoneyInput } from "@/components/MoneyInput";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Dialog,
  DialogContent,
  Field,
  Input,
  Skeleton,
  Textarea,
} from "@/components/ui";
import { BookingDetailsDialog } from "@/features/BookingDialogs";
import { PageHeader } from "@/features/Layout";
import { pickName, STATUS_VARIANT, useLevels } from "@/features/queries";
import { ADMIN, api, call, errorMessage } from "@/lib/api";
import { Can, useCan } from "@/lib/auth";
import { useFormat } from "@/lib/format";

export default function ClientCard() {
  const { clientId = "" } = useParams();
  const { t, i18n } = useTranslation();
  const { money, date, dateTime } = useFormat();
  const can = useCan();
  const client = useQueryClient();
  const levels = useLevels();
  const [selected, setSelected] = useState<AdminBooking | null>(null);
  const [adjusting, setAdjusting] = useState(false);

  const card = useQuery({
    queryKey: ["clients", clientId],
    queryFn: () =>
      call(api.GET(`${ADMIN}/clients/{client_id}`, { params: { path: { client_id: clientId } } })),
  });
  const history = useQuery({
    queryKey: ["bookings", { clientId }],
    queryFn: () =>
      call(
        api.GET(`${ADMIN}/bookings`, { params: { query: { client_id: clientId, limit: 100 } } }),
      ),
  });
  const bonus = useQuery({
    queryKey: ["clients", clientId, "bonus"],
    enabled: can("clients:read"),
    queryFn: () =>
      call(
        api.GET(`${ADMIN}/clients/{client_id}/bonus`, {
          params: { path: { client_id: clientId } },
        }),
      ),
  });

  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [birthday, setBirthday] = useState("");
  const [tags, setTags] = useState("");
  const [notes, setNotes] = useState("");
  useEffect(() => {
    if (!card.data) return;
    setName(card.data.name);
    setPhone(card.data.phone ?? "");
    setBirthday(card.data.birthday ?? "");
    setTags(card.data.tags.join(", "));
    setNotes(card.data.notes ?? "");
  }, [card.data]);

  const refresh = () => void client.invalidateQueries({ queryKey: ["clients"] });
  const save = useMutation({
    mutationFn: () =>
      call(
        api.PATCH(`${ADMIN}/clients/{client_id}`, {
          params: { path: { client_id: clientId } },
          body: {
            name,
            phone: phone || null,
            birthday: birthday || null,
            tags: tags
              .split(",")
              .map((x) => x.trim())
              .filter(Boolean),
            notes: notes || null,
          },
        }),
      ),
    onSuccess: () => {
      toast.success(t("common.saved"));
      refresh();
    },
    onError: (error) => toast.error(errorMessage(error)),
  });
  const block = useMutation({
    mutationFn: (blocked: boolean) =>
      call(
        api.POST(`${ADMIN}/clients/{client_id}/block`, {
          params: { path: { client_id: clientId } },
          body: { blocked, reason: null },
        }),
      ),
    onSuccess: refresh,
    onError: (error) => toast.error(errorMessage(error)),
  });

  if (card.isPending) return <Skeleton className="h-96" />;
  if (card.isError) return <p className="text-destructive">{errorMessage(card.error)}</p>;
  const c = card.data;
  const level = levels.data?.find((item) => item.id === c.level_id);

  return (
    <div className="space-y-4">
      <PageHeader
        title={c.name}
        actions={
          <Can perm="clients:write">
            <Button
              variant={c.is_blocked ? "outline" : "destructive"}
              onClick={() => block.mutate(!c.is_blocked)}
            >
              {c.is_blocked ? t("clients.unblock") : t("clients.block")}
            </Button>
          </Can>
        }
      />
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
        {[
          [t("clients.visits"), c.visits_count],
          [t("clients.spent"), money(c.total_spent)],
          [t("clients.averageCheck"), money(c.average_check)],
          [t("clients.bonus"), money(c.bonus_balance)],
          [t("clients.noShows"), c.no_show_count],
        ].map(([label, value]) => (
          <Card key={String(label)}>
            <CardContent className="pt-5">
              <div className="text-sm text-muted-foreground">{label}</div>
              <div className="text-xl font-semibold tabular-nums">{value}</div>
            </CardContent>
          </Card>
        ))}
      </div>
      <div className="grid gap-4 xl:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle>{t("barbers.profile")}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex flex-wrap gap-2">
              {c.is_blocked && <Badge variant="destructive">{t("clients.blocked")}</Badge>}
              {level && (
                <Badge>
                  {t("clients.level")}: {pickName(level.name_i18n, i18n.language)}
                </Badge>
              )}
              {c.telegram_username && <Badge variant="secondary">@{c.telegram_username}</Badge>}
            </div>
            <Field label={t("common.name")} htmlFor="c-name">
              <Input id="c-name" value={name} onChange={(e) => setName(e.target.value)} />
            </Field>
            <Field label={t("common.phone")} htmlFor="c-phone">
              <Input id="c-phone" value={phone} onChange={(e) => setPhone(e.target.value)} />
            </Field>
            <Field label={t("clients.birthday")} htmlFor="c-bday">
              <Input
                id="c-bday"
                type="date"
                value={birthday}
                onChange={(e) => setBirthday(e.target.value)}
              />
            </Field>
            <Field label={t("clients.tags")} hint={t("clients.tagsHint")} htmlFor="c-tags">
              <Input id="c-tags" value={tags} onChange={(e) => setTags(e.target.value)} />
            </Field>
            <Field label={t("clients.notes")} htmlFor="c-notes">
              <Textarea id="c-notes" value={notes} onChange={(e) => setNotes(e.target.value)} />
            </Field>
            <Can perm="clients:write">
              <Button loading={save.isPending} onClick={() => save.mutate()}>
                {t("common.save")}
              </Button>
            </Can>
          </CardContent>
        </Card>
        <Card className="xl:col-span-2">
          <CardHeader>
            <CardTitle>{t("clients.history")}</CardTitle>
          </CardHeader>
          <CardContent className="divide-y">
            {history.data?.items.length === 0 && (
              <p className="text-sm text-muted-foreground">{t("common.empty")}</p>
            )}
            {history.data?.items
              .slice()
              .reverse()
              .map((booking) => (
                <button
                  key={booking.id}
                  type="button"
                  onClick={() => setSelected(booking)}
                  className="flex w-full items-center gap-3 py-2 text-left text-sm hover:bg-muted/50"
                >
                  <span className="w-36">{dateTime(booking.start_at)}</span>
                  <span className="flex-1">
                    {booking.barber.name} ·{" "}
                    {booking.services.map((s) => pickName(s.name_i18n, i18n.language)).join(", ")}
                  </span>
                  <Badge variant={STATUS_VARIANT[booking.status]}>
                    {t(`status.${booking.status}`)}
                  </Badge>
                  <span className="w-24 text-right tabular-nums">{money(booking.total_due)}</span>
                </button>
              ))}
          </CardContent>
        </Card>
      </div>
      <Card>
        <CardHeader className="flex-row items-center justify-between">
          <CardTitle>{t("clients.transactions")}</CardTitle>
          <Can perm="bonus:adjust">
            <Button size="sm" variant="outline" onClick={() => setAdjusting(true)}>
              {t("clients.adjust")}
            </Button>
          </Can>
        </CardHeader>
        <CardContent className="divide-y">
          {bonus.data && bonus.data.balance !== bonus.data.ledger_balance && (
            <p className="py-2 text-sm text-destructive" role="alert">
              {t("clients.ledgerMismatch")}
            </p>
          )}
          {bonus.data?.transactions.map((tx) => (
            <div key={tx.id} className="flex items-center gap-3 py-2 text-sm">
              <span className="w-28 text-muted-foreground">{date(tx.created_at)}</span>
              <Badge variant="secondary">{tx.type}</Badge>
              <span className="flex-1 text-muted-foreground">{tx.comment}</span>
              <span className={tx.amount > 0 ? "tabular-nums text-emerald-600" : "tabular-nums"}>
                {tx.amount > 0 ? "+" : ""}
                {money(tx.amount)}
              </span>
              <span className="w-24 text-right tabular-nums text-muted-foreground">
                {money(tx.balance_after)}
              </span>
            </div>
          ))}
        </CardContent>
      </Card>
      <BookingDetailsDialog booking={selected} onClose={() => setSelected(null)} />
      <AdjustDialog clientId={clientId} open={adjusting} onOpenChange={setAdjusting} />
    </div>
  );
}

function AdjustDialog({
  clientId,
  open,
  onOpenChange,
}: {
  clientId: string;
  open: boolean;
  onOpenChange: (o: boolean) => void;
}) {
  const { t } = useTranslation();
  const client = useQueryClient();
  const [amount, setAmount] = useState<number | null>(null);
  const [negative, setNegative] = useState(false);
  const [comment, setComment] = useState("");
  const [days, setDays] = useState("");
  const adjust = useMutation({
    mutationFn: () =>
      call(
        api.POST(`${ADMIN}/clients/{client_id}/bonus/adjust`, {
          params: { path: { client_id: clientId } },
          body: {
            amount: negative ? -(amount ?? 0) : (amount ?? 0),
            comment,
            expires_in_days: days ? Number(days) : null,
          },
        }),
      ),
    onSuccess: () => {
      toast.success(t("common.saved"));
      void client.invalidateQueries({ queryKey: ["clients"] });
      onOpenChange(false);
      setAmount(null);
      setComment("");
    },
    onError: (error) => toast.error(errorMessage(error)),
  });
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent title={t("clients.adjust")}>
        <div className="flex gap-2">
          <Button
            size="sm"
            variant={negative ? "outline" : "default"}
            onClick={() => setNegative(false)}
          >
            +
          </Button>
          <Button
            size="sm"
            variant={negative ? "default" : "outline"}
            onClick={() => setNegative(true)}
          >
            −
          </Button>
        </div>
        <Field label={t("bonus.amount")} htmlFor="adj-amount">
          <MoneyInput id="adj-amount" value={amount} onChange={setAmount} />
        </Field>
        {!negative && (
          <Field label={t("clients.adjustExpires")} htmlFor="adj-days">
            <Input
              id="adj-days"
              type="number"
              min={1}
              value={days}
              onChange={(e) => setDays(e.target.value)}
            />
          </Field>
        )}
        <Field label={t("common.comment")} htmlFor="adj-comment">
          <Textarea id="adj-comment" value={comment} onChange={(e) => setComment(e.target.value)} />
        </Field>
        <div className="flex justify-end">
          <Button
            disabled={!amount || comment.trim().length < 3}
            loading={adjust.isPending}
            onClick={() => adjust.mutate()}
          >
            {t("common.save")}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
