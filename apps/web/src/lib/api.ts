import "server-only";

/**
 * Server-side API access. The browser never talks to the database and never
 * decides transaction state; it only renders what the backend returns.
 */

export type HealthResponse = {
  status: "ok";
  service: string;
  version: string;
  environment: string;
  simulation_only: boolean;
};

export type ReadinessResponse = {
  status: "ready" | "not_ready";
  checks: Record<string, { ok: boolean; detail: string | null }>;
};

function apiBaseUrl(): string {
  return process.env.API_INTERNAL_URL ?? "http://localhost:8000";
}

async function getJson<T>(path: string): Promise<{ httpStatus: number; body: T } | null> {
  try {
    const res = await fetch(`${apiBaseUrl()}${path}`, {
      cache: "no-store",
      signal: AbortSignal.timeout(3000),
    });
    return { httpStatus: res.status, body: (await res.json()) as T };
  } catch {
    return null;
  }
}

export const getHealth = () => getJson<HealthResponse>("/health");
export const getReadiness = () => getJson<ReadinessResponse>("/ready");
