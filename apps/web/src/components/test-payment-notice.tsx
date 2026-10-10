/** Mandatory notice on every screen that shows or moves (simulated) money. */
export const TEST_PAYMENT_LABEL = "ТУРШИЛТЫН ТӨЛБӨР — БОДИТ МӨНГӨ БИШ";

export function TestPaymentNotice({ detail }: { detail?: string }) {
  return (
    <div
      role="note"
      data-testid="test-payment-notice"
      className="rounded-xl border-2 border-dashed border-amber-400 bg-amber-50 p-3 text-center text-amber-900 dark:bg-amber-950 dark:text-amber-100"
    >
      <div className="text-sm font-extrabold tracking-wide">{TEST_PAYMENT_LABEL}</div>
      {detail ? <div className="mt-1 text-xs">{detail}</div> : null}
    </div>
  );
}
