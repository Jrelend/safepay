"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { AuthGuard } from "@/components/auth-guard";
import { DealCard } from "@/components/deal-card";
import { Icon } from "@/components/icons";
import { Alert, ButtonLink, EmptyState, PageTitle, SegmentedControl, Skeleton, WIDTH } from "@/components/ui";
import { useApi } from "@/lib/client/use-api";
import type { DealSummary } from "@/lib/types";

const TABS = [
  { value: "active", label: "Идэвхтэй" },
  { value: "closed", label: "Хаагдсан" },
  { value: "all", label: "Бүгд" },
] as const;

const EMPTY: Record<(typeof TABS)[number]["value"], string> = {
  active: "Одоо явагдаж буй гэрээ алга. Шинэ гэрээ үүсгээд холбоосоо нөгөө талдаа илгээнэ үү.",
  closed: "Дууссан, цуцлагдсан эсвэл буцаагдсан гэрээ энд харагдана.",
  all: "Та хараахан гэрээ хийгээгүй байна.",
};

function List() {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const scope = TABS.find((t) => t.value === params.get("scope"))?.value ?? "active";
  const { data, error, loading } = useApi<DealSummary[]>(`/deals?scope=${scope}`);

  return (
    <div className={WIDTH.form}>
      <PageTitle
        title="Миний гэрээнүүд"
        actions={
          <div className="hidden md:block">
            <ButtonLink href="/deals/new" size="sm">
              <Icon name="plus" className="size-4" />
              Шинэ гэрээ
            </ButtonLink>
          </div>
        }
      />
      <div className="mb-4">
        <SegmentedControl
          label="Гэрээний шүүлтүүр"
          options={TABS}
          value={scope}
          onChange={(v) => router.replace(`${pathname}?scope=${v}`)}
        />
      </div>
      <div className="space-y-3" aria-live="polite" aria-busy={loading || undefined}>
        {loading && !data ? <Skeleton /> : null}
        {error ? <Alert tone="danger">{error.message}</Alert> : null}
        {data && data.length === 0 ? (
          <EmptyState
            title="Гэрээ олдсонгүй"
            body={EMPTY[scope]}
            action={<ButtonLink href="/deals/new">Шинэ гэрээ</ButtonLink>}
          />
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
