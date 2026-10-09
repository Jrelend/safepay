"use client";

import { AdminGuard } from "@/components/admin-guard";
import { Alert, PageTitle, Skeleton } from "@/components/ui";
import { useApi } from "@/lib/client/use-api";
import { formatDateTime } from "@/lib/format";
import type { AuditEntry } from "@/lib/types";

function Content() {
  const { data, error, loading } = useApi<AuditEntry[]>("/admin/audit?limit=200");
  return (
    <div className="space-y-4">
      <PageTitle title="Аудитын бүртгэл" subtitle="Өөрчлөгдөшгүй. Сүүлийн 200 үйлдэл." />
      {loading && !data ? <Skeleton /> : null}
      {error ? <Alert tone="danger">{error.message}</Alert> : null}
      <ol className="space-y-2">
        {data?.map((a) => (
          <li key={a.id} className="bg-surface border-border rounded-xl border p-3 text-xs">
            <div className="flex justify-between gap-2">
              <span className="font-mono font-medium">{a.action}</span>
              <span className="text-muted">{formatDateTime(a.occurred_at)}</span>
            </div>
            <div className="text-muted mt-1 break-all">
              {a.actor_type}
              {a.actor_user_id ? ` ${a.actor_user_id.slice(0, 8)}` : ""} → {a.entity_type} {a.entity_id.slice(0, 8)}
              {typeof a.data.action === "string" ? ` · ${a.data.action}` : ""}
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}

export function AdminAudit() {
  return (
    <AdminGuard>
      <Content />
    </AdminGuard>
  );
}
