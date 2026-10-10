/** Shapes returned by the SafePay API. Money is always an integer string (MNT). */
import type { DealStatus } from "./deal-status";

export type Role = "BUYER" | "SELLER";
export type ItemType = "PHYSICAL_GOODS" | "DIGITAL_GOODS" | "SERVICE";
export type DeliveryMethod = "FACE_TO_FACE" | "COURIER" | "DIGITAL";
export type DealAction =
  | "SUBMIT"
  | "ACCEPT"
  | "DECLINE"
  | "CANCEL"
  | "FUND"
  | "MARK_DELIVERED"
  | "CONFIRM_RECEIPT"
  | "REFUND"
  | "OPEN_DISPUTE";

export type Me = {
  id: string;
  email: string;
  display_name: string;
  phone_e164: string | null;
  email_verified: boolean;
  is_admin: boolean;
  created_at: string;
};

export type Deal = {
  id: string;
  reference: string;
  title: string;
  description: string;
  amount_mnt: string;
  currency: string;
  status: DealStatus;
  version: number;
  item_type: ItemType;
  delivery_method: DeliveryMethod;
  inspection_days: number;
  my_role: Role;
  created_by_me: boolean;
  counterparty_name: string | null;
  counterparty_phone: string | null;
  my_accepted: boolean;
  counterparty_accepted: boolean;
  dispute_id: string | null;
  actions: DealAction[];
  inspection_ends_at: string | null;
  /** Set only if the platform enables automatic release (never in Beta v0.1). */
  auto_release_at: string | null;
  status_changed_at: string;
  created_at: string;
};

export type DealSummary = {
  id: string;
  reference: string;
  title: string;
  amount_mnt: string;
  status: DealStatus;
  my_role: Role;
  updated_at: string;
};

export type TimelineEvent = {
  action: string;
  actor: string;
  occurred_at: string;
  data: Record<string, unknown>;
};

export type Posting = { kind: string; amount_mnt: string; created_at: string };

export type Wallet = {
  simulated: true;
  balance_mnt: string;
  entries: { kind: string; direction: string; amount_mnt: string; deal_id: string | null; created_at: string }[];
};

export type Notification = {
  id: string;
  kind: string;
  deal_id: string | null;
  data: Record<string, unknown>;
  created_at: string;
  read: boolean;
};

export type Evidence = {
  id: string;
  kind: "STATEMENT" | "FILE" | "ADMIN_NOTE";
  mine: boolean;
  author_role: string;
  body: string;
  file_name: string | null;
  content_type: string | null;
  file_size: number | null;
  created_at: string;
};

export type Dispute = {
  id: string;
  deal_id: string;
  deal_reference: string;
  deal_title: string;
  status: "OPEN" | "RESOLVED";
  reason: string;
  opened_by_me: boolean;
  opened_at: string;
  resolved_at: string | null;
  outcome: "RELEASE_TO_SELLER" | "REFUND_TO_BUYER" | null;
  decision_reason: string | null;
  evidence: Evidence[];
};

export type SessionInfo = {
  id: string;
  created_at: string;
  last_seen_at: string;
  expires_at: string;
  user_agent: string;
  ip_address: string;
  current: boolean;
};

export type InvitePreview = {
  reference: string;
  title: string;
  description: string;
  amount_mnt: string;
  item_type: ItemType;
  delivery_method: DeliveryMethod;
  inspection_days: number;
  creator_name: string;
  offered_role: Role;
};

export type AdminOverview = {
  open_disputes: number;
  users: number;
  suspended_users: number;
  deals_by_status: Record<string, number>;
};

export type AdminDisputeSummary = {
  id: string;
  deal_id: string;
  deal_reference: string;
  deal_title: string;
  amount_mnt: string;
  status: "OPEN" | "RESOLVED";
  opened_at: string;
};

export type AdminDispute = AdminDisputeSummary & {
  reason: string;
  opened_by_role: string;
  deal_status: DealStatus;
  resolved_at: string | null;
  outcome: Dispute["outcome"];
  decision_reason: string | null;
  participants: { user_id: string; role: string; display_name: string; email: string; status: string }[];
  evidence: Evidence[];
  timeline: TimelineEvent[];
};

export type AdminUser = {
  id: string;
  email: string;
  display_name: string;
  status: "ACTIVE" | "SUSPENDED";
  email_verified: boolean;
  is_admin: boolean;
  created_at: string;
};

export type AuditEntry = {
  id: string;
  occurred_at: string;
  actor_type: string;
  actor_user_id: string | null;
  action: string;
  entity_type: string;
  entity_id: string;
  deal_id: string | null;
  data: Record<string, unknown>;
};
