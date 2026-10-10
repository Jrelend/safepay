"use client";

import { useState, type FormEvent } from "react";

import { Alert, Button, Card, Field, PageTitle } from "@/components/ui";
import { api, ApiError } from "@/lib/client/api";

export function ForgotPasswordForm() {
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api("/auth/password-reset/request", {
        json: { email: String(new FormData(e.currentTarget).get("email")).trim() },
      });
      setSent(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Алдаа гарлаа.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <PageTitle title="Нууц үг сэргээх" back="/login" />
      {sent ? (
        <Alert tone="success" title="Хүсэлт хүлээн авлаа">
          Хэрэв энэ хаягаар бүртгэл байгаа бол нууц үг сэргээх холбоос илгээгдсэн. Холбоос 1 цагийн дотор хүчинтэй.
        </Alert>
      ) : (
        <Card>
          <form onSubmit={onSubmit} className="space-y-4">
            <Field label="Бүртгэлтэй имэйл" name="email" type="email" required autoComplete="email" />
            {error ? <Alert tone="danger">{error}</Alert> : null}
            <Button type="submit" loading={busy} className="w-full">
              Холбоос авах
            </Button>
          </form>
        </Card>
      )}
    </div>
  );
}
