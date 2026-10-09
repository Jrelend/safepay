"use client";

import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useState } from "react";

import { ActionDialog } from "@/components/action-dialog";
import { AuthGuard } from "@/components/auth-guard";
import { StatusBadge } from "@/components/status-badge";
import { TestPaymentNotice } from "@/components/test-payment-notice";
import { Alert, Button, ButtonLink, Card, DefinitionList, Money, PageTitle, Skeleton } from "@/components/ui";
import { useApi } from "@/lib/client/use-api";
import { ACTION_META, ACTOR_LABEL, timelineLabel } from "@/lib/deal-actions";
import { DEAL_STATUS_META } from "@/lib/deal-status";
import { DELIVERY_LABEL, ITEM_TYPE_LABEL, ROLE_LABEL, formatDateTime } from "@/lib/format";
import type { Deal, DealAction, Posting, TimelineEvent } from "@/lib/types";

import { InviteBox } from "./invite-box";

const POSTING_LABEL: Record<string, string> = {
  ESCROW_HOLD: "Барьцаанд байршсан",
  ESCROW_RELEASE: "Худалдагчид шилжсэн",
  ESCROW_REFUND: "Худалдан авагчид буцсан",
};

function Detail() {
  const { id } = useParams<{ id: string }>();
  const created = useSearchParams().get("created");
  const deal = useApi<Deal>(`/deals/${id}`);
  const timeline = useApi<TimelineEvent[]>(`/deals/${id}/timeline`);
  const postings = useApi<Posting[]>(`/deals/${id}/escrow`);
  const [pending, setPending] = useState<DealAction | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [inviteUrl] = useState(() =>
    typeof window === "undefined" ? null : sessionStorage.getItem(`invite:${id}`),
  );

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
  const status = DEAL_STATUS_META[d.status];
  const awaitingCounterparty = !d.counterparty_name && (d.status === "DRAFT" || d.status === "PENDING_ACCEPTANCE");

  return (
    <div className="space-y-4">
      <PageTitle title={d.title} subtitle={`${d.reference} · Та: ${ROLE_LABEL[d.my_role]}`} back="/deals" />
      {created ? <Alert tone="success">Гэрээ үүслээ. Одоо нөгөө талыг урина уу.</Alert> : null}
      {notice ? <Alert tone="success">{notice}</Alert> : null}

      <Card className="space-y-3">
        <div className="flex items-center justify-between gap-3">
          <StatusBadge status={d.status} />
          <span className="text-muted text-xs">{formatDateTime(d.status_changed_at)}</span>
        </div>
        <p className="text-muted text-sm">{status.description}</p>
        <Money value={d.amount_mnt} className="block text-3xl font-bold" />
        <TestPaymentNotice />
        {d.status === "DELIVERED" && d.auto_release_at ? (
          <Alert tone="info">
            Шалгах хугацаа <strong>{formatDateTime(d.auto_release_at)}</strong>-д дуусна. Тэр хүртэл асуудал
            мэдэгдээгүй бол мөнгө худалдагчид автоматаар шилжинэ.
          </Alert>
        ) : null}
        {d.dispute_id ? (
          <ButtonLink href={`/disputes/${d.dispute_id}`} variant="secondary" className="w-full">
            Маргааны дэлгэрэнгүй
          </ButtonLink>
        ) : null}
      </Card>

      {d.actions.length > 0 ? (
        <section aria-label="Үйлдлүүд" className="grid gap-2">
          {d.actions.map((a) => (
            <Button
              key={a}
              variant={ACTION_META[a].variant}
              onClick={() => {
                setNotice(null);
                setPending(a);
              }}
              className="w-full"
            >
              {ACTION_META[a].label}
            </Button>
          ))}
        </section>
      ) : null}

      {d.status === "DRAFT" && d.created_by_me ? (
        <ButtonLink href={`/deals/${d.id}/edit`} variant="secondary" className="w-full">
          Нөхцөл засах
        </ButtonLink>
      ) : null}

      {awaitingCounterparty && d.created_by_me ? <InviteBox dealId={d.id} initialUrl={inviteUrl} /> : null}

      <Card>
        <h2 className="mb-1 font-semibold">Нөхцөл</h2>
        <DefinitionList
          items={[
            ["Төрөл", ITEM_TYPE_LABEL[d.item_type]],
            ["Хүлээлгэн өгөх", DELIVERY_LABEL[d.delivery_method]],
            ["Шалгах хугацаа", `${d.inspection_days} хоног`],
            [d.my_role === "BUYER" ? "Худалдагч" : "Худалдан авагч", d.counterparty_name ?? "Нэгдээгүй"],
            ...(d.counterparty_phone ? [["Утас", d.counterparty_phone] as [string, string]] : []),
            ["Таны зөвшөөрөл", d.my_accepted ? "Зөвшөөрсөн ✓" : "Хүлээгдэж буй"],
            ["Нөгөө талын зөвшөөрөл", d.counterparty_accepted ? "Зөвшөөрсөн ✓" : "Хүлээгдэж буй"],
            ["Үүсгэсэн", formatDateTime(d.created_at)],
          ]}
        />
        {d.description ? <p className="mt-3 text-sm whitespace-pre-wrap">{d.description}</p> : null}
      </Card>

      {postings.data && postings.data.length > 0 ? (
        <Card>
          <h2 className="mb-1 font-semibold">Барьцааны гүйлгээ (туршилт)</h2>
          <DefinitionList
            items={postings.data.map((p) => [
              `${POSTING_LABEL[p.kind] ?? p.kind} · ${formatDateTime(p.created_at)}`,
              <Money key={p.created_at} value={p.amount_mnt} />,
            ])}
          />
        </Card>
      ) : null}

      <Card>
        <h2 className="mb-3 font-semibold">Түүх</h2>
        {timeline.loading && !timeline.data ? <Skeleton lines={2} /> : null}
        <ol className="border-border space-y-4 border-l pl-4">
          {timeline.data
            ?.slice()
            .reverse()
            .map((e, i) => (
              <li key={`${e.occurred_at}-${i}`} className="relative">
                <span aria-hidden className="bg-brand absolute top-1.5 -left-[21px] size-2.5 rounded-full" />
                <div className="text-sm font-medium">{timelineLabel(e.action, e.data)}</div>
                <div className="text-muted text-xs">
                  {ACTOR_LABEL[e.actor] ?? e.actor} · {formatDateTime(e.occurred_at)}
                </div>
                {typeof e.data.reason === "string" && e.data.reason ? (
                  <div className="text-muted mt-1 text-xs">“{e.data.reason}”</div>
                ) : null}
              </li>
            ))}
        </ol>
      </Card>

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
      <Link href="/deals" className="text-brand block text-center text-sm">
        Бүх гэрээ
      </Link>
    </div>
  );
}

export function DealDetail() {
  return <AuthGuard>{() => <Detail />}</AuthGuard>;
}
