"use client";

import { useParams, useRouter } from "next/navigation";
import { useState } from "react";

import { AuthGuard } from "@/components/auth-guard";
import { TestPaymentNotice } from "@/components/test-payment-notice";
import { Alert, Button, Card, DefinitionList, Money, PageTitle, Skeleton } from "@/components/ui";
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
      <div className="space-y-4">
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
    <div className="space-y-4">
      <PageTitle title="Гэрээний урилга" subtitle={`${p.creator_name} таныг гэрээнд урьж байна.`} />
      <Card className="space-y-3">
        <div className="text-muted text-xs">{p.reference}</div>
        <div className="text-lg font-semibold">{p.title}</div>
        <Money value={p.amount_mnt} className="block text-3xl font-bold" />
        <TestPaymentNotice />
        <DefinitionList
          items={[
            ["Таны үүрэг", ROLE_LABEL[p.offered_role]],
            ["Төрөл", ITEM_TYPE_LABEL[p.item_type]],
            ["Хүлээлгэн өгөх", DELIVERY_LABEL[p.delivery_method]],
            ["Шалгах хугацаа", `${p.inspection_days} хоног`],
          ]}
        />
        {p.description ? <p className="text-sm whitespace-pre-wrap">{p.description}</p> : null}
      </Card>
      <Alert tone="info">
        Нэгдсэнээр нөхцөлийг шууд зөвшөөрөхгүй. Гэрээний хуудаснаас нөхцөлийг сайтар уншаад зөвшөөрнө үү.
      </Alert>
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
