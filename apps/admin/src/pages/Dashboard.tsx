import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { Badge, Card, CardContent, CardHeader, CardTitle, Skeleton } from "@/components/ui";
import { PageHeader } from "@/features/Layout";
import { STATUS_VARIANT } from "@/features/queries";
import { ADMIN, api, call } from "@/lib/api";
import { useFormat } from "@/lib/format";

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <Card>
      <CardHeader className="p-3 pb-1 sm:p-5 sm:pb-1">
        <span className="text-xs text-muted-foreground sm:text-sm">{label}</span>
      </CardHeader>
      <CardContent className="p-3 pt-0 sm:p-5 sm:pt-0">
        <div
          className="text-lg font-semibold tabular-nums sm:text-2xl"
          data-testid={`stat-${label}`}
        >
          {value}
        </div>
      </CardContent>
    </Card>
  );
}

export default function Dashboard() {
  const { t } = useTranslation();
  const { money, time } = useFormat();
  const data = useQuery({
    queryKey: ["dashboard"],
    queryFn: () => call(api.GET(`${ADMIN}/dashboard`)),
    refetchInterval: 60_000,
  });

  if (data.isPending) return <Skeleton className="h-96 w-full" />;
  if (data.isError) return <p className="text-destructive">{String(data.error)}</p>;
  const d = data.data;
  const chart = d.revenue_chart.map((point) => ({
    day: point.date.slice(8, 10) + "." + point.date.slice(5, 7),
    revenue: Math.trunc(point.revenue / 100), // chart axis in major units (display only)
    bookings: point.bookings,
  }));

  return (
    <div className="space-y-6">
      <PageHeader title={t("nav.dashboard")} />
      <div className="grid grid-cols-2 gap-2 sm:gap-4 xl:grid-cols-3">
        <Stat label={t("dashboard.today")} value={d.bookings_today} />
        <Stat label={t("dashboard.revenueDay")} value={money(d.revenue_day)} />
        <Stat label={t("dashboard.revenueWeek")} value={money(d.revenue_week)} />
        <Stat label={t("dashboard.revenueMonth")} value={money(d.revenue_month)} />
        <Stat label={t("dashboard.averageCheck")} value={money(d.average_check)} />
        <Stat label={t("dashboard.newClients")} value={d.new_clients_month} />
      </div>
      <div className="grid gap-4 xl:grid-cols-3">
        <Card className="xl:col-span-2">
          <CardHeader>
            <CardTitle>{t("dashboard.chart")}</CardTitle>
          </CardHeader>
          <CardContent className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={chart}>
                <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                <XAxis dataKey="day" fontSize={11} tickLine={false} />
                <YAxis fontSize={11} tickLine={false} width={60} />
                <Tooltip
                  formatter={(value: number) => [money(value * 100), t("dashboard.revenueDay")]}
                  contentStyle={{
                    background: "hsl(var(--popover))",
                    border: "1px solid hsl(var(--border))",
                  }}
                />
                <Bar dataKey="revenue" fill="hsl(var(--primary))" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>{t("dashboard.load")}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {d.barbers.map((barber) => (
              <div key={barber.barber_id}>
                <div className="mb-1 flex justify-between text-sm">
                  <span>{barber.name}</span>
                  <span className="tabular-nums text-muted-foreground">
                    {barber.load_percent}% · {barber.bookings}
                  </span>
                </div>
                <div className="h-2 rounded-full bg-muted">
                  <div
                    className="h-2 rounded-full bg-primary"
                    style={{ width: `${barber.load_percent}%` }}
                  />
                </div>
              </div>
            ))}
          </CardContent>
        </Card>
      </div>
      <Card>
        <CardHeader>
          <CardTitle>{t("dashboard.upcoming")}</CardTitle>
        </CardHeader>
        <CardContent className="divide-y">
          {d.upcoming.length === 0 && (
            <p className="text-sm text-muted-foreground">{t("common.empty")}</p>
          )}
          {d.upcoming.map((item) => (
            <div
              key={String(item.id)}
              className="flex items-center justify-between gap-3 py-2 text-sm"
            >
              <span className="w-14 font-medium tabular-nums">{time(String(item.start_at))}</span>
              <span className="flex-1">{String(item.client ?? "—")}</span>
              <span className="text-muted-foreground">{String(item.barber)}</span>
              <Badge
                variant={STATUS_VARIANT[item.status as keyof typeof STATUS_VARIANT] ?? "default"}
              >
                {t(`status.${String(item.status)}`)}
              </Badge>
              <span className="w-24 text-right tabular-nums">{money(Number(item.total_due))}</span>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}
