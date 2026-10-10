"use client";

import { useParams } from "next/navigation";
import { useState, type FormEvent } from "react";

import { AdminGuard } from "@/components/admin-guard";
import { EvidenceList } from "@/components/evidence-list";
import { StatusBadge } from "@/components/status-badge";
import { TestPaymentNotice } from "@/components/test-payment-notice";
import { Alert, Button, Card, DefinitionList, Money, PageTitle, Skeleton, TextArea } from "@/components/ui";
import { api, ApiError } from "@/lib/client/api";
import { useApi } from "@/lib/client/use-api";
import { ACTOR_LABEL, timelineLabel } from "@/lib/deal-actions";
import { formatDateTime } from "@/lib/format";
import type { AdminDispute } from "@/lib/types";

type Outcome = "RELEASE_TO_SELLER" | "REFUND_TO_BUYER";
const OUTCOME_LABEL: Record<Outcome, string> = {
  RELEASE_TO_SELLER: "Худалдагчид шилжүүлэх",
  REFUND_TO_BUYER: "Худалдан авагчид буцаах",
};

function Content() {
  const { id } = useParams<{ id: string }>();
  const dispute = useApi<AdminDispute>(`/admin/disputes/${id}`);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const [reason, setReason] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (dispute.loading && !dispute.data) return <Skeleton />;
  if (!dispute.data) return <Alert tone="danger">{dispute.error?.message ?? "Олдсонгүй."}</Alert>;
  const d = dispute.data;

  async function decide(e: FormEvent) {
    e.preventDefault();
    if (!outcome) return;
    if (reason.trim().length < 10) {
      setError("Шийдвэрийн үндэслэлийг дор хаяж 10 тэмдэгтээр бичнэ үү.");
      return;
    }
    setBusy("decide");
    setError(null);
    try {
      await api(`/admin/disputes/${id}/decision`, { json: { outcome, reason: reason.trim() } });
      setOutcome(null);
      await dispute.reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Алдаа гарлаа.");
    } finally {
      setBusy(null);
    }
  }

  async function addNote(e: FormEvent) {
    e.preventDefault();
    if (!note.trim()) return;
    setBusy("note");
    try {
      await api(`/admin/disputes/${id}/notes`, { json: { body: note.trim() } });
      setNote("");
      await dispute.reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Алдаа гарлаа.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-4">
      <PageTitle title={d.deal_title} subtitle={`${d.deal_reference} · маргаан`} back="/admin" />
      <Card className="space-y-3">
        <div className="flex items-center justify-between">
          <StatusBadge status={d.deal_status} />
          <Money value={d.amount_mnt} className="text-xl font-bold" />
        </div>
        <TestPaymentNotice />
        <DefinitionList
          items={[
            ["Нээсэн", `${ACTOR_LABEL[d.opened_by_role] ?? d.opened_by_role} · ${formatDateTime(d.opened_at)}`],
            ...d.participants.map(
              (p) => [ACTOR_LABEL[p.role] ?? p.role, `${p.display_name} (${p.email})${p.status === "SUSPENDED" ? " · түдгэлзүүлсэн" : ""}`] as [string, string],
            ),
          ]}
        />
        <div className="text-sm">
          <div className="text-muted text-xs">Шалтгаан</div>
          <p className="whitespace-pre-wrap">{d.reason}</p>
        </div>
      </Card>
      {d.outcome ? (
        <Alert tone="success" title={`Шийдвэрлэсэн: ${OUTCOME_LABEL[d.outcome]}`}>
          {d.decision_reason}
        </Alert>
      ) : null}
      <Card className="space-y-3">
        <h2 className="font-semibold">Нотлох баримт</h2>
        <EvidenceList items={d.evidence} fileHref={(e) => `/api/admin/disputes/${id}/evidence/${e.id}/file`} />
      </Card>
      {d.status === "OPEN" ? (
        <>
          <Card>
            <form onSubmit={addNote} className="space-y-3">
              <TextArea label="Дотоод тэмдэглэл (талуудад харагдахгүй)" value={note} onChange={(e) => setNote(e.target.value)} maxLength={5000} />
              <Button type="submit" variant="secondary" loading={busy === "note"} className="w-full">
                Тэмдэглэл нэмэх
              </Button>
            </form>
          </Card>
          <Card>
            <form onSubmit={decide} className="space-y-3">
              <h2 className="font-semibold">Шийдвэр</h2>
              <div className="grid grid-cols-2 gap-2">
                {(Object.keys(OUTCOME_LABEL) as Outcome[]).map((o) => (
                  <Button
                    key={o}
                    variant={outcome === o ? "primary" : "secondary"}
                    aria-pressed={outcome === o}
                    onClick={() => setOutcome(o)}
                  >
                    {OUTCOME_LABEL[o]}
                  </Button>
                ))}
              </div>
              <TextArea
                label="Шийдвэрийн үндэслэл (талуудад харагдана)"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                minLength={10}
                maxLength={2000}
                required
              />
              <Button type="submit" variant="danger" loading={busy === "decide"} disabled={!outcome} className="w-full">
                Шийдвэрийг батлах
              </Button>
              <p className="text-muted text-xs">Шийдвэрийг буцаах боломжгүй. Өөрийн оролцсон гэрээг шийдвэрлэх боломжгүй.</p>
            </form>
          </Card>
        </>
      ) : null}
      {error ? <Alert tone="danger">{error}</Alert> : null}
      <Card>
        <h2 className="mb-3 font-semibold">Гэрээний түүх</h2>
        <ol className="space-y-2 text-sm">
          {d.timeline.map((e, i) => (
            <li key={i}>
              <span className="font-medium">{timelineLabel(e.action, e.data)}</span>{" "}
              <span className="text-muted text-xs">
                · {ACTOR_LABEL[e.actor] ?? e.actor} · {formatDateTime(e.occurred_at)}
              </span>
            </li>
          ))}
        </ol>
      </Card>
    </div>
  );
}

export function AdminDisputeView() {
  return (
    <AdminGuard>
      <Content />
    </AdminGuard>
  );
}
