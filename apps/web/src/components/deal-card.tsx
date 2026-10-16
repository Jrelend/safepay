import Link from "next/link";

import { TurnChip } from "@/components/deal-flow-ui";
import { Icon } from "@/components/icons";
import { StatusBadge } from "@/components/status-badge";
import { Money } from "@/components/ui";
import { summaryNeedsMe } from "@/lib/deal-flow";
import { ROLE_LABEL, formatDateTime } from "@/lib/format";
import type { DealSummary } from "@/lib/types";

export function DealCard({ deal }: { deal: DealSummary }) {
  const mine = summaryNeedsMe(deal);
  return (
    <Link
      href={`/deals/${deal.id}`}
      className={`bg-surface shadow-card group flex items-center gap-3 rounded-2xl border p-4 transition-colors hover:border-border-strong ${
        mine ? "border-primary/40" : "border-border"
      }`}
    >
      <div className="min-w-0 flex-1 space-y-2">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="truncate font-semibold">{deal.title}</div>
            <div className="text-muted text-xs">
              {deal.reference} · {ROLE_LABEL[deal.my_role]}
            </div>
          </div>
          <StatusBadge status={deal.status} />
        </div>
        <div className="flex flex-wrap items-end justify-between gap-x-3 gap-y-1">
          <Money value={deal.amount_mnt} className="text-lg font-bold" />
          <span className="flex items-center gap-2">
            {mine ? <TurnChip /> : null}
            <span className="text-muted text-xs">{formatDateTime(deal.updated_at)}</span>
          </span>
        </div>
      </div>
      <Icon name="chevronRight" className="text-muted size-5 transition-transform group-hover:translate-x-0.5" />
    </Link>
  );
}
