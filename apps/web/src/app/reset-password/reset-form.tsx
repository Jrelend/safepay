"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Alert, Button, Card, Field, PageTitle, WIDTH } from "@/components/ui";
import { api, ApiError } from "@/lib/client/api";
import { useSession } from "@/lib/client/session";

export function ResetPasswordForm() {
  const token = useSearchParams().get("token");
  const router = useRouter();
  const { setMe } = useSession();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    const password = String(form.get("password"));
    if (password !== String(form.get("confirm"))) {
      setError("Нууц үгнүүд таарахгүй байна.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api("/auth/password-reset/confirm", { json: { token, new_password: password } });
      setMe(null); // every session was revoked
      router.replace("/login?reset=1");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Алдаа гарлаа.");
      setBusy(false);
    }
  }

  return (
    <div className={WIDTH.narrow}>
      <PageTitle title="Шинэ нууц үг" subtitle="Шинэчилсний дараа бүх төхөөрөмжөөс гарна." />
      {!token ? (
        <Alert tone="danger">Холбоос дутуу байна.</Alert>
      ) : (
        <Card>
          <form onSubmit={onSubmit} className="space-y-4">
            <Field
              label="Шинэ нууц үг"
              name="password"
              type="password"
              required
              minLength={10}
              maxLength={128}
              autoComplete="new-password"
              hint="Хамгийн багадаа 10 тэмдэгт."
            />
            <Field label="Нууц үг давтах" name="confirm" type="password" required autoComplete="new-password" />
            {error ? <Alert tone="danger">{error}</Alert> : null}
            <Button type="submit" loading={busy} className="w-full">
              Хадгалах
            </Button>
          </form>
        </Card>
      )}
    </div>
  );
}
