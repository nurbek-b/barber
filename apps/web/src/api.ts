import { ApiError, call, createApi, newIdempotencyKey } from "@barber/api-client";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";

export { ApiError, newIdempotencyKey };

export const api = createApi({ baseUrl: import.meta.env.VITE_API_BASE ?? "" });
const P = "/api/v1/public";

export function useSalon() {
  return useQuery({ queryKey: ["salon"], queryFn: () => call(api.GET(`${P}/salon`)) });
}

export function useBarbers() {
  return useQuery({ queryKey: ["barbers"], queryFn: () => call(api.GET(`${P}/barbers`)) });
}

export function useProfile(id: string | null) {
  return useQuery({
    queryKey: ["barber", id],
    enabled: Boolean(id),
    queryFn: () =>
      call(api.GET(`${P}/barbers/{barber_id}`, { params: { path: { barber_id: id ?? "" } } })),
  });
}

export function useReviews(id: string | null) {
  return useInfiniteQuery({
    queryKey: ["reviews", id],
    enabled: Boolean(id),
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) =>
      call(
        api.GET(`${P}/barbers/{barber_id}/reviews`, {
          params: { path: { barber_id: id ?? "" }, query: { cursor: pageParam ?? undefined } },
        }),
      ),
    getNextPageParam: (last) => last.next_cursor ?? null,
  });
}

export function useServices(barberId: string | null) {
  return useQuery({
    queryKey: ["services", barberId],
    queryFn: () =>
      call(api.GET(`${P}/services`, { params: { query: { barber_id: barberId ?? undefined } } })),
  });
}

export function useDays(barberId: string | null, serviceIds: string[]) {
  return useQuery({
    queryKey: ["days", barberId, serviceIds],
    enabled: serviceIds.length > 0,
    queryFn: () =>
      call(
        api.GET(`${P}/availability/days`, {
          params: { query: { service_ids: serviceIds, barber_id: barberId ?? undefined } },
        }),
      ),
  });
}

export function useSlots(barberId: string | null, serviceIds: string[], day: string | null) {
  return useQuery({
    queryKey: ["slots", barberId, serviceIds, day],
    enabled: Boolean(day) && serviceIds.length > 0,
    queryFn: () =>
      call(
        api.GET(`${P}/availability/slots`, {
          params: {
            query: { service_ids: serviceIds, date: day ?? "", barber_id: barberId ?? undefined },
          },
        }),
      ),
  });
}

export interface BookInput {
  name: string;
  phone: string;
  website: string;
  barberId: string | null;
  serviceIds: string[];
  startAt: string;
  comment: string;
  promo: string;
}

/** hold (name + phone) → optional promo check → confirm; returns the pending booking. */
export async function book(input: BookInput, idempotencyKey: string) {
  const held = await call(
    api.POST(`${P}/holds`, {
      body: {
        name: input.name.trim(),
        phone: input.phone.trim(),
        website: input.website || null,
        barber_id: input.barberId,
        service_ids: input.serviceIds,
        start_at: input.startAt,
      },
    }),
  );
  const promo = input.promo.trim();
  if (promo) {
    await call(api.POST(`${P}/holds/promo`, { body: { token: held.token, code: promo } }));
  }
  return call(
    api.POST(`${P}/bookings`, {
      params: { header: { "Idempotency-Key": idempotencyKey } },
      body: { token: held.token, comment: input.comment.trim() || null, promo_code: promo || null },
    }),
  );
}
