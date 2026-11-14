import {
  ApiError,
  call,
  createApi,
  newIdempotencyKey,
  type Booking,
  type BookingPage,
  type ClientMe,
  type Hold,
} from "@barber/api-client";
import {
  QueryClient,
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import { telegramEnv } from "./telegram/sdk";

export const api = createApi({
  baseUrl: import.meta.env.VITE_API_BASE ?? "",
  authorization: () => {
    const raw = telegramEnv().initDataRaw;
    return raw ? `tma ${raw}` : null;
  },
});

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      gcTime: 5 * 60_000,
      refetchOnWindowFocus: false,
      // 4xx won't fix itself; retry only network/5xx
      retry: (count, error) =>
        count < 2 && (!(error instanceof ApiError) || error.isNetwork || error.status >= 500),
    },
    mutations: { retry: false },
  },
});

export const keys = {
  me: ["me"] as const,
  salon: ["salon"] as const,
  barbers: (serviceIds: string[]) => ["barbers", serviceIds] as const,
  services: (barberId: string | null) => ["services", barberId] as const,
  days: (barberId: string | null, serviceIds: string[]) => ["days", barberId, serviceIds] as const,
  slots: (barberId: string | null, serviceIds: string[], day: string) =>
    ["slots", barberId, serviceIds, day] as const,
  bookings: (scope: "upcoming" | "past") => ["bookings", scope] as const,
  repeat: ["repeat"] as const,
  bonus: ["bonus"] as const,
  bonusHistory: ["bonus", "history"] as const,
  referral: ["referral"] as const,
};

const BASE = "/api/v1/miniapp";

export function useMe() {
  return useQuery({ queryKey: keys.me, queryFn: () => call(api.GET(`${BASE}/me`)) });
}

export function useSalon() {
  return useQuery({
    queryKey: keys.salon,
    queryFn: () => call(api.GET(`${BASE}/salon`)),
    staleTime: 10 * 60_000,
  });
}

export function useBarbers() {
  return useQuery({
    queryKey: keys.barbers([]),
    queryFn: () => call(api.GET(`${BASE}/barbers`)),
  });
}

export function useServices(barberId: string | null) {
  return useQuery({
    queryKey: keys.services(barberId),
    queryFn: () =>
      call(
        api.GET(`${BASE}/services`, { params: { query: { barber_id: barberId ?? undefined } } }),
      ),
  });
}

export function useDays(barberId: string | null, serviceIds: string[], enabled = true) {
  return useQuery({
    queryKey: keys.days(barberId, serviceIds),
    enabled: enabled && serviceIds.length > 0,
    queryFn: () =>
      call(
        api.GET(`${BASE}/availability/days`, {
          params: { query: { service_ids: serviceIds, barber_id: barberId ?? undefined } },
        }),
      ),
  });
}

export function useSlots(barberId: string | null, serviceIds: string[], day: string | null) {
  return useQuery({
    queryKey: keys.slots(barberId, serviceIds, day ?? ""),
    enabled: Boolean(day) && serviceIds.length > 0,
    staleTime: 10_000,
    queryFn: () =>
      call(
        api.GET(`${BASE}/availability/slots`, {
          params: {
            query: { date: day ?? "", service_ids: serviceIds, barber_id: barberId ?? undefined },
          },
        }),
      ),
  });
}

export function useRepeat() {
  return useQuery({
    queryKey: keys.repeat,
    queryFn: () => call(api.GET(`${BASE}/bookings/repeat`)),
  });
}

export function useBookings(scope: "upcoming" | "past") {
  return useInfiniteQuery({
    queryKey: keys.bookings(scope),
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) =>
      call(
        api.GET(`${BASE}/bookings`, {
          params: { query: { scope, limit: 10, cursor: pageParam ?? undefined } },
        }),
      ),
    getNextPageParam: (last: BookingPage) => last.next_cursor ?? null,
  });
}

export function useBonus() {
  return useQuery({ queryKey: keys.bonus, queryFn: () => call(api.GET(`${BASE}/bonus`)) });
}

export function useBonusHistory() {
  return useInfiniteQuery({
    queryKey: keys.bonusHistory,
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) =>
      call(
        api.GET(`${BASE}/bonus/transactions`, {
          params: { query: { limit: 20, cursor: pageParam ?? undefined } },
        }),
      ),
    getNextPageParam: (last) => last.next_cursor ?? null,
  });
}

export function useReferral() {
  return useQuery({ queryKey: keys.referral, queryFn: () => call(api.GET(`${BASE}/referral`)) });
}

// ------------------------------------------------------------------ mutations

export interface HoldRequest {
  barberId: string | null;
  serviceIds: string[];
  startAt: string;
  rescheduleBookingId?: string | null;
}

export function placeHold(request: HoldRequest): Promise<Hold> {
  return call(
    api.POST(`${BASE}/holds`, {
      body: {
        barber_id: request.barberId,
        service_ids: request.serviceIds,
        start_at: request.startAt,
        reschedule_booking_id: request.rescheduleBookingId ?? null,
      },
    }),
  );
}

export function releaseHold(holdId: string): Promise<unknown> {
  return call(api.DELETE(`${BASE}/holds/{hold_id}`, { params: { path: { hold_id: holdId } } }));
}

export function useCreateBooking() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: {
      holdId: string;
      comment: string | null;
      bonusToSpend: number;
      idempotencyKey: string;
    }) =>
      call(
        api.POST(`${BASE}/bookings`, {
          params: { header: { "Idempotency-Key": input.idempotencyKey } },
          body: {
            hold_id: input.holdId,
            comment: input.comment,
            bonus_to_spend: input.bonusToSpend,
          },
        }),
      ),
    onSuccess: () => invalidateAfterBooking(client),
  });
}

export function useReschedule() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: { bookingId: string; holdId: string }) =>
      call(
        api.POST(`${BASE}/bookings/{booking_id}/reschedule`, {
          params: { path: { booking_id: input.bookingId } },
          body: { hold_id: input.holdId },
        }),
      ),
    onSuccess: () => invalidateAfterBooking(client),
  });
}

type BookingsData = { pages: BookingPage[]; pageParams: (string | null)[] };

/** Optimistic: the booking is shown as cancelled at once and rolled back on error. */
export function useCancelBooking() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (bookingId: string) =>
      call(
        api.POST(`${BASE}/bookings/{booking_id}/cancel`, {
          params: { path: { booking_id: bookingId } },
          body: {},
        }),
      ),
    onMutate: async (bookingId) => {
      await client.cancelQueries({ queryKey: keys.bookings("upcoming") });
      const previous = client.getQueryData<BookingsData>(keys.bookings("upcoming"));
      client.setQueryData<BookingsData>(keys.bookings("upcoming"), (data) =>
        data
          ? {
              ...data,
              pages: data.pages.map((page) => ({
                ...page,
                items: page.items.map((item: Booking) =>
                  item.id === bookingId
                    ? { ...item, status: "cancelled", can_cancel: false, can_reschedule: false }
                    : item,
                ),
              })),
            }
          : data,
      );
      return { previous };
    },
    onError: (_error, _id, context) => {
      if (context?.previous) client.setQueryData(keys.bookings("upcoming"), context.previous);
    },
    onSettled: () => invalidateAfterBooking(client),
  });
}

export function useSavePhone() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (contact: string) => call(api.POST(`${BASE}/me/phone`, { body: { contact } })),
    onSuccess: (me: ClientMe) => client.setQueryData(keys.me, me),
  });
}

function invalidateAfterBooking(client: QueryClient): void {
  void client.invalidateQueries({ queryKey: ["bookings"] });
  void client.invalidateQueries({ queryKey: ["slots"] });
  void client.invalidateQueries({ queryKey: ["days"] });
  void client.invalidateQueries({ queryKey: keys.me });
  void client.invalidateQueries({ queryKey: keys.bonus });
  void client.invalidateQueries({ queryKey: keys.repeat });
}

export { ApiError, newIdempotencyKey };
