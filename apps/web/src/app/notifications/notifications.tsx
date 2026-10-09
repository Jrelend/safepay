"use client";

import Link from "next/link";
import { useState } from "react";

import { AuthGuard } from "@/components/auth-guard";
import { Alert, Button, EmptyState, PageTitle, Skeleton } from "@/components/ui";
import { api } from "@/lib/client/api";
import { useApi } from "@/lib/client/use-api";
import { ACTOR_LABEL, timelineLabel } from "@/lib/deal-actions";
import { formatDateTime } from "@/lib/format";
import type { Notification } from "@/lib/types";

function text(n: Notification): string {
  if (n.kind === "deal.joined") return "Нөгөө тал таны гэрээнд нэгдлээ";
  const who = typeof n.data.actor === "string" ? (ACTOR_LABEL[n.data.actor] ?? "") : "";
  return `${who ? `${who}: ` : ""}${timelineLabel(n.kind, n.data)}`;
}

function List() {
  const { data, error, loading, reload } = useApi<{ unread: number; items: Notification[] }>("/me/notifications");
  const [busy, setBusy] = useState(false);
  return (
    <div className="space-y-4">
      <PageTitle title="Мэдэгдэл" subtitle={data ? `${data.unread} уншаагүй` : undefined} />
      {data && data.unread > 0 ? (
        <Button
          variant="secondary"
          loading={busy}
          className="w-full"
          onClick={async () => {
            setBusy(true);
            try {
              await api("/me/notifications/read-all", { json: {} });
              await reload();
            } finally {
              setBusy(false);
            }
          }}
        >
          Бүгдийг уншсан болгох
        </Button>
      ) : null}
      {loading && !data ? <Skeleton /> : null}
      {error ? <Alert tone="danger">{error.message}</Alert> : null}
      {data && data.items.length === 0 ? <EmptyState title="Мэдэгдэл алга" /> : null}
      <ul className="space-y-2">
        {data?.items.map((n) => (
          <li key={n.id}>
            <Link
              href={n.deal_id ? `/deals/${n.deal_id}` : "/dashboard"}
              className={`bg-surface block rounded-2xl border p-4 ${n.read ? "border-border" : "border-brand"}`}
            >
              <div className="flex items-start justify-between gap-2">
                <div className="text-sm font-medium">{text(n)}</div>
                {!n.read ? <span className="bg-brand mt-1 size-2 shrink-0 rounded-full" aria-label="Уншаагүй" /> : null}
              </div>
              <div className="text-muted mt-1 text-xs">
                {typeof n.data.title === "string" ? `${n.data.title} · ` : ""}
                {formatDateTime(n.created_at)}
              </div>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function Notifications() {
  return <AuthGuard>{() => <List />}</AuthGuard>;
}
