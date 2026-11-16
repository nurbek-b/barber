import type { components } from "@barber/api-client";
import {
  dayOfMonth,
  formatDate,
  formatDateTime,
  formatDayLong,
  formatMoney,
  formatMoneyRange,
  formatTime,
  formatWeekdayNarrow,
} from "@barber/ui";
import { useEffect, useMemo, useState, type ReactNode } from "react";

import {
  ApiError,
  book,
  checkCertificate,
  newIdempotencyKey,
  useBarbers,
  useDays,
  useProfile,
  useReviews,
  useSalon,
  useServices,
  useSlots,
} from "./api";
import { LangContext, detectLang, isKey, pick, translate, useLang, useT, type Lang } from "./i18n";

type Slot = components["schemas"]["Slot"];
type Booked = components["schemas"]["WebBookingOut"];
type Step = "barber" | "services" | "time" | "contacts" | "done";
const ANY = "any";

export default function App() {
  const [lang, setLang] = useState<Lang>(detectLang);
  useEffect(() => {
    document.documentElement.lang = lang;
    document.title = translate(lang, "title");
    try {
      localStorage.setItem("lang", lang);
    } catch {
      // ignore
    }
  }, [lang]);
  return (
    <LangContext.Provider value={lang}>
      <Booking lang={lang} onLang={setLang} />
    </LangContext.Provider>
  );
}

function Booking({ lang, onLang }: { lang: Lang; onLang: (lang: Lang) => void }) {
  const t = useT();
  const salon = useSalon();
  const [step, setStep] = useState<Step>("barber");
  const [barber, setBarber] = useState<string | null>(null);
  const [serviceIds, setServiceIds] = useState<string[]>([]);
  const [slot, setSlot] = useState<Slot | null>(null);
  const [profile, setProfile] = useState<string | null>(null);
  const [booked, setBooked] = useState<Booked | null>(null);
  const barberId = barber === ANY ? null : barber;
  const tz = salon.data?.timezone ?? "Asia/Bishkek";
  const currency = salon.data?.currency ?? "KGS";
  const money = (n: number) => formatMoney(n, currency, lang);

  const go = (next: Step) => {
    setStep(next);
    window.scrollTo({ top: 0, behavior: "smooth" });
  };
  const restart = () => {
    setBarber(null);
    setServiceIds([]);
    setSlot(null);
    setBooked(null);
    go("barber");
  };

  return (
    <div className="mx-auto min-h-screen max-w-xl px-4 pb-16 pt-6">
      <header className="mb-6 flex items-center gap-3">
        {salon.data?.logo_url && (
          <img
            src={salon.data.logo_url}
            alt=""
            className="h-12 w-12 rounded-xl bg-card object-contain p-1"
          />
        )}
        <div className="min-w-0 flex-1">
          <div className="truncate text-lg font-semibold">{salon.data?.name ?? "…"}</div>
          <div className="text-sm text-hint">{t("title")}</div>
        </div>
        <LangSwitch value={lang} onChange={onLang} />
      </header>

      {step === "barber" && salon.data?.gallery?.length ? (
        <div className="-mx-4 mb-6 flex snap-x gap-2 overflow-x-auto px-4">
          {salon.data.gallery.map((url) => (
            <img
              key={url}
              src={url}
              alt=""
              loading="lazy"
              className="aspect-[4/3] w-[80%] shrink-0 snap-center rounded-2xl bg-card object-cover sm:w-[60%]"
            />
          ))}
        </div>
      ) : null}

      {step === "barber" && <CertificateCheck money={money} />}
      {step === "barber" && (
        <BarberStep
          selected={barber}
          onPick={(id) => {
            setBarber(id);
            setServiceIds([]);
            go("services");
          }}
          onDetails={setProfile}
        />
      )}
      {step === "services" && (
        <ServicesStep
          barberId={barberId}
          selected={serviceIds}
          onChange={setServiceIds}
          money={money}
          onBack={() => go("barber")}
          onNext={() => go("time")}
        />
      )}
      {step === "time" && (
        <TimeStep
          barberId={barberId}
          serviceIds={serviceIds}
          tz={tz}
          onBack={() => go("services")}
          onPick={(picked) => {
            setSlot(picked);
            go("contacts");
          }}
        />
      )}
      {step === "contacts" && slot && (
        <ContactsStep
          barberId={barberId}
          serviceIds={serviceIds}
          slot={slot}
          tz={tz}
          money={money}
          onBack={() => go("time")}
          onRepick={(picked) => setSlot(picked)}
          onDone={(result) => {
            setBooked(result);
            go("done");
          }}
        />
      )}
      {step === "done" && booked && (
        <Done
          booked={booked}
          tz={tz}
          money={money}
          onAgain={restart}
          phone={salon.data?.contacts?.phone}
        />
      )}

      {profile && (
        <ProfileSheet
          barberId={profile}
          tz={tz}
          onClose={() => setProfile(null)}
          onBook={() => {
            setBarber(profile);
            setProfile(null);
            setServiceIds([]);
            go("services");
          }}
        />
      )}

      <footer className="mt-10 space-y-1 text-center text-sm text-hint">
        {salon.data?.contacts?.address && <div>{salon.data.contacts.address}</div>}
        {salon.data?.contacts?.phone && (
          <a className="underline" href={`tel:${salon.data.contacts.phone}`}>
            {salon.data.contacts.phone}
          </a>
        )}
      </footer>
    </div>
  );
}

function LangSwitch({ value, onChange }: { value: Lang; onChange: (lang: Lang) => void }) {
  return (
    <div className="flex rounded-full bg-card p-0.5 text-xs" role="group" aria-label="language">
      {(["ru", "ky", "en"] as const).map((code) => (
        <button
          key={code}
          type="button"
          aria-pressed={code === value}
          onClick={() => onChange(code)}
          className={`rounded-full px-2.5 py-1 uppercase ${code === value ? "bg-brand text-brand-text" : "text-hint"}`}
        >
          {code}
        </button>
      ))}
    </div>
  );
}

function Title({ children }: { children: ReactNode }) {
  return <h1 className="mb-4 text-xl font-semibold">{children}</h1>;
}

function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`rounded-2xl bg-card p-4 ${className}`}>{children}</div>;
}

function Avatar({ url, name, size = 56 }: { url?: string | null; name: string; size?: number }) {
  return url ? (
    <img
      src={url}
      alt=""
      className="shrink-0 rounded-full object-cover"
      style={{ width: size, height: size }}
    />
  ) : (
    <div
      className="flex shrink-0 items-center justify-center rounded-full bg-bg font-semibold text-hint"
      style={{ width: size, height: size }}
    >
      {name.slice(0, 1)}
    </div>
  );
}

function Stars({ value }: { value: number }) {
  const full = Math.round(value);
  return (
    <span className="text-amber-500" aria-label={`${value} / 5`}>
      {"★".repeat(full)}
      <span className="text-hint opacity-40">{"★".repeat(5 - full)}</span>
    </span>
  );
}

function Primary(props: { onClick: () => void; disabled?: boolean; children: ReactNode }) {
  return (
    <button
      type="button"
      onClick={props.onClick}
      disabled={props.disabled}
      className="w-full rounded-2xl bg-brand py-3.5 font-semibold text-brand-text transition disabled:opacity-40"
    >
      {props.children}
    </button>
  );
}

function BackLink({ onClick }: { onClick: () => void }) {
  const t = useT();
  return (
    <button type="button" onClick={onClick} className="mb-3 text-sm text-hint">
      ← {t("back")}
    </button>
  );
}

function BarberStep(props: {
  selected: string | null;
  onPick: (id: string) => void;
  onDetails: (id: string) => void;
}) {
  const t = useT();
  const lang = useLang();
  const barbers = useBarbers();
  return (
    <section>
      <Title>{t("step_barber")}</Title>
      <div className="space-y-2">
        <button type="button" onClick={() => props.onPick(ANY)} className="w-full text-left">
          <Card className="flex items-center gap-3">
            <div className="flex h-14 w-14 items-center justify-center rounded-full bg-bg text-2xl">
              ✂️
            </div>
            <div>
              <div className="font-medium">{t("any_barber")}</div>
              <div className="text-sm text-hint">{t("any_hint")}</div>
            </div>
          </Card>
        </button>
        {barbers.data?.map((barber) => (
          <Card key={barber.id} className="flex items-center gap-3">
            <button
              type="button"
              className="flex min-w-0 flex-1 items-center gap-3 text-left"
              onClick={() => props.onPick(barber.id)}
            >
              <Avatar url={barber.photo_url} name={barber.name} />
              <div className="min-w-0">
                <div className="font-medium">{barber.name}</div>
                <div className="truncate text-sm text-hint">
                  {pick(barber.specialization_i18n, lang)}
                </div>
                <div className="text-sm">
                  {barber.rating ? (
                    <>
                      <Stars value={barber.rating} /> {barber.rating.toFixed(1)}
                    </>
                  ) : (
                    <span className="text-hint">{t("new_barber")}</span>
                  )}
                </div>
              </div>
            </button>
            <button
              type="button"
              className="shrink-0 text-sm text-hint underline"
              onClick={() => props.onDetails(barber.id)}
            >
              {t("details")}
            </button>
          </Card>
        ))}
      </div>
    </section>
  );
}

function ServicesStep(props: {
  barberId: string | null;
  selected: string[];
  onChange: (ids: string[]) => void;
  money: (n: number) => string;
  onBack: () => void;
  onNext: () => void;
}) {
  const t = useT();
  const lang = useLang();
  const services = useServices(props.barberId);
  const salon = useSalon();
  const currency = salon.data?.currency ?? "KGS";
  const toggle = (id: string) =>
    props.onChange(
      props.selected.includes(id)
        ? props.selected.filter((x) => x !== id)
        : [...props.selected, id],
    );
  return (
    <section>
      <BackLink onClick={props.onBack} />
      <Title>{t("step_services")}</Title>
      <div className="space-y-2">
        {services.data?.services.map((service) => {
          const active = props.selected.includes(service.id);
          return (
            <button
              key={service.id}
              type="button"
              onClick={() => toggle(service.id)}
              className="w-full text-left"
            >
              <Card className={`flex items-center gap-3 ${active ? "ring-2 ring-brand" : ""}`}>
                <div
                  className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-md border-2 ${active ? "border-brand bg-brand text-brand-text" : "border-line"}`}
                >
                  {active ? "✓" : ""}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="font-medium">{pick(service.name_i18n, lang)}</div>
                  <div className="text-sm text-hint">{t("min", { n: service.duration_min })}</div>
                </div>
                <div className="shrink-0 tabular-nums">
                  {service.price_min === service.price_max
                    ? props.money(service.price_min)
                    : formatMoneyRange(service.price_min, service.price_max, currency, lang)}
                </div>
              </Card>
            </button>
          );
        })}
      </div>
      <div className="sticky bottom-4 mt-6">
        <Primary onClick={props.onNext} disabled={props.selected.length === 0}>
          {t("next")}
        </Primary>
      </div>
    </section>
  );
}

function TimeStep(props: {
  barberId: string | null;
  serviceIds: string[];
  tz: string;
  onBack: () => void;
  onPick: (slot: Slot) => void;
}) {
  const t = useT();
  const lang = useLang();
  const days = useDays(props.barberId, props.serviceIds);
  const [day, setDay] = useState<string | null>(null);
  const slots = useSlots(props.barberId, props.serviceIds, day);

  useEffect(() => {
    if (!day && days.data) {
      const first = days.data.days.find((item) => item.slots_count > 0);
      if (first) setDay(first.date);
    }
  }, [day, days.data]);

  const none = days.data && !days.data.days.some((item) => item.slots_count > 0);
  return (
    <section>
      <BackLink onClick={props.onBack} />
      <Title>{t("step_time")}</Title>
      {none && <p className="py-8 text-center text-hint">{t("no_free_days")}</p>}
      {!none && (
        <div
          className="-mx-4 flex gap-2 overflow-x-auto px-4 pb-2"
          role="listbox"
          aria-label="days"
        >
          {days.data?.days.map((item) => {
            const active = item.date === day;
            const empty = item.slots_count === 0;
            return (
              <button
                key={item.date}
                type="button"
                role="option"
                aria-selected={active}
                disabled={empty}
                onClick={() => setDay(item.date)}
                className={`flex w-14 shrink-0 flex-col items-center rounded-xl py-2 text-sm ${active ? "bg-brand text-brand-text" : "bg-card"} ${empty ? "opacity-35" : ""}`}
              >
                <span className="text-xs capitalize">{formatWeekdayNarrow(item.date, lang)}</span>
                <span className="text-lg font-semibold">{dayOfMonth(item.date)}</span>
              </button>
            );
          })}
        </div>
      )}
      {day && (
        <h2 className="mb-3 mt-4 font-medium first-letter:uppercase">{formatDayLong(day, lang)}</h2>
      )}
      {slots.data && slots.data.slots.length === 0 && (
        <p className="py-6 text-center text-hint">{t("no_slots_day")}</p>
      )}
      <div className="grid grid-cols-4 gap-2 sm:grid-cols-5">
        {slots.data?.slots.map((item) => (
          <button
            key={item.start_at}
            type="button"
            onClick={() => props.onPick(item)}
            className="h-11 rounded-xl bg-card text-sm font-medium tabular-nums hover:ring-2 hover:ring-brand"
          >
            {formatTime(item.start_at, props.tz)}
          </button>
        ))}
      </div>
    </section>
  );
}

function errorText(error: unknown, t: ReturnType<typeof useT>): string {
  if (error instanceof ApiError) {
    if (error.status === 429) return t("too_many");
    if (error.code === "invalid_phone") return t("invalid_phone");
    if (error.code === "client_blocked") return t("blocked");
    if (error.status === 401 || error.code === "hold_expired") return t("expired");
    if (isKey(error.code)) return t(error.code);
  }
  return t("error");
}

function ContactsStep(props: {
  barberId: string | null;
  serviceIds: string[];
  slot: Slot;
  tz: string;
  money: (n: number) => string;
  onBack: () => void;
  onRepick: (slot: Slot) => void;
  onDone: (booked: Booked) => void;
}) {
  const t = useT();
  const lang = useLang();
  const services = useServices(props.barberId);
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("+996 ");
  const [comment, setComment] = useState("");
  const [promo, setPromo] = useState("");
  const [website, setWebsite] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [alternatives, setAlternatives] = useState<Slot[]>([]);
  const key = useMemo(() => newIdempotencyKey(), []);
  const chosen = services.data?.services.filter((s) => props.serviceIds.includes(s.id)) ?? [];
  const subtotal = chosen.reduce((sum, s) => sum + s.price_min, 0);
  const digits = phone.replace(/\D/g, "");
  const valid = name.trim().length > 0 && digits.length >= 9;

  const submit = async () => {
    setPending(true);
    setError(null);
    setAlternatives([]);
    try {
      const booked = await book(
        {
          name,
          phone,
          website,
          barberId: props.barberId,
          serviceIds: props.serviceIds,
          startAt: props.slot.start_at,
          comment,
          promo,
        },
        key,
      );
      props.onDone(booked);
    } catch (caught) {
      if (caught instanceof ApiError && caught.code === "slot_conflict") {
        setAlternatives((caught.details.alternatives as Slot[] | undefined) ?? []);
        setError(t("taken"));
      } else {
        setError(errorText(caught, t));
      }
    } finally {
      setPending(false);
    }
  };

  const input =
    "w-full rounded-xl border border-line bg-card px-3 py-3 outline-none focus:border-brand";
  return (
    <section>
      <BackLink onClick={props.onBack} />
      <Title>{t("step_contacts")}</Title>
      <Card className="mb-4 space-y-1">
        <div className="font-semibold">{formatDateTime(props.slot.start_at, props.tz, lang)}</div>
        <div className="text-sm text-hint">
          {chosen.map((s) => pick(s.name_i18n, lang)).join(", ")}
        </div>
        <div className="flex justify-between pt-2">
          <span>{t("total")}</span>
          <span className="font-semibold tabular-nums">{props.money(subtotal)}</span>
        </div>
      </Card>
      <div className="space-y-3">
        <label className="block">
          <span className="mb-1 block text-sm text-hint">{t("name")}</span>
          <input
            className={input}
            value={name}
            maxLength={200}
            autoComplete="name"
            onChange={(e) => setName(e.target.value)}
          />
        </label>
        <label className="block">
          <span className="mb-1 block text-sm text-hint">{t("phone")}</span>
          <input
            className={input}
            value={phone}
            inputMode="tel"
            autoComplete="tel"
            maxLength={32}
            onChange={(e) => setPhone(e.target.value)}
          />
          <span className="mt-1 block text-xs text-hint">{t("phone_hint")}</span>
        </label>
        <label className="block">
          <span className="mb-1 block text-sm text-hint">{t("comment")}</span>
          <textarea
            className={input}
            rows={2}
            maxLength={500}
            value={comment}
            onChange={(e) => setComment(e.target.value)}
          />
        </label>
        <label className="block">
          <span className="mb-1 block text-sm text-hint">{t("promo")}</span>
          <input
            className={`${input} uppercase`}
            value={promo}
            maxLength={32}
            onChange={(e) => setPromo(e.target.value)}
          />
        </label>
        {/* honeypot: hidden from people, filled by bots */}
        <input
          type="text"
          tabIndex={-1}
          autoComplete="off"
          aria-hidden="true"
          className="absolute left-[-10000px] h-0 w-0 opacity-0"
          value={website}
          onChange={(e) => setWebsite(e.target.value)}
          name="website"
        />
      </div>
      {error && (
        <p className="mt-4 rounded-xl bg-danger/10 px-3 py-2 text-sm text-danger" role="alert">
          {error}
        </p>
      )}
      {alternatives.length > 0 && (
        <div className="mt-3 grid grid-cols-4 gap-2">
          {alternatives.map((item) => (
            <button
              key={item.start_at}
              type="button"
              onClick={() => {
                props.onRepick(item);
                setAlternatives([]);
                setError(null);
              }}
              className="h-11 rounded-xl bg-card text-sm font-medium tabular-nums"
            >
              {formatTime(item.start_at, props.tz)}
            </button>
          ))}
        </div>
      )}
      <div className="sticky bottom-4 mt-6">
        <Primary onClick={() => void submit()} disabled={!valid || pending}>
          {pending ? t("sending") : t("submit")}
        </Primary>
      </div>
    </section>
  );
}

function Done(props: {
  booked: Booked;
  tz: string;
  money: (n: number) => string;
  onAgain: () => void;
  phone?: string;
}) {
  const t = useT();
  const lang = useLang();
  const { booked } = props;
  return (
    <section className="space-y-4 text-center">
      <div className="pt-6 text-5xl">✅</div>
      <h1 className="text-2xl font-semibold">{t("done_title")}</h1>
      <p className="text-hint">{t("done_text")}</p>
      <Card className="space-y-1 text-left">
        <div className="font-semibold">{formatDateTime(booked.start_at, props.tz, lang)}</div>
        <div className="text-sm text-hint">
          {booked.barber.name} · {booked.services.map((s) => pick(s.name_i18n, lang)).join(", ")}
        </div>
        {booked.discount > 0 && (
          <div className="flex justify-between pt-2 text-sm">
            <span>{t("discount")}</span>
            <span className="tabular-nums">−{props.money(booked.discount)}</span>
          </div>
        )}
        <div className="flex justify-between pt-1">
          <span>{t("total")}</span>
          <span className="font-semibold tabular-nums">{props.money(booked.total_due)}</span>
        </div>
      </Card>
      {props.phone && (
        <a className="block text-sm underline" href={`tel:${props.phone}`}>
          {t("call")}: {props.phone}
        </a>
      )}
      <button type="button" className="text-sm text-hint underline" onClick={props.onAgain}>
        {t("book_again")}
      </button>
    </section>
  );
}

function ProfileSheet(props: {
  barberId: string;
  tz: string;
  onClose: () => void;
  onBook: () => void;
}) {
  const t = useT();
  const lang = useLang();
  const profile = useProfile(props.barberId);
  const reviews = useReviews(props.barberId);
  const items = reviews.data?.pages.flatMap((page) => page.items) ?? [];
  const barber = profile.data;
  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/50 sm:items-center"
      onClick={props.onClose}
    >
      <div
        className="max-h-[90vh] w-full max-w-xl overflow-y-auto rounded-t-3xl bg-bg p-5 sm:rounded-3xl"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        {barber && (
          <div className="space-y-4">
            <div className="flex items-center gap-4">
              <Avatar url={barber.photo_url} name={barber.name} size={80} />
              <div>
                <div className="text-lg font-semibold">{barber.name}</div>
                <div className="text-sm text-hint">{pick(barber.specialization_i18n, lang)}</div>
                {barber.rating ? (
                  <div className="text-sm">
                    <Stars value={barber.rating} /> {barber.rating.toFixed(1)} ·{" "}
                    {t("reviews_count", { n: barber.rating_count })}
                  </div>
                ) : null}
              </div>
            </div>
            {pick(barber.bio_i18n, lang) && (
              <p className="whitespace-pre-line text-sm">{pick(barber.bio_i18n, lang)}</p>
            )}
            {barber.portfolio.length > 0 && (
              <div>
                <h3 className="mb-2 text-sm font-medium uppercase text-hint">{t("works")}</h3>
                <div className="grid grid-cols-3 gap-1.5">
                  {barber.portfolio.map((url) => (
                    <a key={url} href={url} target="_blank" rel="noreferrer">
                      <img
                        src={url}
                        alt=""
                        loading="lazy"
                        className="aspect-square w-full rounded-xl object-cover"
                      />
                    </a>
                  ))}
                </div>
              </div>
            )}
            <div>
              <h3 className="mb-2 text-sm font-medium uppercase text-hint">{t("reviews")}</h3>
              {items.length === 0 && <p className="text-sm text-hint">{t("no_reviews")}</p>}
              <div className="space-y-2">
                {items.map((review) => (
                  <Card key={review.booking_id} className="space-y-1">
                    <div className="flex justify-between">
                      <span className="font-medium">{review.author}</span>
                      <Stars value={review.rating} />
                    </div>
                    {review.text && <p className="text-sm">{review.text}</p>}
                    <div className="text-xs text-hint">
                      {formatDate(review.created_at, props.tz, lang)}
                    </div>
                  </Card>
                ))}
              </div>
            </div>
            <Primary onClick={props.onBook}>{t("book_with")}</Primary>
          </div>
        )}
      </div>
    </div>
  );
}

function CertificateCheck({ money }: { money: (n: number) => string }) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const [code, setCode] = useState("");
  const [result, setResult] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const run = async () => {
    setBusy(true);
    try {
      const cert = await checkCertificate(code);
      setResult(
        cert.state === "active"
          ? `${t("cert_balance", { amount: money(cert.balance) })}${cert.expires_on ? ` · ${t("cert_until", { date: cert.expires_on })}` : ""}`
          : t("cert_inactive"),
      );
    } catch (error) {
      setResult(
        error instanceof ApiError && error.status === 404
          ? t("cert_not_found")
          : errorText(error, t),
      );
    } finally {
      setBusy(false);
    }
  };
  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="mb-3 text-sm text-hint underline"
      >
        🎁 {t("cert_check")}
      </button>
    );
  }
  return (
    <Card className="mb-3 space-y-2">
      <div className="flex gap-2">
        <input
          aria-label={t("cert_code")}
          placeholder="GIFT-XXXX-XXXX"
          value={code}
          onChange={(e) => setCode(e.target.value)}
          className="min-w-0 flex-1 rounded-xl border border-line bg-bg px-3 py-2 font-mono uppercase"
        />
        <button
          type="button"
          disabled={busy || code.trim().length < 4}
          onClick={() => void run()}
          className="rounded-xl bg-brand px-4 py-2 font-medium text-brand-text disabled:opacity-50"
        >
          {t("check")}
        </button>
      </div>
      {result && <p className="text-sm">{result}</p>}
    </Card>
  );
}
