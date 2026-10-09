"use client";

import { useState, type FormEvent } from "react";

import { AdminGuard } from "@/components/admin-guard";
import { Alert, Button, Card, Field, PageTitle, Skeleton } from "@/components/ui";
import { api, ApiError } from "@/lib/client/api";
import { useApi } from "@/lib/client/use-api";
import type { AdminUser } from "@/lib/types";

function Content() {
  const [q, setQ] = useState("");
  const users = useApi<AdminUser[]>(`/admin/users?q=${encodeURIComponent(q)}`);
  const [target, setTarget] = useState<AdminUser | null>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function apply() {
    if (!target) return;
    setBusy(true);
    setError(null);
    try {
      await api(`/admin/users/${target.id}/status`, {
        json: { status: target.status === "ACTIVE" ? "SUSPENDED" : "ACTIVE", reason: reason.trim() },
      });
      setTarget(null);
      setReason("");
      await users.reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Алдаа гарлаа.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      <PageTitle title="Хэрэглэгчид" />
      <form
        onSubmit={(e: FormEvent<HTMLFormElement>) => {
          e.preventDefault();
          setQ(String(new FormData(e.currentTarget).get("q")));
        }}
        className="flex items-end gap-2"
      >
        <div className="flex-1">
          <Field label="Хайх (имэйл, нэр)" name="q" type="search" />
        </div>
        <Button type="submit" variant="secondary">
          Хайх
        </Button>
      </form>
      {users.loading && !users.data ? <Skeleton /> : null}
      {users.error ? <Alert tone="danger">{users.error.message}</Alert> : null}
      <ul className="space-y-2">
        {users.data?.map((u) => (
          <li key={u.id}>
            <Card className="space-y-2">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="font-medium">
                    {u.display_name} {u.is_admin ? <span className="text-brand text-xs">· админ</span> : null}
                  </div>
                  <div className="text-muted text-xs break-all">{u.email}</div>
                </div>
                <span
                  className={`rounded-full px-2 py-0.5 text-xs ${u.status === "ACTIVE" ? "bg-emerald-100 text-emerald-800" : "bg-rose-100 text-rose-800"}`}
                >
                  {u.status === "ACTIVE" ? "Идэвхтэй" : "Түдгэлзүүлсэн"}
                </span>
              </div>
              {target?.id === u.id ? (
                <div className="space-y-2">
                  <Field label="Шалтгаан (заавал)" value={reason} onChange={(e) => setReason(e.target.value)} minLength={5} />
                  <div className="grid grid-cols-2 gap-2">
                    <Button variant="secondary" onClick={() => setTarget(null)}>
                      Болих
                    </Button>
                    <Button variant="danger" loading={busy} disabled={reason.trim().length < 5} onClick={apply}>
                      Батлах
                    </Button>
                  </div>
                </div>
              ) : (
                <Button variant="ghost" onClick={() => setTarget(u)} className="w-full">
                  {u.status === "ACTIVE" ? "Түдгэлзүүлэх" : "Сэргээх"}
                </Button>
              )}
            </Card>
          </li>
        ))}
      </ul>
      {error ? <Alert tone="danger">{error}</Alert> : null}
    </div>
  );
}

export function AdminUsers() {
  return (
    <AdminGuard>
      <Content />
    </AdminGuard>
  );
}
