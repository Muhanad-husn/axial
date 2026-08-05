# Feature: The analysis record & rendered answer — the output contract

Stage 6 of the analysis engine (§5 stage 6, P0-8): give Phase B its load-bearing
artifact and the command that produces it. `axial brief run <brief_file>` drives
stages 1 through 6 and writes one analysis-record JSON per brief run at
`data/analyses/<brief_id>.json`, carrying the full §7.3 shape — the brief
verbatim, the corpus pin, the schema version, the lens, the interrogation
result, the claim graph, the counter-position section, the coverage map, the
confidence disclosure, the retrieval trajectory, and `model_by_pass`. Alongside
it, a deterministic markdown answer renders the claims with their (a)/(b)/(c)
kinds legible to the reader, plus the counter-position, the coverage map, and
the confidence disclosure (§7.10). The founder benefits: every run leaves one
auditable file where each claim traces to grounds, each grounds pointer resolves
to a real vault id, and the trajectory shows how retrieval got there — plus a
readable answer that never hides which claims are the tool's inference.

- **Slug:** analysis-record
- **Created:** 2026-07-20
- **Status:** planned
- **New system?** no (new stage module `src/axial/answer/` on the existing
  `axial` CLI; stages 1–5 are already built beneath it)
- **Project directory:** `.`

## Slices

Develop top to bottom. One slice = one red-green-refactor pass = one PR.

| # | Slice | Issue | Goal (one line) | Status | PR |
|---|-------|-------|-----------------|--------|----|
| 01 | [analysis-record-and-brief-run](01-analysis-record-and-brief-run.md) | [#257](https://github.com/Muhanad-husn/axial/issues/257) | `axial brief run <brief_file>` drives stages 1–6 and writes the full §7.3 record to `data/analyses/<brief_id>.json`, pinned by `corpus_pin` + `schema_version`; a `refuse` disposition still writes a record with empty `claims` and makes no synthesis call, exit 0 | ☐ todo | TBD |
| 02 | [markdown-answer-rendering](02-markdown-answer-rendering.md) | [#261](https://github.com/Muhanad-husn/axial/issues/261) | A deterministic markdown answer renders from the record alongside the JSON — claim kinds legible, counter-position, coverage map, confidence — and the same record renders byte-identical markdown every time | ☐ todo | TBD |

<!-- Status values: ☐ todo · ◐ in-progress · ✅ done. Update the row when a slice's PR opens. -->

## Dependencies

- Slice 01 depends on `analysis-synthesis` slice 02 (the claim graph it
  persists) and on `analysis-foundation` slice 02 (the corpus-pin manifest whose
  id the record records).
- Slice 01 depends transitively on `analysis-foundation` slice 01 (the brief
  loader and `brief_id`, which names the record file), `brief-interrogation`
  slice 01 (the `interrogation` block and the disposition that gates synthesis),
  and `retrieval-loop` slice 02 (the `trajectory` log, §7.6).
- Slice 02 depends on `analysis-validators` slice 03 (coverage map and
  confidence). It is **deliberately ordered after the validators feature** so
  the renderer has real coverage-band and confidence content to present rather
  than placeholder fields.
- Slice 01 does **not** wait on the validators: it lands the record spine and
  the run command, writing the validator-owned fields from whatever the
  validators compute once they exist.

## Out of scope (whole feature)

- Computing the counter-position section (§7.8), the coverage map's bands
  (§7.7), and the confidence disclosure. Those are `analysis-validators`. This
  feature carries them in the record and presents them in the answer.
- The validators themselves (P0-5, P0-6, P0-7) and the release-blocking
  behaviour on a failed mechanical check (§7.9). The record is the surface they
  check; blocking release is theirs.
- Synthesis, retrieval, and interrogation. This feature orchestrates them
  through `run` and persists what they returned; it does not reimplement any of
  them.
- The corpus-pin manifest *format and writer* — `analysis-foundation` slice 02.
  This feature records the pin id, it does not compute the pin.
- **Venue, length, and style adaptation.** §7.10 renders one plain markdown
  answer; adapting it to a venue or house style is Phase D (§3 non-goal 2).
- The rung-3 gate harnesses (P0-12). They *read* the record and the trajectory;
  they are a separate feature.
- Multi-brief batching, sweeps, or cross-brief caching (§3 non-goal 6).
- Any live-LLM test. Every acceptance test drives the `stub`/`record`/`explode`
  providers.

## Notes / open questions

- **Confidence vocabulary needs founder adjudication.** §7.3 locks the record
  field as `confidence: {overall_band, rationale}` — the word *band* leans the
  output contract toward discrete confidence bands. But the spec's Open
  Questions still park the choice: "*Confidence vocabulary — discrete bands
  (high/medium/low) vs. a numeric score, for both per-claim and overall
  confidence (§7.4, §7.7)*". The two are not obviously reconcilable, and §7.4's
  per-claim `confidence` carries no band wording at all. **Flagging, not
  deciding.** Whichever way it lands, it should land once and apply to the
  per-claim field, the record's `overall_band`, and the calibration metric
  together, since §10's calibration gate scores disclosed confidence against
  judged correctness and needs a single vocabulary to score against.
- **`refuse` is a completed run, not an error.** §7.2 and P0-1 are explicit: on
  refusal the record is written, `claims` is empty, the answer states the
  refusal and its reason, and no synthesis call is made. Slice 01's acceptance
  test asserts all four, with the synthesis pass poisoned so "no synthesis call"
  is mechanical rather than assumed. `claims` empty is valid **only** here
  (§7.3).
- **Pins make records comparable, or not.** §7.12 and P0-10: two records are
  comparable only if their `corpus_pin` values match. Slice 01 records the pin;
  detecting a pin mismatch across runs is eval work, not this feature's.
- **Determinism is the renderer's lockable property.** §7.10 says the same
  record renders the same markdown. Slice 02 asserts byte-identity across two
  renders of one record, which forces out set iteration order, timestamps, and
  anything else non-deterministic in the renderer.
- **Record shape is locked (§7.3, [FIRM]).** No field is nullable except where
  §7.3–§7.8 state it. A missing field is a spec-drift issue for the founder, not
  a quiet omission by the implementer.
