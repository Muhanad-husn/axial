# config/briefs/sim/ — SIMULATED dev briefs (throwaway)

`origin: simulated`. AI-generated stand-in research questions, **not** the real #250
backlog (that lands in [`../dev/`](../dev/)). They exist to unblock Phase B during the
academic pause and are deleted and re-run on real input before any promoted result.
See [`docs/sim-academic/`](../../../docs/sim-academic/) and `docs/DECISIONS.md` DEC-29.

Each `*.yaml` here must still load under `axial.brief.load_brief` — shape
`{case, request}`, `lens` omitted. Provenance lives in leading YAML comment lines, not
data keys (the loader rejects unknown keys).
