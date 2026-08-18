// @vitest-environment jsdom

/** `Essay` renders the markdown `GET /asks/{id}/paper` serves as `essay`
 * (issue #784) -- a thesis, sections in plan order, and (defensively, since
 * a drafter's free-form prose could in principle carry one even though no
 * real essay on disk does today) a blockquote read as quoted book text,
 * distinct from the tool's own prose. */

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { Essay } from "./Essay";

afterEach(cleanup);

describe("Essay", () => {
  it("renders the thesis and every section heading, in order", () => {
    const markdown = [
      "# War made the state.",
      "",
      "## The mandate's bureaucracy",
      "",
      "A centralised bureaucracy was built.",
      "",
      "## The case for a Ba'thist rebuild",
      "",
      "The apparatus was rebuilt after 1963.",
      "",
    ].join("\n");

    render(<Essay markdown={markdown} />);

    const headings = screen.getAllByRole("heading").map((node) => node.textContent);
    expect(headings).toEqual([
      "War made the state.",
      "The mandate's bureaucracy",
      "The case for a Ba'thist rebuild",
    ]);
  });

  it("renders a blockquote as quoted book text, visually distinct from the tool's own prose", () => {
    const markdown = [
      "# War made the state.",
      "",
      "## The mandate's bureaucracy",
      "",
      "A centralised bureaucracy was built.",
      "",
      "> A residue, not a design.",
      "",
    ].join("\n");

    render(<Essay markdown={markdown} />);

    const quote = screen.getByText("A residue, not a design.");
    const prose = screen.getByText("A centralised bureaucracy was built.");
    // A markdown blockquote is its own element, structurally distinct from
    // the tool's own paragraphs -- the actual pixel treatment (italic,
    // muted ink, a rule) is a taste call judged from a rendered screenshot
    // (#770), not from jsdom's stylesheet-free computed style.
    const blockquote = quote.closest("blockquote");
    expect(blockquote).not.toBeNull();
    expect(blockquote?.className ?? "").toContain("italic");
    expect(prose.closest("blockquote")).toBeNull();
  });
});
