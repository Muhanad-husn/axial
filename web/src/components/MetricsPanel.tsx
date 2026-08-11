import type { Metrics } from "@/lib/api";

/** The telemetry sibling (issue #745, #724): cost, model-by-pass, the
 * coverage map, confidence -- never inside the prose (`render.py`
 * deliberately keeps it out), shut until an analyst opens it. A plain
 * `<details>` is the whole disclosure mechanism, matching the Composer's
 * own "weight sources" panel -- no state to wire, and it is collapsed
 * by construction because neither element carries `open`. */
export function MetricsPanel({ metrics }: { metrics: Metrics }) {
  const costByPass = Object.entries(metrics.cost?.by_pass ?? {});
  const modelByPass = Object.entries(metrics.model_by_pass ?? {});
  const coverage = Object.entries(metrics.coverage_map ?? {}).sort(([a], [b]) => a.localeCompare(b));

  return (
    <details data-testid="metrics-panel" className="rounded-lg border border-rule bg-panel">
      <summary className="cursor-pointer px-4 py-2.5 font-mono text-[9.5px] font-semibold tracking-[0.13em] text-ink3 uppercase">
        Metrics
      </summary>
      <div className="flex flex-col gap-4 border-t border-rule2 px-4 py-3.5 text-[11.5px] leading-[1.5] text-ink2">
        <div>
          <div className="mb-1 font-mono text-[9.5px] font-semibold tracking-[0.1em] text-ink3 uppercase">
            Cost
          </div>
          <p className="m-0">
            Total: {metrics.cost?.total_usd != null ? `$${metrics.cost.total_usd.toFixed(2)}` : "unknown"}
          </p>
          {costByPass.map(([pass, entry]) => (
            <p key={pass} className="m-0 font-mono text-[10.5px] text-ink3">
              {pass}: {entry.total_tokens} tokens, {entry.usd != null ? `$${entry.usd.toFixed(4)}` : "unknown"}
            </p>
          ))}
        </div>

        <div>
          <div className="mb-1 font-mono text-[9.5px] font-semibold tracking-[0.1em] text-ink3 uppercase">
            Model by pass
          </div>
          {modelByPass.length === 0 ? (
            <p className="m-0">(none)</p>
          ) : (
            modelByPass.map(([pass, model]) => (
              <p key={pass} className="m-0 font-mono text-[10.5px]">
                {pass}: {model}
              </p>
            ))
          )}
        </div>

        <div>
          <div className="mb-1 font-mono text-[9.5px] font-semibold tracking-[0.1em] text-ink3 uppercase">
            Coverage map
          </div>
          {coverage.length === 0 ? (
            <p className="m-0">(none)</p>
          ) : (
            coverage.map(([name, entry]) => (
              <p key={name} className="m-0">
                {name}: {entry.coverage_band} ({entry.evidence_note_count} of{" "}
                {entry.corpus_note_count ?? "?"} notes)
              </p>
            ))
          )}
        </div>

        <div>
          <div className="mb-1 font-mono text-[9.5px] font-semibold tracking-[0.1em] text-ink3 uppercase">
            Confidence
          </div>
          <p className="m-0">{metrics.confidence?.overall_band ?? "not measured"}</p>
          {metrics.confidence?.rationale && <p className="m-0 text-[10.5px] text-ink3">{metrics.confidence.rationale}</p>}
        </div>
      </div>
    </details>
  );
}
