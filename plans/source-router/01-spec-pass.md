# Slice 01: Spec pass — insert the routing stage into the contract

- **Feature:** source-router
- **Slice slug:** spec-pass
- **GitHub issue:** #166
- **Branch:** spec/source-router/01-spec-pass (spec window)
- **Project directory:** .
- **Status:** ☐ todo
- **Walking skeleton?** no — this is the spec precondition, not an implementation slice

## Goal — the minimum change

Amend `specs/PRODUCT.md` so the classify-once source router is part of the locked
contract **before** any implementation. Done by the **spec-author** role in a deliberate
spec window (founder opens `.claude/spec-mode`); no code, no outer acceptance test.

## What the spec pass amends

- **§5 (pipeline order).** Insert the routing step between stage 2 (structural extraction)
  and stage 4 (chunking): a step that classifies each tree block by its docling structural
  type and routes it to prose / artifact / apparatus, so only prose reaches the chunk stage.
  State its pipeline position explicitly and that downstream passes consume the routed
  result rather than re-deriving prose/non-prose.
- **A routing-decision contract (new §7 subsection, e.g. §7.8).** Define: the three routes
  (prose / artifact / apparatus) and the docling `label` → route mapping; the founder
  decisions (endnotes/footnotes DROPPED as apparatus; tables/charts KEEP the artifact
  classification pass); the `list_item`-under-back-matter rule; and that apparatus drops are
  recorded as the single source of skip truth (generalizing the garbage-skip sidecar).
- **P0-4.** State the chunk stage consumes a **prose-only routed tree** — apparatus and
  artifact blocks never enter the chunk path.
- **P0-4b.** Point `axial chunk examine`'s skipped-block reporting at the **router's**
  decisions, not a per-pass guard.
- **§5 stage 5 / P0-5 (light touch).** Note the artifact pass is the sole home of
  tables/figures/captions and receives them from the router.

## Acceptance (spec-review, not a test)

- The amended §5 names the routing step and its position; a reader can see only prose reaches
  chunking.
- The routing-decision contract enumerates the label→route mapping and both founder decisions.
- P0-4 and P0-4b reference the routed tree / router decisions.
- The `non_prose_skip_reason` per-pass guard is described as demoted to a backstop, not the
  primary gate.
- Reviewer (spec-compliance stage) confirms the amendment is internally consistent with
  §7.4 (tree shape) and §7.7 (chunk artifact).

## Out of scope (this slice)

- Any code. This is `specs/` only, spec-author only, in a spec window.
- Deciding whether the route is persisted onto the tree vs. computed on read — the spec
  sanctions either; slice 02 chooses.

## Notes

- Frozen-spec rule: this is the ONE window in which `specs/` is editable for #164. All later
  slices build against the ratified contract; drift found mid-build routes to a `spec-drift`
  issue, never an in-place patch.
- Precedent: chunk-redesign's own spec pass was ratified/merged in #150 before its build
  slices (memory [[chunking-redesign-148]]).
