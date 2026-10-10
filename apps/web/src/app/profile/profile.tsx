"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Icon } from "@/components/icons";

import { AuthGuard, VerifyFirst } from "@/components/auth-guard";
import {
  Alert,
  Button,
  Card,
  CardTitle,
  DefinitionList,
  Field,
  PageTitle,
  SegmentedControl,
  WIDTH,
} from "@/components/ui";
import { api, ApiError } from "@/lib/client/api";
import { useSession } from "@/lib/client/session";
import { applyTheme, readTheme, type ThemePreference } from "@/lib/client/theme";
import { formatDateTime } from "@/lib/format";
import type { Me } from "@/lib/types";

function Content({ me }: { me: Me }) {
  const { setMe } = useSession();
  const router = useRouter();
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // Profile renders only on the client (behind AuthGuard), so localStorage is available here.
  const [theme, setTheme] = useState<ThemePreference>(() => (typeof window === "undefined" ? "system" : readTheme()));

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
    <div className={`${WIDTH.form} space-y-4`}>
      <PageTitle title="Профайл" />
      {!me.email_verified ? <VerifyFirst email={me.email} /> : null}
      <Card>
        <DefinitionList
          items={[
            ["Имэйл", me.email],
            [
              "Баталгаажсан",
              me.email_verified ? (
                <span key="v" className="text-success inline-flex items-center gap-1">
                  <Icon name="check" className="size-4" />
                  Тийм
                </span>
              ) : (
                "Үгүй"
              ),
            ],
            ["Бүртгүүлсэн", formatDateTime(me.created_at)],
          ]}
        />
      </Card>
      <Card aria-labelledby="details-title">
        <CardTitle id="details-title">Хувийн мэдээлэл</CardTitle>
        <form onSubmit={onSubmit} className="space-y-4">
          <Field
            label="Нэр"
            name="display_name"
            defaultValue={me.display_name}
            required
            minLength={2}
            maxLength={100}
          />
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
      <Card aria-labelledby="theme-title">
        <CardTitle id="theme-title">Харагдах байдал</CardTitle>
        <SegmentedControl
          label="Өнгөний горим"
          options={[
            { value: "system", label: "Төхөөрөмжөөр" },
            { value: "light", label: "Цайвар" },
            { value: "dark", label: "Бараан" },
          ]}
          value={theme}
          onChange={(t) => {
            setTheme(t);
            applyTheme(t);
          }}
        />
        <p className="text-muted mt-2 text-[13px]">Зөвхөн энэ хөтөч дээр хадгалагдана.</p>
      </Card>
      <Link
        href="/security"
        className="bg-surface border-border shadow-card hover:border-border-strong flex min-h-14 items-center justify-between gap-3 rounded-2xl border px-4 font-medium"
      >
        <span className="flex items-center gap-2">
          <Icon name="shield" className="text-muted size-[18px]" />
          Аюулгүй байдал ба нууц үг
        </span>
        <Icon name="chevronRight" className="text-muted size-5" />
      </Link>
      <Button variant="secondary" onClick={logout} className="w-full">
        <Icon name="logout" className="size-4" />
        Гарах
      </Button>
    </div>
  );
}

export function Profile() {
  return <AuthGuard>{(me) => <Content me={me} />}</AuthGuard>;
}
