/** Deep links (startapp=...): book, review_<bookingId>, barber_<barberId>. */
export function pathForStartParam(param: string | null | undefined): string {
  if (param === "book") return "/book/barber";
  const review = /^review_([0-9a-f-]{36})$/.exec(param ?? "");
  if (review) return `/review/${review[1]}`;
  const barber = /^barber_([0-9a-f-]{36})$/.exec(param ?? "");
  if (barber) return `/barber/${barber[1]}`;
  return "/"; // the referral payload (ref_...) is handled by the backend
}
