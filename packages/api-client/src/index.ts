import createClient, { type Middleware } from "openapi-fetch";

import type { components, paths } from "./schema";

export type { components, paths } from "./schema";

type Schemas = components["schemas"];

// Handy aliases used across apps.
export type BarberPublic = Schemas["PublicBarberOut"];
export type PublicCatalog = Schemas["PublicCatalogOut"];
export type PublicService = Schemas["PublicServiceOut"];
export type ServiceCategory = Schemas["ServiceCategoryOut"];
export type Salon = Schemas["SalonPublicOut"];
export type ClientMe = Schemas["ClientMe"];
export type AvailabilityDays = Schemas["AvailabilityDaysOut"];
export type AvailabilitySlots = Schemas["AvailabilitySlotsOut"];
export type Slot = Schemas["Slot"];
export type Hold = Schemas["HoldOut"];
export type Quote = Schemas["QuoteOut"];
export type Booking = Schemas["BookingOut"];
export type BookingPage = Schemas["BookingPage"];
export type RepeatDraft = Schemas["RepeatDraftOut"];
export type BonusSummary = Schemas["BonusSummaryOut"];
export type BonusTransaction = Schemas["BonusTransactionOut"];
export type Referral = Schemas["ReferralOut"];
export type AdminMe = Schemas["AdminMe"];
export type AdminBooking = Schemas["AdminBookingOut"];

export interface ErrorBody {
  code: string;
  message: string;
  details?: Record<string, unknown> | null;
  request_id?: string | null;
}

/** Every non-2xx response becomes an ApiError with the backend's unified error body. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: Record<string, unknown>;
  readonly requestId: string | null;

  constructor(status: number, body: ErrorBody) {
    super(body.message);
    this.name = "ApiError";
    this.status = status;
    this.code = body.code;
    this.details = body.details ?? {};
    this.requestId = body.request_id ?? null;
  }

  get isNetwork(): boolean {
    return this.status === 0;
  }
}

export const NETWORK_ERROR = "network_error";

async function toApiError(response: Response): Promise<ApiError> {
  try {
    const json = (await response.clone().json()) as { error?: ErrorBody };
    if (json.error?.code) return new ApiError(response.status, json.error);
  } catch {
    // not JSON
  }
  return new ApiError(response.status, {
    code: `http_${response.status}`,
    message: response.statusText || "Request failed",
  });
}

export interface ClientOptions {
  baseUrl: string;
  /** Mini App: returns `tma <initData>`. */
  authorization?: () => string | null;
  /** Admin: send cookies and mirror the csrf_token cookie into X-CSRF-Token. */
  cookies?: boolean;
  /**
   * Admin behind Firebase Hosting: the session lives in one httpOnly `__session` cookie, so
   * the CSRF token comes from the login/refresh response instead of a readable cookie.
   */
  csrfToken?: () => string | null;
  fetch?: typeof fetch;
}

function readCookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie.split("; ").find((item) => item.startsWith(`${name}=`));
  return match ? decodeURIComponent(match.slice(name.length + 1)) : null;
}

const SAFE = new Set(["GET", "HEAD", "OPTIONS"]);

export function createApi(options: ClientOptions) {
  const client = createClient<paths>({
    baseUrl: options.baseUrl,
    credentials: options.cookies ? "include" : "same-origin",
    fetch: options.fetch,
  });

  const auth: Middleware = {
    onRequest({ request }) {
      const value = options.authorization?.();
      if (value) request.headers.set("Authorization", value);
      if (options.cookies && !SAFE.has(request.method)) {
        const csrf = options.csrfToken?.() ?? readCookie("csrf_token");
        if (csrf) request.headers.set("X-CSRF-Token", csrf);
      }
      return request;
    },
    async onResponse({ response }) {
      if (!response.ok) throw await toApiError(response);
      return response;
    },
  };
  client.use(auth);
  return client;
}

export type Api = ReturnType<typeof createApi>;

/**
 * Unwraps an openapi-fetch result. Network failures (fetch rejects) become ApiError(0).
 * Usage: `const me = await call(api.GET("/api/v1/miniapp/me"))`.
 */
export async function call<T>(promise: Promise<{ data?: T; error?: unknown }>): Promise<T> {
  let result: { data?: T; error?: unknown };
  try {
    result = await promise;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    throw new ApiError(0, { code: NETWORK_ERROR, message: String(error) });
  }
  if (result.error !== undefined) {
    throw result.error instanceof ApiError
      ? result.error
      : new ApiError(500, { code: "unknown", message: "Unexpected response" });
  }
  return result.data as T;
}

export function newIdempotencyKey(): string {
  return crypto.randomUUID().replaceAll("-", "");
}
