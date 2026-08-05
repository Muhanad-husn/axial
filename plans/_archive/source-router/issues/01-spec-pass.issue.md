# chore(source-router): spec pass — insert the classify-once routing stage into the contract [slice 01]

**Spec:** specs/PRODUCT.md#5 · new §7.8 (routing-decision contract) · §8 P0-4 · P0-4b · **Plan:** plans/source-router/01-spec-pass.md
**Depends on:** none (this precedes all implementation)
**Labels:** sub:ingestion-v0
**Charter:** #164

## Deliverable

In a deliberate spec window (spec-author only, `specs/` unfrozen), amend `specs/PRODUCT.md`
so the classify-once source router is part of the locked contract before any code is written.
No code, no outer acceptance test — the deliverable is the ratified spec amendment.

## Acceptance criterion

- §5 names the routing step and its pipeline position (between structural extraction and
  chunking) and states downstream passes consume the routed result, not a re-derived
  prose/non-prose decision.
- A new §7 subsection defines the three routes (prose / artifact / apparatus), the docling
  `label` → route mapping, both founder decisions (endnotes/footnotes DROPPED; tables/charts
  KEEP the artifact classification pass), the `list_item`-under-back-matter rule, and that
  apparatus drops are the single source of skip truth.
- P0-4 states the chunk stage consumes a prose-only routed tree; P0-4b points examine's
  skip-reporting at the router's decisions.
- `non_prose_skip_reason` is described as demoted from primary gate to backstop.
- Reviewer (spec-compliance) confirms internal consistency with §7.4 (tree shape) and §7.7
  (chunk artifact).

## Out of scope

- Any code — `specs/` only. Whether the route is persisted onto the tree vs. computed on read
  is left to slice 02; the spec sanctions either.
