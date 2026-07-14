"""Shared non-prose input guard (issue #132): one deterministic heuristic,
used identically by every per-item LLM-driving loop in the pipeline (xref,
chunk, tag, artifacts) to skip oversized/OCR-garbled text BEFORE it ever
reaches an LLM call.

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
live for `axial.xref`/`axial.tag`/`axial.artifacts`, which still skip
oversized/OCR-garbled chunks before an LLM call.

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
