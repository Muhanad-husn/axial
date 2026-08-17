import { describe, expect, it } from "vitest";

import type { Ground } from "@/lib/api";
import { accentFor, citationLine, citationSummary, markerLabel, quotesFor, sourceCount } from "./paper";

const groundWith = (source_id: string, extra: Partial<Ground["citation"]> = {}): Ground => ({
  ref_type: "chunk",
  ref_id: `${source_id}_02_troupes-speciales_003`,
  citation: {
    source_id,
    author: null,
    title: null,
    date: null,
    chapter: null,
    section: null,
    ...extra,
  },
});

describe("accentFor", () => {
  it("maps the three named kinds to their own accent", () => {
    expect(accentFor("a")).toBe("stated");
    expect(accentFor("b")).toBe("concluded");
    expect(accentFor("c")).toBe("spec");
  });

  it("falls back rather than crashing on an unrecognised kind", () => {
    expect(accentFor("z")).toBe("spec");
  });
});

describe("sourceCount", () => {
  it("counts distinct resolved source ids, not grounds", () => {
    const grounds = [groundWith("batatu-1999"), groundWith("batatu-1999"), groundWith("vignal-2022")];
    expect(sourceCount(grounds)).toBe(2);
  });

  it("is zero when the server resolved no citation, rather than counting grounds as sources", () => {
    // Two chunks from the SAME book. Counting grounds here would render
    // "concluded across 2 sources" for one source.
    const grounds: Ground[] = [
      { ref_type: "chunk", ref_id: "batatu-1999_08_x_003" },
      { ref_type: "chunk", ref_id: "batatu-1999_08_x_004" },
    ];
    expect(sourceCount(grounds)).toBe(0);
  });
});

describe("markerLabel", () => {
  it("states the (a) marker verbatim", () => {
    expect(markerLabel("a", [groundWith("batatu-1999")])).toBe("stated");
  });

  it("names the source count for a (b) claim", () => {
    const grounds = [groundWith("batatu-1999"), groundWith("vignal-2022"), groundWith("hinnebusch-2001")];
    expect(markerLabel("b", grounds)).toBe("concluded across 3 sources");
  });

  it("uses the singular for one source", () => {
    expect(markerLabel("b", [groundWith("batatu-1999")])).toBe("concluded across 1 source");
  });

  it("drops the count rather than inventing one when nothing resolved", () => {
    const grounds: Ground[] = [
      { ref_type: "chunk", ref_id: "batatu-1999_08_x_003" },
      { ref_type: "chunk", ref_id: "batatu-1999_08_x_004" },
    ];
    expect(markerLabel("b", grounds)).toBe("concluded");
  });

  it("states the (c) marker verbatim regardless of grounds", () => {
    expect(markerLabel("c", [])).toBe("runs past the books");
  });
});

describe("citationLine", () => {
  it("is null when nothing resolved", () => {
    expect(citationLine(undefined)).toBeNull();
  });

  it("prints the string the server formatted, rather than composing a second one", () => {
    const line = citationLine({
      source_id: "batatu-1999",
      author: "Batatu",
      title: null,
      date: "1999",
      chapter: "8",
      section: "Troupes Spéciales recruitment",
      display: "Batatu (1999), 8, Troupes Spéciales recruitment",
    });
    expect(line).toBe("Batatu (1999), 8, Troupes Spéciales recruitment");
  });

  it("falls back to the fields for a server that predates the display string", () => {
    const line = citationLine({
      source_id: "batatu-1999",
      author: "Batatu",
      title: null,
      date: "1999",
      chapter: "8",
      section: "Troupes Spéciales recruitment",
    });
    expect(line).toBe("Batatu (1999), ch. 8, Troupes Spéciales recruitment");
  });

  it("falls back to the source id when no author was resolved", () => {
    const line = citationLine({
      source_id: "batatu-1999",
      author: null,
      title: null,
      date: null,
      chapter: null,
      section: null,
    });
    expect(line).toBe("batatu-1999");
  });
});

describe("citationSummary", () => {
  it("states no supporting passage for empty grounds -- a correct value, not a gap", () => {
    expect(citationSummary([])).toBe("no supporting passage");
  });

  it("falls back to the raw pointer for a ground that resolved nothing", () => {
    expect(citationSummary([{ ref_type: "chunk", ref_id: "batatu-1999_02_x_003" }])).toBe(
      "chunk:batatu-1999_02_x_003",
    );
  });
});

describe("quotesFor", () => {
  it("is empty when no ground carries a quote -- locator mode, by construction", () => {
    expect(quotesFor([groundWith("batatu-1999")])).toEqual([]);
  });

  it("collects every ground's quote when the server resolved one", () => {
    const grounds = [groundWith("batatu-1999", { quote: "the passage itself" })];
    expect(quotesFor(grounds)).toEqual([
      { ref_id: "batatu-1999_02_troupes-speciales_003", quote: "the passage itself" },
    ]);
  });
});
