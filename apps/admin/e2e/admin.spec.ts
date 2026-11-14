import { expect, test, type Page, type Route } from "@playwright/test";

/** Admin smoke flows with a mocked API (the backend itself is covered by pytest). */

const ME = {
  id: "u1",
  login: "owner",
  full_name: "Owner",
  role: "owner",
  branch_id: null,
  barber_id: null,
  language: "ru",
  permissions: [
    "dashboard:read",
    "bookings:read",
    "bookings:write",
    "clients:read",
    "clients:write",
    "barbers:read",
    "barbers:write",
    "services:read",
    "services:write",
    "finance:read",
    "finance:export",
    "settings:read",
    "settings:write",
    "bonus:adjust",
    "bonus_settings:write",
    "staff:manage",
    "audit:read",
    "notifications:read",
  ],
};
const SALON = {
  name: "Test",
  timezone: "Asia/Bishkek",
  currency: "KGS",
  default_language: "ru",
  slot_step_min: 15,
  buffer_min: 0,
  min_lead_time_min: 60,
  max_days_ahead: 30,
  cancel_min_hours: 2,
  reschedule_min_hours: 2,
  max_active_bookings_per_client: 3,
  reminder_offsets_min: [1440, 120],
  admin_chat_id: null,
  notify_barbers: false,
  notification_templates: {},
  contacts: {},
};

async function mockApi(page: Page, created: unknown[]): Promise<void> {
  let loggedIn = false;
  const json = (route: Route, body: unknown, status = 200) =>
    route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
  await page.routeWebSocket(/\/api\/v1\/admin\/ws/, (ws) => {
    ws.send(JSON.stringify({ type: "hello" }));
  });
  await page.route("**/api/v1/admin/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace("/api/v1/admin", "");
    const method = request.method();
    if (path === "/auth/me")
      return loggedIn
        ? json(route, ME)
        : json(route, { error: { code: "unauthorized", message: "no" } }, 401);
    if (path === "/auth/refresh")
      return json(route, { error: { code: "refresh_missing", message: "no" } }, 401);
    if (path === "/auth/login") {
      const body = request.postDataJSON() as { password: string };
      if (body.password !== "correct-password")
        return json(route, { error: { code: "invalid_credentials", message: "bad" } }, 401);
      loggedIn = true;
      return json(route, { user: ME, csrf_token: "c" });
    }
    if (path === "/settings/salon") return json(route, SALON);
    if (path === "/notifications/unread-count") return json(route, { unread: 2 });
    if (path === "/notifications") return json(route, []);
    if (path === "/dashboard") {
      return json(route, {
        today: "2026-12-07",
        timezone: "Asia/Bishkek",
        currency: "KGS",
        bookings_today: 4,
        bookings_today_by_status: { confirmed: 4 },
        revenue_day: 230_000,
        revenue_week: 230_000,
        revenue_month: 300_000,
        average_check: 75_000,
        new_clients_month: 3,
        barbers: [
          {
            barber_id: "b1",
            name: "Азамат",
            booked_minutes: 120,
            working_minutes: 600,
            load_percent: 20,
            bookings: 2,
          },
        ],
        revenue_chart: [{ date: "2026-12-07", revenue: 230_000, bookings: 3 }],
        upcoming: [
          {
            id: "x",
            start_at: "2026-12-07T13:00:00Z",
            barber: "Азамат",
            client: "Бек",
            total_due: 80_000,
            status: "confirmed",
          },
        ],
      });
    }
    if (path === "/barbers")
      return json(route, {
        items: [
          {
            id: "b1",
            name: "Азамат",
            photo_url: null,
            specialization_i18n: {},
            bio_i18n: {},
            rating: null,
            rating_count: 0,
            sort_order: 0,
            is_active: true,
            is_bookable_online: true,
            telegram_chat_id: null,
          },
        ],
        total: 1,
        limit: 200,
        offset: 0,
      });
    if (path === "/barbers/b1")
      return json(route, {
        id: "b1",
        name: "Азамат",
        photo_url: null,
        specialization_i18n: {},
        bio_i18n: {},
        rating: null,
        rating_count: 0,
        sort_order: 0,
        is_active: true,
        is_bookable_online: true,
        telegram_chat_id: null,
        services: [
          {
            service_id: "s1",
            price: null,
            duration_min: null,
            is_active: true,
            effective_price: 80_000,
            effective_duration_min: 60,
          },
        ],
      });
    if (path === "/services")
      return json(route, {
        items: [
          {
            id: "s1",
            category_id: null,
            name_i18n: { ru: "Стрижка" },
            description_i18n: {},
            duration_min: 60,
            base_price: 80_000,
            is_active: true,
            sort_order: 0,
          },
        ],
        total: 1,
        limit: 500,
        offset: 0,
      });
    if (path === "/clients")
      return json(route, {
        items: [
          {
            id: "c1",
            name: "Бек Тестов",
            phone: "+996555000111",
            telegram_username: null,
            language: "ru",
            tags: [],
            is_blocked: false,
            level_id: null,
            bonus_balance: 0,
            total_spent: 0,
            visits_count: 0,
            no_show_count: 0,
            last_visit_at: null,
            created_at: "2026-11-01T00:00:00Z",
          },
        ],
        total: 1,
        limit: 8,
        offset: 0,
      });
    if (path === "/availability/slots")
      return json(route, {
        date: "2026-12-07",
        timezone: "Asia/Bishkek",
        step_min: 15,
        durations: { b1: 60 },
        slots: [{ start_at: "2026-12-07T06:00:00Z", barber_ids: ["b1"] }],
      });
    if (path === "/bookings" && method === "POST") {
      created.push(request.postDataJSON());
      return json(route, { id: "bk" }, 201);
    }
    if (path === "/bookings") return json(route, { items: [], total: 0, limit: 25, offset: 0 });
    if (path === "/calendar") return json(route, []);
    return json(route, { error: { code: "not_found", message: path } }, 404);
  });
}

test("login, dashboard and a phone booking", async ({ page }) => {
  const created: unknown[] = [];
  await mockApi(page, created);
  await page.goto("./");
  await expect(page).toHaveURL(/\/admin\/login/);

  await page.getByLabel("Логин").fill("owner");
  await page.getByLabel("Пароль").fill("wrong");
  await page.getByRole("button", { name: "Войти" }).click();
  await expect(page.getByRole("alert")).toHaveText("Неверный логин или пароль");
  await page.getByLabel("Пароль").fill("correct-password");
  await page.getByRole("button", { name: "Войти" }).click();

  await expect(page.getByRole("heading", { name: "Дашборд" })).toBeVisible();
  await expect(page.getByTestId("stat-Выручка за день")).toHaveText("2\u00a0300\u00a0сом");
  await expect(page.getByTestId("unread-badge")).toHaveText("2");
  // 13:00Z is 19:00 in Bishkek even though the browser runs in New York
  await expect(page.getByText("19:00")).toBeVisible();

  await page.getByRole("link", { name: "Записи" }).click();
  await page.getByRole("button", { name: "Новая запись" }).click();
  const dialog = page.getByRole("dialog", { name: "Новая запись" });
  await dialog.getByLabel("Имя или телефон клиента").fill("Бек");
  await dialog.getByRole("button", { name: /Бек Тестов/ }).click();
  await dialog.getByLabel("Мастер").selectOption("b1");
  await dialog.getByLabel("Стрижка").check();
  await dialog.getByLabel("Дата").fill("2026-12-07");
  await dialog.getByRole("button", { name: "12:00" }).click();
  await dialog.getByRole("button", { name: "Создать" }).click();

  await expect.poll(() => created.length).toBe(1);
  expect(created[0]).toMatchObject({
    client_id: "c1",
    barber_id: "b1",
    service_ids: ["s1"],
    start_at: "2026-12-07T06:00:00.000Z",
  });
});
