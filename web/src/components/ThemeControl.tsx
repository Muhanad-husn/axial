import { THEME_CHOICES, type ThemeChoice } from "@/lib/theme";

/** The segmented control in the top bar. Driven entirely by props now
 * (issue #764) -- `useTheme` (`@/lib/useTheme`) owns the fetch, the profile
 * write, and applying the resolved mode to the root; this component only
 * ever renders whatever it is given, the same pattern `TopBar` already uses
 * for the spend meters. */
export function ThemeControl({
  choice,
  onChange,
}: {
  choice: ThemeChoice;
  onChange: (choice: ThemeChoice) => void;
}) {
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
          onClick={() => onChange(option)}
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
