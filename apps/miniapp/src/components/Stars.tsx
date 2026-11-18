import { useT } from "../i18n";

/** Read-only stars, e.g. ★★★★☆ for 4.2 (rounded to the nearest star). */
export function Stars({ value, size = "text-sm" }: { value: number; size?: string }) {
  const t = useT();
  const full = Math.round(value);
  return (
    <span
      className={`${size} tracking-tight text-gold`}
      aria-label={t("review.stars", { n: value })}
    >
      {"★".repeat(full)}
      <span className="text-hint opacity-40">{"★".repeat(5 - full)}</span>
    </span>
  );
}

/** 1..5 star picker with 44px touch targets. */
export function StarInput({ value, onChange }: { value: number; onChange: (n: number) => void }) {
  const t = useT();
  return (
    <div className="flex justify-center gap-1" role="radiogroup" aria-label={t("review.rate")}>
      {[1, 2, 3, 4, 5].map((n) => (
        <button
          key={n}
          type="button"
          role="radio"
          aria-checked={value === n}
          aria-label={t("review.stars", { n })}
          onClick={() => onChange(n)}
          className={`h-12 w-12 text-4xl leading-none transition ${n <= value ? "text-gold" : "text-hint opacity-30"}`}
        >
          ★
        </button>
      ))}
    </div>
  );
}
