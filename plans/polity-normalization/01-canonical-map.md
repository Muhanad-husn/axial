# Slice 01: Offline canonical polity normalization map (living alias→canonical)

- **Feature:** polity-normalization
- **Slice slug:** canonical-map
- **GitHub issue:** #205
- **Branch:** feat/polity-normalization/205-canonical-map
- **Project directory:** .
- **Status:** ☐ in progress
- **Walking skeleton?** no (extends the tag/vault pipeline; #194/PR #199 shipped the `polity` seam)

## Goal — the minimum testable behaviour

A **deterministic, offline, model-free** canonical polity normalization map that folds
alias and historical polity verbatims to canonical referents, built from the completed
run's collected `polity` verbatims and applied downstream (no second LLM pass). It is a
**living reconciliation layer with graceful degradation** (founder ruling 2026-07-16,
spec-drift #206 reconciled in PR #209): never a closed tag-time gate — an unmapped
verbatim passes through unchanged and is logged as a candidate at any corpus scale.

Founder chose **one slice / one PR** for the whole deliverable (2026-07-17).

## Design constraints (from spec — Appendix C, §11 step 7)

- **Deterministic, offline, model-free.** No LLM. Same inputs → same output.
- **Faithful naming preserved upstream.** The tagger still emits true polity as free
  text (Appendix C); this map is a *downstream reconciliation layer*, never a tag-time
  gate. It never prevents a new/historical/supra-national polity from being named.
- **Non-fatal.** An unmapped verbatim is accepted and logged, never an error.
- **Distinguish, don't blanket-merge.** Sub-polities (`Scotland` under `United
  Kingdom`; `North Korea` vs `South Korea`) and distinct historical referents must not
  collapse under any naive substring/prefix rule. Folding is by **explicit alias lists
  only** — exact (normalized) match, never fuzzy.

## The deliverable (four parts, one slice)

1. **The artifact — `config/domains/syria/polity_canonical.yaml`.** A versioned,
   human-editable **canonical tree** (sibling to `schema.yaml`/`codebook.yaml`).
   Structure: a list of `nodes`, each with `canonical` (the referent name), `kind`
   (`modern` | `historical` | `supra-national`), an explicit `aliases` list (verbatims
   that fold to this node), and optional nested `children` (the real parent→child
   relation, e.g. `Scotland`/`England` under `United Kingdom`). Growable at the root: a
   candidate that fits no node opens a **new root or child node** by hand-edit. Seeded
   from the run's real `polity` verbatims with the obvious clusters folded (UK cluster,
   `Soviet Union`/`USSR`, `East Timor`/`Timor-Leste`, spelling variants; empires and
   defunct polities as standalone `historical` nodes).

2. **The engine — `src/axial/polity_canonical.py`.**
   - `load_polity_canonical(domain_dir)` → a `PolityCanonical` object with `version`, the
     node tree, and a flattened normalized index `alias|canonical → node`. Typed error
     hierarchy (mirror `codebook.py`): missing file, malformed, missing version, and a
     **duplicate-alias** error (the same verbatim folding to two different nodes is an
     ambiguity the loader must reject — this is what enforces "distinguish, don't merge").
   - `canonicalize(verbatim, cmap) → CanonResult(verbatim, status, node?)` where
     `status ∈ {mapped, candidate, leak}`:
     - **mapped** — normalized exact match against an alias/canonical → the node.
     - **leak** — the verbatim splits on a multi-polity separator (` and `, `, `, `/`,
       ` & `) into ≥2 parts that **each independently canonicalize to a known node**
       (so `Syria and Lebanon` → leak, but `Bosnia and Herzegovina` → NOT a leak
       because its parts are not standalone nodes). Surfaced as a flag, **never folded.**
     - **candidate** — no match and not a leak → passthrough unchanged, logged.

3. **The seed build — `axial polity build`.** A deterministic, model-free scan of the
   vault prose notes (reuse `gold.py`'s glob + `_split_frontmatter` scan) that harvests
   the distinct `polity` (and, when populated, `polities_touched`) verbatims and emits a
   **seed** canonical tree (one node per distinct verbatim, sorted) for the operator to
   curate. Same vault → identical seed.

4. **The downstream pass + operator notification — `axial polity report`.** Reads the
   vault's collected verbatims, canonicalizes each via the shipped tree, and emits the
   **post-run notification**: a count plus the list of unmapped **candidates** (value +
   occurrence count + source note ids) and the **leak** flags. Zero candidates → a clean
   "nothing to resolve" confirmation that every verbatim was covered. Deterministic:
   editing the tree (fold an alias, open a new node) and re-running changes the output
   predictably — this is the append/edit resolution loop (no interactive editor; the
   YAML is the surface the operator edits, per the founder ruling).

## Acceptance criterion (outer loop — the failing e2e/integration test)

Hermetic: drives a **fixture** domain + staged vault (never the real gitignored vault),
via the `isolated_vault_root` pattern in `tests/ingestion/test_tag_polity_capture.py`.

```gherkin
Given a fixture domain with a polity_canonical.yaml tree (United Kingdom{aliases: Britain, UK; children: Scotland, England}; Soviet Union{aliases: USSR}; Syria; Lebanon; Ottoman Empire[historical])
And   a staged vault of prose notes carrying polity verbatims: "Britain", "UK", "Scotland", "North Korea", "South Korea", "USSR", "Syria and Lebanon", "Freedonia" (unmapped)
When  the user runs `axial polity report`
Then  "Britain" and "UK" canonicalize to United Kingdom, "Scotland" to the Scotland child (NOT to United Kingdom), "USSR" to Soviet Union
And   "North Korea" and "South Korea" are NOT collapsed (distinct — one is unmapped-candidate here, both never merged)
And   "Syria and Lebanon" is surfaced as a multi-polity leak flag, never folded
And   "Freedonia" passes through unchanged and is reported as a candidate with its count and source note id (exit 0 — non-fatal)
And   the notification prints the candidate count + list (and a clean "nothing to resolve" when the set is empty)
When  the operator edits polity_canonical.yaml to add "Freedonia" as a new canonical node and re-runs `axial polity report`
Then  "Freedonia" is now mapped and no longer a candidate — the edit+rerun changes output deterministically
And   `axial polity build` over the staged vault emits a deterministic seed tree (same vault → identical bytes)
```

- **Boundary / endpoint:** CLI `axial polity report` and `axial polity build`.
- **Outer test type:** pytest integration test (subprocess; model-free, no stub LLM needed).
- **Outer test file (planned):** tests/ingestion/test_polity_canonical_map.py — test-author, red, locked.

## Inner loop — initial unit test list

- [ ] `load_polity_canonical` reads `polity_canonical.yaml`, returns `PolityCanonical`
      with version + node tree; missing file / malformed / missing version → typed errors.
- [ ] loader flattens nested `children` and builds a normalized `alias|canonical → node`
      index; a **duplicate alias across two nodes** raises `AmbiguousAliasError`.
- [ ] `canonicalize` — normalized exact match folds an alias to its node (case/space-insensitive match, original verbatim preserved in the result).
- [ ] `canonicalize` — a child-node alias resolves to the **child**, not the parent
      (`Scotland` ≠ `United Kingdom`); sibling tokens (`North`/`South Korea`) never merge.
- [ ] `canonicalize` — multi-polity leak: split-and-both-parts-map → `status=leak`;
      `Bosnia and Herzegovina` (parts not standalone nodes) → NOT a leak.
- [ ] `canonicalize` — unmapped verbatim → `status=candidate`, verbatim unchanged, non-fatal.
- [ ] vault harvest helper collects distinct `polity` + `polities_touched` verbatims from
      prose-note frontmatter with occurrence counts + source note ids (reuse gold scan).
- [ ] `axial polity build` emits a deterministic seed tree (sorted; one node per distinct
      verbatim); same vault → identical output.
- [ ] `axial polity report` prints the candidate count + list + leak flags; zero → clean
      "nothing to resolve"; exit 0 in all non-error cases.
- [ ] editing the tree + re-running `report` moves a former candidate to mapped.

## Out of scope for this slice (deferred)

- **Mutating existing vault notes** with a canonical field — the downstream pass is a
  *report/annotation* over collected verbatims, not an in-place rewrite of `data/vault`.
- **An interactive resolution CLI** (`polity add-node`/`add-alias`) — resolution is
  hand-editing the YAML + re-running, per the founder ruling. A helper command may be
  added later if the loop proves it needed.
- **`polities_touched` population** — empty across the current 16,946-note run; the
  harvester reads it (append-able by construction) but v1 seeds from `polity`.

## Definition of done

- [ ] Outer acceptance test authored by the test-author, committed RED (flag-approved),
      seen to fail for the right reason — then locked.
- [ ] All seeded unit behaviours covered; current-subproject acceptance tier passes
      locally; outer test GREEN.
- [ ] Refactor pass complete with the bar green.
- [ ] Slice's tests run in CI.
- [ ] Reviewer's two-stage review passed.
- [ ] Evidence collected and PR prepared into `main` — merge awaits founder approval.

## Status / progress log

- 2026-07-17 planned (orchestrator); founder ratified one slice / one PR for the full
  deliverable. Spec contract (Appendix C, §11 step 7) already aligned via #206/PR #209.
