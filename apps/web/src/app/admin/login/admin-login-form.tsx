"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Icon } from "@/components/icons";
import { Alert, Button, Card, Field, PageTitle, WIDTH } from "@/components/ui";
import { api, ApiError } from "@/lib/client/api";
import { signInAsAdmin, useDemoAccounts } from "@/lib/client/demo";

function safeAdminNext(next: string | null): string {
  return next && next.startsWith("/admin") && !next.startsWith("//") ? next : "/admin";
}

export function AdminLoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const demoAdmin = useDemoAccounts()?.find((a) => a.key === "admin");

  async function demoSignIn() {
    if (!demoAdmin) return;
    setBusy(true);
    setError(null);
    try {
      await signInAsAdmin(demoAdmin);
      router.replace(safeAdminNext(params.get("next")));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Алдаа гарлаа.");
      setBusy(false);
    }
  }

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    setBusy(true);
    setError(null);
    try {
      await api("/admin/auth/login", {
        json: {
          email: String(form.get("email")).trim(),
          password: String(form.get("password")),
          code: String(form.get("code")).replace(/\s/g, ""),
        },
      });
      router.replace(safeAdminNext(params.get("next")));
    } catch (err) {
      setError(
        err instanceof ApiError && err.code === "invalid_credentials"
          ? "Имэйл, админ нууц үг эсвэл баталгаажуулах код буруу байна."
          : err instanceof ApiError
            ? err.message
            : "Алдаа гарлаа.",
      );
      setBusy(false);
    }
  }

  return (
    <div className={WIDTH.narrow}>
      <span aria-hidden className="bg-mark text-mark-foreground mb-4 grid size-11 place-items-center rounded-xl">
        <Icon name="key" />
      </span>
      <PageTitle
        title="Админ нэвтрэх"
        subtitle="Зөвхөн SafePay ажилтанд. Тусдаа админ нууц үг болон баталгаажуулах апп-ын 6 оронтой код шаардлагатай."
      />
      {demoAdmin ? (
        <Card className="mb-4 space-y-3" data-testid="demo-admin-login">
          <p className="text-muted text-[13px]">
            Демо орчин: админ нууц үг болон 6 оронтой кодыг автоматаар бөглөнө.
          </p>
          <Button variant="secondary" className="w-full" disabled={busy} onClick={() => void demoSignIn()}>
            <Icon name="scale" className="size-4" />
            Демо админаар нэвтрэх
          </Button>
        </Card>
      ) : null}
      <Card>
        <form onSubmit={onSubmit} className="space-y-4">
          <Field label="Имэйл" name="email" type="email" required autoComplete="username" />
          <Field label="Админ нууц үг" name="password" type="password" required autoComplete="current-password" />
          <Field
            label="Баталгаажуулах код"
            name="code"
            required
            inputMode="numeric"
            autoComplete="one-time-code"
            pattern="[0-9 ]{6,7}"
            maxLength={7}
            hint="Authenticator апп дээрх 6 оронтой код."
          />
          {error ? <Alert tone="danger">{error}</Alert> : null}
          <Button type="submit" loading={busy} className="w-full">
            Нэвтрэх
          </Button>
        </form>
      </Card>
    </div>
  );
}
