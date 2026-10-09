"use client";

import { useState } from "react";

import { Alert, Button, Card } from "@/components/ui";
import { api, ApiError } from "@/lib/client/api";

/** Converts the API's absolute invite URL to this site's origin (same path). */
function onThisSite(url: string): string {
  try {
    const u = new URL(url);
    return `${window.location.origin}${u.pathname}`;
  } catch {
    return url;
  }
}

export function InviteBox({ dealId, initialUrl }: { dealId: string; initialUrl: string | null }) {
  const [url, setUrl] = useState<string | null>(initialUrl ? onThisSite(initialUrl) : null);
  const [copied, setCopied] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function regenerate() {
    setBusy(true);
    setError(null);
    try {
      const res = await api<{ invite_url: string }>(`/deals/${dealId}/invite`, { json: {} });
      setUrl(onThisSite(res.invite_url));
      setCopied(false);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Алдаа гарлаа.");
    } finally {
      setBusy(false);
    }
  }

  async function share() {
    if (!url) return;
    if (navigator.share) {
      try {
        await navigator.share({ title: "SafePay гэрээний урилга", url });
        return;
      } catch {
        /* fall back to copy */
      }
    }
    await navigator.clipboard.writeText(url);
    setCopied(true);
  }

  return (
    <Card className="space-y-3">
      <div className="font-semibold">Нөгөө талыг урих</div>
      <p className="text-muted text-sm">
        Холбоосыг зөвхөн гэрээ хийх хүндээ илгээнэ үү. Нэг удаа ашиглагдана; шинэ холбоос үүсгэвэл хуучин нь хүчингүй
        болно.
      </p>
      {url ? (
        <>
          <input
            readOnly
            value={url}
            aria-label="Урилгын холбоос"
            onFocus={(e) => e.currentTarget.select()}
            className="bg-background border-border w-full rounded-xl border px-3 py-3 font-mono text-xs"
          />
          <Button onClick={share} className="w-full">
            {copied ? "Хуулагдлаа ✓" : "Холбоос хуваалцах"}
          </Button>
        </>
      ) : null}
      <Button variant="secondary" onClick={regenerate} loading={busy} className="w-full">
        {url ? "Шинэ холбоос үүсгэх" : "Урилгын холбоос үүсгэх"}
      </Button>
      {error ? <Alert tone="danger">{error}</Alert> : null}
    </Card>
  );
}
