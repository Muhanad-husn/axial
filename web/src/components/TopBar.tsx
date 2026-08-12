import { ThemeControl } from "@/components/ThemeControl";
import { UsageMeter } from "@/components/UsageMeter";
import type { UsageResponse } from "@/lib/api";
import type { ThemeChoice } from "@/lib/theme";

/** The Axial mark. Ink is `currentColor` -- it inherits the page's own
 * text colour, so this one markup serves light, dark and system themes with
 * no dark variant to keep in sync (verified: this only works inlined --
 * through an `<img>`/`next/image` the SVG can't see page CSS at all).
 * Mirrors the canonical asset at the repo root (`axial_logo.svg`), which
 * `axial console` (the operator UI, issue #770) reads directly; a browser
 * bundle can't read a file outside `web/`, so this is the same artwork
 * hand-kept in step with it rather than a third copy served from
 * `web/public/`. 22px, not smaller -- under ~20px the strokes get thin
 * enough that the mark reads as an asterisk. The two open-ring nodes are
 * `var(--panel)`, not a hardcoded white, so they read as a hole in the
 * mark rather than a solid dot on a dark background. */
function AxialMark() {
  return (
    <svg
      width="22"
      height="22"
      viewBox="0 0 120 120"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
      className="flex-none"
    >
      <g strokeLinecap="round" fill="none">
        <line x1="23.63" y1="81" x2="96.37" y2="39" stroke="currentColor" strokeWidth="3.4" />
        <line x1="23.63" y1="39" x2="96.37" y2="81" stroke="currentColor" strokeWidth="3.4" />
        <line x1="60" y1="18" x2="60" y2="102" stroke="#C8553D" strokeWidth="3.8" />
      </g>
      <circle cx="60" cy="60" r="7" fill="currentColor" />
      <circle cx="60" cy="60" r="2.6" fill="#C8553D" />
      <circle cx="60" cy="18" r="7.5" fill="#C8553D" />
      <circle cx="60" cy="102" r="7.5" fill="#C8553D" />
      <circle cx="23.63" cy="39" r="5.6" fill="currentColor" />
      <circle cx="96.37" cy="81" r="5.6" fill="currentColor" />
      <circle cx="23.63" cy="81" r="5.4" fill="var(--panel)" stroke="currentColor" strokeWidth="2.6" />
      <circle cx="96.37" cy="39" r="5.4" fill="var(--panel)" stroke="currentColor" strokeWidth="2.6" />
    </svg>
  );
}

/** Wordmark left, the corpus pin, the two spend meters (issue #746), the
 * theme control and sign-out right. `usage` is `null` until `GET /me/usage`
 * answers -- both meters render with their icon and a dash rather than
 * waiting, since a real ask has already been submitted (or not) regardless
 * of this fetch. `theme`/`onThemeChange` are `useTheme`'s own state (issue
 * #764) -- this component holds no theme logic of its own. A `.neon` glow
 * sits under the whole bar (issue #770); its strength is the
 * `--glowalpha`/`--bloomalpha` custom properties in `globals.css`, not
 * anything hardcoded here. */
export function TopBar({
  corpusPin,
  usage,
  theme,
  onThemeChange,
  onSignOut,
}: {
  corpusPin: string | null;
  usage: UsageResponse | null;
  theme: ThemeChoice;
  onThemeChange: (choice: ThemeChoice) => void;
  onSignOut: () => void;
}) {
  return (
    <header className="neon flex items-center justify-between gap-4 border-b border-rule2 py-[11px] pr-4 pl-5">
      <span className="flex items-center gap-2">
        <AxialMark />
        <span className="text-[13px] font-semibold tracking-[0.14em] uppercase">Axial</span>
      </span>
      <span className="flex items-center gap-2.5">
        {corpusPin && (
          <span
            className="hidden font-mono text-[10.5px] text-ink3 sm:inline"
            title={corpusPin}
            aria-label={`Corpus pin ${corpusPin}`}
          >
            corpus {corpusPin.slice(0, 8)}
          </span>
        )}
        <UsageMeter
          testId="usage-session"
          icon="⏱"
          label="This session"
          window={usage?.session ?? null}
        />
        <UsageMeter
          testId="usage-month"
          icon="▤"
          label="Month to date"
          window={usage?.month_to_date ?? null}
          quota={
            usage
              ? [
                  { label: "Daily quota", status: usage.quota.day },
                  { label: "Monthly quota", status: usage.quota.month },
                ]
              : undefined
          }
        />
        <ThemeControl choice={theme} onChange={onThemeChange} />
        <button
          type="button"
          onClick={onSignOut}
          title="Sign out"
          className="cursor-pointer rounded-md border border-rule px-2.5 py-1 text-[10px] font-semibold text-ink2"
        >
          Sign out
        </button>
      </span>
    </header>
  );
}
