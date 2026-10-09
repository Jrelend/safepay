"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { AuthGuard } from "@/components/auth-guard";
import { DealTermsFields, readTerms } from "@/components/deal-terms-fields";
import { Alert, Button, Card, Field, PageTitle } from "@/components/ui";
import { api, ApiError } from "@/lib/client/api";
import type { Deal, Role } from "@/lib/types";

function Form() {
  const router = useRouter();
  const [role, setRole] = useState<Role>("SELLER");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    const { terms, errors: fieldErrors } = readTerms(form);
    setErrors(fieldErrors);
    if (Object.keys(fieldErrors).length) return;
    setBusy(true);
    setError(null);
    try {
      const counterparty = String(form.get("counterparty_email") ?? "").trim();
      const res = await api<{ deal: Deal; invite_url: string }>("/deals", {
        json: { ...terms, my_role: role, counterparty_email: counterparty || null },
      });
      sessionStorage.setItem(`invite:${res.deal.id}`, res.invite_url);
      router.push(`/deals/${res.deal.id}?created=1`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Алдаа гарлаа.");
      setBusy(false);
    }
  }

  return (
    <div>
      <PageTitle title="Шинэ гэрээ" subtitle="Нөхцөлөө бичээд нөгөө талдаа урилга илгээнэ." back="/dashboard" />
      <form onSubmit={onSubmit} className="space-y-4">
        <Card className="space-y-3">
          <fieldset>
            <legend className="mb-2 text-sm font-medium">Би энэ гэрээнд</legend>
            <div className="grid grid-cols-2 gap-2">
              {(["SELLER", "BUYER"] as const).map((r) => (
                <label
                  key={r}
                  className={`flex min-h-12 cursor-pointer items-center justify-center rounded-xl border text-sm font-medium ${
                    role === r ? "border-brand bg-brand-soft text-brand" : "border-border"
                  }`}
                >
                  <input
                    type="radio"
                    name="my_role"
                    value={r}
                    checked={role === r}
                    onChange={() => setRole(r)}
                    className="sr-only"
                  />
                  {r === "SELLER" ? "Худалдагч" : "Худалдан авагч"}
                </label>
              ))}
            </div>
          </fieldset>
        </Card>
        <Card className="space-y-4">
          <DealTermsFields errors={errors} />
        </Card>
        <Card className="space-y-2">
          <Field
            label={role === "SELLER" ? "Худалдан авагчийн имэйл (заавал биш)" : "Худалдагчийн имэйл (заавал биш)"}
            name="counterparty_email"
            type="email"
            autoComplete="off"
            hint="Бичвэл урилгын холбоосоор зөвхөн энэ имэйлээр бүртгэлтэй хүн нэгдэж чадна."
          />
        </Card>
        {error ? <Alert tone="danger">{error}</Alert> : null}
        <Button type="submit" loading={busy} className="w-full">
          Гэрээ үүсгэх
        </Button>
      </form>
    </div>
  );
}

export function NewDealForm() {
  return <AuthGuard verified>{() => <Form />}</AuthGuard>;
}
