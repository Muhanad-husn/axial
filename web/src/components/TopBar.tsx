import { ThemeControl } from "@/components/ThemeControl";
import { UsageMeter } from "@/components/UsageMeter";
import type { UsageResponse } from "@/lib/api";

/** Wordmark left, the corpus pin, the two spend meters (issue #746) and the
 * theme control right. `usage` is `null` until `GET /me/usage` answers --
 * both meters render with their icon and a dash rather than waiting, since
 * a real ask has already been submitted (or not) regardless of this fetch. */
export function TopBar({
  corpusPin,
  usage,
}: {
  corpusPin: string | null;
  usage: UsageResponse | null;
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
        <ThemeControl />
      </span>
    </header>
  );
}
