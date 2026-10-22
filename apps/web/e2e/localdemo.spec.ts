import { expect, test, type Page } from "@playwright/test";

import { act, shot } from "./helpers";

/**
 * LOCAL DEMO (web :3002 → API :8003 with LOCAL_DEMO=true, seeded database): the
 * presenter's flow in ONE browser, switching between the seeded buyer, seller and
 * admin with the demo bar. The buyer pays from a simulated 10,000,000 ₮ wallet.
 */

const DEMO = "DEMO — SIMULATED MONEY — NO REAL PAYMENTS";
type Who = "Худалдан авагч" | "Худалдагч" | "Админ";

function mnt(n: number): string {
  return `${n.toLocaleString("en-US")} ₮`;
}

async function switchTo(page: Page, who: Who): Promise<void> {
  await page.getByTestId("demo-switcher").getByRole("button", { name: who }).click();
  await expect(page).toHaveURL(who === "Админ" ? /\/admin$/ : /\/dashboard$/);
  await expect(page.getByTestId("demo-switcher").getByRole("button", { name: who })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
}

async function available(page: Page): Promise<number> {
  const text = await page.getByTestId("wallet-available").innerText();
  return Number(text.replace(/[^\d]/g, ""));
}

async function openDeal(page: Page, title: string): Promise<void> {
  await page.getByRole("link", { name: new RegExp(title) }).first().click();
  await expect(page.getByRole("heading", { name: title })).toBeVisible();
}

/** Buyer creates a deal naming the seeded seller, submits the terms; seller accepts. */
async function agreedDeal(page: Page, title: string, amount: number): Promise<void> {
  await page.goto("/login");
  await page.getByTestId("demo-login").getByRole("button", { name: "Худалдан авагч" }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  await page.goto("/deals/new");
  await expect(page.getByRole("radio", { name: /Худалдан авагч/ })).toBeChecked();
  await expect(page.getByLabel(/Худалдагчийн имэйл/)).toHaveValue("demo.seller@example.com");
  await page.getByLabel("Юу худалдаж байна вэ?").fill(title);
  await page.getByLabel("Дэлгэрэнгүй тайлбар").fill("Шинэ, баталгаатай. Хайрцаг, цэнэглэгчтэй.");
  await page.getByLabel("Үнэ (₮)").fill(amount.toLocaleString("en-US"));
  await page.getByRole("button", { name: "Гэрээ үүсгэх" }).click();
  await expect(page.getByText(/гэрээнд нэгдсэн/)).toBeVisible();
  await act(page, "Нөхцөлийг батлаад илгээх");

  await switchTo(page, "Худалдагч");
  await openDeal(page, title);
  await act(page, "Нөхцөлийг зөвшөөрөх");
  await expect(page.getByText("Төлбөр хүлээж буй").first()).toBeVisible();
}

/** Buyer pays from the demo wallet; returns the balance before paying. */
async function fund(page: Page, title: string, amount: number): Promise<number> {
  await switchTo(page, "Худалдан авагч");
  const before = await available(page);
  await openDeal(page, title);
  await page.getByRole("button", { name: "Төлбөр байршуулах" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByTestId("demo-label")).toHaveText(DEMO);
  await expect(dialog.getByTestId("demo-fund-preview")).toContainText(mnt(before - amount));
  await shot(page, "localdemo-fund-dialog");
  await dialog.getByRole("button", { name: "Батлах" }).click();
  await expect(page.getByText("Барьцаанд байршсан").first()).toBeVisible();
  await page.goto("/dashboard");
  expect(await available(page)).toBe(before - amount);
  await expect(page.getByTestId("wallet-held")).toContainText(mnt(amount));
  return before;
}

test("presenter: buyer pays into escrow, seller delivers, buyer releases", async ({ page }) => {
  const title = `Демо MacBook ${Date.now()}`;
  const amount = 3_200_000;
  await agreedDeal(page, title, amount);
  await expect(page.getByTestId("demo-banner")).toHaveText(DEMO);
  const before = await fund(page, title, amount);
  await shot(page, "localdemo-buyer-funded");

  await switchTo(page, "Худалдагч");
  const sellerBefore = await available(page);
  await openDeal(page, title);
  await act(page, "Хүлээлгэн өгсөн гэж тэмдэглэх");

  await switchTo(page, "Худалдан авагч");
  await openDeal(page, title);
  await act(page, "Хүлээн авснаа батлах");
  await expect(page.getByText("Амжилттай дууссан").first()).toBeVisible();
  await page.goto("/dashboard");
  expect(await available(page)).toBe(before - amount);

  await switchTo(page, "Худалдагч");
  expect(await available(page)).toBe(sellerBefore + amount);
  await expect(page.getByTestId("demo-wallet")).toContainText("Гэрээний төлбөр орж ирсэн");
  await shot(page, "localdemo-seller-paid");
});

test("presenter: seller refunds a paid deal back to the buyer's wallet", async ({ page }) => {
  const title = `Демо буцаалт ${Date.now()}`;
  const amount = 450_000;
  await agreedDeal(page, title, amount);
  const before = await fund(page, title, amount);

  await switchTo(page, "Худалдагч");
  await openDeal(page, title);
  await act(page, "Мөнгийг буцаан олгох", "Бараа дууссан тул буцаана.");
  await expect(page.getByText("Буцаан олгосон").first()).toBeVisible();

  await switchTo(page, "Худалдан авагч");
  expect(await available(page)).toBe(before);
  await expect(page.getByTestId("demo-wallet")).toContainText("Барьцаанаас буцаж ирсэн");
});

test("presenter: a deal is cancelled before payment and no money moves", async ({ page }) => {
  const title = `Демо цуцлалт ${Date.now()}`;
  await agreedDeal(page, title, 300_000);
  await switchTo(page, "Худалдан авагч");
  const before = await available(page);
  await openDeal(page, title);
  await act(page, "Гэрээг цуцлах", "Өөр худалдагчаас авлаа.");
  await expect(page.getByText("Цуцлагдсан").first()).toBeVisible();
  await page.goto("/dashboard");
  expect(await available(page)).toBe(before);
});

test("presenter: buyer disputes, the demo admin refunds in one click", async ({ page }) => {
  const title = `Демо маргаан ${Date.now()}`;
  const amount = 2_000_000;
  await agreedDeal(page, title, amount);
  const before = await fund(page, title, amount);

  await switchTo(page, "Худалдагч");
  await openDeal(page, title);
  await act(page, "Хүлээлгэн өгсөн гэж тэмдэглэх");

  await switchTo(page, "Худалдан авагч");
  await openDeal(page, title);
  await act(page, "Маргаан нээх", "Дэлгэц нь хагарсан ирсэн.");
  await expect(page.getByText("Маргаантай").first()).toBeVisible();

  await switchTo(page, "Админ");
  await page.getByRole("link", { name: new RegExp(title) }).first().click();
  await page.getByRole("button", { name: "Худалдан авагчид буцаах" }).click();
  await page.getByLabel(/Шийдвэрийн үндэслэл/).fill("Барааны гэмтлийг зургаар нотолсон тул буцаан олгоно.");
  await shot(page, "localdemo-admin-decision");
  await page.getByRole("button", { name: "Шийдвэрийг батлах" }).click();
  await expect(page.getByText("Шийдвэрлэсэн: Худалдан авагчид буцаах")).toBeVisible();

  // Switching again keeps working (admin session reused; party logins not rate limited).
  await switchTo(page, "Худалдан авагч");
  expect(await available(page)).toBe(before);
  await switchTo(page, "Админ");
  await switchTo(page, "Худалдагч");
});

test("the admin login page signs the demo admin in with one click", async ({ browser }) => {
  const page = await (await browser.newContext()).newPage();
  await page.goto("/admin/login");
  await page.getByRole("button", { name: "Демо админаар нэвтрэх" }).click();
  await expect(page.getByText("Админ самбар")).toBeVisible();
});

test("signing up in the local demo needs no email verification", async ({ browser }) => {
  const page = await (await browser.newContext()).newPage();
  const email = `signup-${Date.now()}@example.com`;
  await page.goto("/register");
  await page.getByLabel("Таны нэр").fill("Шинэ хэрэглэгч");
  await page.getByLabel("Имэйл").fill(email);
  await page.getByLabel("Нууц үг", { exact: true }).fill("Correct-Horse-Battery-9");
  await page.getByLabel("Нууц үг давтах").fill("Correct-Horse-Battery-9");
  await page.getByRole("button", { name: "Бүртгүүлэх" }).click();
  await expect(page.getByText("Одоо нэвтэрч болно")).toBeVisible();
  await page.goto("/login");
  await page.getByLabel("Имэйл").fill(email);
  await page.getByLabel("Нууц үг").fill("Correct-Horse-Battery-9");
  await page.getByRole("button", { name: "Нэвтрэх" }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  await page.goto("/deals/new");
  await expect(page.getByLabel("Юу худалдаж байна вэ?")).toBeVisible();
  await expect(page.getByText("Имэйлээ баталгаажуулна уу")).toHaveCount(0);
});
