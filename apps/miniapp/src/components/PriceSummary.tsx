import type { Quote } from "@barber/api-client";
import { computeTotals } from "@barber/ui";

import { useLang, useT, pickI18n } from "../i18n";
import { useMoney } from "./ui";

/** Confirmation price block: lines, bonus toggle with limit, amount to pay. */
export function PriceSummary({
  quote,
  useBonus,
  onToggleBonus,
}: {
  quote: Quote;
  useBonus: boolean;
  onToggleBonus: (value: boolean) => void;
}) {
  const t = useT();
  const lang = useLang();
  const { money } = useMoney();
  const discount = quote.discount ?? 0;
  const totals = computeTotals(
    quote.subtotal,
    quote.max_bonus_spend,
    useBonus ? quote.max_bonus_spend : 0,
    discount,
  );
  const canUse = quote.max_bonus_spend > 0;

  return (
    <div className="space-y-3">
      <ul className="space-y-1">
        {quote.lines.map((line) => (
          <li key={line.service_id} className="flex justify-between gap-3">
            <span>{pickI18n(line.name_i18n, lang)}</span>
            <span className="tabular-nums">{money(line.price)}</span>
          </li>
        ))}
      </ul>
      <div className="flex justify-between border-t border-separator pt-2 text-hint">
        <span>{t("confirm.subtotal")}</span>
        <span className="tabular-nums" data-testid="subtotal">
          {money(totals.subtotal)}
        </span>
      </div>

      {discount > 0 && (
        <div className="flex justify-between text-accent">
          <span>
            {t("confirm.promo")} {quote.promo_code}
          </span>
          <span className="tabular-nums" data-testid="discount">
            −{money(discount)}
          </span>
        </div>
      )}

      <label className={`flex items-center justify-between gap-3 ${canUse ? "" : "opacity-60"}`}>
        <span>
          <span className="block">{t("confirm.useBonus")}</span>
          <span className="block text-xs text-hint">
            {canUse
              ? t("confirm.bonusAvailable", {
                  amount: money(quote.bonus_balance),
                  max: money(quote.max_bonus_spend),
                })
              : t("confirm.bonusNone")}
          </span>
        </span>
        <input
          type="checkbox"
          role="switch"
          aria-label={t("confirm.useBonus")}
          className="h-6 w-11 shrink-0 cursor-pointer appearance-none rounded-full bg-bg-secondary transition before:block before:h-5 before:w-5 before:translate-x-0.5 before:translate-y-0.5 before:rounded-full before:bg-white before:shadow before:transition checked:bg-button checked:before:translate-x-[22px] disabled:cursor-not-allowed"
          checked={useBonus && canUse}
          disabled={!canUse}
          onChange={(event) => onToggleBonus(event.target.checked)}
        />
      </label>
      {totals.bonusSpent > 0 && (
        <div className="flex justify-between text-accent">
          <span>{t("confirm.useBonus")}</span>
          <span className="tabular-nums" data-testid="bonus-spent">
            −{money(totals.bonusSpent)}
          </span>
        </div>
      )}
      <div className="flex justify-between text-lg font-semibold">
        <span>{t("confirm.toPay")}</span>
        <span className="tabular-nums" data-testid="total-due">
          {money(totals.totalDue)}
        </span>
      </div>
    </div>
  );
}

export function bonusToSpend(quote: Quote, useBonus: boolean): number {
  return computeTotals(
    quote.subtotal,
    quote.max_bonus_spend,
    useBonus ? quote.max_bonus_spend : 0,
    quote.discount ?? 0,
  ).bonusSpent;
}
