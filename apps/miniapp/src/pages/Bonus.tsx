import type { BonusSummary } from "@barber/api-client";
import { formatDate, formatPercentBp } from "@barber/ui";
import { useNavigate } from "react-router-dom";

import { useBonus, useBonusHistory, useMySubscriptions, useReferral } from "../api";
import {
  Card,
  ErrorState,
  Screen,
  Skeleton,
  SkeletonList,
  useMoney,
  useTimezone,
} from "../components/ui";
import { pickI18n, useLang, useT, type MessageKey } from "../i18n";
import { share } from "../telegram/sdk";
import { useBackButton, useMainButton } from "../telegram/hooks";

/** Progress towards the next level, by visits or by money (whichever is closer). */
export function LevelProgress({ summary }: { summary: BonusSummary }) {
  const t = useT();
  const lang = useLang();
  const { money } = useMoney();
  const next = summary.next_level;
  if (!next) return <p className="text-sm text-hint">{t("bonus.top")}</p>;

  const visitShare = next.min_visits > 0 ? 1 - summary.visits_left / next.min_visits : 0;
  const spentShare = next.min_spent > 0 ? 1 - summary.spent_left / next.min_spent : 0;
  const ratio =
    summary.level_rule === "all"
      ? Math.min(visitShare, spentShare)
      : Math.max(visitShare, spentShare);
  const percent = Math.round(Math.max(0, Math.min(1, ratio)) * 100);

  return (
    <div>
      <div className="mb-1 h-2 overflow-hidden rounded-full bg-bg-secondary">
        <div
          className="h-full rounded-full bg-button"
          style={{ width: `${percent}%` }}
          data-testid="level-bar"
        />
      </div>
      <p className="text-sm text-hint">
        {t(summary.level_rule === "all" ? "bonus.nextAll" : "bonus.next", {
          level: pickI18n(next.name_i18n, lang),
          visits: summary.visits_left,
          amount: money(summary.spent_left),
        })}
      </p>
    </div>
  );
}

export default function Bonus() {
  const t = useT();
  const lang = useLang();
  const tz = useTimezone();
  const navigate = useNavigate();
  const { money } = useMoney();
  const bonus = useBonus();
  const subscriptions = useMySubscriptions();
  const history = useBonusHistory();
  const referral = useReferral();

  useBackButton(() => navigate("/"));
  useMainButton({ text: "", visible: false, onClick: () => undefined });

  if (bonus.isError) {
    return (
      <Screen title={t("nav.bonus")}>
        <ErrorState error={bonus.error} onRetry={() => void bonus.refetch()} />
      </Screen>
    );
  }
  const summary = bonus.data;
  const items = history.data?.pages.flatMap((page) => page.items) ?? [];

  return (
    <Screen title={t("nav.bonus")}>
      <div className="space-y-4">
        {!summary && <Skeleton className="h-40" />}
        {summary && (
          <Card className="space-y-3">
            {!summary.enabled && <p className="text-sm text-hint">{t("bonus.disabled")}</p>}
            <div>
              <div className="text-sm text-hint">{t("bonus.balance")}</div>
              <div
                className="text-3xl font-semibold tabular-nums text-brand2-ink"
                data-testid="bonus-balance"
              >
                {money(summary.balance)}
              </div>
            </div>
            <div className="flex items-center justify-between">
              <span className="rounded-full bg-brand2/15 px-3 py-1 text-sm font-medium text-brand2-ink">
                {summary.level ? pickI18n(summary.level.name_i18n, lang) : t("bonus.level")}
              </span>
              <span className="text-sm text-hint">
                {t("bonus.cashback", { percent: formatPercentBp(summary.cashback_bp, lang) })}
              </span>
            </div>
            <LevelProgress summary={summary} />
            {summary.expiring.map((item) => (
              <p key={item.expires_at} className="text-sm text-destructive">
                {t("bonus.expiring", {
                  date: formatDate(item.expires_at, tz, lang),
                  amount: money(item.amount),
                })}
              </p>
            ))}
          </Card>
        )}
        {subscriptions.data
          ?.filter((sub) => sub.state === "active")
          .map((sub) => (
            <Card key={sub.id} className="space-y-1">
              <div className="text-sm text-hint">🎟 {t("subs.title")}</div>
              <div className="font-semibold">{sub.name}</div>
              <div className="flex justify-between text-sm">
                <span>{t("subs.left", { left: sub.visits_left, total: sub.visits_total })}</span>
                <span className="text-hint">
                  {t("subs.until", { date: formatDate(sub.expires_on, tz, lang) })}
                </span>
              </div>
            </Card>
          ))}

        {referral.data?.enabled && (
          <Card className="space-y-2">
            <div className="font-semibold">{t("bonus.invite")}</div>
            <p className="text-sm text-hint">
              {t("bonus.inviteText", {
                referee: money(referral.data.referee_amount),
                referrer: money(referral.data.referrer_amount),
              })}
            </p>
            <button
              type="button"
              onClick={() => referral.data && share(referral.data.miniapp_link, t("bonus.invite"))}
              className="w-full rounded-xl bg-button py-3 font-medium text-button-text"
            >
              {t("bonus.share")}
            </button>
          </Card>
        )}

        <section>
          <h2 className="mb-2 px-1 text-sm font-medium uppercase text-hint">
            {t("bonus.history")}
          </h2>
          {history.isPending && <SkeletonList rows={4} height="h-12" />}
          <Card className="divide-y divide-separator p-0">
            {items.map((tx) => (
              <div key={tx.id} className="flex items-center justify-between gap-3 px-4 py-3">
                <div>
                  <div className="text-sm">{t(`tx.${tx.type}` as MessageKey)}</div>
                  <div className="text-xs text-hint">{formatDate(tx.created_at, tz, lang)}</div>
                </div>
                <div className={`tabular-nums ${tx.amount > 0 ? "text-green-600" : "text-hint"}`}>
                  {tx.amount > 0 ? "+" : "−"}
                  {money(Math.abs(tx.amount))}
                </div>
              </div>
            ))}
          </Card>
          {history.hasNextPage && (
            <button
              type="button"
              className="mt-3 w-full py-2 text-link"
              onClick={() => void history.fetchNextPage()}
            >
              {t("bookings.more")}
            </button>
          )}
        </section>
      </div>
    </Screen>
  );
}
