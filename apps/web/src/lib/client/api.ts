/**
 * Browser-side API client. Talks only to the same-origin `/api` proxy, sends the
 * CSRF token from the (non-HttpOnly) CSRF cookie, and never stores the session
 * token (it is an HttpOnly cookie the page cannot read).
 */
import { errorMessage } from "@/lib/errors";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
  ) {
    super(errorMessage(code));
  }
}

const CSRF_COOKIES = ["__Host-safepay_csrf", "safepay_csrf"];

export function readCsrfToken(cookieString: string): string | null {
  for (const part of cookieString.split(";")) {
    const [name, ...rest] = part.trim().split("=");
    if (CSRF_COOKIES.includes(name)) return decodeURIComponent(rest.join("="));
  }
  return null;
}

export function newIdempotencyKey(): string {
  return crypto.randomUUID();
}

type Options = {
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  json?: unknown;
  form?: FormData;
  idempotencyKey?: string;
};

export async function api<T>(path: string, opts: Options = {}): Promise<T> {
  const method = opts.method ?? (opts.json !== undefined || opts.form ? "POST" : "GET");
  const headers: Record<string, string> = { accept: "application/json" };
  if (method !== "GET") {
    const csrf = typeof document === "undefined" ? null : readCsrfToken(document.cookie);
    if (csrf) headers["x-csrf-token"] = csrf;
  }
  if (opts.idempotencyKey) headers["idempotency-key"] = opts.idempotencyKey;
  let body: BodyInit | undefined;
  if (opts.form) body = opts.form;
  else if (opts.json !== undefined) {
    headers["content-type"] = "application/json";
    body = JSON.stringify(opts.json);
  }
  let res: Response;
  try {
    res = await fetch(`/api${path}`, { method, headers, body, credentials: "same-origin", cache: "no-store" });
  } catch {
    throw new ApiError(0, "network_error");
  }
  if (res.status === 204) return undefined as T;
  const data: unknown = await res.json().catch(() => null);
  if (!res.ok) {
    const code =
      (data as { error?: { code?: string } } | null)?.error?.code ??
      (res.status === 401 ? "not_authenticated" : res.status === 429 ? "rate_limited" : "unknown");
    throw new ApiError(res.status, code);
  }
  return data as T;
}
