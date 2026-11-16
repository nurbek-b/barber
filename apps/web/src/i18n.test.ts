import { describe, expect, it } from "vitest";

import { isKey, pick, translate } from "./i18n";

describe("web i18n", () => {
  it("translates with values and falls back to Russian names", () => {
    expect(translate("ru", "reviews_count", { n: 3 })).toBe("Отзывов: 3");
    expect(translate("ky", "submit")).toBe("Жазылуу");
    expect(pick({ ru: "Стрижка" }, "en")).toBe("Стрижка");
  });

  it("knows the API error codes it can explain", () => {
    expect(isKey("promo_expired")).toBe(true);
    expect(isKey("something_else")).toBe(false);
  });
});
