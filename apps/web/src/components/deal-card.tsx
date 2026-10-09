import Link from "next/link";

import { StatusBadge } from "@/components/status-badge";
import { Money } from "@/components/ui";
import { ROLE_LABEL, formatDateTime } from "@/lib/format";
import type { DealSummary } from "@/lib/types";

export function DealCard({ deal }: { deal: DealSummary }) {
  return (
    <Link
      href={`/deals/${deal.id}`}
      className="bg-surface border-border hover:border-brand focus-visible:outline-brand block rounded-2xl border p-4 transition focus-visible:outline-2"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="truncate font-medium">{deal.title}</div>
          <div className="text-muted text-xs">
            {deal.reference} · {ROLE_LABEL[deal.my_role]}
          </div>
        </div>
        <StatusBadge status={deal.status} />
      </div>
      <div className="mt-2 flex items-end justify-between">
        <Money value={deal.amount_mnt} className="text-lg font-semibold" />
        <span className="text-muted text-xs">{formatDateTime(deal.updated_at)}</span>
      </div>
    </Link>
  );
}
