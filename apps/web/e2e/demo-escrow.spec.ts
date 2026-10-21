import { expect, test, type Browser, type Page } from "@playwright/test";

import {
  act,
  adminSignIn,
  createDeal,
  grantAdmin,
  newUserPage,
  resetRateLimits,
  shot,
  signUp,
  signUpDemo,
  uniqueEmail,
} from "./helpers";

/**
 * BETA_DEMO_MODE (web :3001 → demo API :8002): two independent people register,
 * skip email verification entirely, and run deals end to end with simulated money.
 */
test.beforeEach(() => resetRateLimits());

const DEMO = "DEMO — SIMULATED MONEY — NO REAL PAYMENTS";
const STANDARD = process.env.E2E_BASE_URL ?? "http://localhost:3000";

async function agreedDeal(browser: Browser, title: string, amount: string) {
  const seller = await newUserPage(browser);
  const buyer = await newUserPage(browser);
  await signUpDemo(seller, "Демо Болд");
  const { dealUrl, invite } = await createDeal(seller, title, amount);
  await signUpDemo(buyer, "Демо Сараа");
  await buyer.goto(invite);
  await buyer.getByRole("button", { name: "Гэрээнд нэгдэх" }).click();
  await expect(buyer).toHaveURL(dealUrl);
  await seller.goto(dealUrl);
  await act(seller, "Нөхцөлийг батлаад илгээх");
  await buyer.reload();
  await act(buyer, "Нөхцөлийг зөвшөөрөх");
  await expect(buyer.getByText("Төлбөр хүлээж буй").first()).toBeVisible();
  return { seller, buyer, dealUrl };
}

async function fund(buyer: Page, amount: string) {
  await buyer.getByRole("button", { name: "Төлбөр байршуулах" }).click();
  const dialog = buyer.getByRole("dialog");
  await expect(dialog.getByTestId("demo-label")).toHaveText(DEMO);
  await expect(dialog.getByText(amount)).toBeVisible();
  await dialog.getByRole("button", { name: "Батлах" }).click();
  await expect(buyer.getByText("Барьцаанд байршсан").first()).toBeVisible();
}

test("two demo users complete a deal without email verification", async ({ browser }) => {
  const { seller, buyer, dealUrl } = await agreedDeal(browser, "Демо iPhone 13", "1,250,000");
  for (const p of [seller, buyer]) {
    await expect(p.getByTestId("demo-banner")).toHaveText(DEMO);
    await expect(p.getByText(/· DEMO ·/)).toBeVisible();
  }
  await shot(buyer, "demo-01-agreed");
  await fund(buyer, "1,250,000 ₮");

  await seller.reload();
  await act(seller, "Хүлээлгэн өгсөн гэж тэмдэглэх");
  await buyer.reload();
  await act(buyer, "Хүлээн авснаа батлах");
  await expect(buyer.getByText("Амжилттай дууссан").first()).toBeVisible();
  await shot(buyer, "demo-02-completed");

  await seller.goto("/dashboard");
  await expect(seller.getByText("1,250,000 ₮")).toBeVisible();
  await expect(seller.getByTestId("demo-banner")).toHaveText(DEMO);
  await seller.goto("/profile");
  await expect(seller.getByText("Демо бүртгэл", { exact: true })).toBeVisible();
  await expect(seller.getByText("Имэйлээ баталгаажуулна уу")).toHaveCount(0);
  expect(new URL(dealUrl).port).toBe("3001");
});

test("a demo deal can be cancelled before payment", async ({ browser }) => {
  const { seller, buyer } = await agreedDeal(browser, "Демо цуцлах", "300,000");
  await act(buyer, "Гэрээг цуцлах", "Өөр худалдагчаас авлаа.");
  await expect(buyer.getByText("Цуцлагдсан").first()).toBeVisible();
  await seller.reload();
  await expect(seller.getByText("Цуцлагдсан").first()).toBeVisible();
  await expect(seller.getByRole("button", { name: "Хүлээлгэн өгсөн гэж тэмдэглэх" })).toHaveCount(0);
});

test("the seller refunds a funded demo deal", async ({ browser }) => {
  const { seller, buyer } = await agreedDeal(browser, "Демо буцаалт", "450,000");
  await fund(buyer, "450,000 ₮");
  await seller.reload();
  await act(seller, "Мөнгийг буцаан олгох", "Бараа дууссан.");
  await expect(seller.getByText("Буцаан олгосон").first()).toBeVisible();
  await buyer.goto("/dashboard");
  await expect(buyer.getByText("450,000 ₮")).toBeVisible();
  await seller.goto("/dashboard");
  await expect(seller.getByText("450,000 ₮")).toHaveCount(0);
});

test("a demo dispute is resolved by an admin with password and TOTP", async ({ browser }) => {
  const { seller, buyer } = await agreedDeal(browser, "Демо маргаантай TV", "2,000,000");
  await fund(buyer, "2,000,000 ₮");
  await seller.reload();
  await act(seller, "Хүлээлгэн өгсөн гэж тэмдэглэх");
  await buyer.reload();
  await act(buyer, "Маргаан нээх", "Дэлгэц нь хагарсан ирсэн.");
  await expect(buyer.getByText("Маргаантай").first()).toBeVisible();
  // A demo party is not an admin: the admin area asks for admin sign-in.
  await buyer.goto("/admin");
  await expect(buyer).toHaveURL(/\/admin\/login/);
  expect((await buyer.request.get("/api/admin/overview")).status()).toBe(401);

  // Admins are staff with a VERIFIED, non-demo account (grant-admin refuses anything
  // else), registered on the standard site, plus a separate admin password and TOTP.
  const admin = await (await browser.newContext({ baseURL: STANDARD })).newPage();
  const adminEmail = uniqueEmail("admin");
  await signUp(admin, "Админ", adminEmail);
  const secret = grantAdmin(adminEmail);
  await adminSignIn(admin, adminEmail, secret);
  await admin.getByRole("link", { name: /Демо маргаантай TV/ }).first().click();
  await admin.getByRole("button", { name: "Худалдагчид шилжүүлэх" }).click();
  await admin.getByLabel(/Шийдвэрийн үндэслэл/).fill("Хүргэлтийн үед бүрэн бүтэн байсныг нотолсон.");
  await admin.getByRole("button", { name: "Шийдвэрийг батлах" }).click();
  await expect(admin.getByText("Шийдвэрлэсэн: Худалдагчид шилжүүлэх")).toBeVisible();
  await shot(admin, "demo-03-admin-decision");

  await seller.goto("/dashboard");
  await expect(seller.getByText("2,000,000 ₮")).toBeVisible();
});
