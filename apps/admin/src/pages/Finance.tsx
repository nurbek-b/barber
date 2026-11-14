import { addDaysKey, todayKey } from "@barber/ui";
import { useQuery } from "@tanstack/react-query";
import { Download } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { toast } from "sonner";

import {
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Input,
  Skeleton,
  Table,
  Td,
  Th,
} from "@/components/ui";
import { PageHeader } from "@/features/Layout";
import { pickName } from "@/features/queries";
import { ADMIN, api, call, downloadFile, errorMessage } from "@/lib/api";
import { Can } from "@/lib/auth";
import { useFormat } from "@/lib/format";

export default function Finance() {
  const { t, i18n } = useTranslation();
  const { money, tz } = useFormat();
  const [to, setTo] = useState(() => todayKey(tz));
  const [from, setFrom] = useState(() => addDaysKey(todayKey(tz), -29));
  const report = useQuery({
    queryKey: ["finance", from, to],
    queryFn: () =>
      call(
        api.GET(`${ADMIN}/finance/report`, { params: { query: { date_from: from, date_to: to } } }),
      ),
  });

  const exportAs = (format: "csv" | "xlsx") =>
    downloadFile(`${ADMIN}/finance/export`, { date_from: from, date_to: to, format }).catch(
      (error) => toast.error(errorMessage(error)),
    );

  return (
    <div className="space-y-4">
      <PageHeader
        title={t("finance.title")}
        actions={
          <>
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
            <Can perm="finance:export">
              <Button variant="outline" onClick={() => void exportAs("csv")}>
                <Download /> CSV
              </Button>
              <Button variant="outline" onClick={() => void exportAs("xlsx")}>
                <Download /> XLSX
              </Button>
            </Can>
          </>
        }
      />
      {report.isPending && <Skeleton className="h-64" />}
      {report.isError && <p className="text-destructive">{errorMessage(report.error)}</p>}
      {report.data && (
        <>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            {[
              [t("finance.visits"), String(report.data.totals.bookings)],
              [t("finance.subtotal"), money(report.data.totals.subtotal)],
              [t("finance.bonusSpent"), money(report.data.totals.bonus_spent)],
              [t("finance.paid"), money(report.data.totals.paid)],
            ].map(([label, value]) => (
              <Card key={label}>
                <CardContent className="pt-5">
                  <div className="text-sm text-muted-foreground">{label}</div>
                  <div className="text-2xl font-semibold tabular-nums">{value}</div>
                </CardContent>
              </Card>
            ))}
          </div>
          <Card>
            <CardContent className="h-64 pt-5">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart
                  data={report.data.daily.map((d) => ({
                    day: d.date.slice(5),
                    revenue: Math.trunc(d.revenue / 100),
                  }))}
                >
                  <XAxis dataKey="day" fontSize={11} />
                  <YAxis fontSize={11} width={60} />
                  <Tooltip
                    formatter={(v: number) => money(v * 100)}
                    contentStyle={{ background: "hsl(var(--popover))" }}
                  />
                  <Line
                    type="monotone"
                    dataKey="revenue"
                    stroke="hsl(var(--primary))"
                    strokeWidth={2}
                    dot={false}
                  />
                </LineChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>
          <div className="grid gap-4 xl:grid-cols-3">
            <Card className="xl:col-span-2">
              <CardHeader>
                <CardTitle>{t("finance.byBarber")}</CardTitle>
              </CardHeader>
              <CardContent>
                <Table>
                  <thead className="border-b">
                    <tr>
                      <Th>{t("booking.barber")}</Th>
                      <Th>{t("finance.visits")}</Th>
                      <Th>{t("finance.subtotal")}</Th>
                      <Th>{t("finance.bonusSpent")}</Th>
                      <Th>{t("finance.paid")}</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {report.data.by_barber.map((row) => (
                      <tr key={row.barber_id} className="border-b last:border-0">
                        <Td className="font-medium">{row.name}</Td>
                        <Td>{row.bookings}</Td>
                        <Td className="tabular-nums">{money(row.subtotal)}</Td>
                        <Td className="tabular-nums">{money(row.bonus_spent)}</Td>
                        <Td className="tabular-nums">{money(row.paid)}</Td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              </CardContent>
            </Card>
            <div className="space-y-4">
              <Card>
                <CardHeader>
                  <CardTitle>{t("finance.byService")}</CardTitle>
                </CardHeader>
                <CardContent className="space-y-1 text-sm">
                  {report.data.by_service.map((row) => (
                    <div
                      key={`${row.service_id}-${row.name_i18n.ru}`}
                      className="flex justify-between"
                    >
                      <span>
                        {pickName(row.name_i18n, i18n.language)} × {row.count}
                      </span>
                      <span className="tabular-nums">{money(row.revenue)}</span>
                    </div>
                  ))}
                </CardContent>
              </Card>
              <Card>
                <CardHeader>
                  <CardTitle>{t("finance.byMethod")}</CardTitle>
                </CardHeader>
                <CardContent className="space-y-1 text-sm">
                  {report.data.by_payment_method.map((row) => (
                    <div key={row.payment_method ?? "none"} className="flex justify-between">
                      <span>
                        {row.payment_method ? t(`payment.${row.payment_method}`) : "—"} ×{" "}
                        {row.bookings}
                      </span>
                      <span className="tabular-nums">{money(row.paid)}</span>
                    </div>
                  ))}
                </CardContent>
              </Card>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
