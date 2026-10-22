"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

import { Icon } from "@/components/icons";
import { Alert, Button, Card, Field, PageTitle, WIDTH } from "@/components/ui";
import { api, ApiError } from "@/lib/client/api";
import { signInAsAdmin, signInAsParty, useDemoAccounts, type DemoAccount } from "@/lib/client/demo";
import { safeNext, useSession } from "@/lib/client/session";
import type { Me } from "@/lib/types";

const DEMO_LABEL = { buyer: "Худалдан авагч", seller: "Худалдагч", admin: "Админ" } as const;

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
  const demoAccounts = useDemoAccounts();

  async function demoSignIn(account: DemoAccount) {
    setBusy(true);
    setError(null);
    try {
      if (account.key === "admin") {
        await signInAsAdmin(account);
        router.replace("/admin");
      } else {
        setMe(await signInAsParty(account));
        router.replace("/dashboard");
      }
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
      {demoAccounts ? (
        <Card className="mb-4 space-y-3" data-testid="demo-login">
          <div>
            <h2 className="text-sm font-semibold">Демо бүртгэлээр нэг товшилтоор нэвтрэх</h2>
            <p className="text-muted text-[13px]">Туршилтын мөнгө. Бодит төлбөр огт хийгдэхгүй.</p>
          </div>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
            {demoAccounts.map((a) => (
              <Button key={a.key} variant="secondary" disabled={busy} onClick={() => void demoSignIn(a)}>
                <Icon name={a.key === "admin" ? "scale" : a.key === "buyer" ? "wallet" : "inbox"} className="size-4" />
                {DEMO_LABEL[a.key]}
              </Button>
            ))}
          </div>
        </Card>
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
