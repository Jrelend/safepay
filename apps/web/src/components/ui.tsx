import Link from "next/link";
import type {
  ButtonHTMLAttributes,
  InputHTMLAttributes,
  ReactNode,
  Ref,
  SelectHTMLAttributes,
  TextareaHTMLAttributes,
} from "react";
import { useId } from "react";

import { Icon, type IconName } from "@/components/icons";
import { formatMnt } from "@/lib/money";

/** Page content widths (the layout's main column is wide; each page picks its measure). */
export const WIDTH = {
  narrow: "mx-auto w-full max-w-md",
  form: "mx-auto w-full max-w-2xl",
  wide: "w-full",
} as const;

type Variant = "primary" | "secondary" | "danger" | "dangerOutline" | "ghost";
type Size = "md" | "sm";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-primary text-primary-foreground shadow-card hover:bg-primary-hover",
  secondary: "bg-surface border border-border-strong/60 text-foreground hover:bg-surface-muted",
  danger: "bg-danger-solid text-white hover:brightness-110",
  dangerOutline: "bg-surface border border-danger-border text-danger hover:bg-danger-soft",
  ghost: "text-brand hover:bg-brand-soft",
};

const SIZES: Record<Size, string> = {
  md: "min-h-12 px-5 text-[15px]",
  sm: "min-h-10 px-3 text-sm",
};

const BASE =
  "inline-flex items-center justify-center gap-2 rounded-xl font-semibold transition-colors " +
  "disabled:opacity-50 disabled:pointer-events-none";

export function buttonClass(variant: Variant = "primary", size: Size = "md", className = "") {
  return `${BASE} ${SIZES[size]} ${VARIANTS[variant]} ${className}`;
}

export function Button({
  variant = "primary",
  size = "md",
  loading = false,
  className = "",
  children,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: Size; loading?: boolean }) {
  return (
    <button
      type="button"
      {...props}
      disabled={props.disabled || loading}
      aria-busy={loading || undefined}
      className={buttonClass(variant, size, className)}
    >
      {loading ? <Spinner /> : null}
      {children}
    </button>
  );
}

export function ButtonLink({
  href,
  variant = "primary",
  size = "md",
  className = "",
  children,
}: {
  href: string;
  variant?: Variant;
  size?: Size;
  className?: string;
  children: ReactNode;
}) {
  return (
    <Link href={href} className={buttonClass(variant, size, className)}>
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

export function Card({
  children,
  className = "",
  as: Tag = "section",
  ...rest
}: {
  children: ReactNode;
  className?: string;
  as?: "section" | "div" | "article";
  "aria-labelledby"?: string;
  "aria-label"?: string;
}) {
  return (
    <Tag {...rest} className={`bg-surface border-border shadow-card rounded-2xl border p-4 sm:p-5 ${className}`}>
      {children}
    </Tag>
  );
}

/** Card heading: one size everywhere (h2). */
export function CardTitle({ id, children, action }: { id?: string; children: ReactNode; action?: ReactNode }) {
  return (
    <div className="mb-3 flex items-center justify-between gap-3">
      <h2 id={id} className="text-base font-semibold">
        {children}
      </h2>
      {action}
    </div>
  );
}

export type Tone = "info" | "success" | "warning" | "danger" | "neutral";

export const TONE_SOFT: Record<Tone, string> = {
  info: "bg-info-soft text-info border-info-border",
  success: "bg-success-soft text-success border-success-border",
  warning: "bg-warning-soft text-warning border-warning-border",
  danger: "bg-danger-soft text-danger border-danger-border",
  neutral: "bg-surface-muted text-muted border-border",
};

const TONE_ICON: Record<Tone, IconName> = {
  info: "info",
  success: "checkCircle",
  warning: "alert",
  danger: "alert",
  neutral: "info",
};

export function Alert({
  tone = "info",
  title,
  children,
  id,
  focusRef,
}: {
  tone?: Tone;
  title?: string;
  children?: ReactNode;
  id?: string;
  /** Pass a ref to move focus here (e.g. after an action) so it is seen and announced. */
  focusRef?: Ref<HTMLDivElement>;
}) {
  return (
    <div
      id={id}
      ref={focusRef}
      tabIndex={focusRef ? -1 : undefined}
      role={tone === "danger" ? "alert" : "status"}
      className={`flex gap-3 rounded-xl border p-3 text-sm ${TONE_SOFT[tone]}`}
    >
      <Icon name={TONE_ICON[tone]} className="mt-0.5 size-[18px]" />
      <div className="min-w-0 flex-1">
        {title ? <div className="font-semibold">{title}</div> : null}
        {children ? <div className={`text-foreground ${title ? "mt-0.5" : ""}`}>{children}</div> : null}
      </div>
    </div>
  );
}

export function PageTitle({
  title,
  subtitle,
  back,
  actions,
}: {
  title: string;
  subtitle?: ReactNode;
  back?: string;
  actions?: ReactNode;
}) {
  return (
    <div className="mb-5 space-y-1">
      {back ? (
        <Link
          href={back}
          className="text-muted hover:text-foreground -ml-1 inline-flex min-h-11 items-center gap-1 rounded-lg pr-2 text-sm font-medium"
        >
          <Icon name="chevronLeft" className="size-4" />
          Буцах
        </Link>
      ) : null}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0 space-y-1">
          <h1 className="text-2xl leading-tight font-bold tracking-tight break-words sm:text-[28px]">{title}</h1>
          {subtitle ? <p className="text-muted text-sm">{subtitle}</p> : null}
        </div>
        {actions}
      </div>
    </div>
  );
}

export function Skeleton({ lines = 3 }: { lines?: number }) {
  return (
    <div role="status" aria-label="Ачаалж байна" className="space-y-3">
      {Array.from({ length: lines }, (_, i) => (
        <div key={i} className="bg-surface-muted h-16 animate-pulse rounded-2xl" />
      ))}
    </div>
  );
}

export function EmptyState({
  title,
  body,
  action,
  icon = "inbox",
}: {
  title: string;
  body?: string;
  action?: ReactNode;
  icon?: IconName;
}) {
  return (
    <div className="border-border-strong/40 space-y-3 rounded-2xl border border-dashed px-6 py-8 text-center">
      <span className="bg-surface-muted text-muted mx-auto grid size-11 place-items-center rounded-full">
        <Icon name={icon} />
      </span>
      <div className="font-semibold">{title}</div>
      {body ? <p className="text-muted mx-auto max-w-sm text-sm">{body}</p> : null}
      {action ? <div className="pt-1">{action}</div> : null}
    </div>
  );
}

export function Money({ value, className = "" }: { value: string | number; className?: string }) {
  return <span className={`whitespace-nowrap tabular-nums ${className}`}>{formatMnt(value)}</span>;
}

/**
 * Exclusive filter buttons (deal scope, dispute status). These are filters on
 * one list, not ARIA tabs, so they use aria-pressed buttons.
 */
export function SegmentedControl<T extends string>({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: readonly { value: T; label: string }[];
  value: T;
  onChange: (value: T) => void;
}) {
  return (
    <div
      role="group"
      aria-label={label}
      className="bg-surface-muted border-border grid auto-cols-fr grid-flow-col gap-1 rounded-xl border p-1"
    >
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          aria-pressed={o.value === value}
          onClick={() => onChange(o.value)}
          className={`min-h-10 rounded-lg px-3 text-sm font-medium transition-colors ${
            o.value === value ? "bg-surface text-foreground shadow-card" : "text-muted hover:text-foreground"
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

const INPUT =
  "bg-surface border-border-strong text-foreground placeholder:text-muted/80 w-full rounded-xl border px-3.5 py-3 text-base " +
  "outline-none transition-colors focus:border-focus focus:ring-2 focus:ring-focus/25 " +
  "aria-[invalid=true]:border-danger aria-[invalid=true]:ring-danger/20";

type FieldProps = { label: string; hint?: string; error?: string | null };

function FieldShell({ id, label, hint, error, children }: FieldProps & { id: string; children: ReactNode }) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className="block text-sm font-medium">
        {label}
      </label>
      {children}
      {error ? (
        <p id={`${id}-error`} role="alert" className="text-danger flex items-start gap-1.5 text-sm font-medium">
          <Icon name="alert" className="mt-0.5 size-4" />
          {error}
        </p>
      ) : hint ? (
        <p id={`${id}-hint`} className="text-muted text-[13px] leading-snug">
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
        <div key={k} className="flex flex-wrap items-start justify-between gap-x-4 gap-y-0.5 py-2.5">
          <dt className="text-muted">{k}</dt>
          <dd className="min-w-0 text-right font-medium break-words">{v}</dd>
        </div>
      ))}
    </dl>
  );
}
