"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";

import { Alert, Button, Card, Field, PageTitle } from "@/components/ui";
import { api, ApiError } from "@/lib/client/api";

export function RegisterForm() {
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
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
      const email = String(form.get("email")).trim();
      await api("/auth/register", {
        json: { email, password, display_name: String(form.get("display_name")).trim() },
      });
      setDone(email);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Алдаа гарлаа.");
    } finally {
      setBusy(false);
    }
  }

  if (done) {
    return (
      <div className="space-y-4">
        <PageTitle title="Имэйлээ шалгана уу" />
        <Alert tone="success" title="Бүртгэлийн хүсэлт хүлээн авлаа">
          Хэрэв <strong>{done}</strong> хаяг шинэ бол баталгаажуулах холбоос илгээгдсэн. Аль хэдийн бүртгэлтэй
          бол нэвтрэх заавар очно.
        </Alert>
        <p className="text-muted text-sm">
          Beta хувилбарт бодит имэйл илгээхгүй. Орон нутгийн хөгжүүлэлтийн орчинд{" "}
          <Link href="/dev/mailbox" className="text-brand underline">
            туршилтын шуудан
          </Link>
          -аас холбоосоо авна уу.
        </p>
        <Link href="/login" className="text-brand block text-center text-sm font-semibold">
          Нэвтрэх хуудас руу
        </Link>
      </div>
    );
  }

  return (
    <div>
      <PageTitle title="Бүртгүүлэх" subtitle="SafePay-д нэгдэж, худалдаагаа хамгаалаарай." />
      <Card>
        <form onSubmit={onSubmit} className="space-y-4" noValidate={false}>
          <Field label="Таны нэр" name="display_name" required minLength={2} maxLength={100} autoComplete="name" />
          <Field label="Имэйл" name="email" type="email" required autoComplete="email" inputMode="email" />
          <Field
            label="Нууц үг"
            name="password"
            type="password"
            required
            minLength={10}
            maxLength={128}
            autoComplete="new-password"
            hint="Хамгийн багадаа 10 тэмдэгт. Түгээмэл нууц үг ашиглахгүй."
          />
          <Field label="Нууц үг давтах" name="confirm" type="password" required autoComplete="new-password" />
          {error ? <Alert tone="danger">{error}</Alert> : null}
          <Button type="submit" loading={busy} className="w-full">
            Бүртгүүлэх
          </Button>
        </form>
      </Card>
      <p className="text-muted mt-4 text-center text-sm">
        Бүртгэлтэй юу?{" "}
        <Link href="/login" className="text-brand font-semibold">
          Нэвтрэх
        </Link>
      </p>
    </div>
  );
}
