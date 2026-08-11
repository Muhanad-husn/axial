"use client";

import { useEffect, useState } from "react";

import { ApiError, listAsks, type AskStatus } from "@/lib/api";

export interface HistoryState {
  asks: AskStatus[];
  error: string | null;
}

/** `GET /asks` -- this analyst's own past asks, fetched on mount and again
 * whenever `refreshKey` changes, so a just-finished ask shows up in the list
 * without a reload. Nothing here sorts, filters or re-derives anything: the
 * rows are rendered exactly in the order and shape the service sent them. */
export function useHistory(refreshKey: unknown): HistoryState {
  const [asks, setAsks] = useState<AskStatus[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    listAsks(controller.signal)
      .then((response) => setAsks(response))
      .catch((err) => {
        if (controller.signal.aborted) return;
        setError(err instanceof ApiError ? err.message : "Could not load your past asks.");
      });
    return () => controller.abort();
  }, [refreshKey]);

  return { asks, error };
}
