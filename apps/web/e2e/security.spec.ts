import { expect, test } from "@playwright/test";

import { resetRateLimits, shot, signUp } from "./helpers";

test.beforeEach(() => resetRateLimits());

test("anonymous visitors are sent to login and cannot call the API", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await shot(page, "01-landing");
  await page.goto("/deals/new");
  await expect(page).toHaveURL(/\/login\?next=%2Fdeals%2Fnew/);
  await shot(page, "02-login");
  const res = await page.request.get("/api/deals");
  expect(res.status()).toBe(401);
});

test("cross-site and forged-CSRF requests are refused", async ({ page }) => {
  await signUp(page, "Хамгаалагч");
  const body = {
    title: "CSRF test",
    amount_mnt: 1000,
    item_type: "SERVICE",
    delivery_method: "DIGITAL",
    inspection_days: 3,
    my_role: "SELLER",
  };
  const evil = await page.request.post("/api/deals", { data: body, headers: { Origin: "https://evil.example" } });
  expect(evil.status()).toBe(403);
  const forged = await page.request.post("/api/deals", {
    data: body,
    headers: { Origin: "http://localhost:3000", "X-CSRF-Token": "forged" },
  });
  expect(forged.status()).toBe(403);
});

test("session cookie is HttpOnly and not readable by page scripts", async ({ page, context }) => {
  await signUp(page, "Күүки");
  const cookies = await context.cookies();
  const session = cookies.find((c) => c.name.endsWith("safepay_session"));
  expect(session?.httpOnly).toBe(true);
  expect(session?.sameSite).toBe("Lax");
  const visible = await page.evaluate(() => document.cookie);
  expect(visible).not.toContain("safepay_session");
});

test("logout ends the session on the server", async ({ page }) => {
  await signUp(page, "Гарагч");
  await page.goto("/profile");
  await shot(page, "13-profile");
  await page.getByRole("button", { name: "Гарах" }).click();
  await expect(page).toHaveURL(/\/login$/);
  expect((await page.request.get("/api/auth/me")).status()).toBe(401);
});

test("open redirects after login are refused", async ({ page }) => {
  const email = await signUp(page, "Чиглүүлэгч");
  await page.getByRole("link", { name: "Профайл" }).first().click();
  await page.getByRole("button", { name: "Гарах" }).click();
  await page.goto("/login?next=//evil.example/steal");
  await page.getByLabel("Имэйл").fill(email);
  await page.getByLabel("Нууц үг").fill("Correct-Horse-Battery-9");
  await page.getByRole("button", { name: "Нэвтрэх" }).click();
  await expect(page).toHaveURL(/localhost:3000\/dashboard$/);
});
