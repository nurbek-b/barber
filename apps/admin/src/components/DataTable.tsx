import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
  type SortingState,
} from "@tanstack/react-table";
import { ArrowDown, ArrowUp } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Button, EmptyState, Skeleton, Table, Td, Th } from "@/components/ui";
import { useIsPhone } from "@/lib/media";
import { cn } from "@/lib/utils";

/**
 * Server-driven table: the parent owns pagination/sorting state and fetches the page;
 * the table only renders and reports changes (manualPagination / manualSorting).
 * With `mobileCard`, phones get a list of cards instead of a wide table.
 */
export function DataTable<T>({
  columns,
  data,
  total,
  page,
  pageSize,
  onPageChange,
  sorting,
  onSortingChange,
  loading,
  onRowClick,
  mobileCard,
}: {
  columns: ColumnDef<T, unknown>[];
  data: T[];
  total: number;
  page: number;
  pageSize: number;
  onPageChange: (page: number) => void;
  sorting?: SortingState;
  onSortingChange?: (sorting: SortingState) => void;
  loading?: boolean;
  onRowClick?: (row: T) => void;
  mobileCard?: (row: T) => ReactNode;
}) {
  const { t } = useTranslation();
  const table = useReactTable({
    data,
    columns,
    getCoreRowModel: getCoreRowModel(),
    manualPagination: true,
    manualSorting: true,
    pageCount: Math.max(1, Math.ceil(total / pageSize)),
    state: { sorting: sorting ?? [], pagination: { pageIndex: page, pageSize } },
    onSortingChange: (updater) => {
      if (!onSortingChange) return;
      onSortingChange(typeof updater === "function" ? updater(sorting ?? []) : updater);
    },
    enableSortingRemoval: false,
  });
  const pages = table.getPageCount();
  const phone = useIsPhone();
  const cards = phone && mobileCard;

  return (
    <div className={cn(!cards && "rounded-lg border bg-card")}>
      {cards ? (
        <div className="flex flex-col gap-2">
          {loading && Array.from({ length: 4 }, (_, i) => <Skeleton key={i} className="h-24" />)}
          {!loading &&
            table
              .getRowModel()
              .rows.map((row) => <div key={row.id}>{mobileCard(row.original)}</div>)}
        </div>
      ) : (
        <Table>
          <thead className="border-b">
            {table.getHeaderGroups().map((group) => (
              <tr key={group.id}>
                {group.headers.map((header) => {
                  const sortable = header.column.getCanSort() && Boolean(onSortingChange);
                  const direction = header.column.getIsSorted();
                  return (
                    <Th key={header.id}>
                      {sortable ? (
                        <button
                          type="button"
                          className="inline-flex items-center gap-1 hover:text-foreground"
                          onClick={header.column.getToggleSortingHandler()}
                        >
                          {flexRender(header.column.columnDef.header, header.getContext())}
                          {direction === "asc" && <ArrowUp className="h-3 w-3" />}
                          {direction === "desc" && <ArrowDown className="h-3 w-3" />}
                        </button>
                      ) : (
                        flexRender(header.column.columnDef.header, header.getContext())
                      )}
                    </Th>
                  );
                })}
              </tr>
            ))}
          </thead>
          <tbody>
            {loading &&
              Array.from({ length: 5 }, (_, i) => (
                <tr key={`s${i}`}>
                  <Td colSpan={columns.length}>
                    <Skeleton className="h-6" />
                  </Td>
                </tr>
              ))}
            {!loading &&
              table.getRowModel().rows.map((row) => (
                <tr
                  key={row.id}
                  className={cn(
                    "border-b last:border-0",
                    onRowClick && "cursor-pointer hover:bg-muted/50",
                  )}
                  onClick={() => onRowClick?.(row.original)}
                >
                  {row.getVisibleCells().map((cell) => (
                    <Td key={cell.id}>
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </Td>
                  ))}
                </tr>
              ))}
          </tbody>
        </Table>
      )}
      {!loading && data.length === 0 && <EmptyState>{t("common.empty")}</EmptyState>}
      <div
        className={cn(
          "flex flex-wrap items-center justify-between gap-2 px-3 py-2 text-sm text-muted-foreground",
          !cards && "border-t",
        )}
      >
        <span>
          {t("common.total")}: {total}
        </span>
        <div className="flex items-center gap-2">
          <span>{t("common.page", { page: page + 1, pages })}</span>
          <Button
            size="sm"
            variant="outline"
            disabled={page === 0}
            onClick={() => onPageChange(page - 1)}
          >
            {t("common.prev")}
          </Button>
          <Button
            size="sm"
            variant="outline"
            disabled={page + 1 >= pages}
            onClick={() => onPageChange(page + 1)}
          >
            {t("common.next")}
          </Button>
        </div>
      </div>
    </div>
  );
}
