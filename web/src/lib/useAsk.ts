"use client";

import { useCallback, useEffect, useReducer, useRef, useState } from "react";

import {
  ApiError,
  type AskStatus,
  getAsk,
  openEventStream,
  submitAsk,
} from "@/lib/api";
import {
  initialWalkState,
  parseFrames,
  walkReducer,
  type WalkAction,
  type WalkState,
} from "@/lib/events";
import { currentSessionId } from "@/lib/session";

/** How hard the client tries to get back on the stream before it tells the
 * analyst it has lost contact. `attempts` resets to 0 the moment a frame
 * arrives (issue #751) -- this ceiling only bounds a run of *consecutive*
 * failed reconnects, never the total over an ask's 7-15 minute life, so a
 * stream that keeps delivering events one reconnect at a time never trips
 * it. Raised from 3: with the server now warming the connection (`: keepalive`
 * on the quiet path, `api.py::_event_stream`) most drops the ceiling still
 * has to absorb are the ones that happen anyway on a real network. */
const MAX_ATTEMPTS = 5;
const RETRY_DELAY_MS = 1000;

const LOST_CONTACT =
  "Lost contact with the Axial service. The ask may still be running -- reload this page to pick it up.";

export interface Brief {
  case: string;
  request: string;
  weights: Record<string, number> | null;
}

export interface AskSession {
  brief: Brief | null;
  askId: string | null;
  status: AskStatus | null;
  walk: WalkState;
  submitting: boolean;
  /** A refusal from `POST /asks` -- on a `429` this is the service's own
   * wording, rendered verbatim. */
  submitError: string | null;
  submit: (brief: Brief) => void;
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

interface WatchOptions {
  retryDelayMs?: number;
  maxAttempts?: number;
}

/** Replay, then tail, until the job reaches a terminal state. When the
 * stream ends the client asks the service what state the job is in rather
 * than inferring one from a closed connection -- a clean close after a
 * finished job and a dead API look identical from here, and only one of them
 * is an error.
 *
 * Module-level rather than defined inside `useAsk` so it can be driven
 * directly in a test with a mocked `openEventStream`/`getAsk`, with no
 * React renderer involved (issue #751) -- `retryDelayMs`/`maxAttempts`
 * default to the real constants and exist only so a test can shrink the
 * backoff and the ceiling instead of waiting on real seconds. */
export async function watchAskStream(
  id: string,
  signal: AbortSignal,
  dispatch: (action: WalkAction) => void,
  setStatus: (status: AskStatus | null) => void,
  { retryDelayMs = RETRY_DELAY_MS, maxAttempts = MAX_ATTEMPTS }: WatchOptions = {},
): Promise<void> {
  let lastSeq = 0;
  let attempts = 0;
  while (!signal.aborted) {
    try {
      const response = await openEventStream(id, lastSeq, signal);
      const reader = response.body!.pipeThrough(new TextDecoderStream()).getReader();
      let buffer = "";
      let sentFinalError = false;
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += value;
        const { frames, rest } = parseFrames(buffer);
        buffer = rest;
        for (const frame of frames) {
          // A frame is progress, full stop -- reset here rather than only
          // when the read loop later ends cleanly (issue #751). Without
          // this, a connection that delivers events and then drops still
          // spends one of the same `maxAttempts`, so a stream working
          // perfectly one reconnect at a time still declares the service
          // lost.
          attempts = 0;
          if (frame.id === null) sentFinalError = true;
          else if (frame.id > lastSeq) lastSeq = frame.id;
          dispatch({ type: "frame", frame });
        }
      }
      if (sentFinalError) {
        setStatus(await getAsk(id, signal).catch(() => null));
        return;
      }
      const settled = await getAsk(id, signal);
      if (settled.state === "done" || settled.state === "failed") {
        setStatus(settled);
        dispatch({ type: "settled", state: settled.state, error: settled.error });
        return;
      }
      // The stream closed while the job is still alive. Resume from where
      // it stopped rather than starting over.
    } catch {
      if (signal.aborted) return;
      attempts += 1;
      if (attempts >= maxAttempts) {
        dispatch({ type: "lost", error: LOST_CONTACT });
        return;
      }
      await sleep(retryDelayMs);
    }
  }
}

export function useAsk(): AskSession {
  const [walk, dispatch] = useReducer(walkReducer, initialWalkState);
  const [brief, setBrief] = useState<Brief | null>(null);
  const [askId, setAskId] = useState<string | null>(null);
  const [status, setStatus] = useState<AskStatus | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => () => abortRef.current?.abort(), []);

  const watch = useCallback(
    (id: string, signal: AbortSignal) => watchAskStream(id, signal, dispatch, setStatus),
    [],
  );

  const submit = useCallback(
    (next: Brief) => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      setBrief(next);
      setAskId(null);
      setStatus(null);
      setSubmitError(null);
      setSubmitting(true);
      dispatch({ type: "reset" });

      void (async () => {
        try {
          const accepted = await submitAsk(
            {
              case: next.case,
              request: next.request,
              weights: next.weights,
              session_id: currentSessionId(),
            },
            controller.signal,
          );
          setAskId(accepted.id);
          setSubmitting(false);
          await watch(accepted.id, controller.signal);
        } catch (error) {
          if (controller.signal.aborted) return;
          setSubmitting(false);
          setSubmitError(
            error instanceof ApiError
              ? error.message
              : "Could not reach the Axial service to submit this ask.",
          );
        }
      })();
    },
    [watch],
  );

  return { brief, askId, status, walk, submitting, submitError, submit };
}
