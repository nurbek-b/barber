import type { components } from "@barber/api-client";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef, SortingState } from "@tanstack/react-table";
import { Plus } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";

import { DataTable } from "@/components/DataTable";
import {
  Badge,
  Button,
  Dialog,
  DialogContent,
  DisabledReason,
  Field,
  Input,
  NativeSelect,
} from "@/components/ui";
import { PageHeader } from "@/features/Layout";
import { ADMIN, api, call, errorMessage } from "@/lib/api";
import { useCan } from "@/lib/auth";
import { useFormat } from "@/lib/format";

type Row = components["schemas"]["ClientRow"];
type Sort = "name" | "created_at" | "visits_count" | "total_spent" | "last_visit_at";
const PAGE = 50;

function useDebounced<T>(value: T, delay = 300): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const id = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(id);
  }, [value, delay]);
  return debounced;
}

export default function Clients() {
  const { t } = useTranslation();
  const { money, date } = useFormat();
  const navigate = useNavigate();
  const can = useCan();
  const [q, setQ] = useState("");
  const [tag, setTag] = useState("");
  const [blocked, setBlocked] = useState<"" | "true" | "false">("");
  const [page, setPage] = useState(0);
  const [sorting, setSorting] = useState<SortingState>([{ id: "created_at", desc: true }]);
  const [creating, setCreating] = useState(false);
  const search = useDebounced(q);
  const sort = (sorting[0]?.id ?? "created_at") as Sort;

  const query = useQuery({
    queryKey: ["clients", { search, tag, blocked, page, sorting }],
    placeholderData: keepPreviousData,
    queryFn: () =>
      call(
        api.GET(`${ADMIN}/clients`, {
          params: {
            query: {
              q: search || undefined,
              tag: tag || undefined,
              blocked: blocked === "" ? undefined : blocked === "true",
              sort,
              desc: sorting[0]?.desc ?? true,
              limit: PAGE,
              offset: page * PAGE,
            },
          },
        }),
      ),
  });

  const columns = useMemo<ColumnDef<Row, unknown>[]>(
    () => [
      {
        id: "name",
        header: t("common.name"),
        enableSorting: true,
        cell: ({ row }) => (
          <div>
            <div className="font-medium">
              {row.original.name}{" "}
              {row.original.is_blocked && (
                <Badge variant="destructive">{t("clients.blocked")}</Badge>
              )}
            </div>
            <div className="text-xs text-muted-foreground">
              {row.original.phone}{" "}
              {row.original.telegram_username && `@${row.original.telegram_username}`}
            </div>
          </div>
        ),
      },
      {
        id: "tags",
        header: t("clients.tags"),
        enableSorting: false,
        cell: ({ row }) => (
          <div className="flex flex-wrap gap-1">
            {row.original.tags.map((item) => (
              <Badge key={item} variant="secondary">
                {item}
              </Badge>
            ))}
          </div>
        ),
      },
      {
        id: "visits_count",
        header: t("clients.visits"),
        enableSorting: true,
        cell: ({ row }) => row.original.visits_count,
      },
      {
        id: "total_spent",
        header: t("clients.spent"),
        enableSorting: true,
        cell: ({ row }) => money(row.original.total_spent),
      },
      {
        id: "bonus",
        header: t("clients.bonus"),
        enableSorting: false,
        cell: ({ row }) => money(row.original.bonus_balance),
      },
      {
        id: "last_visit_at",
        header: t("clients.lastVisit"),
        enableSorting: true,
        cell: ({ row }) => (row.original.last_visit_at ? date(row.original.last_visit_at) : "—"),
      },
    ],
    [t, money, date],
  );

  return (
    <div>
      <PageHeader
        title={t("clients.title")}
        actions={
          can("clients:write") && (
            <Button onClick={() => setCreating(true)}>
              <Plus /> {t("common.add")}
            </Button>
          )
        }
      />
      <div className="mb-4 grid grid-cols-2 gap-2 sm:flex sm:flex-wrap">
        <Input
          className="col-span-2 sm:w-64"
          placeholder={t("booking.searchClient")}
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setPage(0);
          }}
          aria-label={t("common.search")}
        />
        <Input
          className="sm:w-40"
          placeholder={t("clients.tags")}
          value={tag}
          onChange={(e) => {
            setTag(e.target.value);
            setPage(0);
          }}
          aria-label={t("clients.tags")}
        />
        <NativeSelect
          className="sm:w-44"
          value={blocked}
          onChange={(e) => {
            setBlocked(e.target.value as "" | "true" | "false");
            setPage(0);
          }}
          aria-label={t("clients.blocked")}
        >
          <option value="">{t("common.all")}</option>
          <option value="true">{t("clients.blocked")}</option>
          <option value="false">{t("common.active")}</option>
        </NativeSelect>
      </div>
      <DataTable
        columns={columns}
        data={query.data?.items ?? []}
        total={query.data?.total ?? 0}
        page={page}
        pageSize={PAGE}
        onPageChange={setPage}
        sorting={sorting}
        onSortingChange={(next) => {
          setSorting(next);
          setPage(0);
        }}
        loading={query.isPending}
        onRowClick={(row) => navigate(`/clients/${row.id}`)}
        mobileCard={(row) => (
          <button
            type="button"
            onClick={() => navigate(`/clients/${row.id}`)}
            className="flex w-full flex-col gap-1 rounded-lg border bg-card p-3 text-left text-sm active:bg-muted/60"
          >
            <div className="flex items-baseline justify-between gap-2">
              <span className="font-medium">
                {row.name}{" "}
                {row.is_blocked && <Badge variant="destructive">{t("clients.blocked")}</Badge>}
              </span>
              <span className="tabular-nums">{money(row.total_spent)}</span>
            </div>
            <div className="text-muted-foreground">
              {row.phone} {row.telegram_username && `@${row.telegram_username}`}
            </div>
            <div className="text-xs text-muted-foreground">
              {t("clients.visits")}: {row.visits_count} · {t("clients.lastVisit")}:{" "}
              {row.last_visit_at ? date(row.last_visit_at) : "—"}
            </div>
            {row.tags.length > 0 && (
              <div className="flex flex-wrap gap-1">
                {row.tags.map((item) => (
                  <Badge key={item} variant="secondary">
                    {item}
                  </Badge>
                ))}
              </div>
            )}
          </button>
        )}
      />
      <NewClientDialog open={creating} onOpenChange={setCreating} />
    </div>
  );
}

function NewClientDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
}) {
  const { t } = useTranslation();
  const client = useQueryClient();
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const create = useMutation({
    mutationFn: () =>
      call(api.POST(`${ADMIN}/clients`, { body: { name, phone, language: "ru", tags: [] } })),
    onSuccess: (card) => {
      void client.invalidateQueries({ queryKey: ["clients"] });
      onOpenChange(false);
      navigate(`/clients/${card.id}`);
    },
    onError: (error) => toast.error(errorMessage(error)),
  });
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent title={t("booking.newClient")}>
        <Field label={t("common.name")} htmlFor="nc-name">
          <Input id="nc-name" value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field label={t("common.phone")} htmlFor="nc-phone">
          <Input
            id="nc-phone"
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            placeholder="+996"
          />
        </Field>
        <div className="flex items-center justify-end gap-3">
          <DisabledReason
            reason={
              !name.trim()
                ? t("common.fillIn", { fields: t("common.name") })
                : phone.trim().length < 7 && t("common.phoneShort")
            }
          />
          <Button
            disabled={!name.trim() || phone.trim().length < 7}
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
