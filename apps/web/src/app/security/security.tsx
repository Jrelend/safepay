"use client";

import { useState, type FormEvent } from "react";

import { AuthGuard } from "@/components/auth-guard";
import { Alert, Button, Card, CardTitle, Field, PageTitle, Skeleton, WIDTH } from "@/components/ui";
import { api, ApiError } from "@/lib/client/api";
import { useApi } from "@/lib/client/use-api";
import { formatDateTime } from "@/lib/format";
import type { SessionInfo } from "@/lib/types";

function device(ua: string): string {
  if (/iPhone|iPad/.test(ua)) return "iPhone / iPad";
  if (/Android/.test(ua)) return "Android";
  if (/Mac OS X/.test(ua)) return "Mac";
  if (/Windows/.test(ua)) return "Windows";
  if (/Linux/.test(ua)) return "Linux";
  return ua ? ua.slice(0, 40) : "Тодорхойгүй төхөөрөмж";
}

function Content() {
  const sessions = useApi<SessionInfo[]>("/auth/sessions");
  const [msg, setMsg] = useState<{ tone: "success" | "danger"; text: string } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  async function changePassword(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const formEl = e.currentTarget;
    const form = new FormData(formEl);
    if (form.get("new_password") !== form.get("confirm")) {
      setMsg({ tone: "danger", text: "Шинэ нууц үгнүүд таарахгүй байна." });
      return;
    }
    setBusy("password");
    setMsg(null);
    try {
      await api("/auth/password/change", {
        json: { current_password: form.get("current_password"), new_password: form.get("new_password") },
      });
      formEl.reset();
      setMsg({ tone: "success", text: "Нууц үг солигдлоо. Бусад төхөөрөмжөөс гаргалаа." });
      await sessions.reload();
    } catch (err) {
      setMsg({ tone: "danger", text: err instanceof ApiError ? err.message : "Алдаа гарлаа." });
    } finally {
      setBusy(null);
    }
  }

  async function run(id: string, fn: () => Promise<unknown>) {
    setBusy(id);
    try {
      await fn();
      await sessions.reload();
    } catch (err) {
      setMsg({ tone: "danger", text: err instanceof ApiError ? err.message : "Алдаа гарлаа." });
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className={`${WIDTH.form} space-y-4`}>
      <PageTitle title="Аюулгүй байдал" back="/profile" />
      {msg ? <Alert tone={msg.tone}>{msg.text}</Alert> : null}
      <Card aria-labelledby="password-title">
        <CardTitle id="password-title">Нууц үг солих</CardTitle>
        <form onSubmit={changePassword} className="space-y-4">
          <Field
            label="Одоогийн нууц үг"
            name="current_password"
            type="password"
            required
            autoComplete="current-password"
          />
          <Field
            label="Шинэ нууц үг"
            name="new_password"
            type="password"
            required
            minLength={10}
            maxLength={128}
            autoComplete="new-password"
          />
          <Field label="Шинэ нууц үг давтах" name="confirm" type="password" required autoComplete="new-password" />
          <Button type="submit" loading={busy === "password"} className="w-full">
            Солих
          </Button>
        </form>
      </Card>
      <Card aria-labelledby="sessions-title" className="space-y-3">
        <CardTitle id="sessions-title">Нэвтэрсэн төхөөрөмжүүд</CardTitle>
        {sessions.loading && !sessions.data ? <Skeleton lines={2} /> : null}
        <ul className="divide-border divide-y">
          {sessions.data?.map((s) => (
            <li key={s.id} className="flex items-center justify-between gap-3 py-3">
              <div className="min-w-0 text-sm">
                <div className="font-medium">
                  {device(s.user_agent)}{" "}
                  {s.current ? <span className="text-success text-xs font-semibold">· энэ төхөөрөмж</span> : null}
                </div>
                <div className="text-muted text-xs">
                  {s.ip_address} · сүүлд {formatDateTime(s.last_seen_at)}
                </div>
              </div>
              {!s.current ? (
                <Button
                  variant="dangerOutline"
                  size="sm"
                  loading={busy === s.id}
                  onClick={() => run(s.id, () => api(`/auth/sessions/${s.id}`, { method: "DELETE" }))}
                >
                  Гаргах
                </Button>
              ) : null}
            </li>
          ))}
        </ul>
        {sessions.data && sessions.data.length > 1 ? (
          <Button
            variant="secondary"
            className="w-full"
            loading={busy === "others"}
            onClick={() => run("others", () => api("/auth/sessions/revoke-others", { json: {} }))}
          >
            Бусад бүх төхөөрөмжөөс гаргах
          </Button>
        ) : null}
      </Card>
    </div>
  );
}

export function Security() {
  return <AuthGuard>{() => <Content />}</AuthGuard>;
}
