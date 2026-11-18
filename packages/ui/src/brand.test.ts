import { describe, expect, it } from "vitest";

import { brandColors, contrast, inkOn, textOn } from "./brand";

describe("brand colors", () => {
  it("is off without a main color", () => {
    expect(brandColors(null, "#ffffff", "#ffffff")).toBeNull();
    expect(brandColors("gold", null, "#ffffff")).toBeNull();
  });

  it("picks readable text on fills", () => {
    expect(textOn("#2E3236")).toBe("#ffffff");
    expect(textOn("#F2C230")).toBe("#111111");
  });

  it("darkens light colors for text on a light page and lightens on a dark one", () => {
    const light = inkOn("#E3A6B4", "#ffffff");
    expect(contrast(light, "#ffffff")).toBeGreaterThanOrEqual(4.5);
    const dark = inkOn("#2E3236", "#1c1c1d");
    expect(contrast(dark, "#1c1c1d")).toBeGreaterThanOrEqual(4.5);
  });

  it("uses the second color for buttons when the main one vanishes on the background", () => {
    const onDark = brandColors("#2E3236", "#F2C230", "#1c1c1d")!;
    expect(onDark.brand).toBe("#F2C230");
    expect(onDark.brandText).toBe("#111111");
    const onLight = brandColors("#2E3236", "#F2C230", "#ffffff")!;
    expect(onLight.brand).toBe("#2E3236");
    expect(onLight.brand2).toBe("#F2C230");
  });
});
