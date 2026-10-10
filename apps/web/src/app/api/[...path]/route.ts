import type { NextRequest } from "next/server";

import {
  MAX_BODY_BYTES,
  downstreamResponseHeaders,
  readCapped,
  resolveUpstream,
  upstreamRequestHeaders,
} from "@/lib/proxy";

function env() {
  return {
    publicUrl: process.env.API_INTERNAL_URL ?? "http://localhost:8000",
    adminUrl: process.env.ADMIN_API_INTERNAL_URL,
    devRoutes: process.env.ENABLE_DEV_ROUTES === "true",
  };
}

function problem(status: number, code: string, message: string): Response {
  return Response.json({ error: { code, message } }, { status, headers: { "cache-control": "no-store" } });
}

async function forward(req: NextRequest, ctx: RouteContext<"/api/[...path]">): Promise<Response> {
  const { path } = await ctx.params;
  const target = resolveUpstream(path, env());
  if (!target) return problem(404, "not_found", "not found");

  let body: Uint8Array<ArrayBuffer> | undefined;
  if (req.method !== "GET" && req.method !== "HEAD") {
    const declared = Number(req.headers.get("content-length") ?? "0");
    if (declared > MAX_BODY_BYTES) return problem(413, "payload_too_large", "request too large");
    const read = await readCapped(req.body, MAX_BODY_BYTES);
    if (read === null) return problem(413, "payload_too_large", "request too large");
    body = read as Uint8Array<ArrayBuffer>;
  }

  const url = `${target.base}${target.path}${req.nextUrl.search}`;
  let upstream: Response;
  try {
    upstream = await fetch(url, {
      method: req.method,
      headers: upstreamRequestHeaders(req.headers),
      body,
      redirect: "manual",
      cache: "no-store",
      signal: AbortSignal.timeout(15_000),
    });
  } catch {
    return problem(502, "upstream_unavailable", "service unavailable");
  }
  return new Response(upstream.status === 204 ? null : upstream.body, {
    status: upstream.status,
    headers: downstreamResponseHeaders(upstream.headers),
  });
}

export const GET = forward;
export const POST = forward;
export const PATCH = forward;
export const PUT = forward;
export const DELETE = forward;
