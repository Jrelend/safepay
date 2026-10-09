"use client";

import { usePathname, useRouter } from "next/navigation";
import { createContext, use, useCallback, useEffect, useState, type ReactNode } from "react";

import { api, ApiError } from "./api";
import type { Me } from "@/lib/types";

type SessionState =
  | { status: "loading"; me: null }
  | { status: "anonymous"; me: null }
  | { status: "authenticated"; me: Me };

type SessionContextValue = SessionState & {
  refresh: () => Promise<Me | null>;
  setMe: (me: Me | null) => void;
};

const SessionContext = createContext<SessionContextValue | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<SessionState>({ status: "loading", me: null });

  const setMe = useCallback((me: Me | null) => {
    setState(me ? { status: "authenticated", me } : { status: "anonymous", me: null });
  }, []);

  const refresh = useCallback(async () => {
    try {
      const me = await api<Me>("/auth/me");
      setMe(me);
      return me;
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) setMe(null);
      else setState((s) => (s.status === "loading" ? { status: "anonymous", me: null } : s));
      return null;
    }
  }, [setMe]);

  useEffect(() => {
    // Initial session check runs once on mount; setState happens after the await.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void refresh();
  }, [refresh]);

  return <SessionContext value={{ ...state, refresh, setMe }}>{children}</SessionContext>;
}

export function useSession(): SessionContextValue {
  const ctx = use(SessionContext);
  if (!ctx) throw new Error("useSession must be used inside <SessionProvider>");
  return ctx;
}

/** Redirects anonymous visitors to the login page, remembering where they were. */
export function useRequireSession(): SessionContextValue {
  const session = useSession();
  const router = useRouter();
  const pathname = usePathname();
  useEffect(() => {
    if (session.status === "anonymous") {
      router.replace(`/login?next=${encodeURIComponent(pathname)}`);
    }
  }, [session.status, router, pathname]);
  return session;
}

/** Only allow same-site relative paths as post-login destinations (no open redirects). */
export function safeNext(next: string | null): string {
  if (!next || !next.startsWith("/") || next.startsWith("//") || next.startsWith("/\\")) {
    return "/dashboard";
  }
  return next;
}
