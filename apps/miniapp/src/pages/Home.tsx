import { useNavigate } from "react-router-dom";

import { useBarbers, useBookings, useBonus, useMe, useRepeat, useServices } from "../api";
import { BookingCard } from "../components/BookingCard";
import { Card, ErrorState, Screen, Skeleton, useMoney } from "../components/ui";
import { pickI18n, useLang, useT } from "../i18n";
import { useBooking } from "../store/booking";
import { useBackButton, useMainButton } from "../telegram/hooks";

export default function Home() {
  const t = useT();
  const lang = useLang();
  const navigate = useNavigate();
  const { money } = useMoney();
  const me = useMe();
  const upcoming = useBookings("upcoming");
  const repeat = useRepeat();
  const bonus = useBonus();
  const barbers = useBarbers();
  const repeatServices = useServices(repeat.data?.barber?.id ?? null);
  const startRepeat = useBooking((state) => state.startRepeat);
  const reset = useBooking((state) => state.reset);

  useBackButton(false);
  useMainButton({
    text: t("home.book"),
    onClick: () => {
      reset();
      navigate("/book/barber");
    },
  });

  if (me.isError) {
    return (
      <Screen title={t("app.title")}>
        <ErrorState error={me.error} onRetry={() => void me.refetch()} />
      </Screen>
    );
  }

  const next = upcoming.data?.pages[0]?.items[0];
  const draft = repeat.data;
  const repeatNames = draft
    ? draft.service_ids
        .map((id) => repeatServices.data?.services.find((s) => s.id === id))
        .filter(Boolean)
        .map((service) => pickI18n(service?.name_i18n, lang))
        .join(", ")
    : "";

  return (
    <Screen
      title={me.data ? t("home.hello", { name: me.data.name.split(" ")[0] ?? "" }) : t("app.title")}
      withMainButton
    >
      <div className="space-y-4">
        {me.isPending && <Skeleton className="h-24" />}

        {draft && draft.service_ids.length > 0 && (
          <button
            type="button"
            data-testid="repeat"
            onClick={() => {
              startRepeat(draft.barber?.id ?? null, draft.service_ids);
              navigate("/book/time");
            }}
            className="w-full rounded-2xl bg-button/10 p-4 text-left"
          >
            <div className="font-semibold text-button">↻ {t("home.repeat")}</div>
            <div className="mt-1 text-sm text-hint">
              {[draft.barber?.name ?? t("barber.any"), repeatNames].filter(Boolean).join(" · ")}
            </div>
          </button>
        )}

        {next && (
          <section>
            <h2 className="mb-2 px-1 text-sm font-medium uppercase text-hint">{t("home.next")}</h2>
            <BookingCard booking={next} />
          </section>
        )}

        <button type="button" onClick={() => navigate("/bonus")} className="block w-full text-left">
          <Card className="flex items-center justify-between">
            <span>{t("home.bonus")}</span>
            <span className="text-lg font-semibold tabular-nums">
              {bonus.data ? money(bonus.data.balance) : "…"}
            </span>
          </Card>
        </button>

        {barbers.data && barbers.data.length > 0 && (
          <div className="-mx-4 flex gap-3 overflow-x-auto px-4">
            {barbers.data.map((barber) => (
              <div key={barber.id} className="w-20 shrink-0 text-center text-xs">
                {barber.photo_url ? (
                  <img
                    src={barber.photo_url}
                    alt=""
                    loading="lazy"
                    className="mx-auto mb-1 h-16 w-16 rounded-full object-cover"
                  />
                ) : (
                  <div className="mx-auto mb-1 flex h-16 w-16 items-center justify-center rounded-full bg-bg-secondary">
                    ✂
                  </div>
                )}
                <div className="truncate">{barber.name}</div>
              </div>
            ))}
          </div>
        )}
      </div>
    </Screen>
  );
}
