/**
 * What the user needs to know on every deal, derived only from what the API
 * reports (status, my role, the actions the backend allows me right now):
 *   - where the (simulated) money is,
 *   - who has to act next and what they do,
 *   - how far along the deal is.
 * Display logic only: the backend state machine stays authoritative.
 */
import type { DealStatus } from "./deal-status";
import type { Deal, DealAction, DealSummary } from "./types";

/** Actions that move the deal forward on the normal path. */
export const PRIMARY_ACTIONS = ["SUBMIT", "ACCEPT", "FUND", "MARK_DELIVERED", "CONFIRM_RECEIPT"] as const;
/** Ways out when something is wrong: kept visually separate from the primary path. */
export const ISSUE_ACTIONS = ["OPEN_DISPUTE", "REFUND", "DECLINE", "CANCEL"] as const;

export function splitActions(actions: DealAction[]): { primary: DealAction[]; issue: DealAction[] } {
  const primary = actions.filter((a) => (PRIMARY_ACTIONS as readonly string[]).includes(a));
  const issue = ISSUE_ACTIONS.filter((a) => actions.includes(a));
  return { primary, issue };
}

// --- Where the money is -------------------------------------------------------

export type MoneyLocation = "NOT_PAID" | "HELD" | "LOCKED" | "RELEASED" | "REFUNDED" | "NEVER_PAID";

export const MONEY_LOCATION: Record<DealStatus, MoneyLocation> = {
  DRAFT: "NOT_PAID",
  PENDING_ACCEPTANCE: "NOT_PAID",
  AWAITING_PAYMENT: "NOT_PAID",
  FUNDED: "HELD",
  DELIVERED: "HELD",
  DISPUTED: "LOCKED",
  COMPLETED: "RELEASED",
  REFUNDED: "REFUNDED",
  CANCELLED: "NEVER_PAID",
  EXPIRED: "NEVER_PAID",
};

export const MONEY_COPY: Record<MoneyLocation, { title: string; body: string }> = {
  NOT_PAID: {
    title: "Төлбөр хараахан байршаагүй",
    body: "Хоёр тал нөхцөлийг зөвшөөрсний дараа худалдан авагч төлбөрөө SafePay-ийн барьцаанд байршуулна.",
  },
  HELD: {
    title: "SafePay-ийн барьцаанд хадгалагдаж байна",
    body: "Худалдан авагч хүлээн авснаа батлах эсвэл SafePay ажилтан шийдэх хүртэл хэн ч авах боломжгүй.",
  },
  LOCKED: {
    title: "Барьцаанд түгжигдсэн (маргаан)",
    body: "SafePay ажилтан шийдвэр гаргах хүртэл мөнгө хөдлөхгүй.",
  },
  RELEASED: {
    title: "Худалдагч мөнгөө хүлээн авсан",
    body: "Худалдан авагч баталсан тул барьцааны мөнгө худалдагчийн туршилтын хэтэвчинд орсон.",
  },
  REFUNDED: {
    title: "Худалдан авагч мөнгөө буцааж авсан",
    body: "Барьцааны мөнгө бүтнээрээ худалдан авагчийн туршилтын хэтэвчинд буцсан.",
  },
  NEVER_PAID: {
    title: "Мөнгө хөдлөөгүй",
    body: "Төлбөр байршуулахаас өмнө гэрээ хаагдсан.",
  },
};

// --- Progress -------------------------------------------------------------------

export const FLOW_STEPS = ["Нөхцөл", "Төлбөр", "Хүлээлгэн өгөх", "Шалгах", "Дууссан"] as const;

export type Progress = {
  /** Index into FLOW_STEPS of the current step; FLOW_STEPS.length when all are done. */
  current: number;
  /** The deal left the normal path (dispute, refund, cancel, expiry). */
  halted: null | { label: string; tone: "danger" | "neutral" };
};

export function dealProgress(status: DealStatus): Progress {
  switch (status) {
    case "DRAFT":
    case "PENDING_ACCEPTANCE":
      return { current: 0, halted: null };
    case "AWAITING_PAYMENT":
      return { current: 1, halted: null };
    case "FUNDED":
      return { current: 2, halted: null };
    case "DELIVERED":
      return { current: 3, halted: null };
    case "COMPLETED":
      return { current: FLOW_STEPS.length, halted: null };
    case "DISPUTED":
      return { current: 3, halted: { label: "Маргаан шийдвэрлэж буй", tone: "danger" } };
    case "REFUNDED":
      return { current: 3, halted: { label: "Буцаан олгосон", tone: "neutral" } };
    case "CANCELLED":
      return { current: 1, halted: { label: "Цуцлагдсан", tone: "neutral" } };
    case "EXPIRED":
      return { current: 1, halted: { label: "Хугацаа дууссан", tone: "neutral" } };
  }
}

// --- Who acts next ------------------------------------------------------------------

export type Turn = "me" | "counterparty" | "safepay" | "nobody";

export type NextStep = { turn: Turn; title: string; body: string };

const TERMINAL: DealStatus[] = ["COMPLETED", "REFUNDED", "CANCELLED", "EXPIRED"];

export function nextStep(
  deal: Pick<Deal, "status" | "my_role" | "actions" | "counterparty_name" | "created_by_me">,
): NextStep {
  const { primary } = splitActions(deal.actions);
  const buyer = deal.my_role === "BUYER";
  const joined = Boolean(deal.counterparty_name);

  switch (deal.status) {
    case "DRAFT":
      if (primary.includes("SUBMIT")) {
        return {
          turn: "me",
          title: joined ? "Нөхцөлөө шалгаад илгээнэ үү" : "Нөхцөлөө шалгаад илгээж, нөгөө талыг урина уу",
          body: "Илгээсний дараа нөхцөл түгжигдэж, нөгөө тал зөвшөөрөх эсвэл татгалзана.",
        };
      }
      return joined
        ? {
            turn: "counterparty",
            title: "Нөгөө тал нөхцөлийг илгээхийг хүлээж байна",
            body: "Нөхцөл илгээгдмэгц танд мэдэгдэл ирнэ.",
          }
        : {
            turn: "counterparty",
            title: "Нөгөө тал нэгдэхийг хүлээж байна",
            body: "Урилгын холбоосыг зөвхөн гэрээ хийх хүндээ илгээнэ үү.",
          };
    case "PENDING_ACCEPTANCE":
      if (primary.includes("ACCEPT")) {
        return {
          turn: "me",
          title: "Нөхцөлийг уншаад зөвшөөрнө үү",
          body: "Зөвшөөрсний дараа нөхцөл өөрчлөгдөхгүй. Тохирохгүй бол татгалзаж болно.",
        };
      }
      return {
        turn: "counterparty",
        title: joined ? "Нөгөө талын зөвшөөрлийг хүлээж байна" : "Нөгөө тал нэгдэхийг хүлээж байна",
        body: joined
          ? "Нөгөө тал зөвшөөрмөгц худалдан авагч төлбөрөө байршуулна."
          : "Урилгын холбоосыг зөвхөн гэрээ хийх хүндээ илгээнэ үү.",
      };
    case "AWAITING_PAYMENT":
      return buyer
        ? {
            turn: "me",
            title: "Туршилтын төлбөрөө барьцаанд байршуулна уу",
            body: "Мөнгө SafePay-д хадгалагдаж, та бараагаа хүлээн авч батлах хүртэл худалдагчид очихгүй.",
          }
        : {
            turn: "counterparty",
            title: "Худалдан авагч төлбөр байршуулахыг хүлээж байна",
            body: "Төлбөр барьцаанд орсны дараа л бараагаа хүлээлгэн өгнө үү.",
          };
    case "FUNDED":
      return buyer
        ? {
            turn: "counterparty",
            title: "Худалдагч хүлээлгэн өгөхийг хүлээж байна",
            body: "Таны мөнгө барьцаанд аюулгүй байна. Бараагаа авахаас өмнө юу ч батлах шаардлагагүй.",
          }
        : {
            turn: "me",
            title: "Бараагаа хүлээлгэн өгнө үү",
            body: "Төлбөр барьцаанд орсон. Хүлээлгэн өгсний дараа энд тэмдэглэнэ үү.",
          };
    case "DELIVERED":
      return buyer
        ? {
            turn: "me",
            title: "Бараагаа шалгаад хүлээн авснаа батална уу",
            body: "Батласны дараа мөнгө худалдагчид очно. Асуудалтай бол батлахын оронд маргаан нээнэ үү.",
          }
        : {
            turn: "counterparty",
            title: "Худалдан авагчийн баталгааг хүлээж байна",
            body: "Худалдан авагч хүлээн авснаа батлахад барьцааны мөнгө танд очно.",
          };
    case "DISPUTED":
      return {
        turn: "safepay",
        title: "SafePay ажилтан маргааныг шийдвэрлэж байна",
        body: "Тайлбар, нотлох баримтаа маргааны хуудсанд нэмнэ үү. Шийдвэр гармагц танд мэдэгдэнэ.",
      };
    case "COMPLETED":
      return { turn: "nobody", title: "Гэрээ амжилттай хаагдлаа", body: "Танаас хийх зүйл үлдээгүй." };
    case "REFUNDED":
      return { turn: "nobody", title: "Гэрээ буцаалтаар хаагдлаа", body: "Танаас хийх зүйл үлдээгүй." };
    case "CANCELLED":
      return { turn: "nobody", title: "Гэрээ цуцлагдсан", body: "Шинэ гэрээ үүсгэж дахин эхлүүлж болно." };
    case "EXPIRED":
      return {
        turn: "nobody",
        title: "Гэрээ хугацаа хэтэрч хаагдсан",
        body: "Хугацаандаа хариу өгөөгүй. Шаардлагатай бол шинэ гэрээ үүсгэнэ үү.",
      };
  }
}

export function isTerminal(status: DealStatus): boolean {
  return TERMINAL.includes(status);
}

/**
 * List views only get a summary (no allowed actions), so "my turn" there is
 * the states where only my role can move the deal forward.
 */
export function summaryNeedsMe(d: Pick<DealSummary, "status" | "my_role">): boolean {
  if (d.status === "AWAITING_PAYMENT" || d.status === "DELIVERED") return d.my_role === "BUYER";
  if (d.status === "FUNDED") return d.my_role === "SELLER";
  return false;
}

export const TURN_LABEL: Record<Turn, string> = {
  me: "Таны ээлж",
  counterparty: "Нөгөө талын ээлж",
  safepay: "SafePay шийдэж байна",
  nobody: "Хаагдсан",
};
