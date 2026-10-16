"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { Icon } from "@/components/icons";
import { NAV_ITEMS, isActive, isAdminPath } from "@/components/nav-items";
import { useSession } from "@/lib/client/session";

/** Mobile tab bar (below md). Desktop navigation lives in the header. */
export function BottomNav() {
  const session = useSession();
  const pathname = usePathname();
  if (session.status !== "authenticated" || isAdminPath(pathname)) return null;
  return (
    <nav
      aria-label="Үндсэн цэс"
      className="bg-surface/95 border-border fixed inset-x-0 bottom-0 z-20 border-t pb-[env(safe-area-inset-bottom)] backdrop-blur md:hidden"
    >
      <ul className="mx-auto flex max-w-md">
        {NAV_ITEMS.map((item) => {
          const active = isActive(pathname, item.href);
          const create = item.href === "/deals/new";
          return (
            <li key={item.href} className="flex-1">
              <Link
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={`flex min-h-16 flex-col items-center justify-center gap-1 text-[11px] font-medium ${
                  active ? "text-brand" : "text-muted hover:text-foreground"
                }`}
              >
                <span
                  aria-hidden
                  className={`grid place-items-center rounded-full ${
                    create
                      ? "bg-primary text-primary-foreground shadow-card size-8"
                      : `h-7 w-12 ${active ? "bg-brand-soft" : ""}`
                  }`}
                >
                  <Icon name={item.icon} className="size-5" />
                </span>
                {item.short}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
