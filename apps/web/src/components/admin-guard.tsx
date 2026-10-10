"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { Alert, Button, Skeleton } from "@/components/ui";
import { api } from "@/lib/client/api";
import { useApi } from "@/lib/client/use-api";

type AdminMe = { id: string; email: string; display_name: string; session_expires_at: string };

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
      <div className="text-muted mb-3 flex items-center justify-between gap-2 text-xs">
        <span>
          Админ: <strong className="text-foreground">{me.data.display_name}</strong>
        </span>
        <Button
          variant="ghost"
          loading={leaving}
          className="min-h-9 px-2 text-xs"
          onClick={async () => {
            setLeaving(true);
            try {
              await api("/admin/auth/logout", { json: {} });
            } finally {
              router.replace("/admin/login");
            }
          }}
        >
          Админаас гарах
        </Button>
      </div>
      <nav aria-label="Админ цэс" className="bg-border mb-4 grid grid-cols-3 gap-1 rounded-xl p-1 text-center text-sm">
        <Link href="/admin" className="bg-surface min-h-10 content-center rounded-lg">
          Маргаан
        </Link>
        <Link href="/admin/users" className="bg-surface min-h-10 content-center rounded-lg">
          Хэрэглэгч
        </Link>
        <Link href="/admin/audit" className="bg-surface min-h-10 content-center rounded-lg">
          Аудит
        </Link>
      </nav>
      {children}
    </>
  );
}
