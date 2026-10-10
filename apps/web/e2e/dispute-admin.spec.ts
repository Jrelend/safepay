import { expect, test } from "@playwright/test";

import {
  act,
  adminSignIn,
  createDeal,
  grantAdmin,
  newUserPage,
  resetRateLimits,
  shot,
  signUp,
  uniqueEmail,
} from "./helpers";

test.beforeEach(() => resetRateLimits());

const PNG = Buffer.from(
  "89504e470d0a1a0a0000000d4948445200000001000000010806000000" +
    "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082",
  "hex",
);

test("buyer disputes, admin refunds, everyone sees the outcome", async ({ browser }) => {
  const seller = await newUserPage(browser);
  const buyer = await newUserPage(browser);
  const admin = await newUserPage(browser);

  await signUp(seller, "Батаа");
  const { dealUrl, invite } = await createDeal(seller, "Samsung TV 55\"", "2,400,000");
  await signUp(buyer, "Номин");
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
  await act(buyer, "Маргаан нээх", "Дэлгэц нь хагарсан ирсэн.");
  await expect(buyer.getByText("Маргаантай").first()).toBeVisible();
  await buyer.getByRole("link", { name: "Маргааны дэлгэрэнгүй" }).click();
  await expect(buyer).toHaveURL(/\/disputes\//);
  const disputeUrl = new URL(buyer.url()).pathname;
  await buyer.getByLabel("Тайлбар нэмэх").fill("Хүргэлтээс авахад хайрцаг нь бүрэн байсан.");
  await buyer.getByRole("button", { name: "Илгээх" }).click();
  await expect(buyer.getByText("Хүргэлтээс авахад хайрцаг нь бүрэн байсан.")).toBeVisible();
  await buyer.getByLabel(/Файл хавсаргах/).setInputFiles({ name: "tv.png", mimeType: "image/png", buffer: PNG });
  await buyer.getByRole("button", { name: "Хавсаргах", exact: true }).click();
  await expect(buyer.getByText("tv.png")).toBeVisible();
  await shot(buyer, "11-dispute");

  // A stranger can see neither the deal nor the dispute.
  const stranger = await newUserPage(browser);
  await signUp(stranger, "Гадны хүн");
  await stranger.goto(dealUrl);
  await expect(stranger.getByText("Олдсонгүй эсвэл танд үзэх эрх байхгүй.")).toBeVisible();
  await stranger.goto(disputeUrl);
  await expect(stranger.getByText("Олдсонгүй эсвэл танд үзэх эрх байхгүй.")).toBeVisible();
  await stranger.goto("/admin");
  await expect(stranger).toHaveURL(/\/admin\/login/);
  expect((await stranger.request.get("/api/admin/overview")).status()).toBe(401);

  // Admin decides on the separate admin API.
  const adminEmail = uniqueEmail("admin");
  await signUp(admin, "Админ", adminEmail);
  const secret = grantAdmin(adminEmail);
  // The user's normal session is NOT an admin session: /admin asks for admin sign-in.
  await admin.goto("/admin");
  await expect(admin).toHaveURL(/\/admin\/login/);
  await shot(admin, "14-admin-login");
  await adminSignIn(admin, adminEmail, secret);
  await admin.getByRole("link", { name: /Samsung TV/ }).first().click();
  await expect(admin.getByText("tv.png")).toBeVisible();
  await admin.getByLabel(/Дотоод тэмдэглэл/).fill("Зураг хагарлыг харуулж байна.");
  await admin.getByRole("button", { name: "Тэмдэглэл нэмэх" }).click();
  await expect(admin.getByText("Зураг хагарлыг харуулж байна.")).toBeVisible();
  await admin.getByRole("button", { name: "Худалдан авагчид буцаах" }).click();
  await admin.getByLabel(/Шийдвэрийн үндэслэл/).fill("Барааны гэмтлийг зургаар нотолсон тул буцаан олгоно.");
  await shot(admin, "12-admin-decision");
  await admin.getByRole("button", { name: "Шийдвэрийг батлах" }).click();
  await expect(admin.getByText("Шийдвэрлэсэн: Худалдан авагчид буцаах")).toBeVisible();

  await buyer.goto(disputeUrl);
  await expect(buyer.getByText("Шийдвэр: Мөнгийг худалдан авагчид буцаасан")).toBeVisible();
  // Internal admin notes never reach participants.
  await expect(buyer.getByText("Зураг хагарлыг харуулж байна.")).toHaveCount(0);
  await buyer.goto("/dashboard");
  await expect(buyer.getByText("2,400,000 ₮")).toBeVisible();

  await admin.goto("/admin/audit");
  await expect(admin.getByText("RESOLVE_REFUND").first()).toBeVisible();
});
