"use client";

import { useParams, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { ActionDialog } from "@/components/action-dialog";
import { AuthGuard } from "@/components/auth-guard";
import { DealProgress, MoneyLocation, NextStepPanel } from "@/components/deal-flow-ui";
import { Icon } from "@/components/icons";
import { StatusBadge } from "@/components/status-badge";
import { TestPaymentNotice } from "@/components/test-payment-notice";
import {
  Alert,
  Button,
  ButtonLink,
  Card,
  CardTitle,
  DefinitionList,
  Money,
  PageTitle,
  Skeleton,
} from "@/components/ui";
import { useApi } from "@/lib/client/use-api";
import { ACTION_META, ACTOR_LABEL, timelineLabel } from "@/lib/deal-actions";
import { nextStep, splitActions } from "@/lib/deal-flow";
import { DELIVERY_LABEL, ITEM_TYPE_LABEL, ROLE_LABEL, formatDateTime } from "@/lib/format";
import type { Deal, DealAction, Posting, TimelineEvent } from "@/lib/types";

import { InviteBox } from "./invite-box";

/**
 * Beta v0.1: escrow is never released just because the inspection window ended.
 * Only the buyer's confirmation or a SafePay admin decision releases it.
 */
function InspectionNotice({ deal, endsAt }: { deal: Deal; endsAt: string }) {
  const [now] = useState(() => Date.now());
  const ended = new Date(endsAt).getTime() <= now;
  if (deal.auto_release_at) {
    return (
      <Alert tone="info">
        Шалгах хугацаа <strong>{formatDateTime(deal.auto_release_at)}</strong>-д дуусна. Тэр хүртэл асуудал мэдэгдээгүй
        бол мөнгө худалдагчид автоматаар шилжинэ.
      </Alert>
    );
  }
  return (
    <Alert tone={ended ? "warning" : "info"} title={ended ? "Шалгах хугацаа дууссан" : undefined}>
      {ended ? null : (
        <>
          Шалгах хугацаа <strong>{formatDateTime(endsAt)}</strong>-д дуусна.{" "}
        </>
      )}
      Хугацаа дуусахад мөнгө автоматаар шилжихгүй.
      {ended && deal.my_role === "SELLER" ? " Худалдан авагч хариу өгөхгүй бол маргаан нээж SafePay-д хандана уу." : ""}
    </Alert>
  );
}

const POSTING_LABEL: Record<string, string> = {
  ESCROW_HOLD: "Барьцаанд байршсан",
  ESCROW_RELEASE: "Худалдагчид шилжсэн",
  ESCROW_REFUND: "Худалдан авагчид буцсан",
};

/** Why you would take each way out, in one line. */
const ISSUE_HELP: Partial<Record<DealAction, string>> = {
  OPEN_DISPUTE: "Бараа ирээгүй, тохирохгүй бол. Мөнгө барьцаанд түгжигдэж, SafePay ажилтан шийднэ.",
  REFUND: "Гэрээг биелүүлэх боломжгүй бол мөнгийг худалдан авагчид бүтнээр нь буцаана.",
  DECLINE: "Нөхцөл тохирохгүй бол татгалзана. Гэрээ цуцлагдана.",
  CANCEL: "Төлбөр байршуулахаас өмнө гэрээг цуцална. Мөнгө хөдлөхгүй.",
};

function Detail() {
  const { id } = useParams<{ id: string }>();
  const created = useSearchParams().get("created");
  const deal = useApi<Deal>(`/deals/${id}`);
  const timeline = useApi<TimelineEvent[]>(`/deals/${id}/timeline`);
  const postings = useApi<Posting[]>(`/deals/${id}/escrow`);
  const [pending, setPending] = useState<DealAction | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const noticeRef = useRef<HTMLDivElement>(null);
  const [inviteUrl] = useState(() => (typeof window === "undefined" ? null : sessionStorage.getItem(`invite:${id}`)));

  // After an action, bring the confirmation into view and announce it.
  useEffect(() => {
    if (notice) noticeRef.current?.focus();
  }, [notice]);

  if (deal.loading && !deal.data) return <Skeleton lines={4} />;
  if (deal.error || !deal.data) {
    return (
      <div className="space-y-4">
        <PageTitle title="Гэрээ" back="/deals" />
        <Alert tone="danger">{deal.error?.message ?? "Олдсонгүй."}</Alert>
      </div>
    );
  }
  const d = deal.data;
  const step = nextStep(d);
  const { primary, issue } = splitActions(d.actions);
  const awaitingCounterparty = !d.counterparty_name && (d.status === "DRAFT" || d.status === "PENDING_ACCEPTANCE");
  const open = (a: DealAction) => {
    setNotice(null);
    setPending(a);
  };

  return (
    <div className="space-y-4">
      <PageTitle title={d.title} subtitle={`${d.reference} · Та: ${ROLE_LABEL[d.my_role]}`} back="/deals" />
      {created ? <Alert tone="success">Гэрээ үүслээ. Одоо нөгөө талыг урина уу.</Alert> : null}
      {notice ? (
        <Alert tone="success" focusRef={noticeRef}>
          {notice}
        </Alert>
      ) : null}

      <Card aria-label="Гэрээний тойм" className="space-y-4">
        <div className="grid gap-4 md:grid-cols-2 md:items-start">
          <div className="space-y-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <StatusBadge status={d.status} />
              <span className="text-muted text-xs">{formatDateTime(d.status_changed_at)}</span>
            </div>
            <Money value={d.amount_mnt} className="block text-[32px] leading-tight font-bold tracking-tight" />
            <TestPaymentNotice />
          </div>
          <MoneyLocation status={d.status} />
        </div>
        <DealProgress status={d.status} />
      </Card>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_340px] lg:items-start">
        <div className="space-y-4">
          <NextStepPanel step={step}>
            {d.status === "DELIVERED" && d.inspection_ends_at ? (
              <InspectionNotice deal={d} endsAt={d.inspection_ends_at} />
            ) : null}
            {primary.length > 0 ? (
              <div className="grid gap-2 sm:flex sm:flex-wrap">
                {primary.map((a) => (
                  <Button key={a} onClick={() => open(a)} className="w-full sm:w-auto">
                    {ACTION_META[a].label}
                  </Button>
                ))}
              </div>
            ) : null}
            {d.status === "DRAFT" && d.created_by_me ? (
              <ButtonLink href={`/deals/${d.id}/edit`} variant="secondary" className="w-full sm:w-auto">
                Нөхцөл засах
              </ButtonLink>
            ) : null}
            {d.dispute_id ? (
              <ButtonLink href={`/disputes/${d.dispute_id}`} variant="secondary" className="w-full sm:w-auto">
                Маргааны дэлгэрэнгүй
              </ButtonLink>
            ) : null}
          </NextStepPanel>

          {awaitingCounterparty && d.created_by_me ? <InviteBox dealId={d.id} initialUrl={inviteUrl} /> : null}

          {issue.length > 0 ? (
            <section
              aria-labelledby="issue-title"
              className="border-border space-y-3 rounded-2xl border border-dashed p-4 sm:p-5"
            >
              <h2 id="issue-title" className="flex items-center gap-2 text-base font-semibold">
                <Icon name="alert" className="text-muted size-[18px]" />
                Асуудал гарсан уу?
              </h2>
              <ul className="space-y-3">
                {issue.map((a) => (
                  <li key={a} className="space-y-2 sm:flex sm:items-center sm:justify-between sm:gap-4 sm:space-y-0">
                    <p className="text-muted text-sm">{ISSUE_HELP[a]}</p>
                    <Button
                      variant={a === "REFUND" ? "secondary" : "dangerOutline"}
                      size="sm"
                      onClick={() => open(a)}
                      className="w-full shrink-0 sm:w-auto"
                    >
                      {ACTION_META[a].label}
                    </Button>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}

          <Card aria-labelledby="terms-title">
            <CardTitle id="terms-title">Гэрээний нөхцөл</CardTitle>
            <DefinitionList
              items={[
                ["Төрөл", ITEM_TYPE_LABEL[d.item_type]],
                ["Хүлээлгэн өгөх", DELIVERY_LABEL[d.delivery_method]],
                ["Шалгах хугацаа", `${d.inspection_days} хоног`],
                [d.my_role === "BUYER" ? "Худалдагч" : "Худалдан авагч", d.counterparty_name ?? "Нэгдээгүй"],
                ...(d.counterparty_phone ? [["Утас (баталгаажаагүй)", d.counterparty_phone] as [string, string]] : []),
                ["Таны зөвшөөрөл", <Consent key="me" ok={d.my_accepted} />],
                ["Нөгөө талын зөвшөөрөл", <Consent key="them" ok={d.counterparty_accepted} />],
                ["Үүсгэсэн", formatDateTime(d.created_at)],
              ]}
            />
            {d.description ? (
              <div className="border-border mt-2 border-t pt-3">
                <div className="text-muted mb-1 text-xs font-medium">Тайлбар</div>
                <p className="text-sm whitespace-pre-wrap">{d.description}</p>
              </div>
            ) : null}
          </Card>
        </div>

        <div className="space-y-4">
          {postings.data && postings.data.length > 0 ? (
            <Card aria-labelledby="postings-title">
              <CardTitle id="postings-title">Барьцааны гүйлгээ (туршилт)</CardTitle>
              <ul className="divide-border divide-y text-sm">
                {postings.data.map((p) => (
                  <li key={`${p.kind}-${p.created_at}`} className="flex items-center justify-between gap-3 py-2.5">
                    <div className="min-w-0">
                      <div className="font-medium">{`${POSTING_LABEL[p.kind] ?? p.kind} · ${formatDateTime(p.created_at)}`}</div>
                    </div>
                    <Money value={p.amount_mnt} className="font-semibold" />
                  </li>
                ))}
              </ul>
            </Card>
          ) : null}

          <Card aria-labelledby="timeline-title">
            <CardTitle id="timeline-title">Гэрээний түүх</CardTitle>
            {timeline.loading && !timeline.data ? <Skeleton lines={2} /> : null}
            <ol className="space-y-0">
              {timeline.data
                ?.slice()
                .reverse()
                .map((e, i, all) => (
                  <li key={`${e.occurred_at}-${i}`} className="relative flex gap-3 pb-4 last:pb-0">
                    <span aria-hidden className="relative flex w-3 shrink-0 justify-center">
                      <span className={`mt-1.5 size-2.5 rounded-full ${i === 0 ? "bg-success" : "bg-border-strong"}`} />
                      {i < all.length - 1 ? <span className="bg-border absolute top-5 -bottom-1 w-px" /> : null}
                    </span>
                    <div className="min-w-0">
                      <div className="text-sm font-medium">{timelineLabel(e.action, e.data)}</div>
                      <div className="text-muted text-xs">
                        {ACTOR_LABEL[e.actor] ?? e.actor} · {formatDateTime(e.occurred_at)}
                      </div>
                      {typeof e.data.reason === "string" && e.data.reason ? (
                        <div className="text-muted mt-1 text-xs break-words">“{e.data.reason}”</div>
                      ) : null}
                    </div>
                  </li>
                ))}
            </ol>
          </Card>
        </div>
      </div>

      {pending ? (
        <ActionDialog
          deal={d}
          action={pending}
          onClose={() => setPending(null)}
          onDone={() => {
            setNotice(`${ACTION_META[pending].label}: амжилттай.`);
            setPending(null);
            void deal.reload();
            void timeline.reload();
            void postings.reload();
          }}
        />
      ) : null}
    </div>
  );
}

function Consent({ ok }: { ok: boolean }) {
  return ok ? (
    <span className="text-success inline-flex items-center gap-1">
      <Icon name="check" className="size-4" />
      Зөвшөөрсөн
    </span>
  ) : (
    <span className="text-muted">Хүлээгдэж буй</span>
  );
}

export function DealDetail() {
  return <AuthGuard>{() => <Detail />}</AuthGuard>;
}
