import { addDaysKey, todayKey } from "@barber/ui";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Card, CardContent, Input } from "@/components/ui";
import { ADMIN, api, call } from "@/lib/api";
import { useFormat } from "@/lib/format";

/** Booking funnel: app sessions reaching each step, per source, with the share of opens. */
export function FunnelCard() {
  const { t } = useTranslation();
  const { tz } = useFormat();
  const [to, setTo] = useState(() => todayKey(tz));
  const [from, setFrom] = useState(() => addDaysKey(todayKey(tz), -29));
  const report = useQuery({
    queryKey: ["funnel", from, to],
    queryFn: () =>
      call(
        api.GET(`${ADMIN}/reports/funnel`, { params: { query: { date_from: from, date_to: to } } }),
      ),
  });
  return (
    <Card>
      <CardContent className="space-y-5 pt-5">
        <div className="flex flex-wrap items-center gap-2">
          <Input
            type="date"
            className="w-40"
            value={from}
            onChange={(e) => setFrom(e.target.value)}
            aria-label={t("common.from")}
          />
          <Input
            type="date"
            className="w-40"
            value={to}
            onChange={(e) => setTo(e.target.value)}
            aria-label={t("common.to")}
          />
          <p className="text-sm text-muted-foreground">{t("funnel.hint")}</p>
        </div>
        <div className="grid gap-6 md:grid-cols-2">
          {report.data?.map((source) => (
            <section key={source.source} className="space-y-2">
              <h3 className="font-medium">{t(`funnel.source_${source.source}`)}</h3>
              {source.steps.map((step) => (
                <div key={step.step} className="space-y-1">
                  <div className="flex justify-between text-sm">
                    <span>{t(`funnel.step_${step.step}`)}</span>
                    <span className="tabular-nums">
                      {step.sessions} · {Math.round(step.rate * 100)}%
                    </span>
                  </div>
                  <div className="h-2 overflow-hidden rounded-full bg-muted">
                    <div
                      className="h-full rounded-full bg-primary"
                      style={{ width: `${Math.round(step.rate * 100)}%` }}
                    />
                  </div>
                </div>
              ))}
            </section>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
