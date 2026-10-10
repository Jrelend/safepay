"use client";

import { useRouter } from "next/navigation";
import { useRef, useState, type FormEvent, type ReactNode } from "react";

import { AuthGuard } from "@/components/auth-guard";
import { DealTermsFields, readTerms } from "@/components/deal-terms-fields";
import { Icon } from "@/components/icons";
import { Alert, Button, Card, Field, PageTitle, WIDTH } from "@/components/ui";
import { api, ApiError } from "@/lib/client/api";
import { focusFirstInvalid } from "@/lib/client/focus";
import type { Deal, Role } from "@/lib/types";

const ROLES: { value: Role; title: string; body: string }[] = [
  { value: "SELLER", title: "Худалдагч", body: "Би бараа, үйлчилгээ өгч, мөнгө хүлээн авна." },
  { value: "BUYER", title: "Худалдан авагч", body: "Би төлбөр байршуулж, бараагаа хүлээн авна." },
];

function Section({ n, title, children }: { n: number; title: string; children: ReactNode }) {
  return (
    <Card className="space-y-4">
      <h2 className="flex items-center gap-2.5 text-base font-semibold">
        <span
          aria-hidden
          className="bg-primary text-primary-foreground grid size-6 place-items-center rounded-full text-xs"
        >
          {n}
        </span>
        {title}
      </h2>
      {children}
    </Card>
  );
}

function Form() {
  const router = useRouter();
  const formRef = useRef<HTMLFormElement>(null);
  const [role, setRole] = useState<Role>("SELLER");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    const { terms, errors: fieldErrors } = readTerms(form);
    setErrors(fieldErrors);
    if (Object.keys(fieldErrors).length) {
      focusFirstInvalid(formRef.current);
      return;
    }
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

  const other = role === "SELLER" ? "Худалдан авагчийн" : "Худалдагчийн";

  return (
    <div className={WIDTH.form}>
      <PageTitle
        title="Шинэ гэрээ"
        subtitle="Нөхцөлөө бичээд нөгөө талдаа урилга илгээнэ. Хоёр тал зөвшөөрөх хүртэл мөнгө хөдлөхгүй."
        back="/dashboard"
      />
      <form ref={formRef} onSubmit={onSubmit} className="space-y-4">
        <Section n={1} title="Таны үүрэг">
          <fieldset>
            <legend className="sr-only">Би энэ гэрээнд</legend>
            <div className="grid gap-2 sm:grid-cols-2">
              {ROLES.map((r) => {
                const selected = role === r.value;
                return (
                  <label
                    key={r.value}
                    className={`relative flex min-h-16 cursor-pointer items-start gap-3 rounded-xl border-2 p-3 transition-colors has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-focus ${
                      selected ? "border-primary bg-surface-muted" : "border-border hover:border-border-strong"
                    }`}
                  >
                    <input
                      type="radio"
                      name="my_role"
                      value={r.value}
                      checked={selected}
                      onChange={() => setRole(r.value)}
                      className="sr-only"
                    />
                    <span
                      aria-hidden
                      className={`mt-0.5 grid size-5 shrink-0 place-items-center rounded-full border-2 ${
                        selected ? "border-primary bg-primary text-primary-foreground" : "border-border-strong"
                      }`}
                    >
                      {selected ? <Icon name="check" className="size-3" /> : null}
                    </span>
                    <span>
                      <span className={`block text-sm ${selected ? "font-bold" : "font-semibold"}`}>{r.title}</span>
                      <span className="text-muted block text-[13px] leading-snug">{r.body}</span>
                    </span>
                  </label>
                );
              })}
            </div>
          </fieldset>
        </Section>
        <Section n={2} title="Юу, хэдээр, яаж">
          <DealTermsFields errors={errors} />
        </Section>
        <Section n={3} title="Хэнтэй (заавал биш)">
          <Field
            label={`${other} имэйл (заавал биш)`}
            name="counterparty_email"
            type="email"
            autoComplete="off"
            hint="Бичвэл урилгын холбоосоор зөвхөн энэ имэйлээр бүртгэлтэй хүн нэгдэж чадна."
          />
        </Section>
        {error ? <Alert tone="danger">{error}</Alert> : null}
        <div className="bg-surface-muted text-muted flex gap-2 rounded-xl p-3 text-[13px] leading-snug">
          <Icon name="info" className="mt-0.5 size-4" />
          Гэрээ ноорог байдлаар үүснэ. Дараа нь нөхцөлөө шалгаж, нөгөө талдаа илгээнэ.
        </div>
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
