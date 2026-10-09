"use client";

import { useState, type ReactNode } from "react";

import { Alert, Button, Skeleton } from "@/components/ui";
import { api } from "@/lib/client/api";
import { useRequireSession } from "@/lib/client/session";
import type { Me } from "@/lib/types";

/** Renders children only for signed-in users (redirecting others to /login). */
export function AuthGuard({ children, verified = false }: { children: (me: Me) => ReactNode; verified?: boolean }) {
  const session = useRequireSession();
  if (session.status !== "authenticated") return <Skeleton />;
  if (verified && !session.me.email_verified) return <VerifyFirst email={session.me.email} />;
  return <>{children(session.me)}</>;
}

export function VerifyFirst({ email }: { email: string }) {
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);
  return (
    <div className="space-y-3">
      <Alert tone="warning" title="Имэйлээ баталгаажуулна уу">
        Гэрээ үүсгэх, нэгдэх, төлбөр хийхийн өмнө <strong>{email}</strong> хаягаа баталгаажуулах шаардлагатай.
      </Alert>
      {sent ? (
        <Alert tone="success">Шинэ холбоос илгээгдлээ.</Alert>
      ) : (
        <Button
          variant="secondary"
          className="w-full"
          loading={busy}
          onClick={async () => {
            setBusy(true);
            try {
              await api("/auth/resend-verification", { json: { email } });
              setSent(true);
            } finally {
              setBusy(false);
            }
          }}
        >
          Холбоос дахин илгээх
        </Button>
      )}
    </div>
  );
}
