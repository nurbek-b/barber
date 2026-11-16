import type { components } from "@barber/api-client";
import { todayKey } from "@barber/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { MoneyInput } from "@/components/MoneyInput";
import {
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Dialog,
  DialogContent,
  Field,
  Input,
  NativeSelect,
  Table,
  Td,
  Th,
} from "@/components/ui";
import { ADMIN, api, call, errorMessage } from "@/lib/api";
import { Can, useCan } from "@/lib/auth";
import { useFormat } from "@/lib/format";

type Balance = components["schemas"]["PayoutBalanceOut"];
type Method = components["schemas"]["PayoutIn"]["method"];

/** What each barber earned, what was paid out and what is owed; the owner records payouts. */
export function PayoutsCard({ until }: { until: string }) {
  const { t } = useTranslation();
  const { money, tz } = useFormat();
  const can = useCan();
  const client = useQueryClient();
  const [target, setTarget] = useState<Balance | null>(null);

  const balances = useQuery({
    queryKey: ["payouts", "balances", until],
    queryFn: () => call(api.GET(`${ADMIN}/payouts/balances`, { params: { query: { until } } })),
  });
  const history = useQuery({
    queryKey: ["payouts", "history"],
    queryFn: () => call(api.GET(`${ADMIN}/payouts`)),
  });
  const refresh = () => void client.invalidateQueries({ queryKey: ["payouts"] });
  const remove = useMutation({
    mutationFn: (id: string) =>
      call(api.DELETE(`${ADMIN}/payouts/{payout_id}`, { params: { path: { payout_id: id } } })),
    onSuccess: () => {
      toast.success(t("payouts.deleted"));
      refresh();
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("payouts.title")}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-sm text-muted-foreground">
          {t("payouts.hint")} {t("payouts.until")} {until}.
        </p>
        <Table>
          <thead className="border-b">
            <tr>
              <Th>{t("booking.barber")}</Th>
              <Th>{t("payouts.earned")}</Th>
              <Th>{t("payouts.paidOut")}</Th>
              <Th>{t("payouts.due")}</Th>
              <Th>{t("payouts.last")}</Th>
              <Th />
            </tr>
          </thead>
          <tbody>
            {balances.data?.map((row) => (
              <tr key={row.barber_id} className="border-b last:border-0">
                <Td className="font-medium">{row.barber_name}</Td>
                <Td className="tabular-nums">{money(row.earned)}</Td>
                <Td className="tabular-nums">{money(row.paid)}</Td>
                <Td
                  className={`tabular-nums font-semibold ${row.due < 0 ? "text-destructive" : ""}`}
                >
                  {money(row.due)}
                </Td>
                <Td>{row.last_paid_on ?? "—"}</Td>
                <Td className="text-right">
                  <Can perm="payouts:write">
                    <Button size="sm" variant="outline" onClick={() => setTarget(row)}>
                      {t("payouts.pay")}
                    </Button>
                  </Can>
                </Td>
              </tr>
            ))}
          </tbody>
        </Table>

        <div>
          <h3 className="mb-2 font-medium">{t("payouts.history")}</h3>
          {history.data?.length === 0 && (
            <p className="text-sm text-muted-foreground">{t("payouts.empty")}</p>
          )}
          <div className="divide-y text-sm">
            {history.data?.map((payout) => (
              <div key={payout.id} className="flex items-center justify-between gap-2 py-2">
                <span>
                  {payout.paid_on} · {payout.barber_name} · {t(`payment.${payout.method}`)}
                  {payout.note ? ` · ${payout.note}` : ""}
                </span>
                <span className="flex items-center gap-2">
                  <span className="tabular-nums font-medium">{money(payout.amount)}</span>
                  {can("payouts:write") && (
                    <Button
                      size="sm"
                      variant="ghost"
                      aria-label={t("payouts.delete")}
                      loading={remove.isPending && remove.variables === payout.id}
                      onClick={() => remove.mutate(payout.id)}
                    >
                      <Trash2 />
                    </Button>
                  )}
                </span>
              </div>
            ))}
          </div>
        </div>
      </CardContent>
      {target && (
        <PayoutDialog
          balance={target}
          today={todayKey(tz)}
          onClose={() => setTarget(null)}
          onSaved={refresh}
        />
      )}
    </Card>
  );
}

function PayoutDialog({
  balance,
  today,
  onClose,
  onSaved,
}: {
  balance: Balance;
  today: string;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { t } = useTranslation();
  const [amount, setAmount] = useState<number | null>(balance.due > 0 ? balance.due : null);
  const [paidOn, setPaidOn] = useState(today);
  const [method, setMethod] = useState<Method>("cash");
  const [note, setNote] = useState("");
  const save = useMutation({
    mutationFn: () =>
      call(
        api.POST(`${ADMIN}/payouts`, {
          body: {
            barber_id: balance.barber_id,
            amount: amount!,
            paid_on: paidOn,
            method,
            note: note.trim() || null,
          },
        }),
      ),
    onSuccess: () => {
      toast.success(t("payouts.saved"));
      onSaved();
      onClose();
    },
    onError: (error) => toast.error(errorMessage(error)),
  });
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent title={`${t("payouts.pay")} · ${balance.barber_name}`}>
        <div className="space-y-3">
          <Field label={t("pay.amount")} htmlFor="payout-amount">
            <MoneyInput id="payout-amount" value={amount} onChange={setAmount} />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label={t("payouts.date")} htmlFor="payout-date">
              <Input
                id="payout-date"
                type="date"
                value={paidOn}
                onChange={(e) => setPaidOn(e.target.value)}
              />
            </Field>
            <Field label={t("booking.paymentMethod")} htmlFor="payout-method">
              <NativeSelect
                id="payout-method"
                value={method}
                onChange={(e) => setMethod(e.target.value as Method)}
              >
                {(["cash", "card", "transfer"] as const).map((m) => (
                  <option key={m} value={m}>
                    {t(`payment.${m}`)}
                  </option>
                ))}
              </NativeSelect>
            </Field>
          </div>
          <Field label={t("payouts.note")} htmlFor="payout-note">
            <Input
              id="payout-note"
              maxLength={300}
              value={note}
              onChange={(e) => setNote(e.target.value)}
            />
          </Field>
          <Button
            disabled={!amount || !paidOn}
            loading={save.isPending}
            onClick={() => save.mutate()}
          >
            {t("payouts.pay")}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
