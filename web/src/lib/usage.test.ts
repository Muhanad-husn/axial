import { describe, expect, it } from "vitest";

import { formatCostUsd, formatTokens } from "./usage";

describe("formatCostUsd", () => {
  it("renders null as an em dash, never a zero", () => {
    expect(formatCostUsd(null)).toBe("—");
  });

  it("renders a real zero as $0.00 -- a cache hit cost nothing, and that is not unknown", () => {
    expect(formatCostUsd(0)).toBe("$0.00");
  });

  it("renders a positive figure to two decimal places", () => {
    expect(formatCostUsd(4.821)).toBe("$4.82");
  });
});

describe("formatTokens", () => {
  it("renders null as an em dash", () => {
    expect(formatTokens(null)).toBe("—");
  });

  it("renders a real zero as 0, not unknown", () => {
    expect(formatTokens(0)).toBe("0");
  });

  it("groups a large figure the way toLocaleString does", () => {
    expect(formatTokens(128000)).toBe((128000).toLocaleString());
  });
});
