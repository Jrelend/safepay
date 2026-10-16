"use client";

import { useParams, useRouter } from "next/navigation";
import { useState } from "react";

import { AuthGuard } from "@/components/auth-guard";
import { TestPaymentNotice } from "@/components/test-payment-notice";
import { Alert, Button, Card, DefinitionList, Money, PageTitle, Skeleton, WIDTH } from "@/components/ui";
import { api, ApiError } from "@/lib/client/api";
import { useApi } from "@/lib/client/use-api";
import { DELIVERY_LABEL, ITEM_TYPE_LABEL, ROLE_LABEL } from "@/lib/format";
import type { Deal, InvitePreview } from "@/lib/types";

function View() {
  const { token } = useParams<{ token: string }>();
  const router = useRouter();
  const preview = useApi<InvitePreview>(`/invites/${encodeURIComponent(token)}`);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (preview.loading && !preview.data) return <Skeleton />;
  if (!preview.data) {
    return (
      <div className={`${WIDTH.narrow} space-y-4`}>
        <PageTitle title="Гэрээний урилга" />
        <Alert tone="danger">{preview.error?.message ?? "Урилга олдсонгүй."}</Alert>
      </div>
    );
  }
  const p = preview.data;

  async function join() {
    setBusy(true);
    setError(null);
    try {
      const deal = await api<Deal>(`/invites/${encodeURIComponent(token)}/join`, { json: {} });
      router.replace(`/deals/${deal.id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Алдаа гарлаа.");
      setBusy(false);
    }
  }

  return (
    <div className={`${WIDTH.narrow} space-y-4`}>
      <PageTitle title="Гэрээний урилга" subtitle={`${p.creator_name} таныг гэрээнд урьж байна.`} />
      <Card className="space-y-4">
        <div>
          <div className="text-muted text-xs">{p.reference}</div>
          <div className="text-lg leading-snug font-semibold">{p.title}</div>
        </div>
        <Money value={p.amount_mnt} className="block text-[32px] leading-tight font-bold tracking-tight" />
        <TestPaymentNotice />
        <DefinitionList
          items={[
            ["Таны үүрэг", <strong key="role">{ROLE_LABEL[p.offered_role]}</strong>],
            ["Төрөл", ITEM_TYPE_LABEL[p.item_type]],
            ["Хүлээлгэн өгөх", DELIVERY_LABEL[p.delivery_method]],
            ["Шалгах хугацаа", `${p.inspection_days} хоног`],
          ]}
        />
        {p.description ? (
          <div className="border-border border-t pt-3">
            <div className="text-muted mb-1 text-xs font-medium">Тайлбар</div>
            <p className="text-sm whitespace-pre-wrap">{p.description}</p>
          </div>
        ) : null}
      </Card>
      <ol aria-label="Дараагийн алхмууд" className="bg-surface-muted space-y-2 rounded-2xl p-4 text-sm">
        {[
          "Нэгдсэнээр нөхцөлийг шууд зөвшөөрөхгүй.",
          "Гэрээний хуудаснаас нөхцөлийг уншаад зөвшөөрнө эсвэл татгалзана.",
          "Хоёр тал зөвшөөрөх хүртэл мөнгө хөдлөхгүй.",
        ].map((t, i) => (
          <li key={t} className="flex gap-2.5">
            <span
              aria-hidden
              className="bg-surface text-muted grid size-5 shrink-0 place-items-center rounded-full text-[11px] font-bold"
            >
              {i + 1}
            </span>
            {t}
          </li>
        ))}
      </ol>
      {error ? <Alert tone="danger">{error}</Alert> : null}
      <Button onClick={join} loading={busy} className="w-full">
        Гэрээнд нэгдэх
      </Button>
    </div>
  );
}

export function InviteView() {
  return <AuthGuard verified>{() => <View />}</AuthGuard>;
}
