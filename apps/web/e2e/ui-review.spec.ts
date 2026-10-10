/**
 * Visual review helper (not part of the default run): captures every major page at
 * 375–1440 px (UI_WIDTHS), light and dark (UI_SCHEMES), with realistic data and checks for horizontal overflow.
 *   UI_REVIEW=1 E2E_SCREENSHOT_DIR=... npx playwright test e2e/ui-review.spec.ts
 */
import { expect, test, type Browser, type Page } from "@playwright/test";

import { act, adminSignIn, createDeal, grantAdmin, resetRateLimits, signUp, uniqueEmail } from "./helpers";

test.skip(!process.env.UI_REVIEW, "set UI_REVIEW=1 to run the visual review");
test.setTimeout(900_000);

// Widths and themes are configurable: UI_WIDTHS="375,390" UI_SCHEMES="light,dark".
const ALL_WIDTHS = [
  { name: "375", width: 375, height: 812, mobile: true },
  { name: "390", width: 390, height: 844, mobile: true },
  { name: "430", width: 430, height: 932, mobile: true },
  { name: "768", width: 768, height: 1024, mobile: true },
  { name: "1024", width: 1024, height: 1366, mobile: false },
  { name: "1440", width: 1440, height: 900, mobile: false },
];
const wanted = (process.env.UI_WIDTHS ?? "375,390,430,768,1024,1440").split(",");
const WIDTHS = ALL_WIDTHS.filter((w) => wanted.includes(w.name));
const SCHEMES = (process.env.UI_SCHEMES ?? "light,dark").split(",") as ("light" | "dark")[];
const DIR = process.env.E2E_SCREENSHOT_DIR ?? "test-results/ui-review";

async function capture(browser: Browser, storage: string, pages: [string, string][]): Promise<void> {
  for (const scheme of SCHEMES)
    for (const w of WIDTHS) {
      const ctx = await browser.newContext({
        colorScheme: scheme,
        viewport: { width: w.width, height: w.height },
        isMobile: w.mobile,
        hasTouch: w.mobile,
        storageState: storage,
        locale: "mn-MN",
        timezoneId: "Asia/Ulaanbaatar",
      });
      const page = await ctx.newPage();
      for (const [name, path] of pages) {
        await page.goto(path);
        await page.waitForLoadState("networkidle");
        await expect(page.locator('[aria-label="Ачаалж байна"]')).toHaveCount(0, { timeout: 15_000 });
        // Compare with the configured width, not innerWidth: mobile emulation zooms out
        // to fit wide content, which would hide the overflow.
        const overflow = await page.evaluate((width) => document.documentElement.scrollWidth - width, w.width);
        expect(overflow, `${name} @${w.name}px ${scheme} overflows by ${overflow}px`).toBeLessThanOrEqual(0);
        await page.screenshot({ path: `${DIR}/${name}-${w.name}-${scheme}.png`, fullPage: true });
      }
      await ctx.close();
    }
}

async function save(page: Page, file: string): Promise<string> {
  await page.context().storageState({ path: file });
  return file;
}

test("capture major pages at 390/768/1440", async ({ browser }) => {
  resetRateLimits();
  const sellerCtx = await browser.newContext();
  const seller = await sellerCtx.newPage();
  const buyerCtx = await browser.newContext();
  const buyer = await buyerCtx.newPage();
  await signUp(seller, "Болормаа");
  await signUp(buyer, "Тэмүүлэн");

  // One completed deal, one delivered (inspection notice), one disputed.
  const done = await createDeal(seller, "iPhone 13, 128GB", "1,250,000");
  for (const d of [done]) {
    await buyer.goto(d.invite);
    await buyer.getByRole("button", { name: "Гэрээнд нэгдэх" }).click();
  }
  await seller.goto(done.dealUrl);
  await act(seller, "Нөхцөлийг батлаад илгээх");
  await buyer.goto(done.dealUrl);
  await act(buyer, "Нөхцөлийг зөвшөөрөх");
  await act(buyer, "Төлбөр байршуулах");
  await seller.goto(done.dealUrl);
  await act(seller, "Хүлээлгэн өгсөн гэж тэмдэглэх");
  const delivered = done.dealUrl;

  const disputed = await createDeal(seller, 'Samsung TV 55" — урт нэртэй бараа шалгах зорилготой', "2,400,000");
  await buyer.goto(disputed.invite);
  await buyer.getByRole("button", { name: "Гэрээнд нэгдэх" }).click();
  await seller.goto(disputed.dealUrl);
  await act(seller, "Нөхцөлийг батлаад илгээх");
  await buyer.goto(disputed.dealUrl);
  await act(buyer, "Нөхцөлийг зөвшөөрөх");
  await act(buyer, "Төлбөр байршуулах");
  await act(buyer, "Маргаан нээх", "Бараа эвдэрсэн ирсэн, зураг хавсаргав.");
  await buyer.getByRole("link", { name: "Маргааны дэлгэрэнгүй" }).click();
  const disputeUrl = new URL(buyer.url()).pathname;

  const fresh = await createDeal(seller, "Хуучин ноутбук", "800000");

  const adminEmail = uniqueEmail("admin");
  const adminCtx = await browser.newContext();
  const admin = await adminCtx.newPage();
  await signUp(admin, "Админ", adminEmail);
  await adminSignIn(admin, adminEmail, grantAdmin(adminEmail));
  await admin
    .getByRole("link", { name: /Samsung TV/ })
    .first()
    .click();
  await admin.waitForURL(/\/admin\/disputes\//);
  const adminDisputeUrl = new URL(admin.url()).pathname;

  const anonCtx = await browser.newContext();
  const anon = await save(await anonCtx.newPage(), `${DIR}/anon.json`);
  await capture(browser, anon, [
    ["landing", "/"],
    ["login", "/login"],
    ["register", "/register"],
    ["admin-login", "/admin/login"],
  ]);
  await capture(browser, await save(buyer, `${DIR}/buyer.json`), [
    ["dashboard", "/dashboard"],
    ["deal-delivered-buyer", new URL(delivered).pathname],
    ["dispute", disputeUrl],
    ["notifications", "/notifications"],
    ["profile", "/profile"],
    ["security", "/security"],
  ]);
  await capture(browser, await save(seller, `${DIR}/seller.json`), [
    ["deals", "/deals?scope=all"],
    ["new-deal", "/deals/new"],
    ["deal-draft-invite", new URL(fresh.dealUrl).pathname],
  ]);
  await capture(browser, await save(admin, `${DIR}/admin.json`), [
    ["admin", "/admin"],
    ["admin-dispute", adminDisputeUrl],
    ["admin-users", "/admin/users"],
  ]);
});
