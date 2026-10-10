"use client";

import Link from "next/link";

import { useSession } from "@/lib/client/session";
import { mn } from "@/lib/i18n/mn";

export function AppHeader() {
  const session = useSession();
  return (
    <header className="bg-surface/95 border-border sticky top-0 z-20 border-b backdrop-blur">
      <div className="mx-auto flex h-14 max-w-md md:max-w-2xl items-center justify-between px-4">
        <Link
          href={session.status === "authenticated" ? "/dashboard" : "/"}
          className="flex items-center gap-2 font-semibold"
        >
          <span
            aria-hidden
            className="bg-brand text-brand-foreground grid size-8 place-items-center rounded-lg text-sm font-bold"
          >
            SP
          </span>
          <span>{mn.appName}</span>
          <span className="border-border text-muted rounded-full border px-2 py-0.5 text-[11px] font-medium">
            Beta
          </span>
        </Link>
        {session.status === "authenticated" ? (
          <div className="flex items-center gap-2">
            {session.me.is_admin ? (
              <Link href="/admin" className="text-brand min-h-10 content-center px-2 text-sm font-medium">
                Админ
              </Link>
            ) : null}
            <Link
              href="/profile"
              aria-label="Профайл"
              className="bg-brand-soft text-brand grid size-9 place-items-center rounded-full text-sm font-bold"
            >
              {session.me.display_name.slice(0, 1).toUpperCase()}
            </Link>
          </div>
        ) : session.status === "anonymous" ? (
          <Link href="/login" className="text-brand min-h-10 content-center px-2 text-sm font-semibold">
            Нэвтрэх
          </Link>
        ) : null}
      </div>
    </header>
  );
}
