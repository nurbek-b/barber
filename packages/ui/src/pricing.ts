/** Client-side mirror of backend pricing rules (display only; the backend re-checks). */

export interface Totals {
  subtotal: number;
  bonusSpent: number;
  totalDue: number;
  maxBonus: number;
}

/** Clamp a requested bonus spend to [0, maxBonus] and integer units. */
export function clampBonus(requested: number, maxBonus: number): number {
  if (!Number.isFinite(requested) || requested <= 0 || maxBonus <= 0) return 0;
  return Math.min(Math.trunc(requested), maxBonus);
}

/** Same as the backend: total = subtotal − promo discount − bonuses (bonus limit after discount). */
export function computeTotals(
  subtotal: number,
  maxBonus: number,
  requestedBonus: number,
  discount = 0,
): Totals {
  const afterDiscount = subtotal - Math.min(Math.max(discount, 0), subtotal);
  const bonusSpent = clampBonus(requestedBonus, Math.min(maxBonus, afterDiscount));
  return { subtotal, bonusSpent, totalDue: afterDiscount - bonusSpent, maxBonus };
}

/** Same formula as the backend: amount * bp // 10000 (floor). */
export function percentOf(amount: number, bp: number): number {
  return Math.floor((amount * bp) / 10_000);
}
