import type { DealAction } from "./types";

export type ActionMeta = {
  label: string;
  /** Shown in the confirmation dialog. */
  confirm: string;
  variant: "primary" | "secondary" | "danger";
  /** Moves simulated money: shown with the test-payment notice. */
  money?: boolean;
  /** A note is mandatory (sent as the reason). */
  needsNote?: boolean;
  /** A note may be given. */
  allowsNote?: boolean;
};

export const PUBLIC_ACTIONS = [
  "SUBMIT",
  "ACCEPT",
  "DECLINE",
  "CANCEL",
  "FUND",
  "MARK_DELIVERED",
  "CONFIRM_RECEIPT",
  "REFUND",
  "OPEN_DISPUTE",
] as const satisfies readonly DealAction[];

export const ACTION_META: Record<DealAction, ActionMeta> = {
  SUBMIT: {
    label: "Нөхцөлийг батлаад илгээх",
    confirm: "Илгээсний дараа нөхцөлийг засах боломжгүй. Нөгөө тал зөвшөөрөх эсвэл татгалзана.",
    variant: "primary",
  },
  ACCEPT: {
    label: "Нөхцөлийг зөвшөөрөх",
    confirm: "Хоёр тал зөвшөөрсний дараа нөхцөл өөрчлөгдөхгүй. Үргэлжлүүлэх үү?",
    variant: "primary",
  },
  DECLINE: {
    label: "Татгалзах",
    confirm: "Гэрээ цуцлагдана. Шалтгаанаа бичиж болно.",
    variant: "danger",
    allowsNote: true,
  },
  CANCEL: {
    label: "Гэрээг цуцлах",
    confirm: "Гэрээ цуцлагдана. Энэ үйлдлийг буцаах боломжгүй.",
    variant: "danger",
    allowsNote: true,
  },
  FUND: {
    label: "Төлбөр байршуулах",
    confirm: "Гэрээний дүнг SafePay-ийн барьцаанд (симуляц) байршуулна. Бодит мөнгө шилжихгүй.",
    variant: "primary",
    money: true,
  },
  MARK_DELIVERED: {
    label: "Хүлээлгэн өгсөн гэж тэмдэглэх",
    confirm: "Худалдан авагч барааг шалгаж, хүлээн авснаа батлахад мөнгө танд шилжинэ. Худалдан авагч хариу өгөхгүй бол маргаан нээж SafePay ажилтнаар шийдвэрлүүлнэ.",
    variant: "primary",
  },
  CONFIRM_RECEIPT: {
    label: "Хүлээн авснаа батлах",
    confirm: "Барьцаанд буй (симуляцийн) мөнгө худалдагчид шилжинэ. Энэ үйлдлийг буцаах боломжгүй.",
    variant: "primary",
    money: true,
  },
  REFUND: {
    label: "Мөнгийг буцаан олгох",
    confirm: "Барьцаанд буй (симуляцийн) мөнгийг худалдан авагчид бүтнээр нь буцаана. Энэ үйлдлийг буцаах боломжгүй.",
    variant: "secondary",
    money: true,
    allowsNote: true,
  },
  OPEN_DISPUTE: {
    label: "Маргаан нээх",
    confirm: "Мөнгө барьцаанд хэвээр үлдэж, SafePay-ийн ажилтан хоёр талын нотлох баримтыг үзэж шийднэ.",
    variant: "danger",
    needsNote: true,
  },
};

const TIMELINE: Record<string, string> = {
  "deal.created": "Гэрээ үүсгэсэн",
  "deal.joined": "Нөгөө тал нэгдсэн",
  "deal.terms_updated": "Нөхцөл зассан",
  "deal.invite_regenerated": "Урилгын холбоос шинэчилсэн",
  SUBMIT: "Нөхцөлийг илгээсэн",
  ACCEPT: "Нөхцөлийг зөвшөөрсөн",
  DECLINE: "Татгалзсан",
  CANCEL: "Цуцалсан",
  EXPIRE: "Хугацаа дууссан",
  FUND: "Төлбөр барьцаанд байршсан (туршилт)",
  MARK_DELIVERED: "Хүлээлгэн өгсөн",
  CONFIRM_RECEIPT: "Хүлээн авснаа баталсан",
  AUTO_RELEASE: "Шалгах хугацаа дуусч, мөнгө автоматаар шилжсэн",
  OPEN_DISPUTE: "Маргаан нээсэн",
  REFUND: "Буцаан олгосон",
  RESOLVE_RELEASE: "Маргааныг шийдэж, худалдагчид шилжүүлсэн",
  RESOLVE_REFUND: "Маргааныг шийдэж, худалдан авагчид буцаасан",
};

export function timelineLabel(eventAction: string, data: Record<string, unknown>): string {
  const transition = typeof data.action === "string" ? data.action : null;
  return TIMELINE[transition ?? eventAction] ?? eventAction;
}

export const ACTOR_LABEL: Record<string, string> = {
  BUYER: "Худалдан авагч",
  SELLER: "Худалдагч",
  SYSTEM: "Систем",
  ADMIN: "SafePay ажилтан",
  USER: "Хэрэглэгч",
};
