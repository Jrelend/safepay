"use client";

import { useParams } from "next/navigation";
import { useState, type FormEvent } from "react";

import { AdminGuard } from "@/components/admin-guard";
import { EvidenceList } from "@/components/evidence-list";
import { StatusBadge } from "@/components/status-badge";
import { TestPaymentNotice } from "@/components/test-payment-notice";
import { Icon } from "@/components/icons";
import { Alert, Button, Card, CardTitle, Money, PageTitle, Skeleton, TextArea } from "@/components/ui";
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
const OUTCOME_HELP: Record<Outcome, string> = {
  RELEASE_TO_SELLER: "Барьцааны мөнгийг худалдагчид олгоно.",
  REFUND_TO_BUYER: "Барьцааны мөнгийг худалдан авагчид бүтнээр буцаана.",
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
      {d.outcome ? (
        <Alert tone="success" title={`Шийдвэрлэсэн: ${OUTCOME_LABEL[d.outcome]}`}>
          {d.decision_reason}
        </Alert>
      ) : null}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_360px] lg:items-start">
        <div className="space-y-4">
          <Card className="space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <StatusBadge status={d.deal_status} />
              <Money value={d.amount_mnt} className="text-2xl font-bold" />
            </div>
            <TestPaymentNotice />
            <dl className="divide-border divide-y text-sm">
              <div className="py-2.5">
                <dt className="text-muted text-xs">Нээсэн</dt>
                <dd className="font-medium">
                  {ACTOR_LABEL[d.opened_by_role] ?? d.opened_by_role} · {formatDateTime(d.opened_at)}
                </dd>
              </div>
              {d.participants.map((p) => (
                <div key={p.role} className="py-2.5">
                  <dt className="text-muted text-xs">{ACTOR_LABEL[p.role] ?? p.role}</dt>
                  <dd className="font-medium">
                    {p.display_name}
                    {p.status === "SUSPENDED" ? <span className="text-danger"> · түдгэлзүүлсэн</span> : null}
                  </dd>
                  <dd className="text-muted text-xs break-all">{p.email}</dd>
                </div>
              ))}
            </dl>
            <div className="bg-surface-muted rounded-xl p-3 text-sm">
              <div className="text-muted mb-0.5 text-xs font-medium">Шалтгаан</div>
              <p className="whitespace-pre-wrap">{d.reason}</p>
            </div>
          </Card>
          <Card aria-labelledby="evidence-title" className="space-y-3">
            <CardTitle id="evidence-title">Нотлох баримт</CardTitle>
            <EvidenceList items={d.evidence} fileHref={(e) => `/api/admin/disputes/${id}/evidence/${e.id}/file`} />
          </Card>
          <Card aria-labelledby="history-title">
            <CardTitle id="history-title">Гэрээний түүх</CardTitle>
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
        {d.status === "OPEN" ? (
          <div className="space-y-4 lg:sticky lg:top-24">
            <Card>
              <form onSubmit={addNote} className="space-y-3">
                <TextArea
                  label="Дотоод тэмдэглэл (талуудад харагдахгүй)"
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                  maxLength={5000}
                  rows={3}
                />
                <Button type="submit" variant="secondary" loading={busy === "note"} className="w-full">
                  Тэмдэглэл нэмэх
                </Button>
              </form>
            </Card>
            <Card className="border-border-strong/60">
              <form onSubmit={decide} className="space-y-3">
                <h2 className="text-base font-semibold">Шийдвэр</h2>
                <div className="grid gap-2" role="group" aria-label="Шийдвэрийн сонголт">
                  {(Object.keys(OUTCOME_LABEL) as Outcome[]).map((o) => {
                    const selected = outcome === o;
                    return (
                      <button
                        key={o}
                        type="button"
                        aria-pressed={selected}
                        onClick={() => setOutcome(o)}
                        className={`flex min-h-14 items-start gap-3 rounded-xl border-2 p-3 text-left transition-colors ${
                          selected ? "border-primary bg-surface-muted" : "border-border hover:border-border-strong"
                        }`}
                      >
                        <span
                          aria-hidden
                          className={`mt-0.5 grid size-5 shrink-0 place-items-center rounded-full border-2 ${
                            selected ? "border-primary bg-primary text-primary-foreground" : "border-border-strong"
                          }`}
                        >
                          {selected ? <Icon name="check" className="size-3" /> : null}
                        </span>
                        <span>
                          <span className="block text-sm font-semibold">{OUTCOME_LABEL[o]}</span>
                          <span className="text-muted block text-[13px]">{OUTCOME_HELP[o]}</span>
                        </span>
                      </button>
                    );
                  })}
                </div>
                <TextArea
                  label="Шийдвэрийн үндэслэл (талуудад харагдана)"
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  minLength={10}
                  maxLength={2000}
                  required
                />
                {error ? <Alert tone="danger">{error}</Alert> : null}
                <Button
                  type="submit"
                  variant="danger"
                  loading={busy === "decide"}
                  disabled={!outcome}
                  className="w-full"
                >
                  Шийдвэрийг батлах
                </Button>
                <p className="text-muted text-xs">
                  {outcome ? `Сонгосон: ${OUTCOME_LABEL[outcome]}. ` : "Эхлээд шийдвэрээ сонгоно уу. "}
                  Шийдвэрийг буцаах боломжгүй. Өөрийн оролцсон гэрээг шийдвэрлэх боломжгүй.
                </p>
              </form>
            </Card>
          </div>
        ) : error ? (
          <Alert tone="danger">{error}</Alert>
        ) : null}
      </div>
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
