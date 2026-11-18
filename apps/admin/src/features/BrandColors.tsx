import type { components } from "@barber/api-client";
import { BRAND_PALETTES, brandColors, brandSurfaces, HEX_COLOR, inkBackground } from "@barber/ui";
import { useTranslation } from "react-i18next";

import { Button, Card, CardContent, Input } from "@/components/ui";
import { cn } from "@/lib/utils";

type Salon = components["schemas"]["SalonSettingsOut"];

const THEMES = [
  {
    key: "lightTheme",
    dark: false,
    bg: "#ffffff",
    page: "#f1f1f4",
    text: "#111111",
    hint: "#8a8a8f",
  },
  {
    key: "darkTheme",
    dark: true,
    bg: "#1c1c1d",
    page: "#000000",
    text: "#ffffff",
    hint: "#8a8a8f",
  },
] as const;

/** Brand colors and background tone for the Mini App, with presets and a light/dark preview. */
export function BrandColorsCard({
  form,
  set,
  writable,
}: {
  form: Salon;
  set: <K extends keyof Salon>(key: K, value: Salon[K]) => void;
  writable: boolean;
}) {
  const { t } = useTranslation();
  const primary = form.brand_color ?? null;
  const secondary = form.brand_color_2 ?? null;
  const tone = form.brand_bg ?? null;
  const same = (a: string | null, b: string) => a?.toLowerCase() === b.toLowerCase();
  const pick = (main: string | null, second: string | null, background: string | null) => {
    set("brand_color", main);
    set("brand_color_2", second);
    set("brand_bg", background);
  };

  return (
    <Card className="mb-4">
      <CardContent className="space-y-5 pt-5">
        <div>
          <h2 className="font-semibold">{t("settings.brandColors")}</h2>
          <p className="mt-1 text-sm text-muted-foreground">{t("settings.brandHint")}</p>
        </div>

        <div>
          <div className="mb-2 text-sm font-medium">{t("settings.palettes")}</div>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 2xl:grid-cols-6">
            {BRAND_PALETTES.map((palette) => {
              const [main, second, background] = palette.colors;
              const on = same(primary, main) && same(secondary, second) && same(tone, background);
              return (
                <button
                  key={palette.id}
                  type="button"
                  disabled={!writable}
                  aria-pressed={on}
                  onClick={() => pick(main, second, background)}
                  className={cn(
                    "flex min-h-11 items-center gap-2 rounded-md border px-3 py-2 text-left text-sm transition-colors hover:bg-accent disabled:opacity-60",
                    on && "border-primary ring-1 ring-primary",
                  )}
                >
                  <span className="flex shrink-0 rounded-full border p-0.5" style={{ background }}>
                    <span className="h-5 w-5 rounded-full border" style={{ background: main }} />
                    <span
                      className="-ml-1.5 h-5 w-5 rounded-full border"
                      style={{ background: second }}
                    />
                  </span>
                  {t(`settings.palette_${palette.id}`)}
                </button>
              );
            })}
            <button
              type="button"
              disabled={!writable}
              aria-pressed={!primary && !tone}
              onClick={() => pick(null, null, null)}
              className={cn(
                "flex min-h-11 items-center gap-2 rounded-md border px-3 py-2 text-left text-sm transition-colors hover:bg-accent disabled:opacity-60",
                !primary && !tone && "border-primary ring-1 ring-primary",
              )}
            >
              <span className="h-5 w-5 shrink-0 rounded-full border bg-[#2481cc]" />
              {t("settings.telegramColors")}
            </button>
          </div>
        </div>

        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          <ColorField
            id="brand-color"
            label={t("settings.primaryColor")}
            hint={t("settings.primaryHint")}
            value={primary}
            disabled={!writable}
            onChange={(value) => set("brand_color", value)}
          />
          <ColorField
            id="brand-color-2"
            label={t("settings.secondaryColor")}
            hint={t("settings.secondaryHint")}
            value={secondary}
            disabled={!writable || !primary}
            onChange={(value) => set("brand_color_2", value)}
          />
          <ColorField
            id="brand-bg"
            label={t("settings.backgroundColor")}
            hint={t("settings.backgroundHint")}
            value={tone}
            fallback="#f1f1f4"
            disabled={!writable}
            onChange={(value) => set("brand_bg", value)}
          />
        </div>

        <div>
          <div className="mb-2 text-sm font-medium">{t("settings.preview")}</div>
          <div className="grid gap-3 sm:grid-cols-2">
            {THEMES.map((theme) => (
              <Preview
                key={theme.key}
                theme={theme}
                primary={primary}
                secondary={secondary}
                tone={tone}
              />
            ))}
          </div>
          {writable && (
            <p className="mt-2 text-xs text-muted-foreground">{t("settings.saveColorsHint")}</p>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function ColorField({
  id,
  label,
  hint,
  value,
  fallback = "#2481cc",
  disabled,
  onChange,
}: {
  id: string;
  label: string;
  hint: string;
  value: string | null;
  fallback?: string;
  disabled: boolean;
  onChange: (value: string | null) => void;
}) {
  const { t } = useTranslation();
  return (
    <div>
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      <p className="mb-1.5 text-xs text-muted-foreground">{hint}</p>
      <div className="flex items-center gap-2">
        <input
          type="color"
          aria-label={label}
          value={value ?? fallback}
          disabled={disabled}
          onChange={(e) => onChange(e.target.value.toUpperCase())}
          className="h-10 w-12 shrink-0 cursor-pointer rounded-md border bg-transparent p-1 disabled:cursor-not-allowed disabled:opacity-50"
        />
        <Input
          id={id}
          className="font-mono uppercase"
          placeholder={t("settings.noColor")}
          value={value ?? ""}
          disabled={disabled}
          maxLength={7}
          onChange={(e) => {
            const raw = e.target.value.trim();
            const next = raw.startsWith("#") ? raw : `#${raw}`;
            if (!raw) onChange(null);
            else if (HEX_COLOR.test(next)) onChange(next.toUpperCase());
          }}
        />
        {value && !disabled && (
          <Button type="button" size="sm" variant="ghost" onClick={() => onChange(null)}>
            {t("settings.clearColor")}
          </Button>
        )}
      </div>
    </div>
  );
}

/** A miniature Mini App screen in one theme, painted exactly as the app will do it. */
function Preview({
  theme,
  primary,
  secondary,
  tone,
}: {
  theme: (typeof THEMES)[number];
  primary: string | null;
  secondary: string | null;
  tone: string | null;
}) {
  const { t } = useTranslation();
  const surfaces = brandSurfaces(tone, theme.bg);
  const page = surfaces?.page ?? theme.page;
  const card = surfaces?.section ?? theme.bg;
  const colors = brandColors(
    primary,
    secondary,
    surfaces ? inkBackground(surfaces, theme.dark) : theme.bg,
  ) ?? {
    brand: "#2481cc",
    brandText: "#ffffff",
    brandInk: theme.bg === "#ffffff" ? "#2481cc" : "#5eb5f7",
    brand2: "#2481cc",
    brand2Text: "#ffffff",
    brand2Ink: theme.bg === "#ffffff" ? "#2481cc" : "#5eb5f7",
  };
  const tint = (hex: string) => `color-mix(in srgb, ${hex} 15%, transparent)`;
  return (
    <div className="overflow-hidden rounded-xl border" style={{ background: page }}>
      <div className="px-3 pt-2 text-xs" style={{ color: theme.hint }}>
        {t(`settings.${theme.key}`)}
      </div>
      <div className="space-y-2 p-3">
        <div
          className="flex items-center justify-between rounded-lg p-3"
          style={{ background: card, color: theme.text }}
        >
          <div>
            <div className="text-sm font-semibold">Britva Barber</div>
            <span
              className="mt-1 inline-block rounded-full px-2 py-0.5 text-xs font-medium"
              style={{ background: tint(colors.brand2), color: colors.brand2Ink }}
            >
              🎁 345 сом
            </span>
          </div>
          <span className="text-xs" style={{ color: colors.brand2Ink }}>
            Fade · ★ 5.0
          </span>
        </div>
        <div className="flex gap-1.5">
          {["10:00", "10:15", "10:30"].map((slot, index) => (
            <span
              key={slot}
              className="flex-1 rounded-md py-1.5 text-center text-xs font-medium"
              style={
                index === 1
                  ? { background: colors.brand, color: colors.brandText }
                  : { background: card, color: theme.text }
              }
            >
              {slot}
            </span>
          ))}
        </div>
        <div
          className="rounded-lg py-2 text-center text-sm font-semibold"
          style={{ background: colors.brand, color: colors.brandText }}
        >
          {t("calendar.newBooking")}
        </div>
        <div className="text-xs font-medium" style={{ color: colors.brandInk }}>
          {t("settings.preview")} ›
        </div>
      </div>
    </div>
  );
}
