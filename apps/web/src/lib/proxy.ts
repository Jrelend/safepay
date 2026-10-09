/**
 * Same-origin API proxy helpers (used by `app/api/[...path]/route.ts`).
 *
 * The browser only ever talks to the web origin. Requests under `/api/admin/*`
 * go to the separate admin API service; everything else to the public API.
 * Only an explicit allow-list of headers crosses the boundary in each direction.
 */

const REQUEST_HEADERS = [
  "accept",
  "content-type",
  "cookie",
  "idempotency-key",
  "origin",
  "user-agent",
  "x-csrf-token",
] as const;

const RESPONSE_HEADERS = [
  "cache-control",
  "content-disposition",
  "content-security-policy",
  "content-type",
  "retry-after",
  "x-content-type-options",
  "x-request-id",
] as const;

/** Path segments must be plain URL path pieces: no traversal, no encoded slashes. */
const SEGMENT = /^[A-Za-z0-9._~-]+$/;

export const MAX_BODY_BYTES = 3 * 1024 * 1024;

export type Upstream = { base: string; path: string };

export function resolveUpstream(
  segments: readonly string[],
  env: { publicUrl: string; adminUrl: string | undefined },
): Upstream | null {
  if (segments.length === 0 || segments.length > 8) return null;
  if (!segments.every((s) => SEGMENT.test(s) && s !== "." && s !== "..")) return null;
  const path = `/${segments.join("/")}`;
  if (segments[0] === "admin") {
    return env.adminUrl ? { base: env.adminUrl, path } : null;
  }
  // Operational endpoints are not part of the browser API surface.
  if (["health", "ready", "docs", "openapi.json", "redoc"].includes(segments[0])) return null;
  return { base: env.publicUrl, path };
}

/**
 * The client address to report upstream: the right-most X-Forwarded-For hop,
 * i.e. the one added by the closest proxy (Next itself fills it from the
 * socket when absent). Client-supplied entries further left are ignored.
 */
export function clientAddress(forwardedFor: string | null): string | null {
  if (!forwardedFor) return null;
  const hops = forwardedFor
    .split(",")
    .map((h) => h.trim())
    .filter(Boolean);
  const last = hops.at(-1);
  return last && last.length <= 64 ? last : null;
}

export function upstreamRequestHeaders(incoming: Headers): Headers {
  const out = new Headers();
  for (const name of REQUEST_HEADERS) {
    const value = incoming.get(name);
    if (value !== null) out.set(name, value);
  }
  const ip = clientAddress(incoming.get("x-forwarded-for"));
  if (ip) out.set("x-forwarded-for", ip);
  return out;
}

export function downstreamResponseHeaders(upstream: Headers): Headers {
  const out = new Headers();
  for (const name of RESPONSE_HEADERS) {
    const value = upstream.get(name);
    if (value !== null) out.set(name, value);
  }
  for (const cookie of upstream.getSetCookie()) out.append("set-cookie", cookie);
  if (!out.has("cache-control")) out.set("cache-control", "no-store");
  return out;
}
