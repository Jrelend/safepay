import { expect, test } from "@playwright/test";

import { act, createDeal, newUserPage, resetRateLimits, shot, signUp } from "./helpers";

test.beforeEach(() => resetRateLimits());

test("seller and buyer complete a simulated escrow deal", async ({ browser }) => {
  const seller = await newUserPage(browser);
  const buyer = await newUserPage(browser);

  await signUp(seller, "Болд");
  await shot(seller, "03-dashboard-empty");
  const { dealUrl, invite } = await createDeal(seller, "iPhone 13, 128GB", "1,250,000");
  await expect(seller.getByText("1,250,000 ₮").first()).toBeVisible();
  await expect(seller.getByTestId("test-payment-notice").first()).toHaveText(/ТУРШИЛТЫН ТӨЛБӨР — БОДИТ МӨНГӨ БИШ/);
  await shot(seller, "05-deal-created");

  await signUp(buyer, "Сараа");
  await buyer.goto(invite);
  await expect(buyer.getByText("Болд таныг гэрээнд урьж байна.")).toBeVisible();
  await expect(buyer.getByText("Худалдан авагч")).toBeVisible();
  await shot(buyer, "06-invite");
  await buyer.getByRole("button", { name: "Гэрээнд нэгдэх" }).click();
  await expect(buyer).toHaveURL(dealUrl);

  await seller.goto(dealUrl);
  await act(seller, "Нөхцөлийг батлаад илгээх");
  await expect(seller.getByText("Зөвшөөрөл хүлээж буй").first()).toBeVisible();

  await buyer.reload();
  await act(buyer, "Нөхцөлийг зөвшөөрөх");
  await expect(buyer.getByText("Төлбөр хүлээж буй").first()).toBeVisible();

  // Funding: the dialog must carry the test-payment notice.
  await buyer.getByRole("button", { name: "Төлбөр байршуулах" }).click();
  const dialog = buyer.getByRole("dialog");
  await expect(dialog.getByTestId("test-payment-notice")).toContainText("ТУРШИЛТЫН ТӨЛБӨР — БОДИТ МӨНГӨ БИШ");
  await expect(dialog.getByText("1,250,000 ₮")).toBeVisible();
  await shot(buyer, "07-fund-dialog");
  await dialog.getByRole("button", { name: "Батлах" }).click();
  await expect(buyer.getByText("Барьцаанд байршсан").first()).toBeVisible();

  await seller.reload();
  await act(seller, "Хүлээлгэн өгсөн гэж тэмдэглэх");

  await buyer.reload();
  await expect(buyer.getByText(/Шалгах хугацаа .* дуусна/)).toBeVisible();
  await act(buyer, "Хүлээн авснаа батлах");
  await expect(buyer.getByText("Амжилттай дууссан").first()).toBeVisible();
  await expect(buyer.getByText("Худалдагчид шилжсэн")).toBeVisible();
  await shot(buyer, "08-deal-completed");

  await seller.goto("/dashboard");
  await expect(seller.getByText("1,250,000 ₮")).toBeVisible();
  await shot(seller, "09-dashboard-balance");

  await seller.goto("/notifications");
  await expect(seller.getByText("Худалдан авагч: Хүлээн авснаа баталсан")).toBeVisible();
  await shot(seller, "10-notifications");
});

test("double-clicking a money action executes it once", async ({ browser }) => {
  const seller = await newUserPage(browser);
  const buyer = await newUserPage(browser);
  await signUp(seller, "Ганаа");
  const { dealUrl, invite } = await createDeal(seller, "Хуучин ноутбук", "800000");
  await signUp(buyer, "Тэмүүлэн");
  await buyer.goto(invite);
  await buyer.getByRole("button", { name: "Гэрээнд нэгдэх" }).click();
  await expect(buyer).toHaveURL(dealUrl);
  await seller.goto(dealUrl);
  await act(seller, "Нөхцөлийг батлаад илгээх");
  await buyer.reload();
  await act(buyer, "Нөхцөлийг зөвшөөрөх");

  await buyer.getByRole("button", { name: "Төлбөр байршуулах" }).click();
  await buyer.getByRole("dialog").getByRole("button", { name: "Батлах" }).dblclick();
  await expect(buyer.getByText("Барьцаанд байршсан").first()).toBeVisible();
  await expect(buyer.getByText(/^Барьцаанд байршсан ·/)).toHaveCount(1);
});
