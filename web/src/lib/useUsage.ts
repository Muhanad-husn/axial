"use client";

import { useEffect, useState } from "react";

import { ApiError, getUsage, type UsageResponse } from "@/lib/api";
import { currentSessionId } from "@/lib/session";

export interface UsageState {
  usage: UsageResponse | null;
  error: string | null;
}

/** `GET /me/usage` for this browser's session (`src/lib/session.ts`) and the
 * caller's own month to date -- fetched on mount and again whenever
 * `refreshKey` changes, so the top bar's meters catch up once an ask
 * finishes and its cost is known. The session id is always this browser's
 * own, from `currentSessionId()` -- never read off a served ask or paper,
 * which on a cache hit belongs to whoever asked first (#686/#746). */
export function useUsage(refreshKey: unknown): UsageState {
  const [usage, setUsage] = useState<UsageResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    getUsage(currentSessionId(), controller.signal)
      .then((response) => setUsage(response))
      .catch((err) => {
        if (controller.signal.aborted) return;
        setError(err instanceof ApiError ? err.message : "Could not load usage.");
      });
    return () => controller.abort();
  }, [refreshKey]);

  return { usage, error };
}
