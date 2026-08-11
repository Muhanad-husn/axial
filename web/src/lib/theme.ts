/** Light, dark, system -- system by default.
 *
 * `data-theme` on the root is always the RESOLVED mode, so the stylesheet
 * carries exactly two declaration sets and no media query. That is what makes
 * an explicit choice win in both directions: an analyst on a dark machine who
 * picks Light gets light, because nothing in CSS is watching the machine.
 */

export type ThemeChoice = "light" | "dark" | "system";
export type ResolvedTheme = "light" | "dark";

export const THEME_CHOICES: readonly ThemeChoice[] = ["light", "dark", "system"];
export const THEME_STORAGE_KEY = "axial.theme";
export const DARK_MEDIA_QUERY = "(prefers-color-scheme: dark)";

export function resolveTheme(choice: ThemeChoice, systemPrefersDark: boolean): ResolvedTheme {
  if (choice === "light" || choice === "dark") return choice;
  return systemPrefersDark ? "dark" : "light";
}

function isThemeChoice(value: string | null): value is ThemeChoice {
  return value === "light" || value === "dark" || value === "system";
}

/** Where the choice lives. #687 says it belongs to the analyst, not the
 * device, but there is no analyst until #688 lands sign-in -- so it lives in
 * this browser, and these three functions are the seam a token-backed profile
 * read replaces. */
export function loadThemeChoice(): ThemeChoice {
  try {
    const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
    return isThemeChoice(stored) ? stored : "system";
  } catch {
    return "system";
  }
}

export function saveThemeChoice(choice: ThemeChoice): void {
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, choice);
  } catch {
    // A browser with storage denied still gets a working theme for this page.
  }
  for (const listener of listeners) listener();
}

const listeners = new Set<() => void>();

export function subscribeThemeChoice(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
