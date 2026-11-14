import { ApiError } from "@barber/api-client";
import { formatMoney, formatMoneyRange } from "@barber/ui";
import { useEffect, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";

import { useSalon } from "../api";
import { useLang, useT, type MessageKey } from "../i18n";
import { telegramEnv } from "../telegram/sdk";

export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`animate-pulse rounded-xl bg-bg-secondary ${className}`} aria-hidden />;
}

export function SkeletonList({ rows = 4, height = "h-16" }: { rows?: number; height?: string }) {
  return (
    <div className="space-y-2" data-testid="skeleton">
      {Array.from({ length: rows }, (_, index) => (
        <Skeleton key={index} className={height} />
      ))}
    </div>
  );
}

export function errorKey(error: unknown): MessageKey {
  if (error instanceof ApiError) {
    if (error.isNetwork) return "error.network";
    if (error.code === "client_blocked") return "error.blocked";
  }
  return "error.generic";
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const t = useT();
  const message =
    error instanceof ApiError && !error.isNetwork && error.status < 500 && error.message
      ? error.message
      : t(errorKey(error));
  return (
    <div className="flex flex-col items-center gap-3 py-10 text-center" role="alert">
      <p className="text-hint">{message}</p>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="rounded-lg px-4 py-2 font-medium text-link"
        >
          {t("button.retry")}
        </button>
      )}
    </div>
  );
}

export function OfflineBanner() {
  const t = useT();
  const [online, setOnline] = useState(() => navigator.onLine);
  useEffect(() => {
    const update = () => setOnline(navigator.onLine);
    window.addEventListener("online", update);
    window.addEventListener("offline", update);
    return () => {
      window.removeEventListener("online", update);
      window.removeEventListener("offline", update);
    };
  }, []);
  if (online) return null;
  return (
    <div className="sticky top-0 z-30 bg-destructive px-4 py-2 text-center text-sm text-white">
      {t("error.offline")}
    </div>
  );
}

export function Screen({
  title,
  step,
  totalSteps,
  children,
  withMainButton = false,
  back = false,
}: {
  title: string;
  step?: number;
  totalSteps?: number;
  children: ReactNode;
  withMainButton?: boolean;
  back?: boolean;
}) {
  const t = useT();
  const navigate = useNavigate();
  const showInPageBack = back && !telegramEnv().native;
  return (
    <main
      className={`mx-auto min-h-screen max-w-xl px-4 pt-[calc(12px+var(--safe-top))] ${
        withMainButton ? "pb-28" : "pb-24"
      }`}
    >
      <header className="mb-4">
        <div className="flex items-center gap-2">
          {showInPageBack && (
            <button
              type="button"
              aria-label={t("button.back")}
              onClick={() => navigate(-1)}
              className="-ml-2 rounded-full px-2 text-2xl leading-none text-link"
            >
              ‹
            </button>
          )}
          <h1 className="text-xl font-semibold">{title}</h1>
        </div>
        {step && totalSteps && (
          <div className="mt-3">
            <div className="mb-1 text-xs text-hint">
              {t("step.of", { n: step, total: totalSteps })}
            </div>
            <div className="flex gap-1" aria-hidden>
              {Array.from({ length: totalSteps }, (_, index) => (
                <span
                  key={index}
                  className={`h-1 flex-1 rounded-full ${index < step ? "bg-button" : "bg-bg-secondary"}`}
                />
              ))}
            </div>
          </div>
        )}
      </header>
      {children}
    </main>
  );
}

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <section className={`rounded-2xl bg-section p-4 shadow-sm ${className}`}>{children}</section>
  );
}

export function Avatar({
  name,
  url,
  size = 48,
}: {
  name: string;
  url?: string | null;
  size?: number;
}) {
  const initials = name
    .split(/\s+/)
    .map((part) => part[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
  return url ? (
    <img
      src={url}
      alt=""
      width={size}
      height={size}
      loading="lazy"
      className="shrink-0 rounded-full object-cover"
      style={{ width: size, height: size }}
    />
  ) : (
    <div
      className="flex shrink-0 items-center justify-center rounded-full bg-button/15 font-semibold text-button"
      style={{ width: size, height: size }}
      aria-hidden
    >
      {initials || "✂"}
    </div>
  );
}

/** Money formatter bound to the salon currency and UI language. */
export function useMoney() {
  const lang = useLang();
  const currency = useSalon().data?.currency ?? "KGS";
  return {
    money: (amount: number) => formatMoney(amount, currency, lang),
    range: (min: number, max: number) => formatMoneyRange(min, max, currency, lang),
  };
}

export function useTimezone(): string {
  return useSalon().data?.timezone ?? "Asia/Bishkek";
}
