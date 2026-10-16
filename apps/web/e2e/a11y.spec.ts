import path from "node:path";

import { expect, test, type Browser, type Page } from "@playwright/test";

import { act, adminSignIn, createDeal, grantAdmin, newUserPage, resetRateLimits, signUp, uniqueEmail } from "./helpers";

/**
 * Automated WCAG 2.2 A/AA scan (axe-core) of the main pages, mobile and
 * desktop, light and dark. Automated rules catch only part of WCAG; keyboard,
 * screen-reader and zoom checks are documented in docs/UI_UX_AUDIT.md.
 */
const AXE = path.resolve(__dirname, "../node_modules/axe-core/axe.min.js");
const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];

type Violation = { id: string; impact: string; help: string; nodes: { target: string[] }[] };

async function scan(page: Page, label: string): Promise<string[]> {
  await page.waitForLoadState("networkidle");
  await page.addScriptTag({ path: AXE });
  const violations = await page.evaluate(async (tags) => {
    // @ts-expect-error axe is injected above
    const result = await window.axe.run(document, { runOnly: { type: "tag", values: tags } });
    return result.violations as Violation[];
  }, TAGS);
  return violations.map(
    (v) => `${label}: [${v.impact}] ${v.id} — ${v.help} (${v.nodes.map((n) => n.target.join(" ")).join(", ")})`,
  );
}

/** Scans each path in light and dark at the context's size; returns all findings. */
async function scanAll(browser: Browser, storage: string | undefined, paths: string[], desktop: boolean) {
  const findings: string[] = [];
  for (const colorScheme of ["light", "dark"] as const) {
    const ctx = await browser.newContext({
      ...(desktop ? { viewport: { width: 1280, height: 900 } } : {}),
      colorScheme,
      storageState: storage ? JSON.parse(storage) : undefined,
    });
    const page = await ctx.newPage();
    for (const path of paths) {
      await page.goto(path);
      findings.push(...(await scan(page, `${path} ${colorScheme}${desktop ? " desktop" : ""}`)));
    }
    await ctx.close();
  }
  return findings;
}

test.beforeEach(() => resetRateLimits());

test("main pages have no automated WCAG 2.2 AA violations", async ({ browser }) => {
  test.setTimeout(240_000);
  const seller = await newUserPage(browser);
  const buyer = await newUserPage(browser);
  const admin = await newUserPage(browser);

  await signUp(seller, "Хүртээмж");
  const { dealUrl, invite } = await createDeal(seller, "Хүртээмжийн шалгалт", "500,000");
  await signUp(buyer, "Шалгагч");
  await buyer.goto(invite);
  await buyer.getByRole("button", { name: "Гэрээнд нэгдэх" }).click();
  await expect(buyer).toHaveURL(dealUrl);
  await seller.goto(dealUrl);
  await act(seller, "Нөхцөлийг батлаад илгээх");
  await buyer.reload();
  await act(buyer, "Нөхцөлийг зөвшөөрөх");
  await act(buyer, "Төлбөр байршуулах");
  await seller.reload();
  await act(seller, "Хүлээлгэн өгсөн гэж тэмдэглэх");
  await buyer.reload();
  await act(buyer, "Маргаан нээх", "Шалгалтын маргаан.");
  await buyer.getByRole("link", { name: "Маргааны дэлгэрэнгүй" }).click();
  await expect(buyer).toHaveURL(/\/disputes\//);
  const disputeUrl = new URL(buyer.url()).pathname;
  const dealPath = new URL(dealUrl).pathname;

  const adminEmail = uniqueEmail("a11y-admin");
  await signUp(admin, "Админ", adminEmail);
  await adminSignIn(admin, adminEmail, grantAdmin(adminEmail));
  await admin
    .getByRole("link", { name: /Хүртээмжийн шалгалт/ })
    .first()
    .click();
  const adminDisputeUrl = new URL(admin.url()).pathname;

  const buyerState = JSON.stringify(await buyer.context().storageState());
  const adminState = JSON.stringify(await admin.context().storageState());
  const userPages = [
    "/dashboard",
    "/deals",
    "/deals/new",
    dealPath,
    disputeUrl,
    "/notifications",
    "/profile",
    "/security",
  ];
  const findings = [
    ...(await scanAll(browser, undefined, ["/", "/login", "/register", "/admin/login"], false)),
    ...(await scanAll(browser, buyerState, userPages, false)),
    ...(await scanAll(browser, buyerState, ["/dashboard", dealPath], true)),
    ...(await scanAll(browser, adminState, ["/admin", adminDisputeUrl, "/admin/users"], false)),
  ];
  expect(findings, findings.join("\n")).toEqual([]);
});

test("keyboard: skip link, and the action dialog takes and returns focus", async ({ browser }) => {
  const seller = await newUserPage(browser);
  await signUp(seller, "Гар");
  const { dealUrl } = await createDeal(seller, "Гарын шалгалт", "120,000");
  await seller.goto(dealUrl);

  await seller.keyboard.press("Tab");
  await expect(seller.getByRole("link", { name: "Үндсэн агуулга руу шилжих" })).toBeFocused();

  const cancel = seller.getByRole("button", { name: "Гэрээг цуцлах" });
  await cancel.focus();
  await seller.keyboard.press("Enter");
  const dialog = seller.getByRole("dialog");
  await expect(dialog).toBeVisible();
  expect(await dialog.evaluate((d) => d.contains(document.activeElement))).toBe(true);
  await seller.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(cancel).toBeFocused();
});
