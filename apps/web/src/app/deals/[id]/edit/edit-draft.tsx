"use client";

import { useParams, useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { AuthGuard } from "@/components/auth-guard";
import { DealTermsFields, readTerms } from "@/components/deal-terms-fields";
import { Alert, Button, Card, PageTitle, Skeleton, WIDTH } from "@/components/ui";
import { api, ApiError } from "@/lib/client/api";
import { useApi } from "@/lib/client/use-api";
import type { Deal } from "@/lib/types";

function Form() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const deal = useApi<Deal>(`/deals/${id}`);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (deal.loading && !deal.data) return <Skeleton />;
  if (!deal.data) return <Alert tone="danger">{deal.error?.message ?? "Олдсонгүй."}</Alert>;
  const d = deal.data;
  if (d.status !== "DRAFT" || !d.created_by_me) {
    return (
      <div className="space-y-4">
        <PageTitle title="Нөхцөл засах" back={`/deals/${id}`} />
        <Alert tone="warning">Зөвхөн гэрээ үүсгэсэн тал ноорог төлөвт засах боломжтой.</Alert>
      </div>
    );
  }

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const { terms, errors: fieldErrors } = readTerms(new FormData(e.currentTarget));
    setErrors(fieldErrors);
    if (Object.keys(fieldErrors).length) return;
    setBusy(true);
    setError(null);
    try {
      await api(`/deals/${id}`, { method: "PATCH", json: { ...terms, expected_version: d.version } });
      router.push(`/deals/${id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Алдаа гарлаа.");
      setBusy(false);
    }
  }

  return (
    <div className={WIDTH.form}>
      <PageTitle title="Нөхцөл засах" subtitle={d.reference} back={`/deals/${id}`} />
      <form onSubmit={onSubmit} className="space-y-4">
        <Card className="space-y-4">
          <DealTermsFields
            errors={errors}
            defaults={{
              title: d.title,
              description: d.description,
              amount_mnt: d.amount_mnt,
              item_type: d.item_type,
              delivery_method: d.delivery_method,
              inspection_days: d.inspection_days,
            }}
          />
        </Card>
        {error ? <Alert tone="danger">{error}</Alert> : null}
        <Button type="submit" loading={busy} className="w-full">
          Хадгалах
        </Button>
      </form>
    </div>
  );
}

export function EditDraft() {
  return <AuthGuard verified>{() => <Form />}</AuthGuard>;
}
