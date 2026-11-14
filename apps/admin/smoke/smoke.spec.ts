import { expect, test } from "@playwright/test";

/** Read-only checks after a deploy: services are up, wiring works, security headers present. */

test("API is ready (database and Redis reachable)", async ({ request }) => {
  const response = await request.get("/api/v1/health/ready");
  expect(response.status()).toBe(200);
  expect(await response.json()).toMatchObject({ status: "ok" });
});

test("Mini App is served and embeddable only by Telegram", async ({ request }) => {
  const response = await request.get("/app/");
  expect(response.status()).toBe(200);
  const csp = response.headers()["content-security-policy"] ?? "";
  expect(csp).toContain("frame-ancestors https://web.telegram.org");
  expect(await response.text()).toContain('<div id="root">');
});

test("Mini App API rejects requests without initData", async ({ request }) => {
  const response = await request.get("/api/v1/miniapp/me");
  expect(response.status()).toBe(401);
  expect((await response.json()).error.code).toBe("unauthorized");
});

test("bot webhook requires the secret", async ({ request }) => {
  const response = await request.post("/api/v1/bot/webhook", { data: { update_id: 1 } });
  expect(response.status()).toBe(401);
});

test("admin login works", async ({ page }) => {
  const login = process.env.SMOKE_ADMIN_LOGIN;
  const password = process.env.SMOKE_ADMIN_PASSWORD;
  test.skip(!login || !password, "SMOKE_ADMIN_LOGIN / SMOKE_ADMIN_PASSWORD not set");
  await page.goto("/admin/login");
  await page.getByLabel("Логин").fill(login!);
  await page.getByLabel("Пароль").fill(password!);
  await page.getByRole("button", { name: "Войти" }).click();
  await expect(page.getByRole("link", { name: "Календарь" })).toBeVisible();
});
