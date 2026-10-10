import { Icon } from "@/components/icons";
import { ACTOR_LABEL } from "@/lib/deal-actions";
import { formatDateTime } from "@/lib/format";
import type { Evidence } from "@/lib/types";

export function fileSize(bytes: number | null): string {
  if (!bytes) return "";
  return bytes > 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} МБ` : `${Math.ceil(bytes / 1024)} КБ`;
}

/** `fileHref` builds the (same-origin, proxied) download URL for a file item. */
export function EvidenceList({ items, fileHref }: { items: Evidence[]; fileHref: (e: Evidence) => string }) {
  if (items.length === 0) {
    return (
      <p className="text-muted bg-surface-muted rounded-xl px-3 py-4 text-center text-sm">
        Нотлох баримт хараахан алга. Тайлбар бичих эсвэл зураг, баримт хавсаргана уу.
      </p>
    );
  }
  return (
    <ol className="space-y-3">
      {items.map((e) => {
        const admin = e.kind === "ADMIN_NOTE";
        return (
          <li
            key={e.id}
            className={`rounded-xl border p-3 text-sm ${
              admin
                ? "border-warning-border bg-warning-soft"
                : e.mine
                  ? "border-border bg-surface-muted"
                  : "border-border"
            }`}
          >
            <div className="text-muted mb-1 flex flex-wrap items-center gap-x-1.5 text-xs">
              <span className="text-foreground font-semibold">
                {e.mine ? "Та" : (ACTOR_LABEL[e.author_role] ?? e.author_role)}
              </span>
              {admin ? <span className="text-warning font-semibold">· дотоод тэмдэглэл</span> : null}
              <span>· {formatDateTime(e.created_at)}</span>
            </div>
            {e.body ? <p className="whitespace-pre-wrap">{e.body}</p> : null}
            {e.kind === "FILE" ? (
              <a
                href={fileHref(e)}
                className="text-brand mt-1 inline-flex min-h-11 items-center gap-2 font-medium break-all underline-offset-2 hover:underline"
                rel="noopener"
              >
                <Icon name="paperclip" className="size-4" />
                {e.file_name}
                <span className="text-muted text-xs font-normal">({fileSize(e.file_size)})</span>
              </a>
            ) : null}
          </li>
        );
      })}
    </ol>
  );
}
