/** The walk: what `GET /asks/{id}/events` sends, and what the screen shows.
 *
 * The service streams one frame per `on_event` call as
 * `{"message": ..., "detail": {...}}` with an `id:` line carrying the
 * sequence number. The stream ends when the job reaches a terminal state; a
 * failed job sends its error as one final frame with NO `id:`, because that
 * frame is synthetic and not replayable.
 *
 * Two things here are real logic and are unit-tested: framing the byte stream
 * (getting the `id:` line wrong breaks resume) and folding frames into state
 * (a resume that repeats an event would show it twice). Nothing else in this
 * file decides anything -- the phase comes from the service's own job state.
 */

export interface SseFrame {
  id: number | null;
  data: string;
}

/** Split whatever has arrived so far into whole frames, keeping the partial
 * tail for the next chunk. */
export function parseFrames(buffer: string): { frames: SseFrame[]; rest: string } {
  const blocks = buffer.split("\n\n");
  const rest = blocks.pop() ?? "";
  const frames: SseFrame[] = [];
  for (const block of blocks) {
    let id: number | null = null;
    const data: string[] = [];
    for (const rawLine of block.split("\n")) {
      const line = rawLine.replace(/\r$/, "");
      if (line.startsWith("id:")) {
        const parsed = Number.parseInt(line.slice(3).trim(), 10);
        if (Number.isFinite(parsed)) id = parsed;
      } else if (line.startsWith("data:")) {
        data.push(line.slice(5).replace(/^ /, ""));
      }
    }
    if (data.length > 0) frames.push({ id, data: data.join("\n") });
  }
  return { frames, rest };
}

export interface WalkEvent {
  seq: number | null;
  message: string;
  detail: Record<string, unknown>;
}

export type WalkPhase = "queued" | "running" | "done" | "failed";

export interface WalkState {
  phase: WalkPhase;
  events: WalkEvent[];
  /** What `Last-Event-ID` names on reconnect. */
  lastSeq: number;
  error: string | null;
}

export const initialWalkState: WalkState = {
  phase: "queued",
  events: [],
  lastSeq: 0,
  error: null,
};

export type WalkAction =
  /** A new ask replaces the last one's walk. */
  | { type: "reset" }
  /** One frame off the stream. */
  | { type: "frame"; frame: SseFrame }
  /** The job's own state, read from `GET /asks/{id}` once the stream ends. */
  | { type: "settled"; state: string; error: string | null }
  /** The stream broke and the service could not be reached to say why. */
  | { type: "lost"; error: string };

export function walkReducer(state: WalkState, action: WalkAction): WalkState {
  switch (action.type) {
    case "reset":
      return initialWalkState;
    case "frame": {
      const { id, data } = action.frame;
      let parsed: { message?: unknown; detail?: unknown };
      try {
        parsed = JSON.parse(data);
      } catch {
        return state;
      }
      const event: WalkEvent = {
        seq: id,
        message: typeof parsed.message === "string" ? parsed.message : "",
        detail:
          parsed.detail && typeof parsed.detail === "object"
            ? (parsed.detail as Record<string, unknown>)
            : {},
      };
      // A resume overlaps rather than misses when a reconnect is imprecise;
      // an event already shown is dropped, never shown twice.
      if (id !== null && id <= state.lastSeq) return state;
      if (id === null) {
        // The unstored final frame a failed job sends: its message is the
        // job's error, and it is the last thing the stream will send.
        return {
          ...state,
          phase: "failed",
          events: [...state.events, event],
          error: event.message,
        };
      }
      return {
        ...state,
        phase: "running",
        events: [...state.events, event],
        lastSeq: id,
      };
    }
    case "settled": {
      if (action.state === "failed") {
        return { ...state, phase: "failed", error: state.error ?? action.error };
      }
      if (action.state === "done") return { ...state, phase: "done" };
      return state;
    }
    case "lost":
      return { ...state, phase: "failed", error: state.error ?? action.error };
  }
}
