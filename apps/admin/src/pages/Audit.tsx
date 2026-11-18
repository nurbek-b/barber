import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Button, Card, CardContent, Input, Table, Td, Th } from "@/components/ui";
import { PageHeader } from "@/features/Layout";
import { ADMIN, api, call } from "@/lib/api";
import { useFormat } from "@/lib/format";

const PAGE = 50;

function Changes({
  before,
  after,
}: {
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
}) {
  const keys = [...new Set([...Object.keys(before ?? {}), ...Object.keys(after ?? {})])];
  if (!keys.length) return null;
  return (
    <div className="space-y-0.5 font-mono text-xs">
      {keys.map((key) => (
        <div key={key}>
          <span className="text-muted-foreground">{key}:</span>{" "}
          {before && key in before && (
            <span className="text-destructive line-through">{JSON.stringify(before[key])}</span>
          )}{" "}
          {after && key in after && (
            <span className="text-emerald-600">{JSON.stringify(after[key])}</span>
          )}
        </div>
      ))}
    </div>
  );
}

export default function Audit() {
  const { t } = useTranslation();
  const { dateTime } = useFormat();
  const [action, setAction] = useState("");
  const [page, setPage] = useState(0);
  const log = useQuery({
    queryKey: ["audit", action, page],
    placeholderData: keepPreviousData,
    queryFn: () =>
      call(
        api.GET(`${ADMIN}/audit-log`, {
          params: { query: { action: action || undefined, limit: PAGE, offset: page * PAGE } },
        }),
      ),
  });
  const pages = Math.max(1, Math.ceil((log.data?.total ?? 0) / PAGE));

  return (
    <div>
      <PageHeader title={t("audit.title")} />
      <Input
        className="mb-4 w-full sm:w-80"
        placeholder={t("audit.filter")}
        value={action}
        onChange={(e) => {
          setAction(e.target.value);
          setPage(0);
        }}
        aria-label={t("audit.filter")}
      />
      <Card>
        <CardContent className="pt-5">
          <Table>
            <thead className="border-b">
              <tr>
                <Th>{t("audit.when")}</Th>
                <Th>{t("audit.actor")}</Th>
                <Th>{t("audit.action")}</Th>
                <Th>{t("audit.entity")}</Th>
                <Th>{t("audit.changes")}</Th>
              </tr>
            </thead>
            <tbody>
              {log.data?.items.map((entry) => (
                <tr key={entry.id} className="border-b align-top last:border-0">
                  <Td className="whitespace-nowrap">{dateTime(entry.created_at)}</Td>
                  <Td>
                    {entry.actor_name ?? entry.actor_type}
                    <div className="text-xs text-muted-foreground">{entry.ip}</div>
                  </Td>
                  <Td className="font-mono text-xs">{entry.action}</Td>
                  <Td className="text-xs">
                    {entry.entity_type}
                    <div className="font-mono text-muted-foreground">
                      {entry.entity_id?.slice(0, 8)}
                    </div>
                  </Td>
                  <Td>
                    <Changes before={entry.before ?? null} after={entry.after ?? null} />
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
          <div className="mt-3 flex items-center justify-end gap-2 text-sm text-muted-foreground">
            {t("common.page", { page: page + 1, pages })}
            <Button
              size="sm"
              variant="outline"
              disabled={page === 0}
              onClick={() => setPage(page - 1)}
            >
              {t("common.prev")}
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={page + 1 >= pages}
              onClick={() => setPage(page + 1)}
            >
              {t("common.next")}
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
