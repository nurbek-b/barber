import { useMemo } from "react";
import { useNavigate } from "react-router-dom";

import { useServices } from "../../api";
import { Card, ErrorState, Screen, SkeletonList, useMoney } from "../../components/ui";
import { pickI18n, useLang, useT } from "../../i18n";
import { barberParam, useBooking } from "../../store/booking";
import { haptic } from "../../telegram/sdk";
import { useBackButton, useMainButton } from "../../telegram/hooks";

export default function ServicesStep() {
  const t = useT();
  const lang = useLang();
  const navigate = useNavigate();
  const { money, range } = useMoney();
  const barber = useBooking((state) => state.barber);
  const selected = useBooking((state) => state.serviceIds);
  const toggle = useBooking((state) => state.toggleService);
  const catalog = useServices(barberParam(barber));

  useBackButton();
  useMainButton({
    text: t("button.next"),
    enabled: selected.length > 0,
    onClick: () => navigate("/book/time"),
  });

  const summary = useMemo(() => {
    const chosen = catalog.data?.services.filter((s) => selected.includes(s.id)) ?? [];
    return {
      count: chosen.length,
      minPrice: chosen.reduce((sum, s) => sum + s.price_min, 0),
      maxPrice: chosen.reduce((sum, s) => sum + s.price_max, 0),
      minDuration: chosen.reduce((sum, s) => sum + s.duration_min, 0),
    };
  }, [catalog.data, selected]);

  const groups = useMemo(() => {
    const data = catalog.data;
    if (!data) return [];
    const byCategory = new Map<string | null, typeof data.services>();
    for (const service of data.services) {
      const list = byCategory.get(service.category_id ?? null) ?? [];
      list.push(service);
      byCategory.set(service.category_id ?? null, list);
    }
    const named = data.categories
      .filter((c) => byCategory.has(c.id))
      .map((c) => ({
        id: c.id,
        name: pickI18n(c.name_i18n, lang),
        services: byCategory.get(c.id) ?? [],
      }));
    const loose = byCategory.get(null);
    return loose ? [...named, { id: "other", name: "", services: loose }] : named;
  }, [catalog.data, lang]);

  return (
    <Screen title={t("step.services")} step={2} totalSteps={4} withMainButton back>
      {catalog.isPending && <SkeletonList rows={5} />}
      {catalog.isError && (
        <ErrorState error={catalog.error} onRetry={() => void catalog.refetch()} />
      )}
      <div className="space-y-5">
        {groups.map((group) => (
          <section key={group.id}>
            {group.name && (
              <h2 className="mb-2 px-1 text-sm font-medium uppercase text-hint">{group.name}</h2>
            )}
            <Card className="divide-y divide-separator p-0">
              {group.services.map((service) => {
                const checked = selected.includes(service.id);
                return (
                  <label key={service.id} className="flex cursor-pointer items-center gap-3 p-4">
                    <input
                      type="checkbox"
                      className="h-5 w-5 accent-[var(--tg-theme-button-color,#2481cc)]"
                      checked={checked}
                      onChange={() => {
                        haptic.select();
                        toggle(service.id);
                      }}
                    />
                    <span className="min-w-0 flex-1">
                      <span className="block font-medium">{pickI18n(service.name_i18n, lang)}</span>
                      <span className="block text-sm text-hint">
                        {t("services.min", {
                          n:
                            service.duration_min === service.duration_max_min
                              ? service.duration_min
                              : `${service.duration_min}–${service.duration_max_min}`,
                        })}
                      </span>
                    </span>
                    <span className="text-right text-sm font-medium tabular-nums">
                      {range(service.price_min, service.price_max)}
                    </span>
                  </label>
                );
              })}
            </Card>
          </section>
        ))}
      </div>
      {summary.count > 0 && (
        <p className="mt-4 text-center text-sm text-hint" data-testid="services-summary">
          {summary.count} · {t("services.min", { n: summary.minDuration })} ·{" "}
          {summary.minPrice === summary.maxPrice
            ? money(summary.minPrice)
            : t("services.from", { price: money(summary.minPrice) })}
        </p>
      )}
    </Screen>
  );
}
