"use client";

import { useState } from "react";

import { THEME_CHOICES, type ThemeChoice } from "@/lib/theme";

/** The theme control, collapsed to the current choice (issue #770) -- three
 * always-visible segments were crowding a bar that already holds two meters
 * and sign-out. A native `<details>` does the disclosure, the same pattern
 * `UsageMeter` already uses for its own panel: `role="group"` is `<details>`'s
 * implicit role, so `aria-label="Theme"` names it whether it's open or shut,
 * and the phone-width e2e assertion (`history-usage.spec.ts`) that it stays
 * on screen needs no change. Picking an option closes it back up. */
export function ThemeControl({
  choice,
  onChange,
}: {
  choice: ThemeChoice;
  onChange: (choice: ThemeChoice) => void;
}) {
  const [open, setOpen] = useState(false);

  return (
    <details
      className="relative"
      role="group"
      aria-label="Theme"
      open={open}
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary
        title="Theme"
        className="flex cursor-pointer list-none items-center rounded-md border border-rule px-2 py-1 font-mono text-[9px] font-semibold tracking-[0.09em] text-ink2 uppercase"
      >
        {choice}
      </summary>
      <div className="absolute right-0 z-10 mt-1.5 flex overflow-hidden rounded-md border border-rule bg-panel shadow-sm">
        {THEME_CHOICES.map((option) => (
          <button
            key={option}
            type="button"
            aria-pressed={choice === option}
            onClick={() => {
              onChange(option);
              setOpen(false);
            }}
            className={`cursor-pointer border-r border-rule px-[9px] py-[5px] font-mono text-[9px] font-semibold tracking-[0.09em] uppercase last:border-r-0 ${
              choice === option ? "bg-ink text-panel" : "text-ink3"
            }`}
          >
            {option}
          </button>
        ))}
      </div>
    </details>
  );
}
