import type { DeliveryMethod, ItemType, Role } from "./types";

export const ROLE_LABEL: Record<Role, string> = { BUYER: "Худалдан авагч", SELLER: "Худалдагч" };

export const ITEM_TYPE_LABEL: Record<ItemType, string> = {
  PHYSICAL_GOODS: "Биет бараа",
  DIGITAL_GOODS: "Цахим бараа",
  SERVICE: "Үйлчилгээ",
};

export const DELIVERY_LABEL: Record<DeliveryMethod, string> = {
  FACE_TO_FACE: "Биечлэн уулзаж хүлээлгэн өгөх",
  COURIER: "Хүргэлтээр",
  DIGITAL: "Цахимаар",
};

/** Delivery options allowed for each item type (mirrors the backend's check_terms). */
export const DELIVERY_FOR_ITEM: Record<ItemType, DeliveryMethod[]> = {
  PHYSICAL_GOODS: ["FACE_TO_FACE", "COURIER"],
  DIGITAL_GOODS: ["DIGITAL"],
  SERVICE: ["FACE_TO_FACE", "COURIER", "DIGITAL"],
};

const DATE = new Intl.DateTimeFormat("mn-MN", {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
  timeZone: "Asia/Ulaanbaatar",
});

export function formatDateTime(iso: string): string {
  return DATE.format(new Date(iso));
}
