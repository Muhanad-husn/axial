"""Regression test for issue #204 (`_is_back_matter` false negatives).

Locked behavioral contract (DEC-1) -- do not edit once committed red.

Given a section title that is real back-matter but does not match any
      existing rule in `axial.gold._is_back_matter` --
        (a) "Selected Bibliography" (a qualifier word precedes the bare
            vocabulary term "bibliography", so the exact-match check misses
            it and no prefix rule strips "Selected "),
        (b) "3 General Secondary Sources" (page-number-prefixed AND
            qualified with "General ", defeating both the #134-gap-1
            page-prefix strip -- which requires an exact vocabulary match
            after stripping the leading number -- and the roman-numeral
            "secondary sources" rule, since there is no roman numeral here),
        (c) "Contributors" (the vocabulary only carries the compound "notes
            on contributors", not the bare word) --
When   `axial.gold._is_back_matter(section)` is called directly,
Then   it must return True for each of (a)-(c),
And    it must still return False for "1984 Reforms" -- the #134 gap-1
       guard case, an ordinary chapter title that merely starts with a
       number and is NOT back-matter -- proving the fix does not
       over-exclude titles that legitimately belong in the sampling frame.

On the real 30-source corpus, these three false negatives let 196
non-substantive notes (bibliography subsections, a source-list section, and
a contributors page) leak into the gold sampling pool, displacing
substantive prose that should have been drawn instead (issue #204). This is
a direct unit-level regression test on the private predicate rather than a
full `axial gold sample` CLI run (compare tests/gold/test_gold_frame_guard.py
for the #131/#134 outer-CLI shape) because the bug is entirely localized to
`_is_back_matter`'s title-matching rules; exercising it directly pins the
exact behavioral gap without the added weight and LLM-fallback surface of a
full pipeline run.
"""

from __future__ import annotations

import pytest

from axial.gold import _is_back_matter


class TestIsBackMatterVariants204:
    @pytest.mark.parametrize(
        "section",
        [
            "Selected Bibliography",
            "3 General Secondary Sources",
            "Contributors",
        ],
    )
    def test_variant_excluded(self, section):
        assert _is_back_matter(section) is True, (
            f"expected {section!r} to be recognized as back-matter and "
            f"excluded from the gold sampling frame (issue #204), but "
            f"_is_back_matter returned False"
        )

    def test_number_prefixed_ordinary_title_still_kept(self):
        # The #134 gap-1 guard case, re-pinned here alongside the #204
        # variants above since (b) exercises the very same page-number-
        # prefix code path: a title that merely starts with a number, and
        # is NOT otherwise back-matter, must not be swept up by a fix aimed
        # at "3 General Secondary Sources". Not currently covered by an
        # existing parametrized case in src/axial/test_gold.py's
        # TestIsBackMatter.test_kept.
        assert _is_back_matter("1984 Reforms") is False, (
            "expected '1984 Reforms' (an ordinary chapter title that merely "
            "starts with a number) to survive as substantive, but "
            "_is_back_matter returned True"
        )
