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

export function computeTotals(subtotal: number, maxBonus: number, requestedBonus: number): Totals {
  const bonusSpent = clampBonus(requestedBonus, Math.min(maxBonus, subtotal));
  return { subtotal, bonusSpent, totalDue: subtotal - bonusSpent, maxBonus };
}

/** Same formula as the backend: amount * bp // 10000 (floor). */
export function percentOf(amount: number, bp: number): number {
  return Math.floor((amount * bp) / 10_000);
}
