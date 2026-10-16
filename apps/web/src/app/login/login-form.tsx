"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

import { Alert, Button, Card, Field, PageTitle, WIDTH } from "@/components/ui";
import { api, ApiError } from "@/lib/client/api";
import { safeNext, useSession } from "@/lib/client/session";
import type { Me } from "@/lib/types";

export function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const { setMe, refresh } = useSession();
  useEffect(() => {
    // Arriving here (e.g. after logout) must reflect the server's view of the session.
    void refresh();
  }, [refresh]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    setBusy(true);
    setError(null);
    try {
      const me = await api<Me>("/auth/login", {
        json: { email: String(form.get("email")).trim(), password: String(form.get("password")) },
      });
      setMe(me);
      router.replace(safeNext(params.get("next")));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Алдаа гарлаа.");
      setBusy(false);
    }
  }

  return (
    <div className={WIDTH.narrow}>
      <PageTitle title="Нэвтрэх" subtitle="Гэрээнүүдээ удирдахын тулд нэвтэрнэ үү." />
      {params.get("verified") ? (
        <div className="mb-4">
          <Alert tone="success">Имэйл баталгаажлаа. Одоо нэвтэрнэ үү.</Alert>
        </div>
      ) : null}
      {params.get("reset") ? (
        <div className="mb-4">
          <Alert tone="success">Нууц үг шинэчлэгдлээ. Шинэ нууц үгээрээ нэвтэрнэ үү.</Alert>
        </div>
      ) : null}
      <Card>
        <form onSubmit={onSubmit} className="space-y-4">
          <Field label="Имэйл" name="email" type="email" required autoComplete="email" inputMode="email" />
          <Field label="Нууц үг" name="password" type="password" required autoComplete="current-password" />
          {error ? <Alert tone="danger">{error}</Alert> : null}
          <Button type="submit" loading={busy} className="w-full">
            Нэвтрэх
          </Button>
        </form>
      </Card>
      <div className="mt-4 flex flex-col items-center gap-2 text-sm">
        <Link href="/forgot-password" className="text-brand">
          Нууц үгээ мартсан уу?
        </Link>
        <span className="text-muted">
          Шинэ хэрэглэгч үү?{" "}
          <Link href="/register" className="text-brand font-semibold">
            Бүртгүүлэх
          </Link>
        </span>
      </div>
    </div>
  );
}
