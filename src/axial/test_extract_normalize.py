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


def test_repair_underdot_glyph_joins_across_a_touching_hyphen():
    # `batatu-1999`: the glyph stands where an underdot consonant was dropped
    # and touches the hyphen before it, so the two sides are one word.
    assert _repair_underdot_glyph("al-● Ham id") == "al-Ham id"
    assert _repair_underdot_glyph("Colonel ʿ Abd-ul-● Ham id") == "Colonel ʿ Abd-ul-Ham id"


def test_repair_underdot_glyph_joins_when_it_touches_a_letter():
    assert _repair_underdot_glyph("●halid arrived") == "halid arrived"
    assert _repair_underdot_glyph("Fay●sal") == "Faysal"


def test_repair_underdot_glyph_leaves_one_space_between_two_tokens():
    # `heydemann-2004`: page furniture between two complete words. Removing
    # the glyph must NOT weld the words together -- the defect that killed
    # the first version of this rule, 62 times in that source alone.
    assert _repair_underdot_glyph("does not make clear ● what") == "does not make clear what"
    assert _repair_underdot_glyph("as the ● unit of agency") == "as the unit of agency"
    assert _repair_underdot_glyph("6 ● Steven Heydemann") == "6 Steven Heydemann"


def test_repair_underdot_glyph_drops_a_leading_glyph_without_a_leading_space():
    assert _repair_underdot_glyph("● Hamzah himself") == "Hamzah himself"


def test_repair_underdot_glyph_handles_several_in_one_run():
    assert _repair_underdot_glyph("General ● Sal a ● h Jad id") == "General Sal a h Jad id"


def test_repair_underdot_glyph_leaves_a_word_the_extractor_split_elsewhere():
    # Deliberate limit, not an oversight. `batatu-1999`'s text is fragmented
    # independently of this glyph (`Jibr il`, `Sal a h`), so the rule removes
    # the glyph and stops. Rejoining split words is a separate, larger defect
    # and needs a dictionary, not a neighbour test.
    assert _repair_underdot_glyph("A ● hmad Jibr il") == "A hmad Jibr il"
    assert _repair_underdot_glyph("Gh u ● tah") == "Gh u tah"


def test_repair_underdot_glyph_between_punctuation_leaves_one_space():
    assert _repair_underdot_glyph("figures (● ) omitted") == "figures ( ) omitted"


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


def test_normalize_text_removes_the_glyph_without_welding_words_together():
    # `heydemann-2004`, the case that decides this rule. The glyph is page
    # furniture between two complete words. Removing it must leave a space.
    assert normalize_text("does not make clear ● what") == "does not make clear what"
    assert normalize_text("6 ● Steven Heydemann") == "6 Steven Heydemann"


def test_normalize_text_joins_a_name_the_glyph_sat_inside():
    # `batatu-1999`. The glyph touches the hyphen, so the sides are one word.
    assert normalize_text("Colonel ʿ Abd-ul-● Ham id") == "Colonel ʿ Abd-ul-Ham id"


def test_normalize_text_leaves_a_word_the_extractor_split_elsewhere():
    # A deliberate limit, stated rather than papered over. `batatu-1999`'s
    # text is fragmented independently of this glyph -- `Jibr il` and the
    # space in `A hmad` carry no `●` and are not this transform's damage.
    # Reconstructing them needs a general word-fragment joiner with a
    # dictionary behind it, which is a separate and much larger defect.
    # The illustration in issue #779 shows the fully reconstructed name;
    # this transform does not get there, and is not trying to.
    assert normalize_text("A ● hmad Jibr il") == "A hmad Jibr il"


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
