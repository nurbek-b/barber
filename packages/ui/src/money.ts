/**
 * Money is always an integer number of minor units (tyiyn, kopecks). No floats anywhere:
 * formatting splits the integer with integer arithmetic and groups digits via BigInt.
 */

const CURRENCY_LABEL: Record<string, string> = {
  KGS: "сом",
  KZT: "₸",
  RUB: "₽",
  UZS: "сум",
};

const NBSP = " ";

function assertMinor(amount: number): void {
  if (!Number.isSafeInteger(amount)) {
    throw new TypeError(`money must be an integer number of minor units, got ${amount}`);
  }
}

export function formatAmount(amount: number, locale = "ru"): string {
  assertMinor(amount);
  const negative = amount < 0;
  const abs = Math.abs(amount);
  const major = Math.trunc(abs / 100); // exact for safe integers
  const minor = abs % 100;
  const grouped = new Intl.NumberFormat(locale, { useGrouping: true })
    .format(BigInt(major))
    .replace(/\s/g, NBSP);
  const decimals = minor
    ? `${locale.startsWith("en") ? "." : ","}${String(minor).padStart(2, "0")}`
    : "";
  return `${negative ? "-" : ""}${grouped}${decimals}`;
}

export function currencyLabel(currency: string): string {
  return CURRENCY_LABEL[currency] ?? currency;
}

/** 150000 → "1 500 сом"; 150050 → "1 500,50 сом". */
export function formatMoney(amount: number, currency = "KGS", locale = "ru"): string {
  return `${formatAmount(amount, locale)}${NBSP}${currencyLabel(currency)}`;
}

/** "1 500" … "1 500 – 2 000 сом" for "any barber" ranges. */
export function formatMoneyRange(
  min: number,
  max: number,
  currency = "KGS",
  locale = "ru",
): string {
  if (min === max) return formatMoney(min, currency, locale);
  return `${formatAmount(min, locale)}${NBSP}–${NBSP}${formatMoney(max, currency, locale)}`;
}

/**
 * Parse user input in major units into minor units without floats:
 * "1 234,5" → 123450, "1234.56" → 123456, "12" → 1200. Returns null when invalid.
 */
export function parseMoneyInput(input: string): number | null {
  const cleaned = input.replace(/[\s\u00a0]/g, "");
  const match = /^(\d{1,12})(?:[.,](\d{1,2}))?$/.exec(cleaned);
  if (!match) return null;
  const major = Number(match[1]);
  const minor = Number((match[2] ?? "").padEnd(2, "0") || "0");
  return major * 100 + minor;
}

/** Basis points → "5 %" / "2,5 %". */
export function formatPercentBp(bp: number, locale = "ru"): string {
  assertMinor(bp);
  return `${formatAmount(bp, locale)}${NBSP}%`;
}
