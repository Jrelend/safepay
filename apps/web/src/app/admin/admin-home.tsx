"use client";

import Link from "next/link";
import { useState } from "react";

import { AdminGuard } from "@/components/admin-guard";
import { Alert, Card, EmptyState, Money, PageTitle, Skeleton } from "@/components/ui";
import { useApi } from "@/lib/client/use-api";
import { DEAL_STATUS_META, type DealStatus } from "@/lib/deal-status";
import { formatDateTime } from "@/lib/format";
import type { AdminDisputeSummary, AdminOverview } from "@/lib/types";

function Content() {
  const [status, setStatus] = useState<"OPEN" | "RESOLVED">("OPEN");
  const overview = useApi<AdminOverview>("/admin/overview");
  const disputes = useApi<AdminDisputeSummary[]>(`/admin/disputes?status=${status}`);
  return (
    <div className="space-y-4">
      <PageTitle title="Админ самбар" subtitle="Бүх үйлдэл аудитын бүртгэлд хадгалагдана." />
      {overview.error ? <Alert tone="danger">{overview.error.message}</Alert> : null}
      {overview.data ? (
        <div className="grid grid-cols-3 gap-2 text-center">
          {[
            ["Нээлттэй маргаан", overview.data.open_disputes],
            ["Хэрэглэгч", overview.data.users],
            ["Түдгэлзүүлсэн", overview.data.suspended_users],
          ].map(([label, n]) => (
            <Card key={label} className="p-3">
              <div className="text-2xl font-bold tabular-nums">{n}</div>
              <div className="text-muted text-xs">{label}</div>
            </Card>
          ))}
        </div>
      ) : null}
      {overview.data ? (
        <Card>
          <h2 className="mb-2 font-semibold">Гэрээ төлөвөөр</h2>
          <ul className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
            {Object.entries(overview.data.deals_by_status).map(([s, n]) => (
              <li key={s} className="flex justify-between">
                <span className="text-muted">{DEAL_STATUS_META[s as DealStatus]?.label ?? s}</span>
                <span className="tabular-nums">{n}</span>
              </li>
            ))}
          </ul>
        </Card>
      ) : null}
      <div role="tablist" className="bg-border grid grid-cols-2 gap-1 rounded-xl p-1">
        {(["OPEN", "RESOLVED"] as const).map((s) => (
          <button
            key={s}
            role="tab"
            type="button"
            aria-selected={s === status}
            onClick={() => setStatus(s)}
            className={`min-h-10 rounded-lg text-sm font-medium ${s === status ? "bg-surface shadow-sm" : "text-muted"}`}
          >
            {s === "OPEN" ? "Нээлттэй" : "Шийдвэрлэсэн"}
          </button>
        ))}
      </div>
      {disputes.loading && !disputes.data ? <Skeleton /> : null}
      {disputes.data && disputes.data.length === 0 ? <EmptyState title="Маргаан алга" /> : null}
      <ul className="space-y-2">
        {disputes.data?.map((d) => (
          <li key={d.id}>
            <Link href={`/admin/disputes/${d.id}`} className="bg-surface border-border block rounded-2xl border p-4">
              <div className="flex justify-between gap-2">
                <span className="truncate font-medium">{d.deal_title}</span>
                <Money value={d.amount_mnt} className="shrink-0 font-semibold" />
              </div>
              <div className="text-muted text-xs">
                {d.deal_reference} · {formatDateTime(d.opened_at)}
              </div>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function AdminHome() {
  return (
    <AdminGuard>
      <Content />
    </AdminGuard>
  );
}
