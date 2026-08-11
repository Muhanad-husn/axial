import { describe, expect, it } from "vitest";

import {
  initialWalkState,
  parseFrames,
  walkReducer,
  type SseFrame,
  type WalkState,
} from "./events";

const frame = (id: number | null, message: string): SseFrame => ({
  id,
  data: JSON.stringify({ message, detail: {} }),
});

const fold = (frames: SseFrame[], from: WalkState = initialWalkState): WalkState =>
  frames.reduce((state, f) => walkReducer(state, { type: "frame", frame: f }), from);

describe("framing the stream", () => {
  it("reads the id line and the data line the service sends", () => {
    const { frames, rest } = parseFrames('id: 3\ndata: {"message": "read 48 notes"}\n\n');
    expect(frames).toEqual([{ id: 3, data: '{"message": "read 48 notes"}' }]);
    expect(rest).toBe("");
  });

  it("holds a partial frame back until the rest of it arrives", () => {
    const first = parseFrames('id: 1\ndata: {"message": "a"}\n\nid: 2\ndata: {"mes');
    expect(first.frames).toHaveLength(1);
    expect(first.rest).toBe('id: 2\ndata: {"mes');

    const second = parseFrames(first.rest + 'sage": "b"}\n\n');
    expect(second.frames).toEqual([{ id: 2, data: '{"message": "b"}' }]);
  });

  it("keeps the id null on the final frame a failed job sends", () => {
    const { frames } = parseFrames('data: {"message": "the worker died"}\n\n');
    expect(frames[0].id).toBeNull();
  });
});

describe("folding frames into the walk", () => {
  it("shows the events in the order they arrived", () => {
    const state = fold([frame(1, "interrogated the question"), frame(2, "walked the relations")]);
    expect(state.events.map((event) => event.message)).toEqual([
      "interrogated the question",
      "walked the relations",
    ]);
    expect(state.phase).toBe("running");
    expect(state.lastSeq).toBe(2);
  });

  it("does not repeat an event when a resume overlaps what was already shown", () => {
    const beforeTheBreak = fold([frame(1, "one"), frame(2, "two")]);
    const afterResuming = fold([frame(2, "two"), frame(3, "three")], beforeTheBreak);
    expect(afterResuming.events.map((event) => event.message)).toEqual(["one", "two", "three"]);
    expect(afterResuming.lastSeq).toBe(3);
  });

  it("ends the walk when the job's own state says it is done", () => {
    const state = walkReducer(fold([frame(1, "one")]), {
      type: "settled",
      state: "done",
      error: null,
    });
    expect(state.phase).toBe("done");
    expect(state.error).toBeNull();
  });

  it("takes the failure from the last frame, which carries no id", () => {
    const state = fold([frame(1, "one"), frame(null, "no vault is bound to this pin")]);
    expect(state.phase).toBe("failed");
    expect(state.error).toBe("no vault is bound to this pin");
    expect(state.events).toHaveLength(2);
    expect(state.lastSeq).toBe(1);
  });

  it("says so when the stream broke and the service could not be reached", () => {
    const state = walkReducer(fold([frame(1, "one")]), {
      type: "lost",
      error: "Lost contact with the Axial service.",
    });
    expect(state.phase).toBe("failed");
    expect(state.error).toBe("Lost contact with the Axial service.");
  });
});
