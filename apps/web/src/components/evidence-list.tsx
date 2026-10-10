import { ACTOR_LABEL } from "@/lib/deal-actions";
import { formatDateTime } from "@/lib/format";
import type { Evidence } from "@/lib/types";

function size(bytes: number | null): string {
  if (!bytes) return "";
  return bytes > 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} МБ` : `${Math.ceil(bytes / 1024)} КБ`;
}

/** `fileHref` builds the (same-origin, proxied) download URL for a file item. */
export function EvidenceList({ items, fileHref }: { items: Evidence[]; fileHref: (e: Evidence) => string }) {
  if (items.length === 0) return <p className="text-muted text-sm">Нотлох баримт хараахан алга.</p>;
  return (
    <ol className="space-y-3">
      {items.map((e) => (
        <li
          key={e.id}
          className={`rounded-xl border p-3 text-sm ${
            e.kind === "ADMIN_NOTE" ? "border-amber-300 bg-amber-50 dark:bg-amber-950" : "border-border"
          }`}
        >
          <div className="text-muted mb-1 text-xs">
            {e.mine ? "Та" : (ACTOR_LABEL[e.author_role] ?? e.author_role)}
            {e.kind === "ADMIN_NOTE" ? " · дотоод тэмдэглэл" : ""} · {formatDateTime(e.created_at)}
          </div>
          {e.body ? <p className="whitespace-pre-wrap">{e.body}</p> : null}
          {e.kind === "FILE" ? (
            <a
              href={fileHref(e)}
              className="text-brand mt-1 inline-flex min-h-10 items-center gap-1 font-medium break-all"
              rel="noopener"
            >
              📎 {e.file_name} <span className="text-muted text-xs">({size(e.file_size)})</span>
            </a>
          ) : null}
        </li>
      ))}
    </ol>
  );
}
