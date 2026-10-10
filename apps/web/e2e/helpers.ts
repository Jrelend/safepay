import { execFileSync } from "node:child_process";
import { createHmac } from "node:crypto";
import { mkdirSync } from "node:fs";
import { resolve } from "node:path";

import { expect, type Browser, type Page } from "@playwright/test";

export const PASSWORD = "Correct-Horse-Battery-9";
const API_DIR = resolve(__dirname, "../../api");
const SHOTS = process.env.E2E_SCREENSHOT_DIR;

export function uniqueEmail(prefix: string): string {
  return `${prefix}-${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}@example.com`;
}

export async function shot(page: Page, name: string): Promise<void> {
  if (!SHOTS) return;
  mkdirSync(SHOTS, { recursive: true });
  await page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: true });
}

/** The newest simulated email link for `email`, as a same-origin path. */
export async function mailLink(page: Page, email: string, template: string): Promise<string> {
  const res = await page.request.get(`/api/dev/mailbox?email=${encodeURIComponent(email)}`);
  expect(res.ok()).toBeTruthy();
  const mails = (await res.json()) as { template: string; data: { link?: string } }[];
  const mail = mails.find((m) => m.template === template);
  expect(mail?.data.link, `no ${template} email for ${email}`).toBeTruthy();
  const url = new URL(mail!.data.link!);
  return `${url.pathname}${url.search}`;
}

/** Register through the UI, verify via the simulated mailbox, and sign in. */
export async function signUp(page: Page, name: string, email = uniqueEmail("user")): Promise<string> {
  await page.goto("/register");
  await page.getByLabel("Таны нэр").fill(name);
  await page.getByLabel("Имэйл").fill(email);
  await page.getByLabel("Нууц үг", { exact: true }).fill(PASSWORD);
  await page.getByLabel("Нууц үг давтах").fill(PASSWORD);
  await page.getByRole("button", { name: "Бүртгүүлэх" }).click();
  await expect(page.getByText("Бүртгэлийн хүсэлт хүлээн авлаа")).toBeVisible();

  await page.goto(await mailLink(page, email, "verify_email"));
  await page.getByRole("button", { name: "Баталгаажуулах" }).click();
  await expect(page.getByText("Таны имэйл хаяг баталгаажлаа.")).toBeVisible();

  await page.goto("/login");
  await page.getByLabel("Имэйл").fill(email);
  await page.getByLabel("Нууц үг").fill(PASSWORD);
  await page.getByRole("button", { name: "Нэвтрэх" }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  return email;
}

export async function newUserPage(browser: Browser): Promise<Page> {
  const context = await browser.newContext();
  return context.newPage();
}

/**
 * Test-only: clear rate-limit windows in the disposable E2E database (via the
 * bootstrap superuser, never through the app). Every test user signs up from
 * 127.0.0.1, which would otherwise exhaust the real per-IP limits.
 */
export function resetRateLimits(): void {
  execFileSync("psql", ["-d", process.env.E2E_DB ?? "safepay_e2e", "-qc", "DELETE FROM rate_limits"], {
    env: process.env,
    stdio: "pipe",
  });
}

export const ADMIN_PASSWORD = "Separate-Admin-Secret-77";

/** Grant admin via the real owner CLI; returns the TOTP secret it prints once. */
export function grantAdmin(email: string): string {
  const out = execFileSync(
    "uv",
    ["run", "python", "-m", "app.cli", "grant-admin", email, "--password-stdin"],
    { cwd: API_DIR, env: process.env, input: `${ADMIN_PASSWORD}\n`, encoding: "utf8" },
  );
  const secret = /TOTP secret: ([A-Z2-7]+)/.exec(out)?.[1];
  if (!secret) throw new Error(`no TOTP secret in CLI output: ${out}`);
  return secret;
}

function base32(secret: string): Buffer {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  let bits = "";
  for (const ch of secret.replace(/=+$/, "")) bits += alphabet.indexOf(ch).toString(2).padStart(5, "0");
  const bytes = [];
  for (let i = 0; i + 8 <= bits.length; i += 8) bytes.push(parseInt(bits.slice(i, i + 8), 2));
  return Buffer.from(bytes);
}

/** RFC 6238 TOTP (SHA-1, 6 digits, 30 s) — what an authenticator app shows. */
export function totp(secret: string, offsetSteps = 0): string {
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(Math.floor(Date.now() / 30_000) + offsetSteps));
  const digest = createHmac("sha1", base32(secret)).update(counter).digest();
  const offset = digest[digest.length - 1] & 0x0f;
  const value = digest.readUInt32BE(offset) & 0x7fffffff;
  return String(value % 1_000_000).padStart(6, "0");
}

/** Sign in to the ADMIN area (separate admin password + one-time code). */
export async function adminSignIn(page: Page, email: string, secret: string): Promise<void> {
  await page.goto("/admin/login");
  await page.getByLabel("Имэйл").fill(email);
  await page.getByLabel("Админ нууц үг").fill(ADMIN_PASSWORD);
  await page.getByLabel("Баталгаажуулах код").fill(totp(secret));
  await page.getByRole("button", { name: "Нэвтрэх" }).click();
  await expect(page.getByText("Админ самбар")).toBeVisible();
}

export async function createDeal(page: Page, title: string, amount: string): Promise<{ dealUrl: string; invite: string }> {
  await page.goto("/deals/new");
  await page.getByLabel("Юу худалдаж байна вэ?").fill(title);
  await page.getByLabel("Дэлгэрэнгүй тайлбар").fill("Цэвэрхэн, баталгаатай. Хайрцаг, цэнэглэгчтэй.");
  await page.getByLabel("Үнэ (₮)").fill(amount);
  await page.getByRole("button", { name: "Гэрээ үүсгэх" }).click();
  await expect(page).toHaveURL(/\/deals\/[0-9a-f-]{36}\?created=1$/);
  // The link issued at creation is shown straight away (no extra click).
  const invite = await page.getByLabel("Урилгын холбоос").inputValue();
  expect(invite).toMatch(/\/invite\/[A-Za-z0-9_-]{20,}$/);
  return { dealUrl: page.url().replace("?created=1", ""), invite: new URL(invite).pathname };
}

/** Click an action button and confirm it in the dialog. */
export async function act(page: Page, label: string, note?: string): Promise<void> {
  await page.getByRole("button", { name: label }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  if (note) await dialog.getByRole("textbox").fill(note);
  await dialog.getByRole("button", { name: "Батлах" }).click();
  await expect(dialog).toBeHidden();
  await expect(page.getByText(`${label}: амжилттай.`)).toBeVisible();
}
