"use client";

import { useCallback, useEffect, useReducer, useRef, useState } from "react";

import {
  ApiError,
  type AskStatus,
  getAsk,
  openEventStream,
  submitAsk,
} from "@/lib/api";
import { initialWalkState, parseFrames, walkReducer, type WalkState } from "@/lib/events";
import { currentSessionId } from "@/lib/session";

/** How hard the client tries to get back on the stream before it tells the
 * analyst it has lost contact. A retry policy, not a tuned heuristic: two
 * seconds of silence is worth absorbing, thirty is a lie. */
const MAX_ATTEMPTS = 3;
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

export function useAsk(): AskSession {
  const [walk, dispatch] = useReducer(walkReducer, initialWalkState);
  const [brief, setBrief] = useState<Brief | null>(null);
  const [askId, setAskId] = useState<string | null>(null);
  const [status, setStatus] = useState<AskStatus | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => () => abortRef.current?.abort(), []);

  /** Replay, then tail, until the job reaches a terminal state. When the
   * stream ends the client asks the service what state the job is in rather
   * than inferring one from a closed connection -- a clean close after a
   * finished job and a dead API look identical from here, and only one of them
   * is an error. */
  const watch = useCallback(async (id: string, signal: AbortSignal) => {
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
            if (frame.id === null) sentFinalError = true;
            else if (frame.id > lastSeq) lastSeq = frame.id;
            dispatch({ type: "frame", frame });
          }
        }
        attempts = 0;
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
        if (attempts >= MAX_ATTEMPTS) {
          dispatch({ type: "lost", error: LOST_CONTACT });
          return;
        }
        await sleep(RETRY_DELAY_MS);
      }
    }
  }, []);

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
