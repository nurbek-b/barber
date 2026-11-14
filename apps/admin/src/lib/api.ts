import { ApiError, call, createApi } from "@barber/api-client";
import { QueryClient } from "@tanstack/react-query";

const BASE = import.meta.env.VITE_API_BASE ?? "";
export const ADMIN = "/api/v1/admin";

let refreshing: Promise<boolean> | null = null;
let onSessionExpired: () => void = () => undefined;

export function setSessionExpiredHandler(handler: () => void): void {
  onSessionExpired = handler;
}

/** Single-flight refresh: concurrent 401s wait for one /auth/refresh call. */
async function refreshSession(): Promise<boolean> {
  refreshing ??= fetch(`${BASE}${ADMIN}/auth/refresh`, { method: "POST", credentials: "include" })
    .then((response) => response.ok)
    .catch(() => false)
    .finally(() => {
      setTimeout(() => {
        refreshing = null;
      }, 0);
    });
  return refreshing;
}

/** fetch with one transparent retry after refreshing an expired access token. */
async function fetchWithRefresh(info: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const input = info instanceof Request ? info : new Request(info, init);
  const retry = input.clone();
  const response = await fetch(input);
  if (response.status !== 401 || input.url.includes("/auth/")) return response;
  if (await refreshSession()) {
    // the CSRF cookie rotated with the session: refresh the header on the retried request
    const csrf = document.cookie.split("; ").find((c) => c.startsWith("csrf_token="));
    if (csrf && !["GET", "HEAD"].includes(retry.method)) {
      retry.headers.set("X-CSRF-Token", decodeURIComponent(csrf.slice("csrf_token=".length)));
    }
    return fetch(retry);
  }
  onSessionExpired();
  return response;
}

export const api = createApi({ baseUrl: BASE, cookies: true, fetch: fetchWithRefresh });

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 20_000,
      refetchOnWindowFocus: true,
      retry: (count, error) =>
        count < 2 && (!(error instanceof ApiError) || error.isNetwork || error.status >= 500),
    },
    mutations: { retry: false },
  },
});

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.isNetwork) return "Network error";
    const details = error.details?.errors as { loc: string[]; msg: string }[] | undefined;
    if (details?.length)
      return details.map((d) => `${d.loc.slice(1).join(".")}: ${d.msg}`).join("; ");
    return error.message;
  }
  return error instanceof Error ? error.message : String(error);
}

/** Download a file endpoint (export) with the session cookies. */
export async function downloadFile(path: string, params: Record<string, string>): Promise<void> {
  const url = `${BASE}${path}?${new URLSearchParams(params)}`;
  let response = await fetch(url, { credentials: "include" });
  if (response.status === 401 && (await refreshSession())) {
    response = await fetch(url, { credentials: "include" });
  }
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const blob = await response.blob();
  const name =
    /filename="([^"]+)"/.exec(response.headers.get("content-disposition") ?? "")?.[1] ?? "export";
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = name;
  link.click();
  URL.revokeObjectURL(link.href);
}

export { ApiError, call };
