# Feature: intake source-metadata & holdings (§7.11–§7.13)

Give intake a durable home for the facts it reads off a source file, and make
the holdings-completeness check trustworthy. Today intake returns a `Source`
stub that is never persisted, so the holdings flag reaches no reader and the
bibliographic fields are read nowhere. This feature lands the three §7.11–§7.13
criteria (P0-1b/c/d) as one coherent unit: a model-adjudicated holdings check, a
persisted per-source metadata record, and the author/title/date ownership move
that closes the #278 null-metadata bug. The operator (founder) benefits: a
flagged partial holding is visible and judged rather than silently propagated,
and every chunk's `source_meta` carries real bibliographic facts instead of the
nulls and fabricated slug-titles it carries now.

- **Slug:** intake-metadata
- **Created:** 2026-07-21
- **Status:** planned
- **New system?** no. Three existing modules are reworked (`holdings.py`,
  `intake.py`, `envelope.py`/`vault.py`) and one new writer (`data/source_meta/`)
  is added inside the existing intake pass; no new module tree.
- **Project directory:** `.`

## Operating stance (DEC-32)

Per DEC-32 we build against the simulated academic gold set (DEC-29/30/31) now.
Nothing in this feature reads a gold label, so the sim caveat barely touches it:
the holdings bar (0 false positives over 30 sources) and the metadata records are
measured against the **real** 30-source corpus, not the sim path. The mechanism
these slices build is real; only the downstream tag/eval numbers are provisional.

## Slices

Develop top to bottom. One slice = one red-green-refactor pass = one PR.

| # | Slice | Issue | Goal (one line) | Status | PR |
|---|-------|-------|-----------------|--------|----|
| 01 | [holdings-model-adjudicated](01-holdings-model-adjudicated.md) | [#284](https://github.com/Muhanad-husn/axial/issues/284) | Replace the retired deterministic holdings check with running header/footer stripping + one reasoning-ON model call deciding document kind, claimed extent, and coverage; flag-only, 0 false positives over 30 sources | ☐ todo | TBD |
| 02 | [source-metadata-record](02-source-metadata-record.md) | [#285](https://github.com/Muhanad-husn/axial/issues/285) | Write one JSON per source at `data/source_meta/<source_id>.json` at intake, before extraction — physical page count, the §7.11 holdings flag in full, the full sha256, and author/title/date read at intake; survives envelope regen | ☐ todo | TBD |
| 03 | [envelope-metadata-cleanup](03-envelope-metadata-cleanup.md) | [#278](https://github.com/Muhanad-husn/axial/issues/278) | Make the source-meta record the sole origin of author/title/date: remove the three from the envelope's locked shape, recompose the vault's `source_meta` block from record + envelope, so chunks stop carrying nulls and fabricated titles | ☐ todo | TBD |

<!-- Status values: ☐ todo · ◐ in-progress · ✅ done. Update the row when a slice's PR opens. -->

## The #278 coupling — resolved here

**The decision.** §7.13 and P0-1d already settle ownership: the source-metadata
record (§7.12) is the **sole origin** of `author`, `title` and `date`, and the
envelope **no longer carries them** — its locked shape becomes `{source_id,
thesis, toc[], scope, stated_argument}`. Intake owns the three fields; the
envelope does not mirror them by reference or by copy. This is a deliberate,
founder-approved change to a previously locked shape, in the same spirit as the
`toc` shape change (#235).

**Why the envelope stops advertising them rather than mirroring.** The whole
reason the record exists is that the envelope is regenerated routinely and is
therefore not a durable home for a fact about the file (§7.12). Mirroring
author/title/date back into the envelope would re-import exactly the drift the
record was built to escape, and would give downstream **two** origins to
reconcile. §7.13 is explicit: "There is one answer downstream, not two." So the
fields leave the envelope entirely; the vault writer composes the note's
`source_meta` block from two places — author/title/date from the record,
thesis/scope from the envelope — keeping the five-key frontmatter unchanged so no
note shape or reader changes.

**Fix-lane cleanup, or a third slice? — a third slice (slice 03 here).**
Recommendation with rationale:

1. It is **not** a one-line cleanup. It changes a *locked* envelope shape
   (`build_envelope`, `validate_envelope_fields`, the prompt's now-unneeded title
   handling in `envelope.py`) and it rewrites the vault writer's `source_meta`
   composition (`vault.py:196`, today `{field: envelope.get(field) for field in
   SOURCE_META_FIELDS}`) to read three of the five keys from the record. That is a
   real behavioral change across two modules with its own outer contract — a slice,
   not a fix.
2. It **structurally depends on slice 02.** The vault writer can only compose
   author/title/date from the record once the record exists and carries them
   (P0-1d). So #278 cannot be the *independent, Wave-1, `envelope.py`-only* slice
   the phase-a-completion README sketched for 1a. That placement predates §7.13's
   resolution ("Populate them **or** remove the fields") and is now stale: the spec
   chose *remove*, which couples #278 to the record. **This supersedes the
   completion README's Wave-1 independent placement of 1a — 1a now depends on 1c.**
3. It stays **small (80/20).** Slice 03 makes the writer correct; it does **not**
   itself re-tag the ~17k existing chunks. The corpus flush that replaces the
   in-vault nulls is the stage-4 re-tag operation the completion plan already
   schedules. Slice 03's job is to ensure that when the re-tag runs, it writes
   real bibliographic facts.

## Dependencies

- **01 → 02 → 03, ordered.** Slice 02 carries slice 01's holdings flag into the
  record, so it depends on 01's flag shape. Slice 03 reads author/title/date out
  of slice 02's record, so it depends on 02.
- Slice 01 is otherwise self-contained (`holdings.py` rewrite) and could open
  before 02 exists; 02 and 03 cannot be reordered.
- Slice 02 reuses `envelope.content_digest()` (full sha256) and
  `envelope.compute_source_id()` (the `{stem}-{12hex}` key) rather than inventing
  a second hashing convention (§7.12 names `compute_source_id` as the key source).
- Slice 01 is the one LLM-touching slice here (one reasoning-ON call per source);
  02 and 03 are model-free — 02 records whatever 01 concluded, 03 only moves and
  recomposes fields already in hand.

## Out of scope (whole feature)

- Any change to the eval or gold path. No slice reads a gold label.
- The Google Drive connector (§7.10) and the English-language gate (P0-11c). This
  feature runs inside the local intake path the connector feeds; it does not touch
  the connector.
- Re-tagging the corpus. Slice 03 corrects the writer; the actual re-tag that
  flushes ~17k chunks' `source_meta` is the stage-4 operation in
  `plans/phase-a-completion/`.
- OCR / repairing a partial holding. §7.11 is flag-only in v0 (P0-1b): the check
  never rejects, re-fetches, or repairs.
- Discovering new source-level facts beyond page count, hash, holdings flag, and
  author/title/date. The record's field set is fixed by §7.12/§7.13.

## Notes / open questions

- **DEC-23 is load-bearing across all three slices.** No source text in any
  committed artifact: the holdings flag (01) and the metadata record (02) carry
  values and short reasons only — no title-page transcription, no contents-page
  dump. A reviewer finding source text in a `source_meta` record is a hard fail.
  `data/` is gitignored, but the rule is about content, not location (§7.12).
- **The record is written before extraction (§7.12).** It must be keyed by the
  same `source_id` the tree/envelope/chunk use, so `compute_source_id` (a pure
  content hash, no LLM) runs at intake. This means intake computes the id it does
  not compute today — a small addition to `intake.py`, grounded on the existing
  `envelope.compute_source_id`.
- **The holdings flag reaches its reader only through slice 02.** Slice 01 makes
  the flag *correct*; slice 02 is what makes it *durable and readable* (P0-1c's
  "reaches a downstream reader"). The two are complementary, not redundant.
- **`title` today is fabricated, not null (§7.13).** `envelope._fallback_title`
  produces the filename slug title-cased in all 30 envelopes. Slice 03 removes
  that fallback path along with the field; slice 02 records a real title or
  `unavailable`, never the slug (P0-1d: "the filename is never a source").
- **Three field states, not two (P0-1d).** author/title/date each carry one of:
  a value with provenance; `unavailable` (read attempted, nothing recoverable);
  or `not_attempted`. The record must make these distinguishable — that
  distinction is the #278/§7.13 defect being fixed, so it belongs in slice 02's
  record shape and slice 03's vault composition, not deferred.
