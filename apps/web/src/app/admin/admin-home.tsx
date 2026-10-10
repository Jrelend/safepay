"use client";

import Link from "next/link";
import { useState } from "react";

import { AdminGuard } from "@/components/admin-guard";
import { Icon } from "@/components/icons";
import { Alert, Card, CardTitle, EmptyState, Money, PageTitle, SegmentedControl, Skeleton } from "@/components/ui";
import { useApi } from "@/lib/client/use-api";
import { DEAL_STATUS_META, type DealStatus } from "@/lib/deal-status";
import { formatDateTime } from "@/lib/format";
import type { AdminDisputeSummary, AdminOverview } from "@/lib/types";

function Content() {
  const [status, setStatus] = useState<"OPEN" | "RESOLVED">("OPEN");
  const overview = useApi<AdminOverview>("/admin/overview");
  const disputes = useApi<AdminDisputeSummary[]>(`/admin/disputes?status=${status}`);
  return (
    <div className="space-y-5">
      <PageTitle title="Админ самбар" subtitle="Бүх үйлдэл аудитын бүртгэлд хадгалагдана." />
      {overview.error ? <Alert tone="danger">{overview.error.message}</Alert> : null}
      {overview.data ? (
        <div className="grid grid-cols-3 gap-2 sm:gap-3">
          {[
            ["Нээлттэй маргаан", overview.data.open_disputes],
            ["Хэрэглэгч", overview.data.users],
            ["Түдгэлзүүлсэн", overview.data.suspended_users],
          ].map(([label, n]) => (
            <Card key={label} as="div" className="p-3 sm:p-4">
              <div className="text-2xl font-bold tabular-nums sm:text-3xl">{n}</div>
              <div className="text-muted text-xs leading-snug [overflow-wrap:anywhere] sm:text-[13px]">{label}</div>
            </Card>
          ))}
        </div>
      ) : null}
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,1fr)_300px] lg:items-start">
        <section aria-labelledby="queue-title" className="space-y-3">
          <h2 id="queue-title" className="text-base font-semibold">
            Маргааны жагсаалт
          </h2>
          <SegmentedControl
            label="Маргааны төлөв"
            options={[
              { value: "OPEN", label: "Нээлттэй" },
              { value: "RESOLVED", label: "Шийдвэрлэсэн" },
            ]}
            value={status}
            onChange={setStatus}
          />
          {disputes.loading && !disputes.data ? <Skeleton /> : null}
          {disputes.data && disputes.data.length === 0 ? (
            <EmptyState
              icon="scale"
              title="Маргаан алга"
              body={status === "OPEN" ? "Шийдвэр хүлээж буй маргаан алга." : "Шийдвэрлэсэн маргаан энд харагдана."}
            />
          ) : null}
          <ul className="space-y-2">
            {disputes.data?.map((d) => (
              <li key={d.id}>
                <Link
                  href={`/admin/disputes/${d.id}`}
                  className="bg-surface border-border shadow-card hover:border-border-strong flex items-center gap-3 rounded-2xl border p-4"
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex justify-between gap-2">
                      <span className="truncate font-semibold">{d.deal_title}</span>
                      <Money value={d.amount_mnt} className="shrink-0 font-semibold" />
                    </div>
                    <div className="text-muted text-xs">
                      {d.deal_reference} · {formatDateTime(d.opened_at)}
                    </div>
                  </div>
                  <Icon name="chevronRight" className="text-muted size-5" />
                </Link>
              </li>
            ))}
          </ul>
        </section>
        {overview.data ? (
          <Card aria-labelledby="by-status-title">
            <CardTitle id="by-status-title">Гэрээ төлөвөөр</CardTitle>
            <ul className="divide-border divide-y text-sm">
              {Object.entries(overview.data.deals_by_status).map(([s, n]) => (
                <li key={s} className="flex justify-between py-2">
                  <span>{DEAL_STATUS_META[s as DealStatus]?.label ?? s}</span>
                  <span className="font-semibold tabular-nums">{n}</span>
                </li>
              ))}
            </ul>
          </Card>
        ) : null}
      </div>
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
