"use client";

import { useState, type FormEvent } from "react";

import { Alert, Button, Card, EmptyState, Field, PageTitle, Skeleton } from "@/components/ui";
import { useApi } from "@/lib/client/use-api";
import { formatDateTime } from "@/lib/format";

type Mail = { id: string; to_email: string; template: string; data: Record<string, unknown>; created_at: string };

const TEMPLATE: Record<string, string> = {
  verify_email: "Имэйл баталгаажуулах",
  password_reset: "Нууц үг сэргээх",
  account_exists: "Бүртгэл аль хэдийн байна",
  password_changed: "Нууц үг солигдсон",
};

/** Turns an absolute link from the API into a same-origin path on this site. */
function localPath(link: string): string {
  try {
    const url = new URL(link);
    return `${url.pathname}${url.search}`;
  } catch {
    return "/";
  }
}

export function Mailbox() {
  const [email, setEmail] = useState<string | null>(null);
  const { data, error, loading, reload } = useApi<Mail[]>(
    email ? `/dev/mailbox?email=${encodeURIComponent(email)}` : null,
  );

  function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setEmail(String(new FormData(e.currentTarget).get("email")).trim());
  }

  return (
    <div className="space-y-4">
      <PageTitle
        title="Туршилтын шуудан"
        subtitle="Зөвхөн орон нутгийн хөгжүүлэлтэд. Бодит имэйл илгээгддэггүй тул энд харагдана."
      />
      <Card>
        <form onSubmit={onSubmit} className="space-y-3">
          <Field label="Имэйл хаяг" name="email" type="email" required autoComplete="email" />
          <div className="flex gap-2">
            <Button type="submit" className="flex-1">
              Шуудан харах
            </Button>
            {email ? (
              <Button variant="secondary" onClick={reload}>
                Шинэчлэх
              </Button>
            ) : null}
          </div>
        </form>
      </Card>
      {loading && !data ? <Skeleton /> : null}
      {error ? <Alert tone="warning">Туршилтын шуудан энэ орчинд идэвхгүй байна.</Alert> : null}
      {data && data.length === 0 ? <EmptyState title="Шуудан хоосон" /> : null}
      {data?.map((mail) => {
        const link = typeof mail.data.link === "string" ? mail.data.link : null;
        return (
          <Card key={mail.id} className="space-y-1">
            <div className="text-muted text-xs">{formatDateTime(mail.created_at)}</div>
            <div className="font-medium">{TEMPLATE[mail.template] ?? mail.template}</div>
            <div className="text-muted text-sm break-all">{mail.to_email}</div>
            {link ? (
              <a href={localPath(link)} className="text-brand inline-block min-h-10 content-center text-sm font-semibold">
                Холбоосыг нээх →
              </a>
            ) : null}
          </Card>
        );
      })}
    </div>
  );
}
