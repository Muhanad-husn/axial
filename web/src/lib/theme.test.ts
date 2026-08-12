import { afterEach, describe, expect, it, vi } from "vitest";

import { resolveTheme } from "./theme";

describe("resolving the theme", () => {
  it("follows the machine when the choice is system", () => {
    expect(resolveTheme("system", true)).toBe("dark");
    expect(resolveTheme("system", false)).toBe("light");
  });

  it("lets an explicit choice win in both directions", () => {
    expect(resolveTheme("light", true)).toBe("light");
    expect(resolveTheme("dark", false)).toBe("dark");
  });
});

const { getProfile, putProfile } = vi.hoisted(() => ({
  getProfile: vi.fn(),
  putProfile: vi.fn(),
}));

vi.mock("./api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./api")>();
  return { ...actual, getProfile, putProfile };
});

// `vitest.config.mts` runs these in a plain Node environment, with no
// `window` -- the local-storage fallback below (`loadLocalThemeChoice`) hits
// its own `catch` there exactly as it would in a browser with storage
// denied, which is what proves the fallback never throws past `theme.ts`.
describe("loadThemeChoice", () => {
  afterEach(() => {
    getProfile.mockReset();
  });

  it("reads the signed-in analyst's own profile", async () => {
    const { loadThemeChoice } = await import("./theme");
    getProfile.mockResolvedValue({ theme: "dark" });
    expect(await loadThemeChoice()).toBe("dark");
  });

  it("falls back to the browser's own value when the profile call fails", async () => {
    const { loadThemeChoice } = await import("./theme");
    getProfile.mockRejectedValue(new Error("401"));
    expect(await loadThemeChoice()).toBe("system");
  });
});

describe("saveThemeChoice", () => {
  afterEach(() => {
    putProfile.mockReset();
  });

  it("writes through to the profile", async () => {
    const { saveThemeChoice } = await import("./theme");
    putProfile.mockResolvedValue({ theme: "dark" });
    await saveThemeChoice("dark");
    expect(putProfile).toHaveBeenCalledWith("dark");
  });

  it("never throws past a failed write -- the browser's own storage is the fallback", async () => {
    const { saveThemeChoice } = await import("./theme");
    putProfile.mockRejectedValue(new Error("401"));
    await expect(saveThemeChoice("dark")).resolves.toBeUndefined();
  });
});
