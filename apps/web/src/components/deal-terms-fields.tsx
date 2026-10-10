"use client";

import { useState } from "react";

import { Field, Select, TextArea } from "@/components/ui";
import { DELIVERY_FOR_ITEM, DELIVERY_LABEL, ITEM_TYPE_LABEL } from "@/lib/format";
import type { DeliveryMethod, ItemType } from "@/lib/types";

export type TermsDefaults = {
  title?: string;
  description?: string;
  amount_mnt?: string;
  item_type?: ItemType;
  delivery_method?: DeliveryMethod;
  inspection_days?: number;
};

export const MIN_AMOUNT = 100;
export const MAX_AMOUNT = 100_000_000_000;

/** Parses "1,250,000" / "1 250 000" into an integer amount, or null if invalid. */
export function parseAmountInput(raw: string): number | null {
  const digits = raw.replace(/[\s,.'₮]/g, "");
  if (!/^\d{1,12}$/.test(digits)) return null;
  const n = Number(digits);
  return n >= MIN_AMOUNT && n <= MAX_AMOUNT ? n : null;
}

export function DealTermsFields({ defaults = {}, errors = {} }: { defaults?: TermsDefaults; errors?: Record<string, string> }) {
  const [itemType, setItemType] = useState<ItemType>(defaults.item_type ?? "PHYSICAL_GOODS");
  const allowed = DELIVERY_FOR_ITEM[itemType];
  const [delivery, setDelivery] = useState<DeliveryMethod>(
    defaults.delivery_method && allowed.includes(defaults.delivery_method) ? defaults.delivery_method : allowed[0],
  );
  const deliveryValue = allowed.includes(delivery) ? delivery : allowed[0];

  return (
    <>
      <Field
        label="Юу худалдаж байна вэ?"
        name="title"
        required
        minLength={3}
        maxLength={200}
        defaultValue={defaults.title}
        placeholder="Жишээ: iPhone 13, 128GB"
        error={errors.title}
      />
      <TextArea
        label="Дэлгэрэнгүй тайлбар"
        name="description"
        maxLength={5000}
        defaultValue={defaults.description}
        hint="Барааны байдал, иж бүрдэл, баталгаа зэргийг тодорхой бичвэл маргаан гарах эрсдэл буурна."
      />
      <Field
        label="Үнэ (₮)"
        name="amount_mnt"
        required
        inputMode="numeric"
        autoComplete="off"
        defaultValue={defaults.amount_mnt}
        placeholder="1,250,000"
        hint="Бүхэл төгрөгөөр. 100 ₮-өөс 100 тэрбум ₮ хүртэл."
        error={errors.amount_mnt}
      />
      <Select
        label="Төрөл"
        name="item_type"
        value={itemType}
        onChange={(e) => setItemType(e.target.value as ItemType)}
        options={(Object.keys(ITEM_TYPE_LABEL) as ItemType[]).map((v) => ({ value: v, label: ITEM_TYPE_LABEL[v] }))}
      />
      <Select
        label="Хүлээлгэн өгөх арга"
        name="delivery_method"
        value={deliveryValue}
        onChange={(e) => setDelivery(e.target.value as DeliveryMethod)}
        options={allowed.map((v) => ({ value: v, label: DELIVERY_LABEL[v] }))}
      />
      <Field
        label="Шалгах хугацаа (хоног)"
        name="inspection_days"
        type="number"
        min={1}
        max={14}
        required
        defaultValue={defaults.inspection_days ?? 3}
        hint="Хүлээн авснаас хойш худалдан авагч барааг шалгах хугацаа. Мөнгө зөвхөн худалдан авагч баталсан эсвэл SafePay ажилтан шийдвэрлэсний дараа шилжинэ — хугацаа дуусахад автоматаар шилжихгүй."
      />
    </>
  );
}

export function readTerms(form: FormData): { terms: Record<string, unknown>; errors: Record<string, string> } {
  const errors: Record<string, string> = {};
  const amount = parseAmountInput(String(form.get("amount_mnt") ?? ""));
  if (amount === null) errors.amount_mnt = "Дүнг 100-аас 100,000,000,000 ₮ хооронд бүхэл тоогоор оруулна уу.";
  const title = String(form.get("title") ?? "").trim();
  if (title.length < 3) errors.title = "Дор хаяж 3 тэмдэгт.";
  return {
    terms: {
      title,
      description: String(form.get("description") ?? "").trim(),
      amount_mnt: amount,
      item_type: form.get("item_type"),
      delivery_method: form.get("delivery_method"),
      inspection_days: Number(form.get("inspection_days")),
    },
    errors,
  };
}
