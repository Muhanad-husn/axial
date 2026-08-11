"use client";

import { useEffect, useSyncExternalStore } from "react";

import {
  DARK_MEDIA_QUERY,
  loadThemeChoice,
  resolveTheme,
  saveThemeChoice,
  subscribeThemeChoice,
  THEME_CHOICES,
  type ThemeChoice,
} from "@/lib/theme";

function useSystemPrefersDark(): boolean {
  return useSyncExternalStore(
    (onChange) => {
      const media = window.matchMedia(DARK_MEDIA_QUERY);
      media.addEventListener("change", onChange);
      return () => media.removeEventListener("change", onChange);
    },
    () => window.matchMedia(DARK_MEDIA_QUERY).matches,
    () => false,
  );
}

function useThemeChoice(): ThemeChoice {
  return useSyncExternalStore(subscribeThemeChoice, loadThemeChoice, () => "system" as ThemeChoice);
}

/** The segmented control in the top bar. It writes the resolved mode onto the
 * root; `globals.css` does the rest. The inline boot script in the layout has
 * already resolved the same value before first paint, so this never repaints
 * the page on load -- it only takes over when the analyst chooses. */
export function ThemeControl() {
  const choice = useThemeChoice();
  const systemPrefersDark = useSystemPrefersDark();
  const resolved = resolveTheme(choice, systemPrefersDark);

  useEffect(() => {
    document.documentElement.dataset.theme = resolved;
  }, [resolved]);

  return (
    <div
      className="flex overflow-hidden rounded-md border border-rule"
      role="group"
      aria-label="Theme"
    >
      {THEME_CHOICES.map((option) => (
        <button
          key={option}
          type="button"
          aria-pressed={choice === option}
          onClick={() => saveThemeChoice(option)}
          className={`cursor-pointer border-r border-rule px-[9px] py-[5px] font-mono text-[9px] font-semibold tracking-[0.09em] uppercase last:border-r-0 ${
            choice === option ? "bg-ink text-panel" : "text-ink3"
          }`}
        >
          {option}
        </button>
      ))}
    </div>
  );
}
