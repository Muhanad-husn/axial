import { ThemeControl } from "@/components/ThemeControl";
import { UsageMeter } from "@/components/UsageMeter";
import type { UsageResponse } from "@/lib/api";
import type { ThemeChoice } from "@/lib/theme";

/** Wordmark left, the corpus pin, the two spend meters (issue #746), the
 * theme control and sign-out right. `usage` is `null` until `GET /me/usage`
 * answers -- both meters render with their icon and a dash rather than
 * waiting, since a real ask has already been submitted (or not) regardless
 * of this fetch. `theme`/`onThemeChange` are `useTheme`'s own state (issue
 * #764) -- this component holds no theme logic of its own. */
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
    <header className="flex items-center justify-between gap-4 border-b border-rule2 py-[11px] pr-4 pl-5">
      <span className="text-[13px] font-semibold tracking-[0.14em] uppercase">Axial</span>
      <span className="flex items-center gap-2.5">
        {corpusPin && (
          <span className="hidden font-mono text-[10.5px] text-ink3 sm:inline">
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
          className="cursor-pointer rounded-md border border-rule px-2.5 py-1 text-[10px] font-semibold text-ink2"
        >
          Sign out
        </button>
      </span>
    </header>
  );
}
