"use client";

import type { ReactNode } from "react";

import { AuthGuard } from "@/components/auth-guard";
import { Alert } from "@/components/ui";

/** Hides admin UI from non-admins. The admin API enforces this independently. */
export function AdminGuard({ children }: { children: ReactNode }) {
  return (
    <AuthGuard>
      {(me) =>
        me.is_admin ? (
          <>
            <nav aria-label="Админ цэс" className="bg-border mb-4 grid grid-cols-3 gap-1 rounded-xl p-1 text-center text-sm">
              <a href="/admin" className="bg-surface min-h-10 content-center rounded-lg">
                Маргаан
              </a>
              <a href="/admin/users" className="bg-surface min-h-10 content-center rounded-lg">
                Хэрэглэгч
              </a>
              <a href="/admin/audit" className="bg-surface min-h-10 content-center rounded-lg">
                Аудит
              </a>
            </nav>
            {children}
          </>
        ) : (
          <Alert tone="danger">Энэ хэсэг зөвхөн SafePay-ийн ажилтанд нээлттэй.</Alert>
        )
      }
    </AuthGuard>
  );
}
