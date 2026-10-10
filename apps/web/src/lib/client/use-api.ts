"use client";

import { useCallback, useEffect, useState } from "react";

import { api, ApiError } from "./api";

export type Loadable<T> = {
  data: T | null;
  error: ApiError | null;
  loading: boolean;
  reload: () => Promise<void>;
};

/** Fetch `path` on mount (and whenever it changes). Pass `null` to skip. */
export function useApi<T>(path: string | null): Loadable<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(path !== null);

  const load = useCallback(async () => {
    if (path === null) return;
    setLoading(true);
    try {
      setData(await api<T>(path));
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError(0, "unknown"));
    } finally {
      setLoading(false);
    }
  }, [path]);

  useEffect(() => {
    // Data fetching on mount: state updates happen after the request resolves.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  return { data, error, loading, reload: load };
}
