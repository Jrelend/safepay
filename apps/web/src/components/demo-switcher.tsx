"use client";

import { usePathname } from "next/navigation";
import { useState } from "react";

import { Icon, type IconName } from "@/components/icons";
import { isAdminPath } from "@/components/nav-items";
import { ApiError } from "@/lib/client/api";
import {
  demoKeyOf,
  signInAsAdmin,
  signInAsParty,
  useDemoAccounts,
  type DemoAccount,
  type DemoKey,
} from "@/lib/client/demo";
import { useSession } from "@/lib/client/session";

const ROLE: Record<DemoKey, { label: string; icon: IconName }> = {
  buyer: { label: "Худалдан авагч", icon: "wallet" },
  seller: { label: "Худалдагч", icon: "inbox" },
  admin: { label: "Админ", icon: "scale" },
};

/** One-click account switching (LOCAL DEMO ONLY; renders nothing elsewhere). */
export function DemoSwitcher() {
  const accounts = useDemoAccounts();
  const { me } = useSession();
  const pathname = usePathname();
  const [busy, setBusy] = useState<DemoKey | null>(null);
  const [error, setError] = useState<string | null>(null);
  if (!accounts) return null;

  const current: DemoKey | null = isAdminPath(pathname) ? "admin" : demoKeyOf(accounts, me?.email);

  async function switchTo(account: DemoAccount) {
    setBusy(account.key);
    setError(null);
    try {
      if (account.key === "admin") await signInAsAdmin(account);
      else await signInAsParty(account);
      // A full page load: nothing loaded for the previous account may linger
      // (e.g. the dashboard is already mounted when switching from it).
      window.location.assign(account.key === "admin" ? "/admin" : "/dashboard");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Нэвтэрч чадсангүй.");
      setBusy(null);
    }
  }

  return (
    <div
      data-testid="demo-switcher"
      className="bg-warning-soft border-warning-border text-foreground border-b px-4 py-2 text-sm"
    >
      <div className="mx-auto flex max-w-5xl flex-wrap items-center gap-x-3 gap-y-2">
        <span className="text-warning flex items-center gap-1.5 text-xs font-bold tracking-wide uppercase">
          <Icon name="users" className="size-4" />
          Демо: хэн болж харах вэ?
        </span>
        <div role="group" aria-label="Демо бүртгэл сонгох" className="flex flex-wrap gap-1.5">
          {accounts.map((a) => {
            const active = current === a.key;
            return (
              <button
                key={a.key}
                type="button"
                aria-pressed={active}
                disabled={busy !== null}
                onClick={() => void switchTo(a)}
                className={`inline-flex min-h-9 items-center gap-1.5 rounded-full border px-3 text-[13px] font-semibold transition-colors disabled:opacity-60 ${
                  active
                    ? "bg-primary text-primary-foreground border-primary"
                    : "bg-surface border-border hover:border-border-strong"
                }`}
              >
                <Icon name={ROLE[a.key].icon} className="size-4" />
                {ROLE[a.key].label}
                {busy === a.key ? <span className="sr-only">(нэвтэрч байна)</span> : null}
              </button>
            );
          })}
        </div>
        {error ? (
          <span role="alert" className="text-danger text-xs font-medium">
            {error}
          </span>
        ) : null}
      </div>
    </div>
  );
}
