import { describe, expect, it } from "vitest";

import {
  BRAND_PALETTES,
  brandColors,
  brandSurfaces,
  contrast,
  inkOn,
  luminance,
  textOn,
} from "./brand";

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

  it("keeps the background tone light on a light theme and dark on a dark one", () => {
    expect(brandSurfaces(null, "#ffffff")).toBeNull();
    for (const palette of BRAND_PALETTES) {
      const tone = palette.colors[2];
      const light = brandSurfaces(tone, "#ffffff")!;
      expect(contrast(light.page, "#111111")).toBeGreaterThanOrEqual(12);
      expect(luminance(light.section)).toBeGreaterThan(luminance(light.page));
      const dark = brandSurfaces(tone, "#1c1c1d")!;
      expect(contrast(dark.section, "#ffffff")).toBeGreaterThanOrEqual(12);
      expect(luminance(dark.section)).toBeGreaterThan(luminance(dark.page));
    }
    // a dark tone picked by mistake still gives a light page on a light theme
    expect(luminance(brandSurfaces("#3a2a1a", "#ffffff")!.page)).toBeGreaterThan(0.7);
  });
});
