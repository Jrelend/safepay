"use client";

import { useEffect, useRef, useState } from "react";

import { TestPaymentNotice } from "@/components/test-payment-notice";
import { Alert, Button, Money, TextArea } from "@/components/ui";
import { api, ApiError, newIdempotencyKey } from "@/lib/client/api";
import { ACTION_META } from "@/lib/deal-actions";
import type { Deal, DealAction } from "@/lib/types";

/**
 * Confirmation dialog for a deal action. One idempotency key is generated per
 * opening, so a double click or a retry after a network error can never
 * execute the action twice.
 */
export function ActionDialog({
  deal,
  action,
  onClose,
  onDone,
}: {
  deal: Deal;
  action: DealAction;
  onClose: () => void;
  onDone: (deal: Deal) => void;
}) {
  const meta = ACTION_META[action];
  const ref = useRef<HTMLDialogElement>(null);
  const [key] = useState(newIdempotencyKey);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const dialog = ref.current;
    // Return focus to the button that opened the dialog (WCAG 2.4.3).
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    dialog?.showModal();
    return () => {
      dialog?.close();
      if (opener?.isConnected) opener.focus();
    };
  }, []);

  async function confirm() {
    if (meta.needsNote && note.trim().length < 5) {
      setError("Шалтгаанаа дор хаяж 5 тэмдэгтээр бичнэ үү.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const res = await api<{ deal: Deal }>(`/deals/${deal.id}/actions`, {
        json: { action, expected_version: deal.version, note: note.trim() || null },
        idempotencyKey: key,
      });
      onDone(res.deal);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Алдаа гарлаа.");
      setBusy(false);
    }
  }

  return (
    <dialog
      ref={ref}
      onCancel={(e) => {
        e.preventDefault();
        if (!busy) onClose();
      }}
      aria-labelledby="action-title"
      aria-describedby="action-consequence"
      className="bg-surface text-foreground shadow-raised border-border m-auto w-[calc(100%-2rem)] max-w-md rounded-2xl border p-0 backdrop:bg-[#0b1220]/60"
    >
      <div className="space-y-4 p-5 sm:p-6">
        <h2 id="action-title" className="text-lg leading-snug font-bold">
          {meta.label}
        </h2>
        <p id="action-consequence" className="text-muted text-sm leading-relaxed">
          {meta.confirm}
        </p>
        {meta.money ? (
          <div className="space-y-2">
            <div className="bg-surface-muted rounded-xl py-3 text-center">
              <div className="text-muted text-xs">{deal.title}</div>
              <Money value={deal.amount_mnt} className="text-2xl font-bold" />
            </div>
            <TestPaymentNotice detail="Бодит банк, карт, QPay ашиглагдахгүй. Ямар ч бодит мөнгө шилжихгүй." />
          </div>
        ) : null}
        {meta.needsNote || meta.allowsNote ? (
          <TextArea
            label={meta.needsNote ? "Шалтгаан (заавал)" : "Тайлбар (заавал биш)"}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            maxLength={2000}
            required={meta.needsNote}
          />
        ) : null}
        {error ? <Alert tone="danger">{error}</Alert> : null}
        <div className="grid grid-cols-2 gap-2 pt-1">
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            Болих
          </Button>
          <Button variant={meta.variant === "danger" ? "danger" : "primary"} onClick={confirm} loading={busy}>
            Батлах
          </Button>
        </div>
      </div>
    </dialog>
  );
}
