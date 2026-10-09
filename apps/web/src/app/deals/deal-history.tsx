"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { AuthGuard } from "@/components/auth-guard";
import { DealCard } from "@/components/deal-card";
import { Alert, ButtonLink, EmptyState, PageTitle, Skeleton } from "@/components/ui";
import { useApi } from "@/lib/client/use-api";
import type { DealSummary } from "@/lib/types";

const TABS = [
  { scope: "active", label: "Идэвхтэй" },
  { scope: "closed", label: "Хаагдсан" },
  { scope: "all", label: "Бүгд" },
] as const;

function List() {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const scope = TABS.find((t) => t.scope === params.get("scope"))?.scope ?? "active";
  const { data, error, loading } = useApi<DealSummary[]>(`/deals?scope=${scope}`);

  return (
    <div>
      <PageTitle title="Миний гэрээнүүд" />
      <div role="tablist" aria-label="Гэрээний шүүлтүүр" className="bg-border mb-4 grid grid-cols-3 gap-1 rounded-xl p-1">
        {TABS.map((t) => (
          <button
            key={t.scope}
            role="tab"
            type="button"
            aria-selected={t.scope === scope}
            onClick={() => router.replace(`${pathname}?scope=${t.scope}`)}
            className={`min-h-10 rounded-lg text-sm font-medium ${
              t.scope === scope ? "bg-surface shadow-sm" : "text-muted"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div className="space-y-3" role="tabpanel">
        {loading && !data ? <Skeleton /> : null}
        {error ? <Alert tone="danger">{error.message}</Alert> : null}
        {data && data.length === 0 ? (
          <EmptyState title="Гэрээ олдсонгүй" action={<ButtonLink href="/deals/new">Шинэ гэрээ</ButtonLink>} />
        ) : null}
        {data?.map((d) => (
          <DealCard key={d.id} deal={d} />
        ))}
      </div>
    </div>
  );
}

export function DealHistory() {
  return <AuthGuard>{() => <List />}</AuthGuard>;
}
