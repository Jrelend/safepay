import { Icon } from "@/components/icons";

/** Mandatory notice on every screen that shows or moves (simulated) money. */
export const TEST_PAYMENT_LABEL = "ТУРШИЛТЫН ТӨЛБӨР — БОДИТ МӨНГӨ БИШ";

export function TestPaymentNotice({ detail }: { detail?: string }) {
  return (
    <div
      role="note"
      data-testid="test-payment-notice"
      className="border-warning-border bg-warning-soft text-warning flex items-start gap-2.5 rounded-xl border border-dashed px-3 py-2.5"
    >
      <Icon name="flask" className="mt-0.5 size-[18px]" />
      <div className="min-w-0">
        <div className="text-[13px] font-extrabold tracking-wide">{TEST_PAYMENT_LABEL}</div>
        {detail ? <div className="text-foreground mt-0.5 text-xs leading-snug">{detail}</div> : null}
      </div>
    </div>
  );
}
