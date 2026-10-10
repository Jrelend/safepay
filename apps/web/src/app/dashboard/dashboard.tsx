"use client";

import Link from "next/link";

import { AuthGuard } from "@/components/auth-guard";
import { DealCard } from "@/components/deal-card";
import { TestPaymentNotice } from "@/components/test-payment-notice";
import { Alert, ButtonLink, Card, EmptyState, Money, Skeleton } from "@/components/ui";
import { useApi } from "@/lib/client/use-api";
import type { DealSummary, Me, Wallet } from "@/lib/types";

const NEEDS_ME: Record<string, (d: DealSummary) => boolean> = {
  AWAITING_PAYMENT: (d) => d.my_role === "BUYER",
  DELIVERED: (d) => d.my_role === "BUYER",
  FUNDED: (d) => d.my_role === "SELLER",
};

function Content({ me }: { me: Me }) {
  const deals = useApi<DealSummary[]>("/deals?scope=active");
  const wallet = useApi<Wallet>("/me/wallet");
  const unread = useApi<{ unread: number }>("/me/notifications");
  const todo = (deals.data ?? []).filter((d) => NEEDS_ME[d.status]?.(d));

  return (
    <div className="space-y-6">
      <div>
        <p className="text-muted text-sm">Сайн байна уу,</p>
        <h1 className="text-2xl font-bold">{me.display_name}</h1>
      </div>

      <Card className="space-y-3">
        <div className="text-muted text-sm">Туршилтын хэтэвчний үлдэгдэл</div>
        {wallet.data ? (
          <Money value={wallet.data.balance_mnt} className="block text-3xl font-bold" />
        ) : wallet.error ? (
          <Alert tone="danger">{wallet.error.message}</Alert>
        ) : (
          <div className="bg-border h-9 w-40 animate-pulse rounded" />
        )}
        <TestPaymentNotice />
      </Card>

      <div className="grid grid-cols-2 gap-3">
        <ButtonLink href="/deals/new">+ Шинэ гэрээ</ButtonLink>
        <ButtonLink href="/notifications" variant="secondary">
          Мэдэгдэл{unread.data && unread.data.unread > 0 ? ` (${unread.data.unread})` : ""}
        </ButtonLink>
      </div>

      {todo.length > 0 ? (
        <section className="space-y-3" aria-labelledby="todo-title">
          <h2 id="todo-title" className="font-semibold">
            Таны хариу хүлээж буй
          </h2>
          {todo.map((d) => (
            <DealCard key={d.id} deal={d} />
          ))}
        </section>
      ) : null}

      <section className="space-y-3" aria-labelledby="active-title">
        <div className="flex items-center justify-between">
          <h2 id="active-title" className="font-semibold">
            Идэвхтэй гэрээ
          </h2>
          <Link href="/deals" className="text-brand text-sm">
            Бүгдийг харах
          </Link>
        </div>
        {deals.loading && !deals.data ? <Skeleton /> : null}
        {deals.error ? <Alert tone="danger">{deals.error.message}</Alert> : null}
        {deals.data && deals.data.length === 0 ? (
          <EmptyState
            title="Идэвхтэй гэрээ алга"
            body="Худалдаа хийхдээ шинэ гэрээ үүсгээд холбоосоо нөгөө талдаа илгээнэ үү."
            action={<ButtonLink href="/deals/new">Гэрээ үүсгэх</ButtonLink>}
          />
        ) : null}
        {deals.data?.map((d) => (
          <DealCard key={d.id} deal={d} />
        ))}
      </section>
    </div>
  );
}

export function Dashboard() {
  return <AuthGuard>{(me) => <Content me={me} />}</AuthGuard>;
}
