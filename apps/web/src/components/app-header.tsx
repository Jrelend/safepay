"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Suspense } from "react";

import { Icon } from "@/components/icons";
import { NAV_ITEMS, isActive, isAdminPath } from "@/components/nav-items";
import { useSession } from "@/lib/client/session";
import { mn } from "@/lib/i18n/mn";

function Logo({ href }: { href: string }) {
  return (
    <Link href={href} className="flex min-h-11 items-center gap-2.5 rounded-lg font-semibold">
      <span
        aria-hidden
        className="bg-mark text-mark-foreground ring-border grid size-8 ring-1 place-items-center rounded-lg"
      >
        <Icon name="shieldCheck" className="size-[18px]" />
      </span>
      <span className="text-[17px] tracking-tight">{mn.appName}</span>
      <span className="border-border-strong/50 text-muted rounded-md border px-1.5 py-px text-[11px] font-semibold">
        Beta
      </span>
    </Link>
  );
}

function DesktopNav() {
  const pathname = usePathname();
  if (isAdminPath(pathname)) {
    return (
      <span className="bg-warning-soft text-warning border-warning-border hidden rounded-full border px-3 py-1 text-xs font-semibold whitespace-nowrap sm:inline-block">
        Админ горим
      </span>
    );
  }
  return (
    <nav aria-label="Үндсэн цэс" className="hidden md:block">
      <ul className="flex items-center gap-1">
        {NAV_ITEMS.filter((i) => i.href !== "/profile").map((item) => {
          const active = isActive(pathname, item.href);
          if (item.href === "/deals/new") {
            return (
              <li key={item.href} className="ml-2">
                <Link
                  href={item.href}
                  aria-current={active ? "page" : undefined}
                  className="bg-primary text-primary-foreground hover:bg-primary-hover inline-flex min-h-10 items-center gap-1.5 rounded-xl px-3.5 text-sm font-semibold"
                >
                  <Icon name="plus" className="size-4" />
                  {item.label}
                </Link>
              </li>
            );
          }
          return (
            <li key={item.href}>
              <Link
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={`inline-flex min-h-10 items-center rounded-xl px-3 text-sm font-medium ${
                  active ? "bg-brand-soft text-brand" : "text-muted hover:text-foreground hover:bg-surface-muted"
                }`}
              >
                {item.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

export function AppHeader() {
  const session = useSession();
  const authed = session.status === "authenticated";
  return (
    <header className="bg-surface/95 border-border sticky top-0 z-20 border-b backdrop-blur">
      <div className="mx-auto flex h-16 max-w-5xl items-center justify-between gap-4 px-4 sm:px-6">
        <Logo href={authed ? "/dashboard" : "/"} />
        {authed ? (
          <div className="flex items-center gap-2">
            <Suspense fallback={null}>
              <DesktopNav />
            </Suspense>
            {session.me.is_admin ? (
              <Link
                href="/admin"
                className="text-brand hover:bg-brand-soft inline-flex min-h-10 items-center rounded-xl px-3 text-sm font-medium"
              >
                Админ
              </Link>
            ) : null}
            <Link
              href="/profile"
              aria-label="Профайл"
              className="bg-brand-soft text-brand ring-border grid size-10 place-items-center rounded-full text-sm font-bold ring-1"
            >
              {session.me.display_name.slice(0, 1).toUpperCase()}
            </Link>
          </div>
        ) : session.status === "anonymous" ? (
          <div className="flex items-center gap-1">
            <Link
              href="/login"
              className="text-foreground hover:bg-surface-muted inline-flex min-h-10 items-center rounded-xl px-3 text-sm font-semibold"
            >
              Нэвтрэх
            </Link>
            <Link
              href="/register"
              className="bg-primary text-primary-foreground hover:bg-primary-hover hidden min-h-10 items-center rounded-xl px-3.5 text-sm font-semibold sm:inline-flex"
            >
              Бүртгүүлэх
            </Link>
          </div>
        ) : null}
      </div>
    </header>
  );
}
