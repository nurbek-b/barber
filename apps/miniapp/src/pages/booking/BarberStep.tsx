import { useNavigate } from "react-router-dom";

import { useBarbers } from "../../api";
import { Avatar, Card, ErrorState, Screen, SkeletonList } from "../../components/ui";
import { pickI18n, useLang, useT } from "../../i18n";
import { ANY_BARBER, useBooking } from "../../store/booking";
import { haptic } from "../../telegram/sdk";
import { useBackButton, useMainButton } from "../../telegram/hooks";

export default function BarberStep() {
  const t = useT();
  const lang = useLang();
  const navigate = useNavigate();
  const barbers = useBarbers();
  const selected = useBooking((state) => state.barber);
  const setBarber = useBooking((state) => state.setBarber);

  useBackButton(() => navigate("/"));
  useMainButton({
    text: t("button.next"),
    visible: true,
    enabled: selected !== null,
    onClick: () => navigate("/book/services"),
  });

  const choose = (id: string) => {
    haptic.select();
    setBarber(id);
  };

  const option = (id: string, active: boolean) =>
    `flex w-full items-center gap-3 rounded-2xl p-3 text-left transition ${
      active ? "bg-button/10 ring-2 ring-button" : "bg-section"
    }`;

  return (
    <Screen title={t("step.barber")} step={1} totalSteps={4} withMainButton back>
      <div className="space-y-2">
        <button
          type="button"
          className={option(ANY_BARBER, selected === ANY_BARBER)}
          aria-pressed={selected === ANY_BARBER}
          onClick={() => choose(ANY_BARBER)}
        >
          <div className="flex h-12 w-12 items-center justify-center rounded-full bg-bg-secondary text-xl">
            ✂️
          </div>
          <div>
            <div className="font-medium">{t("barber.any")}</div>
            <div className="text-sm text-hint">{t("barber.anyHint")}</div>
          </div>
        </button>

        {barbers.isPending && <SkeletonList rows={3} />}
        {barbers.isError && (
          <ErrorState error={barbers.error} onRetry={() => void barbers.refetch()} />
        )}
        {barbers.data?.map((barber) => (
          <div key={barber.id} className="relative">
            <button
              type="button"
              className={`${option(barber.id, selected === barber.id)} pr-24`}
              aria-pressed={selected === barber.id}
              onClick={() => choose(barber.id)}
            >
              <Avatar name={barber.name} url={barber.photo_url} />
              <div className="min-w-0 flex-1">
                <div className="font-medium">{barber.name}</div>
                <div className="truncate text-sm text-hint">
                  {pickI18n(barber.specialization_i18n, lang)}
                </div>
              </div>
              <div className="text-sm text-hint">
                {barber.rating !== null && barber.rating !== undefined
                  ? `★ ${barber.rating.toFixed(1)}`
                  : t("barber.noRating")}
              </div>
            </button>
            <button
              type="button"
              onClick={() => navigate(`/barber/${barber.id}`)}
              className="absolute bottom-2 right-3 rounded-full px-2 py-1 text-xs text-link"
            >
              {t("profile.more")} ›
            </button>
          </div>
        ))}
        {barbers.data?.length === 0 && (
          <Card>
            <p className="text-hint">{t("bookings.empty")}</p>
          </Card>
        )}
      </div>
    </Screen>
  );
}
