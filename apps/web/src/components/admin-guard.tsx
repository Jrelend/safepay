"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { Icon, type IconName } from "@/components/icons";
import { Alert, Button, Skeleton } from "@/components/ui";
import { api } from "@/lib/client/api";
import { useApi } from "@/lib/client/use-api";

type AdminMe = { id: string; email: string; display_name: string; session_expires_at: string };

const ADMIN_NAV: { href: string; label: string; icon: IconName }[] = [
  { href: "/admin", label: "Маргаан", icon: "scale" },
  { href: "/admin/users", label: "Хэрэглэгч", icon: "users" },
  { href: "/admin/audit", label: "Аудит", icon: "file" },
];

function adminActive(pathname: string, href: string): boolean {
  if (href === "/admin") return pathname === "/admin" || pathname.startsWith("/admin/disputes");
  return pathname === href || pathname.startsWith(`${href}/`);
}

/**
 * Admin pages require an ADMIN session (separate admin password + TOTP), not the
 * public login. The admin API enforces this independently.
 */
export function AdminGuard({ children }: { children: ReactNode }) {
  const me = useApi<AdminMe>("/admin/auth/me");
  const router = useRouter();
  const pathname = usePathname();
  const [leaving, setLeaving] = useState(false);
  const unauthenticated = me.error?.status === 401;

  useEffect(() => {
    if (unauthenticated) router.replace(`/admin/login?next=${encodeURIComponent(pathname)}`);
  }, [unauthenticated, router, pathname]);

  if (me.loading || unauthenticated) return <Skeleton />;
  if (!me.data) return <Alert tone="danger">{me.error?.message ?? "Алдаа гарлаа."}</Alert>;

  return (
    <>
      <div className="bg-mark mb-5 rounded-2xl p-3 text-white sm:p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex min-w-0 items-center gap-2 text-sm">
            <Icon name="key" className="text-mark-foreground size-[18px]" />
            <span className="truncate">
              Админ горим · <strong className="font-semibold">{me.data.display_name}</strong>
            </span>
          </div>
          <Button
            variant="ghost"
            size="sm"
            loading={leaving}
            className="text-white hover:bg-white/10 focus-visible:outline-white"
            onClick={async () => {
              setLeaving(true);
              try {
                await api("/admin/auth/logout", { json: {} });
              } finally {
                router.replace("/admin/login");
              }
            }}
          >
            <Icon name="logout" className="size-4" />
            Админаас гарах
          </Button>
        </div>
        <nav aria-label="Админ цэс" className="mt-3">
          <ul className="grid grid-cols-3 gap-1 rounded-xl bg-white/10 p-1 text-sm">
            {ADMIN_NAV.map((item) => {
              const active = adminActive(pathname, item.href);
              return (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    aria-current={active ? "page" : undefined}
                    className={`flex min-h-10 items-center justify-center gap-1.5 rounded-lg font-medium focus-visible:outline-white ${
                      active ? "bg-white text-mark" : "text-white/85 hover:bg-white/10 hover:text-white"
                    }`}
                  >
                    <Icon name={item.icon} className="size-4" />
                    {item.label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>
      </div>
      {children}
    </>
  );
}
