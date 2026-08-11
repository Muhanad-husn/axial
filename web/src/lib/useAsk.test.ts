/** `watchAskStream` (issue #751): a stream that keeps delivering events must
 * never declare `LOST_CONTACT`, no matter how many times the underlying
 * connection drops and reconnects -- and a stream that truly never delivers
 * anything must still declare it. Driven directly against a mocked
 * `openEventStream`/`getAsk`, with no React renderer involved: `useAsk`
 * itself is a thin wrapper (`useCallback` closing over `dispatch`/
 * `setStatus`) with no logic of its own left to test.
 */

import { afterEach, describe, expect, it, vi } from "vitest";

import { watchAskStream } from "./useAsk";
import type { AskStatus } from "./api";
import type { WalkAction } from "./events";

const { openEventStream, getAsk } = vi.hoisted(() => ({
  openEventStream: vi.fn(),
  getAsk: vi.fn(),
}));

vi.mock("./api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./api")>();
  return { ...actual, openEventStream, getAsk };
});

afterEach(() => {
  vi.restoreAllMocks();
  openEventStream.mockReset();
  getAsk.mockReset();
});

/** A `Response`-like object whose body streams `frameCount` SSE frames
 * (`id: N\ndata: {...}\n\n` each) and then either errors (simulating a
 * connection that drops mid-stream, the case that used to burn an attempt
 * even though it was delivering) or closes cleanly. */
function frameStream(startId: number, frameCount: number, thenError: boolean): Response {
  const encoder = new TextEncoder();
  let sent = 0;
  // `pull`, not `start` + eager `enqueue` -- erroring a stream discards any
  // chunk still sitting in its queue unread, so an eager enqueue-then-error
  // would drop the very frame this test needs delivered before the drop.
  // `pull` runs once per read, so the frame is drained by a real `read()`
  // before the next `pull` call ends the stream.
  const body = new ReadableStream<Uint8Array>({
    pull(controller) {
      if (sent < frameCount) {
        const id = startId + sent;
        sent += 1;
        controller.enqueue(encoder.encode(`id: ${id}\ndata: {"message": "step ${id}"}\n\n`));
        return;
      }
      if (thenError) controller.error(new Error("connection dropped"));
      else controller.close();
    },
  });
  return { body } as unknown as Response;
}

describe("watchAskStream", () => {
  it("never declares the service lost while frames keep arriving, however many times the connection drops", async () => {
    // Ten consecutive mid-stream drops -- more than both the old ceiling (3)
    // and the new one (5). Each connection delivers one frame before it
    // drops, so `attempts` resets before every increment and the ceiling is
    // never reached.
    const DROPS = 10;
    let nextId = 1;
    for (let i = 0; i < DROPS; i++) {
      openEventStream.mockImplementationOnce(() => {
        const stream = frameStream(nextId, 1, true);
        nextId += 1;
        return Promise.resolve(stream);
      });
    }
    // The final connection ends cleanly and the job is done.
    openEventStream.mockImplementationOnce(() => Promise.resolve(frameStream(nextId, 1, false)));
    getAsk.mockResolvedValue({ state: "done", error: null } as AskStatus);

    const dispatched: WalkAction[] = [];
    const setStatus = vi.fn();
    const controller = new AbortController();

    await watchAskStream(
      "ask-1",
      controller.signal,
      (action) => dispatched.push(action),
      setStatus,
      { retryDelayMs: 0, maxAttempts: 5 },
    );

    expect(openEventStream).toHaveBeenCalledTimes(DROPS + 1);
    expect(dispatched.some((a) => a.type === "lost")).toBe(false);
    expect(dispatched.filter((a) => a.type === "frame")).toHaveLength(DROPS + 1);
    expect(dispatched.at(-1)).toEqual({ type: "settled", state: "done", error: null });
  });

  it("still declares the service lost when nothing ever arrives", async () => {
    openEventStream.mockRejectedValue(new Error("service unreachable"));

    const dispatched: WalkAction[] = [];
    const controller = new AbortController();

    await watchAskStream(
      "ask-1",
      controller.signal,
      (action) => dispatched.push(action),
      vi.fn(),
      { retryDelayMs: 0, maxAttempts: 3 },
    );

    expect(openEventStream).toHaveBeenCalledTimes(3);
    expect(dispatched).toHaveLength(1);
    expect(dispatched[0].type).toBe("lost");
  });
});
