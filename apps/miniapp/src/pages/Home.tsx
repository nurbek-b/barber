import { useNavigate } from "react-router-dom";

import {
  useBarbers,
  useBookings,
  useBonus,
  useMe,
  useRepeat,
  useSalon,
  useServices,
  useSetLanguage,
} from "../api";
import { BookingCard } from "../components/BookingCard";
import { ErrorState, Screen, Skeleton, useMoney } from "../components/ui";
import { type Lang, pickI18n, useLang, useT } from "../i18n";
import { useBooking } from "../store/booking";
import { useBackButton, useMainButton } from "../telegram/hooks";

export default function Home() {
  const t = useT();
  const lang = useLang();
  const navigate = useNavigate();
  const { money } = useMoney();
  const me = useMe();
  const salon = useSalon();
  const setLanguage = useSetLanguage();
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
      hideTitle
    >
      <div className="space-y-4">
        {salon.data && (
          <div className="flex items-center gap-3">
            {salon.data.logo_url && (
              <img
                src={salon.data.logo_url}
                alt=""
                className="h-14 w-14 shrink-0 rounded-2xl bg-section object-contain p-1"
              />
            )}
            <div className="min-w-0 flex-1">
              <div className="truncate text-lg font-semibold leading-tight">{salon.data.name}</div>
              <button
                type="button"
                data-testid="bonus-chip"
                onClick={() => navigate("/bonus")}
                aria-label={`${t("home.bonus")}: ${bonus.data ? money(bonus.data.balance) : ""}`}
                className="mt-1 inline-flex min-h-8 items-center gap-1.5 rounded-full bg-button/10 px-2.5 text-sm font-medium tabular-nums text-button transition active:opacity-60"
              >
                <GiftIcon />
                {bonus.data ? money(bonus.data.balance) : "…"}
              </button>
            </div>
            {draft && draft.service_ids.length > 0 && (
              <button
                type="button"
                data-testid="repeat"
                title={`${t("home.repeat")}: ${[draft.barber?.name ?? t("barber.any"), repeatNames].filter(Boolean).join(" · ")}`}
                onClick={() => {
                  startRepeat(draft.barber?.id ?? null, draft.service_ids);
                  navigate("/book/time");
                }}
                className="flex min-h-11 shrink-0 items-center gap-1 rounded-full bg-button/10 px-3 text-sm font-semibold text-button transition active:opacity-60"
              >
                ↻ {t("home.repeatShort")}
              </button>
            )}
          </div>
        )}
        {salon.data?.gallery?.length ? (
          <Gallery photos={salon.data.gallery} label={t("home.photos")} />
        ) : null}
        {me.isPending && <Skeleton className="h-24" />}

        {next && (
          <section>
            <h2 className="mb-2 px-1 text-sm font-medium uppercase text-hint">{t("home.next")}</h2>
            <BookingCard
              booking={next}
              actions={
                next.can_pay ? (
                  <button
                    type="button"
                    onClick={() => navigate(`/pay/${next.id}`)}
                    className="w-full rounded-xl bg-button py-2 text-sm font-medium text-button-text"
                  >
                    {t("pay.button")}
                  </button>
                ) : undefined
              }
            />
          </section>
        )}

        {barbers.data && barbers.data.length > 0 && (
          <section>
            <h2 className="mb-2 px-1 text-sm font-medium uppercase text-hint">
              {t("home.barbers")}
            </h2>
            <div className="-mx-4 flex gap-3 overflow-x-auto px-4">
              {barbers.data.map((barber) => (
                <button
                  key={barber.id}
                  type="button"
                  onClick={() => navigate(`/barber/${barber.id}`)}
                  className="w-20 shrink-0 text-center text-xs transition active:opacity-60"
                >
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
                  <div className="truncate text-sm">{barber.name}</div>
                  {barber.rating !== null && barber.rating !== undefined && (
                    <div className="text-hint">★ {barber.rating.toFixed(1)}</div>
                  )}
                </button>
              ))}
            </div>
          </section>
        )}

        <LanguageSwitch
          value={lang}
          label={t("home.language")}
          onChange={(next) => setLanguage.mutate(next)}
        />
      </div>
    </Screen>
  );
}

function GiftIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      className="h-4 w-4"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d="M20 12v8a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1v-8m16 0H4m16 0V8H4v4m8-4v13m0-13S10.5 3 8 3.5 7 7 8.5 8M12 8s1.5-5 4-4.5S17 7 15.5 8" />
    </svg>
  );
}

/** Swipeable salon photos; the first one is the cover. */
function Gallery({ photos, label }: { photos: string[]; label: string }) {
  return (
    <section aria-label={label}>
      <div className="-mx-4 flex snap-x snap-mandatory gap-2 overflow-x-auto px-4 pb-1">
        {photos.map((url, index) => (
          <img
            key={url}
            src={url}
            alt=""
            loading={index === 0 ? "eager" : "lazy"}
            className="aspect-[16/9] w-[80%] shrink-0 snap-center rounded-2xl bg-section object-cover"
          />
        ))}
      </div>
    </section>
  );
}

const LANGUAGES: { code: Lang; label: string }[] = [
  { code: "ru", label: "Русский" },
  { code: "ky", label: "Кыргызча" },
  { code: "en", label: "English" },
];

function LanguageSwitch({
  value,
  label,
  onChange,
}: {
  value: Lang;
  label: string;
  onChange: (lang: Lang) => void;
}) {
  return (
    <div
      className="flex items-center justify-center gap-1 pt-2 text-sm"
      role="group"
      aria-label={label}
    >
      {LANGUAGES.map((item) => (
        <button
          key={item.code}
          type="button"
          aria-pressed={item.code === value}
          onClick={() => item.code !== value && onChange(item.code)}
          className={`min-h-10 rounded-full px-4 ${
            item.code === value ? "bg-button text-button-text" : "text-hint"
          }`}
        >
          {item.label}
        </button>
      ))}
    </div>
  );
}
