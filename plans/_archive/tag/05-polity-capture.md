# Slice 05: Loosen & enrich polity capture (country → polity + polities_touched)

- **Feature:** tag
- **Slice slug:** polity-capture
- **GitHub issue:** #194
- **Branch:** feat/tag/05-polity-capture
- **Project directory:** .
- **Status:** ☑ merged (PR #199, merge commit 6863e58, 2026-07-16)
- **Walking skeleton?** no

## Goal — the minimum testable behaviour

`axial tag <file>` captures place referents faithfully ahead of the single full
re-run (spec `e60fd5b`, PRD §4/§5/§7.2, Appendix C/G/H). Three cohesive changes,
one slice (founder-ratified 2026-07-15 as one pre-run capture change):

1. **Loosen capture.** The tag prompt reframes the polity list as *examples, not a
   closed menu*: the tagger is instructed to name the true polity faithfully even
   when it is absent from the examples, historical, defunct, or supra-national (an
   empire, a mandate, a former union). Emitting a value outside the examples is the
   *instructed* behaviour, reconciled with the #77 free-text reality.
2. **Rename `country` → `polity`, `country_list` → `polity_examples`.** A `country`
   field is a category error for an empire/mandate/supra-national referent; `polity`
   makes a non-nation-state referent a legal, honest value. Schema-shape rename
   across the pipeline. The scope tag id `scope:country-case` is unchanged (it is a
   `[FIRM]` tag id, not the extra field).
3. **New `polities_touched` facet.** A separate, many-valued free-text list of every
   polity a chunk *substantively engages* ("engaged, not name-dropped"), kept apart
   from the single-cardinality `empirical_scope` aboutness axis. Feeds the Phase-B
   per-polity coverage map. This needs a genuinely new schema cardinality
   (`cardinality: many`, `values: free_text`) that the loader does not yet accept.

## INVEST check

- **Independent:** extends the tag pass; no other pass's contract changes (vault
  frontmatter gains the renamed key + the new list; gold/eval reshape helpers follow
  the rename).
- **Valuable:** stops the silent empire/mandate → "country" distortion *before* the
  irreversible full re-run, and captures the multi-polity signal Phase-B needs.
- **Small-ish:** one theme (polity capture). Wide but mechanical rename + one new
  many/free-text axis end to end. Founder chose one slice / one PR.
- **Testable:** run `axial tag` (and `axial vault write`) on a fixture; assert the
  renamed `polity` field, examples-not-menu acceptance, and the round-tripped
  `polities_touched` list.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given an extracted fixture source with a stored envelope and chunks, AXIAL_LLM_PROVIDER=stub returning empirical_scope=scope:country-case with polity=<a non-example value> and polities_touched=[<two engaged polities>]
When  the user runs `axial tag <fixture>`
Then  each scope:country-case record carries a free-text `polity` (never a `country` key)
And   a `polity` outside the schema's `polity_examples` is accepted and logged as a candidate, never fatal (#77)
And   a scope:country-case record with a missing/empty `polity` exits non-zero with a clear error (unchanged hard error)
And   each record carries a many-valued `polities_touched` list, validated as free text (no closed-vocabulary check)
And   `axial vault write` round-trips both `empirical_scope.polity` and the `polities_touched` list into the prose note frontmatter
```

- **Boundary / endpoint:** CLI commands `axial tag <file>` and `axial vault write <file>`
- **Outer test type:** pytest integration test (subprocess; stub provider)
- **Outer test file (planned):** tests/ingestion/test_tag_polity_capture.py — test-author, red, locked

## Inner loop — initial unit test list

- [ ] schema loader accepts `cardinality: many` with `values: free_text` (new
      `KNOWN_CARDINALITIES` member; no tag-id vocabulary, `value_count`/`tag_ids` empty)
- [ ] `Schema.polity_examples` replaces `country_list` (loaded from `polity_examples:`)
- [ ] the multi-axis tag prompt frames `polity_examples` as examples-not-menu and
      instructs faithful naming of absent/historical/supra-national polities
- [ ] `scope:country-case` requires a non-empty `polity` (hard error when missing),
      renamed from the country parser/error; the object-dialect nesting still parses
- [ ] a `polity` outside `polity_examples` is accepted + logged to stderr, never fatal
- [ ] `polities_touched` parses as a many-valued free-text list; free text, so no
      `TagNotInSchemaError`; an empty/absent list is handled per spec (empty list ok)
- [ ] `build_tagged_record` emits `polity` (not `country`) and the `polities_touched` list
- [ ] `build_frontmatter` nests `empirical_scope: {value, polity}` and carries
      `polities_touched` as a list into the note
- [ ] gold/eval scalarization + stub (`llm.py`) follow the rename with no regression

## Out of scope for this slice (deferred)

- **Item 4 — offline canonical normalization map** (aliases + historical polities →
  canonical). Deterministic, offline, no second LLM pass; built from the run's
  collected verbatims and enforced only at PRD §11 step 7. Not built here.
- **Enforcing `polity_examples` as a closed vocabulary** — stays a logged candidate
  list in v0 (#77); becomes enforced at §11 step 7.
- **Phase-B retrieval behaviours** (coverage-map disclosure, cross-case surfacing) —
  recorded in the behavioural charter, not this slice.

## Definition of done

- [ ] Outer acceptance test authored by the test-author, committed RED (flag-approved), seen to fail for the right reason — then locked.
- [ ] All seeded unit behaviours covered; current-subproject acceptance tier passes locally; outer test GREEN.
- [ ] Refactor pass complete with the bar green.
- [ ] Slice's tests run in CI.
- [ ] Reviewer's two-stage review passed.
- [ ] Evidence collected and PR prepared into `main` — merge awaits founder approval.

## Status / progress log

- 2026-07-15 planned (orchestrator); founder ratified one slice / one PR for items 1–3.
- 2026-07-16 shipped: red outer test (401458b) → impl (4404236) → two sibling-test migrations (60e15ce, b85db1b). Reviewer stage-1 pass; two stage-2 findings migrated. src 716 / acceptance tier 123 green (isolated worktree); CI green. Merged via PR #199 (6863e58); local branch cleaned. Item 4 (offline normalization map) deferred.
