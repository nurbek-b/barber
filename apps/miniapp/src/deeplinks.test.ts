import { describe, expect, it } from "vitest";

import { pathForStartParam } from "./deeplinks";

describe("pathForStartParam", () => {
  const id = "7ec8023a-2eed-43a2-bc46-597289aafc3b";
  it("maps known start params to routes", () => {
    expect(pathForStartParam("book")).toBe("/book/barber");
    expect(pathForStartParam(`review_${id}`)).toBe(`/review/${id}`);
    expect(pathForStartParam(`barber_${id}`)).toBe(`/barber/${id}`);
    expect(pathForStartParam(`pay_${id}`)).toBe(`/pay/${id}`);
  });
  it("falls back to home for referrals and garbage", () => {
    expect(pathForStartParam("ref_ABC123")).toBe("/");
    expect(pathForStartParam("review_../../etc")).toBe("/");
    expect(pathForStartParam(null)).toBe("/");
  });
});
