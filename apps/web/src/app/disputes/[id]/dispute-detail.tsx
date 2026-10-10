"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useRef, useState, type ChangeEvent, type FormEvent } from "react";

import { AuthGuard } from "@/components/auth-guard";
import { EvidenceList, fileSize } from "@/components/evidence-list";
import { Icon } from "@/components/icons";
import { TestPaymentNotice } from "@/components/test-payment-notice";
import { Alert, Button, Card, CardTitle, DefinitionList, PageTitle, Skeleton, TextArea, WIDTH } from "@/components/ui";
import { api, ApiError } from "@/lib/client/api";
import { useApi } from "@/lib/client/use-api";
import { formatDateTime } from "@/lib/format";
import type { Dispute } from "@/lib/types";

const MAX_FILE = 2 * 1024 * 1024;
const FILE_TYPES = ["image/png", "image/jpeg", "application/pdf"];
const OUTCOME: Record<string, string> = {
  RELEASE_TO_SELLER: "Мөнгийг худалдагчид шилжүүлсэн",
  REFUND_TO_BUYER: "Мөнгийг худалдан авагчид буцаасан",
};

/** Opened → evidence → SafePay decision, with the state in text as well as colour. */
function CaseTracker({ d }: { d: Dispute }) {
  const resolved = d.status === "RESOLVED";
  const steps = [
    { label: "Маргаан нээсэн", sub: formatDateTime(d.opened_at), state: "done" },
    {
      label: "Тайлбар, нотлох баримт",
      sub: resolved ? "Хаагдсан" : "Одоо нэмэх боломжтой",
      state: resolved ? "done" : "current",
    },
    {
      label: "SafePay-ийн шийдвэр",
      sub: d.resolved_at ? formatDateTime(d.resolved_at) : "Хүлээгдэж буй",
      state: resolved ? "done" : "upcoming",
    },
  ] as const;
  return (
    <ol aria-label="Маргааны явц" className="space-y-0">
      {steps.map((s, i) => (
        <li
          key={s.label}
          aria-current={s.state === "current" ? "step" : undefined}
          className="relative flex gap-3 pb-4 last:pb-0"
        >
          <span aria-hidden className="relative flex w-6 shrink-0 justify-center">
            <span
              className={`grid size-6 place-items-center rounded-full border-2 text-[11px] font-bold ${
                s.state === "done"
                  ? "border-success bg-success text-surface"
                  : s.state === "current"
                    ? "border-primary text-foreground"
                    : "border-border text-muted"
              }`}
            >
              {s.state === "done" ? <Icon name="check" className="size-3.5" /> : i + 1}
            </span>
            {i < steps.length - 1 ? <span className="bg-border absolute top-7 -bottom-0.5 w-px" /> : null}
          </span>
          <div className="min-w-0 pt-0.5">
            <div className={`text-sm ${s.state === "current" ? "font-bold" : "font-medium"}`}>{s.label}</div>
            <div className="text-muted text-xs">{s.sub}</div>
            <span className="sr-only">
              {s.state === "done" ? "дууссан" : s.state === "current" ? "одоогийн алхам" : "хүлээгдэж буй"}
            </span>
          </div>
        </li>
      ))}
    </ol>
  );
}

function Detail() {
  const { id } = useParams<{ id: string }>();
  const dispute = useApi<Dispute>(`/disputes/${id}`);
  const [statement, setStatement] = useState("");
  const [busy, setBusy] = useState<"statement" | "file" | null>(null);
  const [statementMsg, setStatementMsg] = useState<{ tone: "success" | "danger"; text: string } | null>(null);
  const [fileMsg, setFileMsg] = useState<{ tone: "success" | "danger"; text: string } | null>(null);
  const [picked, setPicked] = useState<File | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  if (dispute.loading && !dispute.data) return <Skeleton />;
  if (!dispute.data) return <Alert tone="danger">{dispute.error?.message ?? "Олдсонгүй."}</Alert>;
  const d = dispute.data;
  const open = d.status === "OPEN";

  async function addStatement(e: FormEvent) {
    e.preventDefault();
    if (!statement.trim()) return;
    setBusy("statement");
    setStatementMsg(null);
    try {
      await api(`/disputes/${id}/statements`, { json: { body: statement.trim() } });
      setStatement("");
      setStatementMsg({ tone: "success", text: "Тайлбар нэмэгдлээ." });
      await dispute.reload();
    } catch (err) {
      setStatementMsg({ tone: "danger", text: err instanceof ApiError ? err.message : "Алдаа гарлаа." });
    } finally {
      setBusy(null);
    }
  }

  function pick(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0] ?? null;
    setFileMsg(null);
    if (file && !FILE_TYPES.includes(file.type)) {
      setFileMsg({ tone: "danger", text: "Зөвхөн PNG, JPEG эсвэл PDF файл хавсаргана уу." });
    } else if (file && file.size > MAX_FILE) {
      setFileMsg({ tone: "danger", text: "Файл 2 МБ-аас их байна. Жижигрүүлээд дахин сонгоно уу." });
    }
    setPicked(file);
  }

  async function upload(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    const file = form.get("file");
    if (!(file instanceof File) || file.size === 0) {
      setFileMsg({ tone: "danger", text: "Эхлээд файл сонгоно уу." });
      return;
    }
    if (!FILE_TYPES.includes(file.type) || file.size > MAX_FILE) {
      setFileMsg({ tone: "danger", text: "PNG, JPEG эсвэл PDF, 2 МБ хүртэл файл сонгоно уу." });
      return;
    }
    setBusy("file");
    setFileMsg(null);
    try {
      await api(`/disputes/${id}/files`, { form });
      if (fileRef.current) fileRef.current.value = "";
      setPicked(null);
      setFileMsg({ tone: "success", text: "Файл хавсаргагдлаа." });
      await dispute.reload();
    } catch (err) {
      setFileMsg({ tone: "danger", text: err instanceof ApiError ? err.message : "Алдаа гарлаа." });
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className={`${WIDTH.form} space-y-4`}>
      <PageTitle title="Маргаан" subtitle={`${d.deal_reference} · ${d.deal_title}`} back={`/deals/${d.deal_id}`} />

      {d.outcome ? (
        <Alert tone="success" title={`Шийдвэр: ${OUTCOME[d.outcome]}`}>
          {d.decision_reason}
        </Alert>
      ) : (
        <Alert tone="info" title="Мөнгө барьцаанд түгжигдсэн">
          SafePay ажилтан хоёр талын тайлбар, нотлох баримтыг үзээд шийдвэр гаргана. Шийдвэр гармагц танд мэдэгдэнэ.
        </Alert>
      )}

      <Card aria-labelledby="case-title" className="space-y-4">
        <CardTitle id="case-title">Маргааны явц</CardTitle>
        <CaseTracker d={d} />
        <DefinitionList
          items={[
            ["Нээсэн", `${d.opened_by_me ? "Та" : "Нөгөө тал"} · ${formatDateTime(d.opened_at)}`],
            ...(d.resolved_at ? [["Шийдвэрлэсэн", formatDateTime(d.resolved_at)] as [string, string]] : []),
          ]}
        />
        <div className="bg-surface-muted rounded-xl p-3 text-sm">
          <div className="text-muted mb-0.5 text-xs font-medium">Шалтгаан</div>
          <p className="whitespace-pre-wrap">{d.reason}</p>
        </div>
        <TestPaymentNotice />
      </Card>

      <Card aria-labelledby="evidence-title" className="space-y-3">
        <CardTitle id="evidence-title">Нотлох баримт</CardTitle>
        <p className="text-muted text-[13px] leading-snug">
          Зөвхөн гэрээний хоёр тал болон SafePay ажилтан харна. Илгээсний дараа засах, устгах боломжгүй.
        </p>
        <EvidenceList items={d.evidence} fileHref={(e) => `/api/disputes/${id}/evidence/${e.id}/file`} />
      </Card>

      {open ? (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 md:items-start">
          <Card>
            <form onSubmit={addStatement} className="space-y-3">
              <TextArea
                label="Тайлбар нэмэх"
                hint="Юу болсныг он сар, баримттай нь тодорхой бичнэ үү."
                value={statement}
                onChange={(e) => setStatement(e.target.value)}
                maxLength={5000}
                required
              />
              {statementMsg ? <Alert tone={statementMsg.tone}>{statementMsg.text}</Alert> : null}
              <Button type="submit" loading={busy === "statement"} className="w-full">
                Илгээх
              </Button>
            </form>
          </Card>
          <Card>
            <form onSubmit={upload} className="space-y-3">
              <div className="space-y-1.5">
                <label htmlFor="evidence-file" className="block text-sm font-medium">
                  Файл хавсаргах <span className="text-muted font-normal">(PNG, JPEG, PDF · 2 МБ хүртэл)</span>
                </label>
                <input
                  id="evidence-file"
                  ref={fileRef}
                  type="file"
                  name="file"
                  accept="image/png,image/jpeg,application/pdf"
                  onChange={pick}
                  className="peer sr-only"
                />
                <label
                  htmlFor="evidence-file"
                  className="border-border-strong text-foreground hover:bg-surface-muted peer-focus-visible:outline-focus flex min-h-12 cursor-pointer items-center gap-3 rounded-xl border border-dashed px-3 text-sm peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2"
                >
                  <Icon name="upload" className="text-muted size-5" />
                  {picked ? (
                    <span className="min-w-0 truncate">
                      <span className="font-medium">{picked.name}</span>{" "}
                      <span className="text-muted text-xs">({fileSize(picked.size)})</span>
                    </span>
                  ) : (
                    <span className="text-muted">Файл сонгох…</span>
                  )}
                </label>
              </div>
              <input type="hidden" name="caption" value="" />
              {fileMsg ? <Alert tone={fileMsg.tone}>{fileMsg.text}</Alert> : null}
              <Button type="submit" variant="secondary" loading={busy === "file"} className="w-full">
                <Icon name="paperclip" className="size-4" />
                Хавсаргах
              </Button>
            </form>
          </Card>
        </div>
      ) : null}

      <Link
        href={`/deals/${d.deal_id}`}
        className="text-brand mx-auto flex min-h-11 w-fit items-center gap-1 rounded-lg px-2 text-sm font-medium"
      >
        <Icon name="chevronLeft" className="size-4" />
        Гэрээ рүү буцах
      </Link>
    </div>
  );
}

export function DisputeDetail() {
  return <AuthGuard>{() => <Detail />}</AuthGuard>;
}
