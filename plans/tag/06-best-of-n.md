# Slice 06: Best-of-N majority voting on the blind axes (`claim_type`, `theory_school`)

- **Feature:** tag
- **Slice slug:** best-of-n
- **GitHub issue:** #294
- **Branch:** feat/tag/06-best-of-n
- **Project directory:** .
- **Status:** ☑ built (PR pending founder approval)
- **Walking skeleton?** no

## Goal — the minimum testable behaviour

`axial tag <file>` draws the per-chunk tag call `N` times instead of once, then
majority-votes each blind axis (`claim_type`, `theory_school`) across the `N`
draws, so the pipeline records the modal label a single draw was only sampling
around. `N` is read per pass from config, defaulting to 3 for the tag pass and 1
for every other pass, and is never hardcoded at the call site: it mirrors the
existing `reasoning_by_pass` / `model_by_pass` seam exactly (a code-level
`DEFAULT_VOTES_BY_PASS`, a `_resolve_votes_by_pass` resolver, and an
`llm.votes_by_pass` block in `config/pipeline.yaml` that overrides it).

Two behaviours fall out of the vote and both must be represented, not hidden:

1. **Abstention.** When the `N` draws produce no strict-plurality winner for an
   axis (for N=3, all three draws differ), that axis's record carries an explicit
   abstention marker distinct from any vocabulary value, and does not fabricate a
   tag. This is the charter's calibrated-confidence principle at the tag layer:
   flag the contested chunk rather than coin-flip it (DEC-31).
2. **Self-repair of invalid draws.** A draw whose blind-axis value is still
   out-of-vocabulary after its own #102 correction re-ask does not cast a ballot
   for that axis. `theory_school` already soft-lands such a draw to `unlisted`
   (a legal ballot); a `claim_type` draw with no valid value is a spoiled ballot
   the vote ignores. The axis decides among the valid ballots. Only when *every*
   draw is invalid does the existing P0-6 hard error stand, so the schema-gap
   guarantee is preserved at the chunk level.

`N=1` is an exact no-op: one draw, no voting layer, no abstention possible, byte
-identical to today's tag pass. Head/pre-labeled axes (`field`, `empirical_scope`,
`role_in_argument`, `polities_touched`) take their first draw's value unchanged
(see *Voting the head axes*, below).

The measured payoff (DEC-31, six independent draws on 60 chunks): `theory_school`
0.757 → 0.918 at N=3, `claim_type` 0.796 → 0.866, past the 0.73 single-draw
intra-annotator ceiling; the vote also drove `theory_school`'s out-of-vocab rate
0.0056 → 0.0000. Provisional on the simulated gold set (DEC-32); the mechanism is
not.

## The abstention representation — resolved (the slice's load-bearing decision)

**Decision: abstention is a per-axis flag on that axis's record object, never a
value inside the controlled vocabulary.** When an axis abstains, its object is:

```
"theory_school": { "primary": null, "abstained": true, "draws": [<the N distinct
                   primary values, in draw order>], "status": "candidate" }
```

The vote tally / distinct draws are preserved so an operator can review the
contest, exactly as the `theory_school` candidates queue preserves a proposed
name. A decided axis is unchanged from today (`primary` set, no `abstained` key).

**Why a flag and not a sentinel value.** The record already carries three closed
-vocabulary sentinels, and abstention is none of them:

- `not-applicable` (schema `groups.none`) asserts *the passage advances no
  theoretical position*.
- `unlisted` (schema `groups.open`) asserts *a real school applies but the
  vocabulary does not yet cover it*.
- A real school id asserts *this school applies*.

Abstention asserts *the coders disagree about which of the above is true* — a
statement about the draw distribution, not about the passage. DEC-31 and
Appendix E both stress it is a **distinct signal from `not-applicable`**;
Appendix E goes further and calls conflating them "the very error the absence
marker exists to prevent." Putting an `undecided` token into the vocabulary would
reintroduce exactly that confusion, would demand a schema change on every blind
axis, and would let a downstream reader mistake a genuine contest for an asserted
category. Keeping abstention structurally outside the value space makes the two
impossible to confuse: a consumer checks `abstained` before it reads `primary`.

**Why per-axis and not per-record.** The measured abstention rates differ by axis
(`theory_school` 8.8% vs `claim_type` 3.3% at N=3), and a chunk routinely decides
one blind axis while abstaining the other. A record-level flag could not express
that; the per-axis object can.

**Why this shape fits the existing record.** It reuses two precedents already in
`tag.py`: axis-level metadata living on the per-axis object (`status`, taken from
the schema via `_axis_extras`), and a meta-field that is not a tag value marking a
non-standard outcome (`quarantine_reason` on a checkpoint record). Abstention is
the same species of annotation. It is also directly queryable — the stage-2b
per-source rate report (#288) and the P0-10 eval both read `abstained` as its own
outcome rather than scoring it as a wrong tag or silently reading a null primary.

**Downstream consumers this slice must teach the shape** (named, not built out
here): vault frontmatter (slice 04 / Appendix H) writes `abstained` + null
primary rather than a fabricated value; the eval harness (P0-10) counts an
abstained axis as its own bucket. Both are follow-through, not this slice's
acceptance bar.

## Voting the head axes — noted, not forced

Because the tag pass makes **one** multi-axis LLM call per chunk, drawing it `N`
times yields `N` complete records: every axis already has `N` draws in hand. The
marginal token cost of voting a head axis is therefore zero once the `N` draws
exist — "whether to vote the pre-labeled axes too" is a semantics choice (do we
change their recorded values), not a cost choice, and the DEC-31 gains on those
axes are real but small (`field` +0.012, `empirical_scope` +0.045). This slice
keeps head axes on their **first draw**, which is the smallest, measured-scope
change and a strict no-op for them. The `N` draws are retained in the voting
layer, so extending the vote to a head axis later is a toggle, not a rebuild. Left
out on purpose (over-engineering tripwire): no head-axis voting until something
asks for it.

## Config — mirror `reasoning_by_pass` exactly

- `src/axial/llm.py`: add `DEFAULT_VOTES_BY_PASS = {TAG_PASS_NAME: 3}` (the
  code-level fallback, alongside `DEFAULT_REASONING_BY_PASS`), and a
  `_resolve_votes_by_pass(llm_config)` that merges `llm.votes_by_pass` over the
  default (unnamed passes resolve to 1). Same structure as
  `_resolve_reasoning_by_pass`.
- `config/pipeline.yaml`: an `llm.votes_by_pass:` block carrying `tag: 3` as the
  carried-per-pass source of truth ("never hardcoded", the same contract the
  `reasoning_by_pass` / `model_by_pass` blocks already state).
- `src/axial/tag.py`: `run_tag` reads `N = resolve_votes_by_pass(...)` for
  `TAG_PASS_NAME` and loops the existing per-chunk draw+parse+validate+re-ask
  path `N` times, then votes. `N` never appears as a literal in the draw loop.

One-line justification for the tripwire (config consumed by the pass loop, not by
the client request, unlike `reasoning`/`model`): best-of-N is orchestration, but
it is still a per-pass knob and follows the identical config shape/resolver so the
"never hardcoded, per-pass" contract is honoured with no new mechanism.

## INVEST check

- **Independent:** extends the tag pass only. No other pass changes; head axes,
  polity capture, checkpoint/resume, quarantine, and the #102 re-ask are all
  reused unchanged, run `N` times. Voting is a thin layer over `N` existing
  single-draw results.
- **Valuable:** lifts the two blind axes to their measured ceiling (the
  `theory_school` KEEP rests on this, DEC-31/§10), self-repairs invalid draws, and
  ships the abstention signal Phase A's schema freeze and stage 5's teacher labels
  both depend on.
- **Small:** one config knob, one draw loop, one voting function, one abstention
  representation. `N=1` is a no-op, bounding the blast radius.
- **Testable:** the stub provider's response-sequence seam drives `N`
  deterministic draws per chunk end-to-end; the record provider counts the calls.
  A decided vote and an abstained vote are both forced from fixed draws.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given an extracted fixture source with a stored envelope and its chunk records
  And config sets llm.votes_by_pass.tag = 3
  And AXIAL_LLM_PROVIDER=record with a recorded call log
  And the tag pass's three draws for a first chunk are stubbed so two agree on a
      theory_school primary and the third differs
  And the tag pass's three draws for a second chunk are stubbed so all three
      theory_school primaries differ
When  the user runs `axial tag <fixture>`
Then  it exits 0 and emits one tagged record per chunk as JSON
  And the recorded log shows exactly three tag-pass-family calls per chunk
  And the first chunk's theory_school primary is the value the two agreeing draws
      shared, and the record carries no abstained flag for that axis
  And the second chunk's theory_school record carries `abstained: true`, a null
      primary, and the three distinct draw values, and no fabricated tag
```

- **Boundary / endpoint:** CLI command `axial tag <file>` (default domain
  `config/domains/syria`, `--domain` override), config-driven `N`.
- **Outer test type:** pytest integration test (subprocess; record provider so the
  per-chunk call count is asserted, not just the output).
- **Outer test file (planned):** tests/ingestion/test_tag_best_of_n.py —
  test-author, red, locked (DEC-1).

**How the outer test forces `N` draws and asserts the vote + abstention.** It uses
the existing stub/record response-sequence seam,
`AXIAL_STUB_TAG_RESPONSE_SEQUENCE` (the same seam
`tests/ingestion/test_tag_vocab_reask.py` uses to drive a bad-then-corrected
answer): a JSON array of raw tag-pass response bodies, dispatched by the
per-process, 1-indexed `_tag_pass_call_count` that already fires on **every**
tag-pass-family call. With a two-chunk fixture and `N=3`, the test sets a
six-element sequence — the first three drawing chunk 1 (two sharing a
`theory_school` primary, one differing → a decided plurality) and the next three
drawing chunk 2 (three distinct primaries → no plurality → abstention). Running
under `AXIAL_LLM_PROVIDER=record` with `AXIAL_LLM_RECORD_PATH` set, the test
counts tag-pass-family calls from the record log and asserts exactly `3 × chunks`
(proving best-of-N drew `N` times and did not silently fall back to one), then
asserts the decided chunk carries the shared primary with no `abstained` key and
the abstained chunk carries `abstained: true`, a null primary, and the three
recorded draw values. A companion assertion sets `votes_by_pass.tag` absent and
confirms the default `N=3` still applies (config default, not a literal), and a
third confirms `N=1` produces one call per chunk and no `abstained` key ever.

## Inner loop — initial unit test list

- [ ] `_resolve_votes_by_pass` merges `llm.votes_by_pass` over
      `DEFAULT_VOTES_BY_PASS`; an absent block yields `tag: 3`; an unnamed pass
      resolves to 1; a config entry overrides the default.
- [ ] the voting function returns the strict-plurality primary when one exists
      (`{A, A, B}` → `A`) and marks abstention when none does (`{A, B, C}` →
      abstained), for the blind axes only.
- [ ] a `theory_school` draw that soft-landed to `unlisted` casts an `unlisted`
      ballot and can win or lose the vote like any other value.
- [ ] a `claim_type` draw with no valid value (spoiled ballot) is excluded; the
      vote decides among the remaining valid draws; all-invalid preserves the
      existing `TagNotInSchemaError` hard error.
- [ ] an abstained axis object carries `abstained: true`, `primary: null`, the
      distinct `draws`, and (for `theory_school`) the schema `status`; a decided
      axis object is unchanged from the single-draw shape.
- [ ] head/pre-labeled axes take the first draw's value; their objects never gain
      an `abstained` key.
- [ ] `N=1` bypasses the voting layer entirely (one draw, one call, today's record
      shape exactly).
- [ ] the secondary value of a blind axis is voted consistently with its primary
      (record shape for `secondary`/`subtags` preserved on a decided vote).

## Out of scope for this slice (deferred)

- **Voting the head axes** — kept on first-draw; the retained draws make it a later
  toggle (above).
- **Per-source abstention-rate reporting** — the operator-facing rate summary is
  slice 2b / #288, which reads the `abstained` flag this slice writes.
- **The frozen-corpus re-tag** — best-of-N labels feed the stage-4 re-run and the
  stage-5 teacher labels, but producing the corpus is an operation, not this slice
  (plans/phase-a-completion stage 4).
- **Any change to `N` for artifacts/xref/envelope** — those passes resolve to
  `N=1` and are untouched.
- **Tuning `N`** — 3 is the DEC-31 agreement-per-cost point; 5 for near-zero
  abstention is a config change, not code.

## Definition of done

- [ ] Outer acceptance test authored by the test-author, committed RED
      (flag-approved), seen to fail for the right reason — then locked.
- [ ] All seeded unit behaviours covered; full suite passes locally; outer test
      GREEN.
- [ ] Refactor pass complete with the bar green.
- [ ] Slice's tests run in CI.
- [ ] Reviewer's two-stage review passed.
- [ ] Evidence collected and PR prepared into `main` — merge awaits founder
      approval (DEC-3).

## Status / progress log

- 2026-07-21 planned.
- 2026-07-21 built on `feat/tag/06-best-of-n`. Outer acceptance test
  `tests/ingestion/test_tag_best_of_n.py` (3 scenarios: decided + abstained
  vote with the recorded 3x call count; config default N=3 with no
  pipeline.yaml; N=1 exact no-op). Voting layer is `axial.tag.vote_blind_axes`
  + `BLIND_AXES` + `ABSTAINED_KEY`; config seam is
  `axial.llm.DEFAULT_VOTES_BY_PASS` / `_resolve_votes_by_pass` /
  `votes_for_pass` plus `llm.votes_by_pass.tag: 3` in `config/pipeline.yaml`.
  Spec: new §7.14, §7.1 per-draw note, P0-6 bullet, Appendix E abstention
  representation, Appendix H abstained frontmatter example.
  Blast radius: existing re-ask / resume / quarantine / input-guard tests pin
  single-draw (`votes=1`, or a single-draw `pipeline.yaml` in their staging
  root) so the vote does not confound the behavior they were written to lock.
