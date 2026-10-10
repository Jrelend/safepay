import type { Metadata } from "next";

import { AdminAudit } from "./admin-audit";

export const metadata: Metadata = { title: "Аудит" };

export default function AdminAuditPage() {
  return <AdminAudit />;
}
