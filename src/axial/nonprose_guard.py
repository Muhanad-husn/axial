"""Shared non-prose input guard (issue #132): one deterministic heuristic,
used by every per-item LLM-driving loop in the pipeline (xref, chunk, tag,
artifacts) to skip oversized/OCR-garbled text BEFORE it ever reaches an LLM
call. Every caller shares the same non-alpha-ratio *mechanism*
(`garble_only_skip_reason`/`non_prose_skip_reason` below); the *threshold*
each applies is not always this module's own default -- see the tag-pass
note below.

An OCR'd index/bibliography (or any similarly garbled back-matter) becomes
one very large, mostly-non-alphabetic block with no argumentative or
cross-reference value that stalls the LLM. This heuristic -- not a hard rule
-- catches that shape: skip any text over `MAX_CHARS` characters, or whose
non-alphabetic character ratio exceeds `MAX_NON_ALPHA_RATIO`.

First written for `axial.xref` (issue #111), then duplicated verbatim into
`axial.chunk` (issue #118) to avoid an import cycle (`axial.xref` already
imports from `axial.chunk`). This module is the single source of truth
those two copies collapse into, plus the two new call sites (`axial.tag`,
`axial.artifacts`) issue #132 adds.

Note (issue #154, slice 04 of the chunk-redesign subproject): the embedding
chunk stage's own size arm (`axial.chunk._garbage_section_skip_reason`) never
reused this module's size arm to begin with (an oversized section is SPLIT,
not skipped -- see that function's docstring); this module's guard remains
live for `axial.artifacts`, which still skips oversized/OCR-garbled artifact
text before an LLM call.

Note (issue #169, source-router slice 04): the chunk artifact `axial.tag`
and `axial.xref` read was prose-only and size-bounded by the router + chunk
band (source-router slices 02-03), so `non_prose_skip_reason`'s SIZE arm was
no longer a legitimate gate for either pass -- a large chunk reaching
tag/xref is legitimate prose, not back-matter. Both passes called
`garble_only_skip_reason` (below) instead: the SAME non-alpha arm only,
demoting the guard from primary gate to a deliberate, logged backstop for
prose that is genuinely garbled (slips type classification) rather than
merely long. `non_prose_skip_reason` itself is unchanged and stays live for
`axial.artifacts` (see above).

Note (`axial.tag`'s threshold, dated to the 2026-07 Phase A rerun): `axial.
tag` still calls `garble_only_skip_reason`, but with an explicit `max_non_
alpha_ratio` override (`axial.tag.TAG_MAX_NON_ALPHA_RATIO`, currently 0.6)
rather than this module's shared 0.4 default -- measured, not fitted:
legitimate scholarship on the real 17,888-chunk corpus topped out at 0.517
non-alpha, while the genuinely garbled shape this backstop exists to catch
(an OCR'd index/reference dump) sits at 0.68+, a real bimodal gap with
nothing observed in 0.52-0.68. At the shared 0.4 default the guard had
caught 34 chunks in that legitimate band, all false positives, and each
skip left no durable trace (stderr + `continue`, no checkpoint write), so
those 34 chunks vanished from the knowledge graph undetected. The threshold
moved for `axial.tag` alone; this module's own `MAX_NON_ALPHA_RATIO`
default is untouched, and `axial.chunk` / `axial.xref` still call
`garble_only_skip_reason` at that unmodified default -- neither has been
measured against this same evidence, so neither's behavior moves here.
`axial.tag` also now writes every skip to its own durable sidecar
(`axial.tag.tags_skips_sidecar_path`) rather than relying on the stderr log
alone.

Import topology: this is a LEAF module. It must never import from
`axial.xref`, `axial.chunk`, `axial.tag`, or `axial.artifacts` -- all four
import FROM here, and `axial.xref` already imports from both `axial.chunk`
and `axial.tag`, so any import back out of this module toward one of those
four would risk a cycle.
"""

from __future__ import annotations

# Input-guard thresholds for non-prose back-matter (issue #111, lifted to a
# shared home by issue #132): heuristics, not hard rules.
MAX_CHARS = 30000
MAX_NON_ALPHA_RATIO = 0.4


def non_prose_skip_reason(
    text: str,
    max_chars: int = MAX_CHARS,
    max_non_alpha_ratio: float = MAX_NON_ALPHA_RATIO,
) -> str | None:
    """Return a human-readable reason to skip `text` as non-prose
    back-matter, or None to process it normally.

    Skips when `text` exceeds `max_chars` characters, or when its
    non-alphabetic character ratio exceeds `max_non_alpha_ratio`. Both
    thresholds default to this module's own shared constants, so every
    caller applies the identical guard unless it deliberately overrides one.
    """
    char_count = len(text)
    if char_count > max_chars:
        return f"exceeds size limit ({char_count} chars > {max_chars})"
    if char_count:
        non_alpha_ratio = sum(1 for c in text if not c.isalpha()) / char_count
        if non_alpha_ratio > max_non_alpha_ratio:
            return f"high non-alpha ratio ({non_alpha_ratio:.1%})"
    return None


def garble_only_skip_reason(
    text: str,
    max_non_alpha_ratio: float = MAX_NON_ALPHA_RATIO,
) -> str | None:
    """The non-alpha arm ONLY of `non_prose_skip_reason` -- never the size
    arm (issue #169, source-router slice 04). A backstop for genuinely
    garbled prose that slips type classification, not a primary prose/
    non-prose gate: a chunk this large simply reflects the router + chunk
    band (source-router slices 02-03), not back-matter, so size alone must
    never skip it. Mirrors `axial.chunk._garbage_section_skip_reason`'s own
    "non-alpha arm ONLY" precedent (issue #154 slice 04), now lifted here so
    `axial.chunk`, `axial.tag`, and `axial.xref` share one definition of the
    garble-only backstop instead of three copies. `axial.tag` calls this
    with its own `max_non_alpha_ratio` override rather than the default
    below (see the module docstring's tag-pass note)."""
    char_count = len(text)
    if not char_count:
        return None
    non_alpha_ratio = sum(1 for c in text if not c.isalpha()) / char_count
    if non_alpha_ratio > max_non_alpha_ratio:
        return f"high non-alpha ratio ({non_alpha_ratio:.1%})"
    return None
