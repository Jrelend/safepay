"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useRef, useState, type FormEvent } from "react";

import { AuthGuard } from "@/components/auth-guard";
import { EvidenceList } from "@/components/evidence-list";
import { TestPaymentNotice } from "@/components/test-payment-notice";
import { Alert, Button, Card, DefinitionList, PageTitle, Skeleton, TextArea } from "@/components/ui";
import { api, ApiError } from "@/lib/client/api";
import { useApi } from "@/lib/client/use-api";
import { formatDateTime } from "@/lib/format";
import type { Dispute } from "@/lib/types";

const MAX_FILE = 2 * 1024 * 1024;
const OUTCOME: Record<string, string> = {
  RELEASE_TO_SELLER: "Мөнгийг худалдагчид шилжүүлсэн",
  REFUND_TO_BUYER: "Мөнгийг худалдан авагчид буцаасан",
};

function Detail() {
  const { id } = useParams<{ id: string }>();
  const dispute = useApi<Dispute>(`/disputes/${id}`);
  const [statement, setStatement] = useState("");
  const [busy, setBusy] = useState<"statement" | "file" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  if (dispute.loading && !dispute.data) return <Skeleton />;
  if (!dispute.data) return <Alert tone="danger">{dispute.error?.message ?? "Олдсонгүй."}</Alert>;
  const d = dispute.data;
  const open = d.status === "OPEN";

  async function addStatement(e: FormEvent) {
    e.preventDefault();
    if (!statement.trim()) return;
    setBusy("statement");
    setError(null);
    try {
      await api(`/disputes/${id}/statements`, { json: { body: statement.trim() } });
      setStatement("");
      await dispute.reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Алдаа гарлаа.");
    } finally {
      setBusy(null);
    }
  }

  async function upload(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    const file = form.get("file");
    if (!(file instanceof File) || file.size === 0) {
      setError("Файл сонгоно уу.");
      return;
    }
    if (file.size > MAX_FILE) {
      setError("Файл 2 МБ-аас их байна.");
      return;
    }
    setBusy("file");
    setError(null);
    try {
      await api(`/disputes/${id}/files`, { form });
      if (fileRef.current) fileRef.current.value = "";
      await dispute.reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Алдаа гарлаа.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-4">
      <PageTitle title="Маргаан" subtitle={`${d.deal_reference} · ${d.deal_title}`} back={`/deals/${d.deal_id}`} />
      <TestPaymentNotice />
      <Card>
        <DefinitionList
          items={[
            ["Төлөв", open ? "Шийдвэрлэж буй" : "Шийдвэрлэсэн"],
            ["Нээсэн", `${d.opened_by_me ? "Та" : "Нөгөө тал"} · ${formatDateTime(d.opened_at)}`],
            ...(d.resolved_at ? [["Шийдвэрлэсэн", formatDateTime(d.resolved_at)] as [string, string]] : []),
          ]}
        />
        <div className="mt-3 text-sm">
          <div className="text-muted text-xs">Шалтгаан</div>
          <p className="whitespace-pre-wrap">{d.reason}</p>
        </div>
      </Card>
      {d.outcome ? (
        <Alert tone="info" title={`Шийдвэр: ${OUTCOME[d.outcome]}`}>
          {d.decision_reason}
        </Alert>
      ) : (
        <Alert tone="info">
          Мөнгө барьцаанд хэвээр байна. SafePay-ийн ажилтан хоёр талын тайлбар, нотлох баримтыг үзээд шийдвэр гаргана.
        </Alert>
      )}
      <Card className="space-y-3">
        <h2 className="font-semibold">Нотлох баримт</h2>
        <p className="text-muted text-xs">Нотлох баримтыг зөвхөн гэрээний хоёр тал болон SafePay ажилтан харна. Илгээсний дараа засах, устгах боломжгүй.</p>
        <EvidenceList items={d.evidence} fileHref={(e) => `/api/disputes/${id}/evidence/${e.id}/file`} />
      </Card>
      {open ? (
        <>
          <Card>
            <form onSubmit={addStatement} className="space-y-3">
              <TextArea
                label="Тайлбар нэмэх"
                value={statement}
                onChange={(e) => setStatement(e.target.value)}
                maxLength={5000}
                required
              />
              <Button type="submit" loading={busy === "statement"} className="w-full">
                Илгээх
              </Button>
            </form>
          </Card>
          <Card>
            <form onSubmit={upload} className="space-y-3">
              <label htmlFor="evidence-file" className="block text-sm font-medium">
                Файл хавсаргах (PNG, JPEG, PDF · 2 МБ хүртэл)
              </label>
              <input
                id="evidence-file"
                ref={fileRef}
                type="file"
                name="file"
                accept="image/png,image/jpeg,application/pdf"
                className="block w-full text-sm"
              />
              <input type="hidden" name="caption" value="" />
              <Button type="submit" variant="secondary" loading={busy === "file"} className="w-full">
                Хавсаргах
              </Button>
            </form>
          </Card>
        </>
      ) : null}
      {error ? <Alert tone="danger">{error}</Alert> : null}
      <Link href={`/deals/${d.deal_id}`} className="text-brand block text-center text-sm">
        Гэрээ рүү буцах
      </Link>
    </div>
  );
}

export function DisputeDetail() {
  return <AuthGuard>{() => <Detail />}</AuthGuard>;
}
