# Slice 01: Evidence assembly and `examine` — inspect before spend

- **Feature:** analysis-synthesis
- **Slice slug:** evidence-assembly-and-examine
- **GitHub issue:** #255
- **Branch:** `feat/analysis-synthesis/01-evidence-assembly-and-examine`
- **Project directory:** `.`
- **Status:** ☐ todo
- **Walking skeleton?** no (new stage module `src/axial/analyze/`, but it stands
  on the interrogation pass and the retrieval loop already built beneath it)
- **Depends on:** `retrieval-loop` slice 02 (the agentic query loop and the
  trajectory log)

## Goal — the minimum testable behaviour

The evidence set retrieved by stage 3 is assembled into one inspectable object
and reported to the operator **before** the expensive synthesis call
(inspect-before-spend, §5 stage 4, P0-4 bullet 1, P0-9 bullet 2).

`axial brief examine <brief_file>` runs stage 1 (interrogation) and stage 3
(retrieval) and prints, to stdout, three things:

1. the retrieved `chunk_id`s, in retrieval order,
2. the per-polity coverage counts, raw — for each polity the evidence touches,
   the corpus-wide substantive-chunk count from `coverage_count` and the count
   of chunks in *this run's* evidence set,
3. the interrogation result (§7.2): `premises_found`, `bounds_applied`,
   `refusal`, `disposition`.

It makes **zero stage-4 synthesis calls** and exits 0. Its cost is bounded to
interrogation plus retrieval; that boundedness is the lockable property, not a
comment in the code.

On a `refuse` disposition, `examine` prints the refusal and its reason and still
exits 0: a refusal is a completed run, not an error (§7.2).

## INVEST check

- **Independent:** it consumes what `retrieval-loop` already returns and adds no
  new model call. It changes nothing about how retrieval works, only what is
  assembled and shown afterwards.
- **Valuable:** the synthesis call is the phase's one expensive high-tier call
  (§7.11). Being able to look at the evidence set for the price of retrieval,
  and walk away, is the difference between an engine the operator can steer and
  one that only bills. It is P0-9's whole point, and it mirrors `axial chunk
  examine`, the Phase-A precedent for the same affordance.
- **Small:** one assembly function over the retrieval loop's output, one
  coverage-count roll-up, one read-only CLI subcommand. No prompt, no new pass.
- **Testable:** hermetic end to end. The interrogation and retrieval passes are
  driven by the `record`/`stub` providers; the zero-synthesis-calls property is
  asserted by poisoning the synthesis pass and observing exit 0.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given a fixture vault and a brief file config/briefs/dev/fixture-syria-displacement.yaml
  And AXIAL_LLM_PROVIDER=record so the interrogation and retrieval passes are
      scripted and every prompt is written to AXIAL_LLM_RECORD_PATH
  And the scripted retrieval loop returns a known evidence set of chunk ids
When  `axial brief examine config/briefs/dev/fixture-syria-displacement.yaml` runs
Then  the command exits 0
  And stdout lists exactly the retrieved chunk_ids, in retrieval order
  And stdout reports, for every polity the evidence set touches, both a
      corpus_chunk_count and an evidence_chunk_count
  And stdout reports the interrogation result's disposition, premises_found,
      and bounds_applied
  And no file is written under data/analyses/

Given the same brief and vault
  And the synthesis pass is poisoned so that any stage-4 model call raises
      (AXIAL_LLM_PROVIDER=explode on the synthesis pass_name, or the
      equivalent call-counting seam asserting a synthesis call count of 0)
When  `axial brief examine config/briefs/dev/fixture-syria-displacement.yaml` runs
Then  the command still exits 0
  And the synthesis call count is 0

Given a brief whose scripted interrogation yields disposition "refuse" with a
      reason
When  `axial brief examine` runs on it
Then  the command exits 0
  And stdout states the refusal and its reason
  And the synthesis call count is 0
```

- **Boundary / endpoint:** CLI — `axial brief examine <brief_file>`; library
  entry `axial.analyze.assemble_evidence(...) -> EvidenceSet`.
- **Outer test type:** pytest integration/acceptance test.
- **Outer test file (planned):** `tests/test_brief_examine.py` — authored by the
  test-author, committed red, then locked (DEC-1).

## Inner loop — initial unit test list

Co-located under `src/axial/analyze/` (e.g. `src/axial/analyze/test_assembly.py`).

- [ ] `assemble_evidence` de-duplicates chunk ids the retrieval loop returned
      more than once, and preserves first-seen retrieval order.
- [ ] The assembled evidence set carries, per chunk, the `chunk_id` and the
      frontmatter fields synthesis will need (`polities_touched`,
      `role_in_argument`, `theory_school`, `claim_type`, `empirical_scope`), not
      just bare ids.
- [ ] Per-polity counts: `evidence_chunk_count` is the number of evidence chunks
      whose `polities_touched` includes the polity; `corpus_chunk_count` comes
      from the query API's `coverage_count`, not from a recount.
- [ ] A polity appearing in no evidence chunk does not appear in the report; a
      polity in one evidence chunk appears with count 1.
- [ ] An empty evidence set assembles cleanly (empty id list, empty count map)
      rather than raising.
- [ ] `examine` on a `refuse` disposition short-circuits before retrieval or
      reports the refusal with an empty evidence set, per the disposition rule,
      and returns a non-error result.
- [ ] The `axial brief examine` subparser is registered on the existing argparse
      tree and exits non-zero on a missing brief file path.
- [ ] `examine` writes nothing under `data/analyses/`.

## Out of scope for this slice (deferred)

- The synthesis call and the claim graph (§7.4, P0-4 bullets 2–4) — slice 02.
- Coverage **bands** (§7.7 `coverage_band`) and the threshold that derives them.
  This slice reports raw counts; banding is `analysis-validators`.
- The confidence disclosure and its vocabulary (Open Questions, §7.4).
- The counter-position section (§7.8).
- Writing the analysis record (§7.3) or the markdown answer (§7.10).
- `axial brief run` (P0-9 bullet 1) — `analysis-record` slice 01.
- Any change to the retrieval loop's planning or step budget (P0-3).

## Definition of done

- [ ] Outer acceptance test authored by the test-author, committed RED, seen to
      fail for the right reason — then locked.
- [ ] All seeded unit behaviours covered; full suite passes locally; outer test GREEN.
- [ ] Refactor pass complete with the bar green.
- [ ] Slice's tests run in CI (`tdd-ci`).
- [ ] Reviewer's two-stage review passed.
- [ ] Evidence collected and PR prepared into `main` (`safe-pr`) — merge awaits
      founder approval.

## Status / progress log

- 2026-07-20 planned.
