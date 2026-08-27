"""Inner unit tests for post-extract text normalization (issue #188, Slice
A -- Tiers 1 + 2: whitespace + glyph repair). Drives the transforms that
`axial.extract.normalize_tree_text` composes, one red->green cycle per
transform, ahead of the locked outer acceptance test at
tests/ingestion/test_extract_normalization.py.
"""

from __future__ import annotations

import unicodedata

from axial.extract import (
    _collapse_whitespace,
    _decode_pua_offset_glyphs,
    _normalize_dotless_i,
    _remove_detached_sk_marks,
    _repair_glyph_names,
    _repair_underdot_glyph,
    _strip_soft_hyphens,
    normalize_text,
    normalize_tree_text,
)

# --- Tier 1: whitespace -----------------------------------------------------


def test_strip_soft_hyphens_removes_u00ad():
    assert _strip_soft_hyphens("exam­ple") == "example"


def test_strip_soft_hyphens_is_a_noop_when_absent():
    assert _strip_soft_hyphens("plain text") == "plain text"


def test_collapse_whitespace_collapses_runs_to_a_single_space():
    assert _collapse_whitespace("a   b \t  c") == "a b c"


def test_collapse_whitespace_removes_space_before_punctuation():
    assert _collapse_whitespace("hi , there .") == "hi, there."


def test_collapse_whitespace_is_a_noop_on_clean_text():
    assert _collapse_whitespace("a clean sentence.") == "a clean sentence."


# --- Tier 2: glyph repair ----------------------------------------------------


def test_remove_detached_sk_marks_drops_a_stranded_macron():
    macron = "¯"
    assert unicodedata.category(macron) == "Sk"
    assert macron not in _remove_detached_sk_marks(f"a {macron} b")


def test_remove_detached_sk_marks_is_a_noop_when_absent():
    assert _remove_detached_sk_marks("no marks here") == "no marks here"


def test_decode_pua_offset_glyphs_decodes_recoverable_offset():
    pua_e = chr(0xF700 + ord("e"))
    assert _decode_pua_offset_glyphs(f"t{pua_e}st") == "test"


def test_decode_pua_offset_glyphs_drops_unrecoverable_offset():
    pua_bad = chr(0xF700 + 0x01)
    assert _decode_pua_offset_glyphs(f"wo{pua_bad}rd") == "word"


def test_decode_pua_offset_glyphs_is_a_noop_when_absent():
    assert _decode_pua_offset_glyphs("no pua glyphs") == "no pua glyphs"


def test_repair_glyph_names_maps_asper_to_ayn():
    assert _repair_glyph_names("region /asper called") == "region ʿ called"


def test_repair_glyph_names_maps_lenis_to_hamza():
    assert _repair_glyph_names("term /lenis meaning") == "term ʾ meaning"


def test_repair_glyph_names_drops_font_internal_codes():
    assert _repair_glyph_names("before H1234 after") == "before  after"
    assert _repair_glyph_names("before Q12 after") == "before  after"


def test_repair_glyph_names_never_strips_legitimate_slash_words():
    raw = "and/or threat/opportunity /reliefweb /p111"
    assert _repair_glyph_names(raw) == raw


def test_repair_glyph_names_does_not_match_a_longer_token_as_a_prefix():
    # Regression (reviewer finding #1, issue #188 Slice A): the allowlist must
    # anchor on a trailing word boundary so `/asper`/`/lenis` never match as a
    # prefix of a longer word -- only as the whole leaked token.
    assert _repair_glyph_names("a rumor of /aspersion cast") == "a rumor of /aspersion cast"
    assert _repair_glyph_names("a /lenis-ness quality") == "a /lenis-ness quality"
    # The bare leaked tokens (mid-string and end-of-string) still map.
    assert _repair_glyph_names("region /asper called") == "region ʿ called"
    assert _repair_glyph_names("term /lenis meaning") == "term ʾ meaning"
    assert _repair_glyph_names("trailing /asper") == "trailing ʿ"
    assert _repair_glyph_names("trailing /lenis") == "trailing ʾ"


# --- Tier 2: underdot-glyph repair (issue #779) -----------------------------
#
# docling's font-glyph decode leaks U+25CF (`●`) two ways: (a) mid-word, in
# place of an Arabic-transliteration underdot consonant (`batatu-1999`), and
# (b) as a genuine running-header divider (`heydemann-2004`). The rule is
# about the glyph's immediate neighbours, never the source: `●` is damage
# when a directly-touching character (a letter or a hyphen) sits against it,
# or when a single space separates it from a short, lowercase-initial letter
# run -- a signature of a word broken at the point of one dropped consonant.
# It is legitimate, and left untouched, when neither neighbour looks like a
# fragment.


def test_repair_underdot_glyph_is_a_noop_when_absent():
    assert _repair_underdot_glyph("plain text") == "plain text"


def test_repair_underdot_glyph_joins_single_letter_fragments_on_both_sides():
    # The `A ● hmad` half of the issue's headline example, isolated from the
    # unrelated `Jibr il` split next to it (see
    # test_normalize_text_fixes_the_glyph_but_leaves_an_unrelated_word_split
    # below for why that half is out of scope).
    assert _repair_underdot_glyph("A ● hmad") == "Ahmad"


def test_repair_underdot_glyph_closes_a_leading_hyphen_attached_fragment():
    # "al-" touches the glyph directly (no space) -- unambiguously mid-word,
    # so the left side closes. "Ham" is a capitalized, multi-letter token
    # across the space on the right -- not a fragment by this rule, so that
    # space is left alone. The `Ham`/`id` split is a separate, pre-existing
    # word-fragmentation defect unrelated to the glyph, and stays: this rule
    # only closes gaps immediately adjacent to `●`.
    assert _repair_underdot_glyph("al-● Ham id") == "al- Ham id"


def test_repair_underdot_glyph_joins_fragments_on_both_sides():
    # "u" (a single letter) and "tah" (a short, lowercase-initial run) both
    # read as fragments, so both flanking spaces close. "Gh" is two tokens
    # away from the glyph and stays untouched, same reasoning as `Ham id`
    # above.
    assert _repair_underdot_glyph("Gh u ● tah") == "Gh utah"


def test_repair_underdot_glyph_leaves_a_whitespace_isolated_header_untouched():
    # heydemann-2004's running-header divider: `6` (a number) and `Steven`
    # (a capitalized word) are both complete tokens, not fragments.
    assert _repair_underdot_glyph("6 ● Steven Heydemann") == "6 ● Steven Heydemann"


def test_repair_underdot_glyph_joins_a_line_start_touching_fragment():
    # No left neighbour at all (start of string); the right side touches a
    # letter directly, which alone is enough to call it damage.
    assert _repair_underdot_glyph("●halid arrived") == "halid arrived"


def test_repair_underdot_glyph_leaves_a_punctuation_adjacent_glyph_untouched():
    # Touching punctuation on both sides is never a word fragment.
    assert _repair_underdot_glyph("figures (●) omitted") == "figures (●) omitted"


def test_repair_underdot_glyph_leaves_ordinary_lowercase_words_untouched():
    # Guards the length cap that keeps this rule from firing on ordinary
    # prose: a ● between two full lowercase words (neither short, both
    # plausible as complete tokens on their own) is left as-is. This is the
    # one place this rule leans on a tuned constant (max fragment length 5,
    # derived from the longest measured damage-side fragment, "hmad", at 4)
    # rather than a purely structural signal -- flagged, not hidden.
    assert _repair_underdot_glyph("totals ● verified") == "totals ● verified"


def test_normalize_dotless_i_maps_to_ascii_i():
    assert _normalize_dotless_i("Alawı") == "Alawi"


def test_normalize_dotless_i_is_a_noop_when_absent():
    assert _normalize_dotless_i("Alawi") == "Alawi"


# --- Composition: normalize_text --------------------------------------------


def test_normalize_text_cleans_up_after_a_dropped_font_code_leaves_no_gap():
    assert normalize_text("word H4242 dropped code") == "word dropped code"


def test_normalize_text_leaves_out_of_scope_characters_untouched():
    raw = "price · item café total ∑ ± √"
    assert normalize_text(raw) == raw


def test_normalize_text_repairs_a_pua_glyph_that_decodes_to_an_sk_character():
    # Regression (reviewer finding #2, issue #188 Slice A): PUA decoding must
    # run before Sk-mark removal, so a PUA glyph whose decoded value is itself
    # an Sk-category character (e.g. an acute accent) gets caught by the Sk
    # pass on the second traversal, not left leaking through unrepaired.
    acute = chr(0xB4)
    assert unicodedata.category(acute) == "Sk"
    pua_acute = chr(0xF700 + 0xB4)
    assert normalize_text(f"wo{pua_acute}rd") == "word"


def test_normalize_text_fixes_the_glyph_but_leaves_an_unrelated_word_split():
    # Issue #779 acceptance criterion, first half. `normalize_text` repairs
    # the `A ● hmad` fragmentation the glyph caused: "Ahmad". It does NOT
    # also repair "Jibr il" -> "Jibril" -- that split has no `●` in it, isn't
    # this glyph's damage, and reconstructing it would need a general
    # word-fragment joiner the issue explicitly scopes out ("the rule is
    # about the character's neighbours"). Stated plainly, not silently: the
    # full headline reconstruction in the issue's illustration is not what
    # this transform produces end-to-end.
    assert normalize_text("A ● hmad Jibr il") == "Ahmad Jibr il"


def test_normalize_text_leaves_a_legitimate_header_bullet_exactly_as_it_stands():
    # Issue #779 acceptance criterion, second half.
    assert normalize_text("6 ● Steven Heydemann") == "6 ● Steven Heydemann"


# --- normalize_tree_text: tree-walk preserves shape -------------------------


def test_normalize_tree_text_normalizes_leaf_text_and_preserves_other_fields():
    tree = {
        "children": [
            {
                "type": "prose",
                "order": "1",
                "label": "section_header",
                "text": "Intro",
                "children": [
                    {
                        "type": "prose",
                        "order": "1.1",
                        "label": "text",
                        "text": "soft­hyphen  double  space",
                    }
                ],
            }
        ]
    }

    out = normalize_tree_text(tree)

    section = out["children"][0]
    assert section["label"] == "section_header"
    assert section["order"] == "1"
    leaf = section["children"][0]
    assert leaf["text"] == "softhyphen double space"
    assert leaf["label"] == "text"
    assert leaf["order"] == "1.1"


def test_normalize_tree_text_leaves_nodes_without_text_untouched():
    tree = {"children": [{"type": "artifact", "order": "1", "label": "table"}]}

    out = normalize_tree_text(tree)

    assert out == {"children": [{"type": "artifact", "order": "1", "label": "table"}]}
