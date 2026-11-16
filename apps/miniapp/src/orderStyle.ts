/** Badge colours of shop order statuses. */
export const ORDER_STYLE: Record<string, string> = {
  new: "bg-amber-500/15 text-amber-600",
  payment_claimed: "bg-amber-500/15 text-amber-600",
  paid: "bg-green-500/15 text-green-600",
  ready: "bg-green-500/15 text-green-600",
  shipped: "bg-green-500/15 text-green-600",
  completed: "bg-bg-secondary text-hint",
  cancelled: "bg-destructive/10 text-destructive",
};
