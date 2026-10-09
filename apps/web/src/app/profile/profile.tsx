"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { AuthGuard, VerifyFirst } from "@/components/auth-guard";
import { Alert, Button, Card, DefinitionList, Field, PageTitle } from "@/components/ui";
import { api, ApiError } from "@/lib/client/api";
import { useSession } from "@/lib/client/session";
import { formatDateTime } from "@/lib/format";
import type { Me } from "@/lib/types";

function Content({ me }: { me: Me }) {
  const { setMe } = useSession();
  const router = useRouter();
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      const updated = await api<Me>("/me/profile", {
        method: "PATCH",
        json: {
          display_name: String(form.get("display_name")).trim(),
          phone_e164: String(form.get("phone_e164")).trim(),
        },
      });
      setMe(updated);
      setSaved(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Алдаа гарлаа.");
    } finally {
      setBusy(false);
    }
  }

  async function logout() {
    try {
      await api("/auth/logout", { json: {} });
    } finally {
      // The login page re-reads the session on mount, so the header and guards
      // update after this page has unmounted (no redirect race with the guard).
      router.replace("/login");
    }
  }

  return (
    <div className="space-y-4">
      <PageTitle title="Профайл" />
      {!me.email_verified ? <VerifyFirst email={me.email} /> : null}
      <Card>
        <DefinitionList
          items={[
            ["Имэйл", me.email],
            ["Баталгаажсан", me.email_verified ? "Тийм ✓" : "Үгүй"],
            ["Бүртгүүлсэн", formatDateTime(me.created_at)],
          ]}
        />
      </Card>
      <Card>
        <form onSubmit={onSubmit} className="space-y-4">
          <Field label="Нэр" name="display_name" defaultValue={me.display_name} required minLength={2} maxLength={100} />
          <Field
            label="Утас (заавал биш)"
            name="phone_e164"
            type="tel"
            defaultValue={me.phone_e164 ?? ""}
            placeholder="+97699112233"
            hint="Гэрээний нөгөө талд харагдана."
          />
          {saved ? <Alert tone="success">Хадгалагдлаа.</Alert> : null}
          {error ? <Alert tone="danger">{error}</Alert> : null}
          <Button type="submit" loading={busy} className="w-full">
            Хадгалах
          </Button>
        </form>
      </Card>
      <Link
        href="/security"
        className="bg-surface border-border flex min-h-12 items-center justify-between rounded-2xl border px-4 font-medium"
      >
        Аюулгүй байдал ба нууц үг <span aria-hidden>›</span>
      </Link>
      <Button variant="secondary" onClick={logout} className="w-full">
        Гарах
      </Button>
    </div>
  );
}

export function Profile() {
  return <AuthGuard>{(me) => <Content me={me} />}</AuthGuard>;
}
