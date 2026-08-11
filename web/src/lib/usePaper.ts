"use client";

import { useEffect, useState } from "react";

import { ApiError, getPaper, type PaperResponse } from "@/lib/api";

export interface PaperState {
  paper: PaperResponse | null;
  error: string | null;
}

interface PaperEntry {
  askId: string;
  response: PaperResponse | null;
  error: string | null;
}

/** Fetches `GET /asks/{id}/paper` once the ask is `done` -- the record
 * exists only from that point on (§7.3 is written at the end of a run), so
 * this never fires before `ready`. What it last fetched is tagged with the
 * `askId` it belongs to; a fresh ask (a new `askId`) is served nothing
 * until its own fetch resolves, rather than showing the previous paper
 * while the new one loads. */
export function usePaper(askId: string | null, ready: boolean): PaperState {
  const [entry, setEntry] = useState<PaperEntry | null>(null);

  useEffect(() => {
    if (!askId || !ready) return;
    const controller = new AbortController();
    getPaper(askId, controller.signal)
      .then((response) => setEntry({ askId, response, error: null }))
      .catch((err) => {
        if (controller.signal.aborted) return;
        setEntry({
          askId,
          response: null,
          error: err instanceof ApiError ? err.message : "Could not load the paper.",
        });
      });
    return () => controller.abort();
  }, [askId, ready]);

  if (entry && entry.askId === askId) return { paper: entry.response, error: entry.error };
  return { paper: null, error: null };
}
