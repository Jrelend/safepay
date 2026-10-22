"use client";

/**
 * LOCAL DEMO ONLY: one-click switching between the seeded buyer, seller and admin.
 *
 * `/api/demo/*` exists only when the API runs with LOCAL_DEMO=true (local/test) and
 * the web proxy with ENABLE_DEMO_ROUTES=true; everywhere else it is a 404 and every
 * demo affordance stays hidden. Sign-in still uses the normal endpoints: the user
 * login for the buyer and seller, and the admin API's password + one-time code.
 */
import { useEffect, useState } from "react";

import { api, ApiError } from "./api";
import type { Me } from "@/lib/types";

export type DemoKey = "buyer" | "seller" | "admin";
export type DemoAccount = { key: DemoKey; email: string; display_name: string; password: string };

let accountsPromise: Promise<DemoAccount[] | null> | null = null;

function loadAccounts(): Promise<DemoAccount[] | null> {
  accountsPromise ??= api<DemoAccount[]>("/demo/accounts").catch(() => null);
  return accountsPromise;
}

/** The seeded demo accounts, or null when this is not a local demo (or still loading). */
export function useDemoAccounts(): DemoAccount[] | null {
  const [accounts, setAccounts] = useState<DemoAccount[] | null>(null);
  useEffect(() => {
    let live = true;
    void loadAccounts().then((a) => {
      if (live) setAccounts(a);
    });
    return () => {
      live = false;
    };
  }, []);
  return accounts;
}

export function demoKeyOf(accounts: DemoAccount[] | null, email: string | undefined): DemoKey | null {
  return accounts?.find((a) => a.email === email)?.key ?? null;
}

/** Sign out whoever is signed in and sign in as the demo buyer or seller. */
export async function signInAsParty(account: DemoAccount): Promise<Me> {
  try {
    await api("/auth/logout", { json: {} });
  } catch {
    // Nobody was signed in.
  }
  return api<Me>("/auth/login", { json: { email: account.email, password: account.password } });
}

/**
 * Sign in to the admin area as the demo admin. Codes are single-use per 30 s step, so
 * if the current one was just used (a second switch within the same step), the next
 * step's code, which the server also accepts, is tried once.
 */
export async function signInAsAdmin(account: DemoAccount): Promise<void> {
  try {
    await api("/admin/auth/me");
    return; // Admin session still open.
  } catch {
    // Not signed in to the admin area.
  }
  for (const ahead of [0, 1]) {
    const { code } = await api<{ code: string }>(`/demo/admin-code?ahead=${ahead}`);
    try {
      await api("/admin/auth/login", { json: { email: account.email, password: account.password, code } });
      return;
    } catch (err) {
      if (!(err instanceof ApiError && err.code === "invalid_credentials") || ahead === 1) throw err;
    }
  }
}
