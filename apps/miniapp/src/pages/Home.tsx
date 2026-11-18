import { useEffect, useRef, useState, type ReactNode } from "react";
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
import { Avatar, ErrorState, Screen, Skeleton, useMoney } from "../components/ui";
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
                className="h-12 w-12 shrink-0 rounded-2xl bg-section object-contain p-1"
              />
            )}
            <div className="min-w-0 flex-1">
              <div className="truncate text-lg font-semibold leading-tight">{salon.data.name}</div>
              <button
                type="button"
                data-testid="bonus-chip"
                onClick={() => navigate("/bonus")}
                aria-label={`${t("home.bonus")}: ${bonus.data ? money(bonus.data.balance) : ""}`}
                className="mt-1 inline-flex min-h-8 max-w-full items-center gap-1.5 rounded-full bg-brand2/15 px-2.5 text-sm font-medium tabular-nums text-brand2-ink transition active:opacity-60"
              >
                <GiftIcon />
                {bonus.data ? money(bonus.data.balance) : "…"}
              </button>
            </div>
            {draft && draft.service_ids.length > 0 && (
              <button
                type="button"
                data-testid="repeat"
                aria-label={`${t("home.repeatShort")}: ${[draft.barber?.name ?? t("barber.any"), repeatNames].filter(Boolean).join(" · ")}`}
                title={t("home.repeatShort")}
                onClick={() => {
                  startRepeat(draft.barber?.id ?? null, draft.service_ids);
                  navigate("/book/time");
                }}
                className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-button/10 text-link transition active:opacity-60"
              >
                <svg
                  viewBox="0 0 24 24"
                  className="h-5 w-5"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth={2}
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  aria-hidden
                >
                  <path d="M21 12a9 9 0 1 1-2.64-6.36M21 3v6h-6" />
                </svg>
              </button>
            )}
            <LanguageMenu
              value={lang}
              label={t("home.language")}
              onChange={(next) => setLanguage.mutate(next)}
            />
          </div>
        )}
        {salon.data?.gallery?.length ? (
          <Gallery photos={salon.data.gallery} label={t("home.photos")} />
        ) : null}
        {me.isPending && <Skeleton className="h-24" />}

        {next && (
          <section>
            <SectionTitle icon="calendar" tone="brand">
              {t("home.next")}
            </SectionTitle>
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
            <SectionTitle icon="scissors" tone="brand2">
              {t("home.barbers")}
            </SectionTitle>
            <div className="space-y-2">
              {barbers.data.map((barber) => {
                const specialization = pickI18n(barber.specialization_i18n, lang);
                const bio = pickI18n(barber.bio_i18n, lang);
                return (
                  <button
                    key={barber.id}
                    type="button"
                    onClick={() => navigate(`/barber/${barber.id}`)}
                    className="flex w-full items-start gap-3 rounded-2xl bg-section p-3 text-left shadow-sm transition active:scale-[0.99]"
                  >
                    <Avatar name={barber.name} url={barber.photo_url} size={56} />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-baseline justify-between gap-2">
                        <span className="truncate font-semibold">{barber.name}</span>
                        {barber.rating !== null && barber.rating !== undefined && (
                          <span className="shrink-0 text-sm text-hint">
                            <span className="text-gold">★</span> {barber.rating.toFixed(1)}
                            {barber.rating_count > 0 && ` (${barber.rating_count})`}
                          </span>
                        )}
                      </div>
                      {specialization && (
                        <div className="text-sm text-brand2-ink">{specialization}</div>
                      )}
                      {bio && <p className="mt-1 line-clamp-2 text-sm text-hint">{bio}</p>}
                    </div>
                    <span aria-hidden className="self-center text-xl text-hint">
                      ›
                    </span>
                  </button>
                );
              })}
            </div>
          </section>
        )}
      </div>
    </Screen>
  );
}

const SECTION_ICONS = {
  calendar:
    "M7 3v3m10-3v3M4 9h16M5 5h14a1 1 0 0 1 1 1v13a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1z",
  scissors:
    "M6 9a3 3 0 1 0 0-6 3 3 0 0 0 0 6zm0 12a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM20 4 8.1 15.9M14.5 14.5 20 20M8.1 8.1 12 12",
} as const;

/** Section heading with a small icon in a tinted circle (main or second brand color). */
function SectionTitle({
  icon,
  tone,
  children,
}: {
  icon: keyof typeof SECTION_ICONS;
  tone: "brand" | "brand2";
  children: ReactNode;
}) {
  return (
    <h2 className="mb-2 flex items-center gap-2 px-1 text-sm font-medium uppercase text-hint">
      <span
        aria-hidden
        className={`flex h-7 w-7 items-center justify-center rounded-full ${
          tone === "brand" ? "bg-button/15 text-link" : "bg-brand2/15 text-brand2-ink"
        }`}
      >
        <svg
          viewBox="0 0 24 24"
          className="h-4 w-4"
          fill="none"
          stroke="currentColor"
          strokeWidth={2}
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d={SECTION_ICONS[icon]} />
        </svg>
      </span>
      {children}
    </h2>
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

const LANGUAGE_SHORT: Record<Lang, string> = { ru: "RU", ky: "KG", en: "EN" };

/** Globe button with a small dropdown; closes on outside tap or Escape. */
function LanguageMenu({
  value,
  label,
  onChange,
}: {
  value: Lang;
  label: string;
  onChange: (lang: Lang) => void;
}) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (event: Event) => {
      if (
        event instanceof KeyboardEvent
          ? event.key === "Escape"
          : !root.current?.contains(event.target as Node)
      )
        setOpen(false);
    };
    document.addEventListener("pointerdown", close);
    document.addEventListener("keydown", close);
    return () => {
      document.removeEventListener("pointerdown", close);
      document.removeEventListener("keydown", close);
    };
  }, [open]);

  return (
    <div ref={root} className="relative shrink-0">
      <button
        type="button"
        aria-label={label}
        aria-haspopup="menu"
        aria-expanded={open}
        data-testid="language-button"
        onClick={() => setOpen((v) => !v)}
        className="flex h-11 w-11 flex-col items-center justify-center rounded-full bg-section text-hint shadow-sm transition active:opacity-60"
      >
        <svg
          viewBox="0 0 24 24"
          className="h-5 w-5"
          fill="none"
          stroke="currentColor"
          strokeWidth={1.8}
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden
        >
          <circle cx="12" cy="12" r="9" />
          <path d="M3 12h18M12 3c2.5 2.5 3.8 5.5 3.8 9s-1.3 6.5-3.8 9c-2.5-2.5-3.8-5.5-3.8-9S9.5 5.5 12 3z" />
        </svg>
        <span className="text-[9px] font-semibold leading-none">{LANGUAGE_SHORT[value]}</span>
      </button>
      {open && (
        <div
          role="menu"
          aria-label={label}
          className="absolute right-0 top-full z-30 mt-2 w-44 overflow-hidden rounded-2xl bg-section py-1 shadow-lg ring-1 ring-separator"
        >
          {LANGUAGES.map((item) => (
            <button
              key={item.code}
              type="button"
              role="menuitemradio"
              aria-checked={item.code === value}
              onClick={() => {
                setOpen(false);
                if (item.code !== value) onChange(item.code);
              }}
              className="flex min-h-11 w-full items-center justify-between px-4 text-left transition active:bg-bg-secondary"
            >
              {item.label}
              {item.code === value && <span className="text-link">✓</span>}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
