import { expect, test, type Page, type Route } from "@playwright/test";

/**
 * End-to-end booking flow in a mobile browser with the Telegram environment mocked by the
 * app (MODE=e2e) and the backend mocked here — fast and deterministic. The real backend is
 * covered by pytest; the staging smoke test (stage 9) runs against a live stack.
 */

const DAY = "2026-12-07";
const SLOTS = ["2026-12-07T06:00:00Z", "2026-12-07T06:15:00Z", "2026-12-07T08:00:00Z"];

interface Recorded {
  holds: unknown[];
  bookings: { body: unknown; idempotencyKey: string | null }[];
}

async function mockApi(
  page: Page,
  options: { conflictOnFirstHold?: boolean } = {},
): Promise<Recorded> {
  const recorded: Recorded = { holds: [], bookings: [] };
  const json = (route: Route, body: unknown, status = 200) =>
    route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

  await page.route("**/api/v1/miniapp/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace("/api/v1/miniapp", "");
    const method = request.method();

    if (path === "/me") {
      return json(route, {
        id: "c1",
        telegram_id: 1,
        name: "Бек Тест",
        phone: "+996555000111",
        birthday: null,
        language: "ru",
        bonus_balance: 60_000,
        referral_code: "abc12345",
        is_new: false,
      });
    }
    if (path === "/salon") {
      return json(route, {
        name: "Test",
        timezone: "Asia/Bishkek",
        currency: "KGS",
        default_language: "ru",
        slot_step_min: 15,
        max_days_ahead: 30,
        cancel_min_hours: 2,
        reschedule_min_hours: 2,
        contacts: {},
      });
    }
    if (path === "/barbers") {
      return json(route, [
        {
          id: "b1",
          name: "Азамат",
          photo_url: null,
          specialization_i18n: { ru: "Фейды" },
          bio_i18n: {},
          rating: 4.9,
          rating_count: 12,
        },
      ]);
    }
    if (path === "/services") {
      return json(route, {
        categories: [{ id: "cat", name_i18n: { ru: "Стрижки" }, sort_order: 0 }],
        services: [
          {
            id: "s1",
            category_id: "cat",
            name_i18n: { ru: "Стрижка" },
            description_i18n: {},
            duration_min: 60,
            duration_max_min: 60,
            price_min: 100_000,
            price_max: 120_000,
          },
          {
            id: "s2",
            category_id: "cat",
            name_i18n: { ru: "Борода" },
            description_i18n: {},
            duration_min: 30,
            duration_max_min: 30,
            price_min: 50_000,
            price_max: 50_000,
          },
        ],
      });
    }
    if (path === "/availability/days") {
      return json(route, {
        timezone: "Asia/Bishkek",
        days: [
          { date: DAY, slots_count: 3 },
          { date: "2026-12-08", slots_count: 0 },
        ],
      });
    }
    if (path === "/availability/slots") {
      return json(route, {
        date: DAY,
        timezone: "Asia/Bishkek",
        step_min: 15,
        durations: { b1: 60 },
        slots: SLOTS.map((start_at) => ({ start_at, barber_ids: ["b1"] })),
      });
    }
    if (path === "/holds" && method === "POST") {
      const body = request.postDataJSON() as { start_at: string };
      recorded.holds.push(body);
      if (options.conflictOnFirstHold && recorded.holds.length === 1) {
        return json(
          route,
          { error: { code: "slot_conflict", message: "Занято", details: { alternatives: [] } } },
          409,
        );
      }
      return json(
        route,
        {
          hold_id: `hold-${recorded.holds.length}`,
          expires_at: new Date(Date.now() + 5 * 60_000).toISOString(),
          barber: {
            id: "b1",
            name: "Азамат",
            photo_url: null,
            specialization_i18n: {},
            bio_i18n: {},
            rating: 4.9,
            rating_count: 12,
          },
          start_at: body.start_at,
          end_at: body.start_at,
          quote: {
            lines: [
              { service_id: "s1", name_i18n: { ru: "Стрижка" }, duration_min: 60, price: 100_000 },
            ],
            subtotal: 100_000,
            duration_min: 60,
            bonus_balance: 60_000,
            max_bonus_spend: 30_000,
          },
        },
        201,
      );
    }
    if (path.startsWith("/holds/") && method === "DELETE") return route.fulfill({ status: 204 });
    if (path === "/bookings" && method === "POST") {
      recorded.bookings.push({
        body: request.postDataJSON(),
        idempotencyKey: request.headers()["idempotency-key"] ?? null,
      });
      return json(route, { id: "bk1", status: "confirmed" }, 201);
    }
    if (path === "/bookings") return json(route, { items: [], next_cursor: null });
    if (path === "/bookings/repeat") return json(route, null);
    if (path === "/bonus") {
      return json(route, {
        enabled: true,
        balance: 60_000,
        level: null,
        next_level: null,
        visits_left: 0,
        spent_left: 0,
        level_rule: "any",
        cashback_bp: 500,
        max_spend_bp: 3000,
        expiring: [],
      });
    }
    return json(route, { error: { code: "not_found", message: path } }, 404);
  });
  return recorded;
}

test("full booking flow with bonuses", async ({ page }) => {
  const recorded = await mockApi(page);
  await page.goto("./");
  await expect(page.getByRole("heading", { name: "Здравствуйте, Бек!" })).toBeVisible();

  await page.getByTestId("main-button").click(); // Записаться
  await page.getByRole("button", { name: /Любой свободный мастер/ }).click();
  await page.getByTestId("main-button").click(); // Далее

  await page.getByText("Стрижка", { exact: true }).click();
  await expect(page.getByTestId("services-summary")).toContainText("от 1 000 сом");
  await page.getByTestId("main-button").click();

  // first day with free time is preselected; times are in Bishkek time
  await expect(page.getByRole("option", { name: "12:00" })).toBeVisible();
  await page.getByRole("option", { name: "12:00" }).click();

  await expect(page.getByRole("heading", { name: "Подтверждение" })).toBeVisible();
  await expect(page.getByTestId("total-due")).toHaveText("1 000 сом");
  await page.getByRole("switch").check();
  await expect(page.getByTestId("total-due")).toHaveText("700 сом");
  await page.getByPlaceholder(/машинка/).fill("покороче");
  await page.getByTestId("main-button").click(); // Записаться

  await expect(page.getByTestId("done-title")).toHaveText("Вы записаны!");
  expect(recorded.holds).toEqual([
    { barber_id: null, service_ids: ["s1"], start_at: SLOTS[0], reschedule_booking_id: null },
  ]);
  expect(recorded.bookings).toHaveLength(1);
  expect(recorded.bookings[0]!.body).toEqual({
    hold_id: "hold-1",
    comment: "покороче",
    bonus_to_spend: 30_000,
  });
  expect(recorded.bookings[0]!.idempotencyKey).toMatch(/^[0-9a-f]{32}$/);
});

test("taken slot shows a message and lets the user pick another", async ({ page }) => {
  const recorded = await mockApi(page, { conflictOnFirstHold: true });
  await page.goto("./");
  await page.getByTestId("main-button").click();
  await page.getByRole("button", { name: /Азамат/ }).click();
  await page.getByTestId("main-button").click();
  await page.getByText("Борода", { exact: true }).click();
  await page.getByTestId("main-button").click();

  await page.getByRole("option", { name: "12:00" }).click();
  await expect(page.getByRole("status")).toContainText("только что заняли");
  await page.getByRole("option", { name: "12:15" }).click();
  await expect(page.getByRole("heading", { name: "Подтверждение" })).toBeVisible();
  expect(recorded.holds).toHaveLength(2);
});
