import Link from "next/link";

import { mn } from "@/lib/i18n/mn";

const ITEMS = [
  { href: "/", label: mn.nav.home, icon: "⌂" },
  { href: "/status", label: mn.nav.system, icon: "◎" },
] as const;

export function BottomNav() {
  return (
    <nav
      aria-label="Үндсэн цэс"
      className="bg-surface border-border fixed inset-x-0 bottom-0 z-10 border-t pb-[env(safe-area-inset-bottom)]"
    >
      <ul className="mx-auto flex max-w-md">
        {ITEMS.map((item) => (
          <li key={item.href} className="flex-1">
            <Link
              href={item.href}
              className="text-muted hover:text-foreground flex min-h-14 flex-col items-center justify-center gap-0.5 text-xs"
            >
              <span aria-hidden className="text-lg leading-none">
                {item.icon}
              </span>
              {item.label}
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}
