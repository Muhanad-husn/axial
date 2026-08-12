"use client";

import { useCallback, useEffect, useState } from "react";

import {
  DARK_MEDIA_QUERY,
  loadThemeChoice,
  resolveTheme,
  saveThemeChoice,
  type ResolvedTheme,
  type ThemeChoice,
} from "@/lib/theme";

export interface ThemeState {
  /** False until the analyst's own theme is known -- `page.tsx` holds the
   * signed-in app off screen until this is true, so the app never paints one
   * analyst's theme and then repaints another's a moment later (issue #764's
   * own "no flash of the wrong theme on load" bar). */
  ready: boolean;
  choice: ThemeChoice;
  resolved: ResolvedTheme;
  setChoice: (choice: ThemeChoice) => void;
}

function systemPrefersDark(): boolean {
  return typeof window !== "undefined" && window.matchMedia(DARK_MEDIA_QUERY).matches;
}

/** Fetches the analyst's own theme once (`theme.ts`'s `loadThemeChoice`,
 * profile-backed now) and keeps `document.documentElement.dataset.theme` in
 * sync with it -- the same attribute the inline boot script in `layout.tsx`
 * already sets before first paint, corrected here to the analyst's real
 * choice the moment it is known. */
export function useTheme(): ThemeState {
  const [choice, setChoiceState] = useState<ThemeChoice>("system");
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let active = true;
    loadThemeChoice().then((loaded) => {
      if (!active) return;
      setChoiceState(loaded);
      setReady(true);
    });
    return () => {
      active = false;
    };
  }, []);

  const resolved = resolveTheme(choice, systemPrefersDark());

  useEffect(() => {
    if (ready) document.documentElement.dataset.theme = resolved;
  }, [ready, resolved]);

  const setChoice = useCallback((next: ThemeChoice) => {
    setChoiceState(next);
    void saveThemeChoice(next);
  }, []);

  return { ready, choice, resolved, setChoice };
}
