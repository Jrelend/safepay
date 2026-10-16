"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useState } from "react";

import { Alert, Button, PageTitle, WIDTH } from "@/components/ui";
import { api, ApiError } from "@/lib/client/api";
import { useSession } from "@/lib/client/session";

export function VerifyEmail() {
  const token = useSearchParams().get("token");
  const session = useSession();
  const [state, setState] = useState<"idle" | "busy" | "done" | "error">("idle");
  const [error, setError] = useState<string | null>(null);

  // Verification is a deliberate click (not on page load), so link scanners
  // and prefetchers cannot consume the one-time token.
  async function verify() {
    if (!token) return;
    setState("busy");
    try {
      await api("/auth/verify-email", { json: { token } });
      setState("done");
      await session.refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Алдаа гарлаа.");
      setState("error");
    }
  }

  return (
    <div className={`${WIDTH.narrow} space-y-4`}>
      <PageTitle title="Имэйл баталгаажуулах" />
      {!token ? (
        <Alert tone="danger">Холбоос дутуу байна. Имэйл дэх холбоосыг бүтнээр нь нээнэ үү.</Alert>
      ) : state === "done" ? (
        <>
          <Alert tone="success" title="Баталгаажлаа">
            Таны имэйл хаяг баталгаажлаа.
          </Alert>
          <Link
            href={session.status === "authenticated" ? "/dashboard" : "/login?verified=1"}
            className="text-brand block text-center font-semibold"
          >
            Үргэлжлүүлэх
          </Link>
        </>
      ) : (
        <>
          <p className="text-muted text-sm">Доорх товчийг дарж имэйл хаягаа баталгаажуулна уу.</p>
          {error ? <Alert tone="danger">{error}</Alert> : null}
          <Button onClick={verify} loading={state === "busy"} className="w-full">
            Баталгаажуулах
          </Button>
        </>
      )}
    </div>
  );
}
