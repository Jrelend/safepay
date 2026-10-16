"use client";

import Link from "next/link";

import { AuthGuard } from "@/components/auth-guard";
import { DealCard } from "@/components/deal-card";
import { Icon } from "@/components/icons";
import { TestPaymentNotice } from "@/components/test-payment-notice";
import { Alert, ButtonLink, Card, EmptyState, Money, Skeleton } from "@/components/ui";
import { useApi } from "@/lib/client/use-api";
import { summaryNeedsMe } from "@/lib/deal-flow";
import type { DealSummary, Me, Wallet } from "@/lib/types";

function Content({ me }: { me: Me }) {
  const deals = useApi<DealSummary[]>("/deals?scope=active");
  const wallet = useApi<Wallet>("/me/wallet");
  const unread = useApi<{ unread: number }>("/me/notifications");
  const todo = (deals.data ?? []).filter(summaryNeedsMe);
  const waiting = (deals.data ?? []).filter((d) => !summaryNeedsMe(d));
  const unreadCount = unread.data?.unread ?? 0;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-muted text-sm">Сайн байна уу,</p>
          <h1 className="text-2xl font-bold tracking-tight sm:text-[28px]">{me.display_name}</h1>
        </div>
        <div className="hidden md:block">
          <ButtonLink href="/deals/new">
            <Icon name="plus" className="size-4" />
            Шинэ гэрээ
          </ButtonLink>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_320px] lg:items-start">
        <div className="space-y-6">
          <section className="space-y-3" aria-labelledby="todo-title">
            <h2 id="todo-title" className="flex items-center gap-2 text-base font-semibold">
              Таны хариу хүлээж буй
              {todo.length > 0 ? (
                <span className="bg-primary text-primary-foreground rounded-full px-2 py-px text-xs">
                  {todo.length}
                </span>
              ) : null}
            </h2>
            {deals.loading && !deals.data ? <Skeleton lines={1} /> : null}
            {deals.data && todo.length === 0 ? (
              <p className="bg-surface-muted text-muted flex items-center gap-2 rounded-xl px-4 py-3 text-sm">
                <Icon name="check" className="text-success size-4" />
                Одоогоор танаас хийх зүйл алга.
              </p>
            ) : null}
            {todo.map((d) => (
              <DealCard key={d.id} deal={d} />
            ))}
          </section>

          <section className="space-y-3" aria-labelledby="active-title">
            <div className="flex items-center justify-between">
              <h2 id="active-title" className="text-base font-semibold">
                Бусад идэвхтэй гэрээ
              </h2>
              <Link
                href="/deals"
                className="text-brand inline-flex min-h-11 items-center gap-1 rounded-lg px-1 text-sm font-medium"
              >
                Бүгдийг харах
                <Icon name="chevronRight" className="size-4" />
              </Link>
            </div>
            {deals.loading && !deals.data ? <Skeleton lines={2} /> : null}
            {deals.error ? <Alert tone="danger">{deals.error.message}</Alert> : null}
            {deals.data && deals.data.length === 0 ? (
              <EmptyState
                icon="shieldCheck"
                title="Идэвхтэй гэрээ алга"
                body="Худалдаа хийх гэж байгаа бол гэрээ үүсгээд холбоосоо нөгөө талдаа илгээнэ үү."
                action={<ButtonLink href="/deals/new">Гэрээ үүсгэх</ButtonLink>}
              />
            ) : null}
            {deals.data && deals.data.length > 0 && waiting.length === 0 ? (
              <p className="text-muted text-sm">Бусад идэвхтэй гэрээ алга.</p>
            ) : null}
            {waiting.map((d) => (
              <DealCard key={d.id} deal={d} />
            ))}
          </section>
        </div>

        <aside className="space-y-4" aria-label="Тойм">
          <Card className="space-y-3">
            <div className="flex items-center gap-2">
              <Icon name="wallet" className="text-muted size-[18px]" />
              <h2 className="text-sm font-semibold">Туршилтын хэтэвч</h2>
            </div>
            {wallet.data ? (
              <Money value={wallet.data.balance_mnt} className="block text-[28px] leading-tight font-bold" />
            ) : wallet.error ? (
              <Alert tone="danger">{wallet.error.message}</Alert>
            ) : (
              <div className="bg-surface-muted h-9 w-40 animate-pulse rounded" />
            )}
            <p className="text-muted text-[13px] leading-snug">
              Дууссан гэрээнээс танд шилжсэн эсвэл буцаж ирсэн туршилтын мөнгө.
            </p>
            <TestPaymentNotice />
          </Card>
          <Link
            href="/notifications"
            className="bg-surface border-border shadow-card hover:border-border-strong flex min-h-14 items-center justify-between gap-3 rounded-2xl border px-4"
          >
            <span className="flex items-center gap-2 text-sm font-semibold">
              <Icon name="bell" className="text-muted size-[18px]" />
              Мэдэгдэл
            </span>
            {unreadCount > 0 ? (
              <span className="bg-primary text-primary-foreground rounded-full px-2 py-0.5 text-xs font-semibold">
                {unreadCount} шинэ
              </span>
            ) : (
              <span className="text-muted text-xs">Шинэ алга</span>
            )}
          </Link>
        </aside>
      </div>
    </div>
  );
}

export function Dashboard() {
  return <AuthGuard>{(me) => <Content me={me} />}</AuthGuard>;
}
