import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { Badge, Button, Dialog, DialogContent, DialogTrigger, EmptyState } from "@/components/ui";
import { ADMIN, api, call } from "@/lib/api";
import { useCan } from "@/lib/auth";
import { useFormat } from "@/lib/format";
import {
  beep,
  connectRealtime,
  websocketUrl,
  type ConnectionState,
  type RealtimeEvent,
} from "@/lib/realtime";
import { cn } from "@/lib/utils";

const feedKey = ["notifications", "feed"] as const;
const unreadKey = ["notifications", "unread"] as const;

/** Queries that depend on bookings: refreshed whenever an event arrives. */
const LIVE_KEYS = [["calendar"], ["bookings"], ["dashboard"], ["finance"], ["clients"]];

function describe(event: { payload: Record<string, unknown> }): string {
  const p = event.payload;
  return [p.when, p.client, p.barber].filter(Boolean).join(" · ");
}

export function useRealtime(): ConnectionState {
  const client = useQueryClient();
  const { t } = useTranslation();
  const can = useCan();
  const [state, setState] = useState<ConnectionState>("connecting");
  const enabled = can("notifications:read");
  const tRef = useRef(t);
  tRef.current = t;

  useEffect(() => {
    if (!enabled) return;
    const refresh = () => {
      for (const key of LIVE_KEYS) void client.invalidateQueries({ queryKey: key });
      void client.invalidateQueries({ queryKey: ["notifications"] });
    };
    return connectRealtime({
      url: websocketUrl("/api/v1/admin/ws"),
      onState: setState,
      onReconnect: refresh, // catch up: the feed is persisted on the server
      onEvent: (event: RealtimeEvent) => {
        beep();
        toast(tRef.current(`notifications.${event.type}`, { defaultValue: event.type }), {
          description: describe(event),
        });
        refresh();
      },
    });
  }, [client, enabled]);
  return state;
}

export function NotificationsBell({ connection }: { connection: ConnectionState }) {
  const { t } = useTranslation();
  const { dateTime } = useFormat();
  const client = useQueryClient();
  const [open, setOpen] = useState(false);
  const unread = useQuery({
    queryKey: unreadKey,
    queryFn: () => call(api.GET(`${ADMIN}/notifications/unread-count`)),
    refetchInterval: connection === "open" ? false : 60_000,
  });
  const feed = useQuery({
    queryKey: feedKey,
    enabled: open,
    queryFn: () => call(api.GET(`${ADMIN}/notifications`, { params: { query: { limit: 50 } } })),
  });
  const markAll = useMutation({
    mutationFn: () => call(api.POST(`${ADMIN}/notifications/read-all`)),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["notifications"] }),
  });
  const markOne = useMutation({
    mutationFn: (id: string) =>
      call(
        api.POST(`${ADMIN}/notifications/{notification_id}/read`, {
          params: { path: { notification_id: id } },
        }),
      ),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["notifications"] }),
  });
  const count = unread.data?.unread ?? 0;

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          aria-label={t("notifications.title")}
          className="relative"
        >
          <Bell />
          {count > 0 && (
            <span
              data-testid="unread-badge"
              className="absolute -right-0.5 -top-0.5 min-w-4 rounded-full bg-destructive px-1 text-[10px] font-semibold leading-4 text-destructive-foreground"
            >
              {count > 99 ? "99+" : count}
            </span>
          )}
          <span
            className={cn(
              "absolute bottom-1 right-1 h-1.5 w-1.5 rounded-full",
              connection === "open" ? "bg-emerald-500" : "bg-amber-500",
            )}
            title={
              connection === "open" ? t("notifications.live") : t("notifications.reconnecting")
            }
          />
        </Button>
      </DialogTrigger>
      <DialogContent title={t("notifications.title")} side="right">
        <div className="flex justify-end">
          <Button size="sm" variant="outline" onClick={() => markAll.mutate()} disabled={!count}>
            {t("notifications.markAll")}
          </Button>
        </div>
        {feed.data?.length === 0 && <EmptyState>{t("notifications.empty")}</EmptyState>}
        <ul className="space-y-2">
          {feed.data?.map((item) => (
            <li key={item.id}>
              <button
                type="button"
                onClick={() => !item.read && markOne.mutate(item.id)}
                className={cn(
                  "w-full rounded-md border p-3 text-left text-sm transition hover:bg-accent",
                  !item.read && "border-primary/40 bg-primary/5",
                )}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-medium">
                    {t(`notifications.${item.type}`, { defaultValue: item.type })}
                  </span>
                  {!item.read && <Badge>•</Badge>}
                </div>
                <div className="text-muted-foreground">{describe(item)}</div>
                <div className="mt-1 text-xs text-muted-foreground">
                  {dateTime(item.created_at)}
                </div>
              </button>
            </li>
          ))}
        </ul>
      </DialogContent>
    </Dialog>
  );
}
