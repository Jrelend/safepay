"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { useSession } from "@/lib/client/session";

// 24×24 stroke icons (paths only), so every item renders at the same size.
const ICONS = {
  home: "M3 10.5 12 3l9 7.5V21h-6v-6H9v6H3z",
  deals: "M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01",
  plus: "M12 5v14M5 12h14",
  bell: "M18 8a6 6 0 1 0-12 0c0 7-3 9-3 9h18s-3-2-3-9M13.73 21a2 2 0 0 1-3.46 0",
  user: "M20 21a8 8 0 0 0-16 0M12 13a4 4 0 1 0 0-8 4 4 0 0 0 0 8",
} as const;

const ITEMS = [
  { href: "/dashboard", label: "Нүүр", icon: ICONS.home },
  { href: "/deals", label: "Гэрээ", icon: ICONS.deals },
  { href: "/deals/new", label: "Шинэ", icon: ICONS.plus },
  { href: "/notifications", label: "Мэдэгдэл", icon: ICONS.bell },
  { href: "/profile", label: "Профайл", icon: ICONS.user },
] as const;

function isActive(pathname: string, href: string): boolean {
  if (href === "/deals") return pathname === "/deals" || (pathname.startsWith("/deals/") && pathname !== "/deals/new");
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function BottomNav() {
  const session = useSession();
  const pathname = usePathname();
  if (session.status !== "authenticated") return null;
  return (
    <nav
      aria-label="Үндсэн цэс"
      className="bg-surface/95 border-border fixed inset-x-0 bottom-0 z-20 border-t pb-[env(safe-area-inset-bottom)] backdrop-blur"
    >
      <ul className="mx-auto flex max-w-md">
        {ITEMS.map((item) => {
          const active = isActive(pathname, item.href);
          return (
            <li key={item.href} className="flex-1">
              <Link
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={`flex min-h-14 flex-col items-center justify-center gap-0.5 text-[11px] ${
                  active ? "text-brand font-semibold" : "text-muted hover:text-foreground"
                }`}
              >
                <span
                  aria-hidden
                  className={`grid size-7 place-items-center ${item.href === "/deals/new" ? "bg-brand text-brand-foreground rounded-full" : ""}`}
                >
                  <svg viewBox="0 0 24 24" className="size-5" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
                    <path d={item.icon} />
                  </svg>
                </span>
                {item.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
