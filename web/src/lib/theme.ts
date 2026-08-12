/** Light, dark, system -- system by default.
 *
 * `data-theme` on the root is always the RESOLVED mode, so the stylesheet
 * carries exactly two declaration sets and no media query. That is what makes
 * an explicit choice win in both directions: an analyst on a dark machine who
 * picks Light gets light, because nothing in CSS is watching the machine.
 *
 * **The choice lives on the analyst's own profile now** (issue #764):
 * `loadThemeChoice`/`saveThemeChoice` read and write `GET`/`PUT /me/profile`
 * (`@/lib/api`), falling back to this browser's `localStorage` only when that
 * call fails -- signed out, unconfigured, or a network blip. Browser storage
 * is the fallback, never the source of truth, so two analysts in turn on the
 * same machine never see a trace of each other's choice in it.
 */

import { getProfile, putProfile } from "@/lib/api";

export type ThemeChoice = "light" | "dark" | "system";
export type ResolvedTheme = "light" | "dark";

export const THEME_CHOICES: readonly ThemeChoice[] = ["light", "dark", "system"];
export const THEME_STORAGE_KEY = "axial.theme";
export const DARK_MEDIA_QUERY = "(prefers-color-scheme: dark)";

export function resolveTheme(choice: ThemeChoice, systemPrefersDark: boolean): ResolvedTheme {
  if (choice === "light" || choice === "dark") return choice;
  return systemPrefersDark ? "dark" : "light";
}

function isThemeChoice(value: string | null | undefined): value is ThemeChoice {
  return value === "light" || value === "dark" || value === "system";
}

function loadLocalThemeChoice(): ThemeChoice {
  try {
    const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
    return isThemeChoice(stored) ? stored : "system";
  } catch {
    return "system";
  }
}

function saveLocalThemeChoice(choice: ThemeChoice): void {
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, choice);
  } catch {
    // A browser with storage denied still gets a working theme for this page.
  }
  for (const listener of listeners) listener();
}

/** The signed-in analyst's own theme, or this browser's fallback when there
 * is no profile to read (module docstring). */
export async function loadThemeChoice(): Promise<ThemeChoice> {
  try {
    const profile = await getProfile();
    return isThemeChoice(profile.theme) ? profile.theme : "system";
  } catch {
    return loadLocalThemeChoice();
  }
}

/** Writes through to the profile; falls back to this browser's storage only
 * when that write fails, so the choice is never silently lost. */
export async function saveThemeChoice(choice: ThemeChoice): Promise<void> {
  try {
    await putProfile(choice);
  } catch {
    saveLocalThemeChoice(choice);
  }
}

const listeners = new Set<() => void>();

/** Notified after a fallback local write (module docstring) -- kept for the
 * signed-out/unconfigured path, which still runs on this browser's own
 * storage and nothing else. */
export function subscribeThemeChoice(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
