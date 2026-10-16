import { TONE_SOFT } from "@/components/ui";
import { DEAL_STATUS_META, type DealStatus } from "@/lib/deal-status";

export function StatusBadge({ status }: { status: DealStatus }) {
  const meta = DEAL_STATUS_META[status];
  return (
    <span
      className={`inline-flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-semibold whitespace-nowrap ${TONE_SOFT[meta.tone]}`}
    >
      <span aria-hidden className="size-1.5 rounded-full bg-current" />
      {meta.label}
    </span>
  );
}
