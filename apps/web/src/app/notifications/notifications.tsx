"use client";

import Link from "next/link";
import { useState } from "react";

import { AuthGuard } from "@/components/auth-guard";
import { Icon } from "@/components/icons";
import { Alert, Button, EmptyState, PageTitle, Skeleton, WIDTH } from "@/components/ui";
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
    <div className={`${WIDTH.form} space-y-4`}>
      <PageTitle
        title="Мэдэгдэл"
        subtitle={data ? (data.unread > 0 ? `${data.unread} уншаагүй` : "Бүгдийг уншсан") : undefined}
      />
      {data && data.unread > 0 ? (
        <Button
          variant="secondary"
          size="sm"
          loading={busy}
          className="w-full sm:w-auto"
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
      {data && data.items.length === 0 ? (
        <EmptyState
          icon="bell"
          title="Мэдэгдэл алга"
          body="Гэрээний нөгөө тал үйлдэл хийх, маргаан шийдэгдэх үед энд мэдэгдэл ирнэ."
        />
      ) : null}
      <ul className="space-y-2">
        {data?.items.map((n) => (
          <li key={n.id}>
            <Link
              href={n.deal_id ? `/deals/${n.deal_id}` : "/dashboard"}
              className={`shadow-card hover:border-border-strong flex gap-3 rounded-2xl border p-4 ${
                n.read ? "bg-surface border-border" : "bg-brand-soft border-brand/30"
              }`}
            >
              <span
                aria-hidden
                className={`mt-0.5 grid size-8 shrink-0 place-items-center rounded-full ${
                  n.read ? "bg-surface-muted text-muted" : "bg-surface text-brand"
                }`}
              >
                <Icon name="bell" className="size-4" />
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex items-start justify-between gap-2">
                  <div className={`text-sm ${n.read ? "font-medium" : "font-semibold"}`}>
                    {!n.read ? <span className="sr-only">Уншаагүй: </span> : null}
                    {text(n)}
                  </div>
                  {!n.read ? <span aria-hidden className="bg-brand mt-1.5 size-2 shrink-0 rounded-full" /> : null}
                </div>
                <div className="text-muted mt-1 text-xs">
                  {typeof n.data.title === "string" ? `${n.data.title} · ` : ""}
                  {formatDateTime(n.created_at)}
                </div>
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
