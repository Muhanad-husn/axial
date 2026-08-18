// @vitest-environment jsdom

/** `Paper` moves the claim list behind its own disclosure once an `essay`
 * exists (issue #784) -- the claims themselves are untouched, only where
 * they sit. Driven with a minimal `AnalysisRecord` fixture; the marker/
 * citation formatting itself is already pinned in `src/lib/paper.test.ts`
 * and `e2e/paper.spec.ts`, so this file only pins the move. */

import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { AnalysisRecord } from "@/lib/api";
import { Paper } from "./Paper";

afterEach(cleanup);

function record(overrides: Partial<AnalysisRecord> = {}): AnalysisRecord {
  return {
    brief_id: "b1",
    brief: { case: "Damascus", request: "Did Mandate recruitment shape later rule?" },
    interrogation: { disposition: "answer" },
    claims: [
      {
        claim_id: "c1",
        text: "Recruitment drew disproportionately from the Alawi highlands.",
        kind: "a",
        grounds: [],
        confidence: "high",
        names_touched: [],
      },
    ],
    ...overrides,
  };
}

const ESSAY = "# War made the state.\n\n## The mandate's bureaucracy\n\nA bureaucracy was built.\n";

describe("Paper", () => {
  it("shows the essay and moves the claim list behind a closed disclosure when essay is present", () => {
    render(<Paper record={record()} essay={ESSAY} />);

    expect(screen.getByTestId("essay")).toBeTruthy();

    const disclosure = screen.getByTestId("claims-disclosure") as HTMLDetailsElement;
    expect(disclosure.tagName).toBe("DETAILS");
    expect(disclosure.open).toBe(false);
    expect(within(disclosure).getByTestId("paper")).toBeTruthy();
  });

  it("shows the claim list plus a stated absence when essay is missing", () => {
    render(<Paper record={record()} />);

    expect(screen.queryByTestId("essay")).toBeNull();
    expect(screen.queryByTestId("claims-disclosure")).toBeNull();
    expect(screen.getByTestId("no-essay").textContent).toBe("No essay was drafted for this answer.");
    expect(screen.getByTestId("paper")).toBeTruthy();
  });

  it("renders a refusal unchanged whether or not essay is present", () => {
    const refused = record({
      interrogation: { disposition: "refuse", refusal: { reason: "the corpus is thin here" } },
    });

    const { container: withEssay } = render(<Paper record={refused} essay={ESSAY} />);
    const { container: withoutEssay } = render(<Paper record={refused} />);

    expect(withEssay.innerHTML).toBe(withoutEssay.innerHTML);
    expect(screen.getAllByText(/the corpus is thin here/)).toHaveLength(2);
    expect(screen.queryAllByTestId("essay")).toHaveLength(0);
    expect(screen.queryAllByTestId("no-essay")).toHaveLength(0);
  });

  it("renders the claim list inside the disclosure exactly as it renders without an essay (the move, pinned)", () => {
    const { container: withoutEssay } = render(<Paper record={record()} />);
    const withoutEssayPaper = withoutEssay.querySelector('[data-testid="paper"]')?.outerHTML;
    const withoutEssayLegend = withoutEssay.querySelector('[data-testid="legend"]')?.outerHTML;
    cleanup();

    const { container: withEssay } = render(<Paper record={record()} essay={ESSAY} />);
    const withEssayPaper = withEssay.querySelector('[data-testid="paper"]')?.outerHTML;
    const withEssayLegend = withEssay.querySelector('[data-testid="legend"]')?.outerHTML;

    expect(withEssayPaper).toBe(withoutEssayPaper);
    expect(withEssayLegend).toBe(withoutEssayLegend);
  });
});
