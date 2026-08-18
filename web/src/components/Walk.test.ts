/** `stageBadge` (issue #784 slice 03): the one phase badge a `draft`-stage
 * event gets on the walk, so an analyst can tell "drafting the essay" from
 * every other stage at a glance. No renderer is involved -- `Walk.tsx` is a
 * component and this repo's vitest config (`environment: "node"`, no
 * `@testing-library/react`) has never rendered one; every prior UI-adjacent
 * test in this package (`paper.test.ts`) is a pure-function pin for exactly
 * that reason, and this follows the same shape. */

import { describe, expect, it } from "vitest";

import { stageBadge } from "./Walk";

describe("stageBadge", () => {
  it("labels a draft-stage event 'Drafting'", () => {
    expect(stageBadge({ stage: "draft" })).toBe("Drafting");
    expect(stageBadge({ stage: "draft", heading: "The bellicist account" })).toBe("Drafting");
  });

  it("is null for every other stage, and for no stage at all", () => {
    expect(stageBadge({ stage: "interrogate" })).toBeNull();
    expect(stageBadge({ stage: "synthesize" })).toBeNull();
    expect(stageBadge({})).toBeNull();
  });
});
