import type { QuotaWindowStatus, UsageWindow } from "@/lib/api";
import { formatCostUsd, formatTokens } from "@/lib/usage";

interface QuotaRow {
  label: string;
  status: QuotaWindowStatus;
}

function formatReset(iso: string): string {
  return new Date(iso).toLocaleString();
}

/** One spend meter in the top bar (issue #746, screens `2a`/`2c`): an icon
 * and the priced estimate, `<details>` open on click to the rest of the
 * window's own figures -- never a panel of its own, matching the
 * `MetricsPanel`/`ExportControl` disclosure already in the top bar's row.
 *
 * Every number here is rendered exactly as `GET /me/usage` sent it: no sum,
 * no month boundary, no re-deriving `asks_charged` from `asks_made` (the
 * issue's one rule). `cost_usd`/`tokens` are `null`-preserving
 * (`formatCostUsd`/`formatTokens`) so an unknown figure is a dash, never the
 * `$0.00` a cache hit legitimately earns. The headline number always
 * carries "estimate" in the breakdown, because `llm.py`'s price table runs
 * ~14% high -- this is a priced ceiling, not a bill. */
export function UsageMeter({
  testId,
  icon,
  label,
  window,
  quota,
}: {
  testId: string;
  icon: string;
  label: string;
  window: UsageWindow | null;
  quota?: QuotaRow[];
}) {
  return (
    <details data-testid={testId} className="relative">
      <summary
        className="flex cursor-pointer list-none items-center gap-1 rounded-md border border-rule px-2 py-1 font-mono text-[10px] text-ink2"
        title={label}
        aria-label={label}
      >
        <span aria-hidden="true">{icon}</span>
        <span>{window ? formatCostUsd(window.cost_usd) : "—"}</span>
      </summary>
      <div className="absolute right-0 z-10 mt-1.5 w-60 rounded-md border border-rule bg-panel p-3.5 text-[11px] leading-[1.55] text-ink2 shadow-sm">
        <div className="mb-1.5 font-mono text-[9.5px] font-semibold tracking-[0.1em] text-ink3 uppercase">
          {label}
        </div>
        {window ? (
          <>
            <p className="m-0">Cost (estimate): {formatCostUsd(window.cost_usd)}</p>
            <p className="m-0">Tokens: {formatTokens(window.tokens)}</p>
            <p className="m-0">Asks made: {window.asks_made}</p>
            <p className="m-0">Asks charged against quota: {window.asks_charged}</p>
          </>
        ) : (
          <p className="m-0">Not available.</p>
        )}
        {quota?.map((row) => (
          <p key={row.label} className="m-0 mt-1.5 border-t border-rule2 pt-1.5">
            {row.label}: {row.status.used} of {row.status.limit}, resets {formatReset(row.status.reset_at)}
          </p>
        ))}
      </div>
    </details>
  );
}
