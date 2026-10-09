import type { Metadata } from "next";
import { connection } from "next/server";
import { Suspense } from "react";

import { getHealth, getReadiness } from "@/lib/api";
import { mn } from "@/lib/i18n/mn";

export const metadata: Metadata = { title: mn.system.title };

function Row({ label, ok, detail }: { label: string; ok: boolean | null; detail?: string | null }) {
  const text = ok === null ? mn.system.checking : ok ? mn.system.ok : mn.system.down;
  const dot = ok === null ? "bg-slate-400" : ok ? "bg-emerald-500" : "bg-rose-500";
  return (
    <li className="flex items-start justify-between gap-3 p-4">
      <div>
        <div className="font-medium">{label}</div>
        {detail ? <div className="text-muted text-xs break-all">{detail}</div> : null}
      </div>
      <span className="flex shrink-0 items-center gap-2 text-sm">
        <span aria-hidden className={`size-2.5 rounded-full ${dot}`} />
        {text}
      </span>
    </li>
  );
}

async function SystemChecks() {
  await connection();
  const [health, readiness] = await Promise.all([getHealth(), getReadiness()]);
  if (!health) {
    return (
      <>
        <Row label={mn.system.api} ok={false} detail={mn.system.unreachable} />
        <Row label={mn.system.database} ok={false} />
        <Row label={mn.system.migrations} ok={false} />
      </>
    );
  }
  const checks = readiness?.body.checks ?? {};
  return (
    <>
      <Row
        label={mn.system.api}
        ok={health.httpStatus === 200}
        detail={`${health.body.service} v${health.body.version} · ${health.body.environment}`}
      />
      <Row label={mn.system.database} ok={checks.database?.ok ?? false} />
      <Row
        label={mn.system.migrations}
        ok={checks.migrations?.ok ?? false}
        detail={checks.migrations?.detail}
      />
    </>
  );
}

function Pending() {
  return (
    <>
      <Row label={mn.system.api} ok={null} />
      <Row label={mn.system.database} ok={null} />
      <Row label={mn.system.migrations} ok={null} />
    </>
  );
}

export default function StatusPage() {
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">{mn.system.title}</h1>
      <ul className="bg-surface border-border divide-border divide-y rounded-2xl border">
        <Suspense fallback={<Pending />}>
          <SystemChecks />
        </Suspense>
      </ul>
    </div>
  );
}
