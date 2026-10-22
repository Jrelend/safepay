"use client";

import { Money } from "@/components/ui";
import { useDemoAccounts } from "@/lib/client/demo";
import { useApi } from "@/lib/client/use-api";
import { formatDateTime } from "@/lib/format";
import type { DealSummary, Wallet } from "@/lib/types";

/** Deal states in which the buyer's (simulated) money sits in escrow. */
const HELD = new Set(["FUNDED", "DELIVERED", "DISPUTED"]);

const KIND: Record<string, string> = {
  DEMO_TOPUP: "Туршилтын эхний үлдэгдэл",
  ESCROW_HOLD: "Барьцаанд байршуулсан",
  ESCROW_RELEASE: "Гэрээний төлбөр орж ирсэн",
  ESCROW_REFUND: "Барьцаанаас буцаж ирсэн",
};

/**
 * LOCAL DEMO: where the simulated money is right now (available vs. held in escrow)
 * and the wallet's latest movements, so an audience can follow every step.
 */
export function DemoWalletDetails({ wallet, deals }: { wallet: Wallet; deals: DealSummary[] }) {
  const held = deals
    .filter((d) => d.my_role === "BUYER" && HELD.has(d.status))
    .reduce((sum, d) => sum + Number(d.amount_mnt), 0);
  return (
    <div className="space-y-3" data-testid="demo-wallet">
      <dl className="grid grid-cols-2 gap-2">
        <div className="bg-surface-muted rounded-xl p-3">
          <dt className="text-muted text-xs">Боломжит</dt>
          <dd data-testid="wallet-available">
            <Money value={wallet.balance_mnt} className="text-sm font-bold" />
          </dd>
        </div>
        <div className="bg-brand-soft rounded-xl p-3">
          <dt className="text-muted text-xs">Барьцаанд байгаа</dt>
          <dd data-testid="wallet-held">
            <Money value={held} className="text-brand text-sm font-bold" />
          </dd>
        </div>
      </dl>
      {wallet.entries.length > 0 ? (
        <div>
          <h3 className="text-muted mb-1 text-xs font-semibold tracking-wide uppercase">Хэтэвчийн гүйлгээ</h3>
          <ul className="divide-border divide-y text-[13px]">
            {wallet.entries.slice(0, 6).map((e, i) => {
              const incoming = e.direction === "CREDIT";
              return (
                <li key={`${e.created_at}-${i}`} className="flex items-start justify-between gap-3 py-2">
                  <span>
                    <span className="block font-medium">{KIND[e.kind] ?? e.kind}</span>
                    <span className="text-muted block text-xs">{formatDateTime(e.created_at)}</span>
                  </span>
                  <span className={`font-semibold tabular-nums ${incoming ? "text-success" : "text-foreground"}`}>
                    {incoming ? "+" : "−"}
                    <Money value={e.amount_mnt} />
                  </span>
                </li>
              );
            })}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

/** LOCAL DEMO: in the payment dialog, the buyer's balance before and after funding. */
export function DemoFundPreview({ amount }: { amount: string }) {
  const localDemo = useDemoAccounts() !== null;
  const wallet = useApi<Wallet>(localDemo ? "/me/wallet" : null);
  if (!localDemo || !wallet.data) return null;
  const before = Number(wallet.data.balance_mnt);
  const after = before - Number(amount);
  return (
    <div data-testid="demo-fund-preview" className="border-border space-y-1.5 rounded-xl border p-3 text-sm">
      <div className="flex justify-between gap-3">
        <span className="text-muted">Туршилтын хэтэвч одоо</span>
        <Money value={before} className="font-semibold" />
      </div>
      <div className="flex justify-between gap-3">
        <span className="text-muted">Төлбөрийн дараа</span>
        <Money value={Math.max(after, 0)} className="font-semibold" />
      </div>
      {after < 0 ? (
        <p className="text-danger text-[13px] font-medium">Үлдэгдэл хүрэлцэхгүй байна.</p>
      ) : null}
    </div>
  );
}
