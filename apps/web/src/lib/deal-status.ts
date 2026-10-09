/**
 * Display metadata for deal states. The authoritative state machine lives in
 * the backend (apps/api/app/domain/deal_states.py); the frontend only renders
 * whatever state the API reports. A unit test keeps this list in sync.
 */

export const DEAL_STATUSES = [
  "DRAFT",
  "PENDING_ACCEPTANCE",
  "AWAITING_PAYMENT",
  "FUNDED",
  "DELIVERED",
  "COMPLETED",
  "DISPUTED",
  "REFUNDED",
  "CANCELLED",
  "EXPIRED",
] as const;

export type DealStatus = (typeof DEAL_STATUSES)[number];

export type StatusTone = "neutral" | "info" | "warning" | "success" | "danger";

export const DEAL_STATUS_META: Record<
  DealStatus,
  { label: string; description: string; tone: StatusTone }
> = {
  DRAFT: {
    label: "Ноорог",
    description: "Гэрээний нөхцөлийг бэлтгэж байна.",
    tone: "neutral",
  },
  PENDING_ACCEPTANCE: {
    label: "Зөвшөөрөл хүлээж буй",
    description: "Нөгөө тал нөхцөлийг зөвшөөрөхийг хүлээж байна.",
    tone: "info",
  },
  AWAITING_PAYMENT: {
    label: "Төлбөр хүлээж буй",
    description: "Худалдан авагч (симуляцийн) төлбөрөө байршуулах ёстой.",
    tone: "info",
  },
  FUNDED: {
    label: "Барьцаанд байршсан",
    description: "Симуляцийн мөнгө SafePay-ийн барьцаанд хадгалагдаж байна.",
    tone: "warning",
  },
  DELIVERED: {
    label: "Хүргэгдсэн",
    description: "Худалдагч бараагаа хүргэсэн гэж мэдэгдсэн.",
    tone: "warning",
  },
  COMPLETED: {
    label: "Амжилттай дууссан",
    description: "Худалдан авагч хүлээн авснаа баталж, мөнгийг худалдагчид шилжүүлсэн.",
    tone: "success",
  },
  DISPUTED: {
    label: "Маргаантай",
    description: "Маргааныг SafePay-ийн ажилтан шийдвэрлэж байна.",
    tone: "danger",
  },
  REFUNDED: {
    label: "Буцаан олгосон",
    description: "Симуляцийн мөнгийг худалдан авагчид буцаасан.",
    tone: "neutral",
  },
  CANCELLED: {
    label: "Цуцлагдсан",
    description: "Төлбөр байршуулахаас өмнө гэрээ цуцлагдсан.",
    tone: "neutral",
  },
  EXPIRED: {
    label: "Хугацаа дууссан",
    description: "Хугацаандаа хариу өгөөгүй тул гэрээ хаагдсан.",
    tone: "neutral",
  },
};
