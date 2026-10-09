import Link from "next/link";
import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes } from "react";
import { useId } from "react";

import { formatMnt } from "@/lib/money";

type Variant = "primary" | "secondary" | "danger" | "ghost";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-brand text-brand-foreground hover:opacity-90",
  secondary: "bg-surface border border-border text-foreground hover:bg-background",
  danger: "bg-rose-600 text-white hover:bg-rose-700",
  ghost: "text-brand hover:bg-brand-soft",
};

const BASE =
  "inline-flex min-h-12 items-center justify-center gap-2 rounded-xl px-4 text-sm font-semibold transition " +
  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand disabled:opacity-50 disabled:pointer-events-none";

export function Button({
  variant = "primary",
  loading = false,
  className = "",
  children,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; loading?: boolean }) {
  return (
    <button
      type="button"
      {...props}
      disabled={props.disabled || loading}
      aria-busy={loading || undefined}
      className={`${BASE} ${VARIANTS[variant]} ${className}`}
    >
      {loading ? <Spinner /> : null}
      {children}
    </button>
  );
}

export function ButtonLink({
  href,
  variant = "primary",
  className = "",
  children,
}: {
  href: string;
  variant?: Variant;
  className?: string;
  children: ReactNode;
}) {
  return (
    <Link href={href} className={`${BASE} ${VARIANTS[variant]} ${className}`}>
      {children}
    </Link>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <span role={label ? "status" : undefined} className="inline-flex items-center gap-2">
      <span aria-hidden className="size-4 animate-spin rounded-full border-2 border-current border-t-transparent" />
      {label ? <span className="text-sm">{label}</span> : null}
    </span>
  );
}

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <section className={`bg-surface border-border rounded-2xl border p-4 ${className}`}>{children}</section>;
}

const ALERT_TONES = {
  info: "bg-sky-50 text-sky-900 border-sky-200 dark:bg-sky-950 dark:text-sky-100 dark:border-sky-900",
  success: "bg-emerald-50 text-emerald-900 border-emerald-200 dark:bg-emerald-950 dark:text-emerald-100 dark:border-emerald-900",
  warning: "bg-warning-soft text-warning-foreground border-amber-200 dark:border-amber-900",
  danger: "bg-rose-50 text-rose-900 border-rose-200 dark:bg-rose-950 dark:text-rose-100 dark:border-rose-900",
};

export function Alert({
  tone = "info",
  title,
  children,
}: {
  tone?: keyof typeof ALERT_TONES;
  title?: string;
  children?: ReactNode;
}) {
  return (
    <div role={tone === "danger" ? "alert" : "status"} className={`rounded-xl border p-3 text-sm ${ALERT_TONES[tone]}`}>
      {title ? <div className="font-semibold">{title}</div> : null}
      {children ? <div className={title ? "mt-1" : ""}>{children}</div> : null}
    </div>
  );
}

export function PageTitle({ title, subtitle, back }: { title: string; subtitle?: string; back?: string }) {
  return (
    <div className="mb-5 space-y-1">
      {back ? (
        <Link href={back} className="text-muted hover:text-foreground inline-flex min-h-8 items-center text-sm">
          ← Буцах
        </Link>
      ) : null}
      <h1 className="text-2xl leading-tight font-bold">{title}</h1>
      {subtitle ? <p className="text-muted text-sm">{subtitle}</p> : null}
    </div>
  );
}

export function Skeleton({ lines = 3 }: { lines?: number }) {
  return (
    <div role="status" aria-label="Ачаалж байна" className="space-y-3">
      {Array.from({ length: lines }, (_, i) => (
        <div key={i} className="bg-border h-16 animate-pulse rounded-2xl" />
      ))}
    </div>
  );
}

export function EmptyState({ title, body, action }: { title: string; body?: string; action?: ReactNode }) {
  return (
    <div className="border-border space-y-3 rounded-2xl border border-dashed p-6 text-center">
      <div className="font-medium">{title}</div>
      {body ? <p className="text-muted text-sm">{body}</p> : null}
      {action}
    </div>
  );
}

export function Money({ value, className = "" }: { value: string | number; className?: string }) {
  return <span className={`whitespace-nowrap tabular-nums ${className}`}>{formatMnt(value)}</span>;
}

const INPUT =
  "bg-surface border-border w-full rounded-xl border px-3 py-3 text-base outline-none " +
  "focus:border-brand focus:ring-2 focus:ring-brand/30 aria-[invalid=true]:border-rose-500";

type FieldProps = { label: string; hint?: string; error?: string | null };

function FieldShell({ id, label, hint, error, children }: FieldProps & { id: string; children: ReactNode }) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className="block text-sm font-medium">
        {label}
      </label>
      {children}
      {error ? (
        <p id={`${id}-error`} className="text-sm text-rose-600 dark:text-rose-400">
          {error}
        </p>
      ) : hint ? (
        <p id={`${id}-hint`} className="text-muted text-xs">
          {hint}
        </p>
      ) : null}
    </div>
  );
}

function describedBy(id: string, hint?: string, error?: string | null) {
  return error ? `${id}-error` : hint ? `${id}-hint` : undefined;
}

export function Field({ label, hint, error, ...props }: FieldProps & InputHTMLAttributes<HTMLInputElement>) {
  const id = useId();
  return (
    <FieldShell id={id} label={label} hint={hint} error={error}>
      <input
        id={id}
        {...props}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(id, hint, error)}
        className={INPUT}
      />
    </FieldShell>
  );
}

export function TextArea({ label, hint, error, ...props }: FieldProps & TextareaHTMLAttributes<HTMLTextAreaElement>) {
  const id = useId();
  return (
    <FieldShell id={id} label={label} hint={hint} error={error}>
      <textarea
        id={id}
        rows={4}
        {...props}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(id, hint, error)}
        className={INPUT}
      />
    </FieldShell>
  );
}

export function Select({
  label,
  hint,
  error,
  options,
  ...props
}: FieldProps & SelectHTMLAttributes<HTMLSelectElement> & { options: { value: string; label: string }[] }) {
  const id = useId();
  return (
    <FieldShell id={id} label={label} hint={hint} error={error}>
      <select
        id={id}
        {...props}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(id, hint, error)}
        className={INPUT}
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </FieldShell>
  );
}

export function DefinitionList({ items }: { items: [string, ReactNode][] }) {
  return (
    <dl className="divide-border divide-y text-sm">
      {items.map(([k, v]) => (
        <div key={k} className="flex items-start justify-between gap-4 py-2.5">
          <dt className="text-muted shrink-0">{k}</dt>
          <dd className="text-right font-medium break-words">{v}</dd>
        </div>
      ))}
    </dl>
  );
}
