import { useQuery } from "@tanstack/react-query";

import { ADMIN, api, call } from "@/lib/api";

export const keys = {
  barbers: ["barbers"] as const,
  barber: (id: string) => ["barbers", id] as const,
  services: ["services"] as const,
  categories: ["service-categories"] as const,
  levels: ["loyalty-levels"] as const,
};

export function useBarbersList(onlyActive = false) {
  return useQuery({
    queryKey: [...keys.barbers, { onlyActive }],
    queryFn: () =>
      call(
        api.GET(`${ADMIN}/barbers`, { params: { query: { only_active: onlyActive, limit: 200 } } }),
      ),
    select: (page) => page.items,
  });
}

export function useServicesList(onlyActive = false) {
  return useQuery({
    queryKey: [...keys.services, { onlyActive }],
    queryFn: () =>
      call(
        api.GET(`${ADMIN}/services`, {
          params: { query: { only_active: onlyActive, limit: 500 } },
        }),
      ),
    select: (page) => page.items,
  });
}

export function useCategories() {
  return useQuery({
    queryKey: keys.categories,
    queryFn: () => call(api.GET(`${ADMIN}/service-categories`)),
  });
}

export function useLevels() {
  return useQuery({
    queryKey: keys.levels,
    queryFn: () => call(api.GET(`${ADMIN}/loyalty-levels`)),
  });
}

export function pickName(value: Record<string, string> | undefined, lang: string): string {
  if (!value) return "";
  return value[lang] || value.ru || Object.values(value)[0] || "";
}

export const STATUS_VARIANT = {
  pending: "warning",
  confirmed: "default",
  completed: "success",
  cancelled: "destructive",
  no_show: "destructive",
} as const;
