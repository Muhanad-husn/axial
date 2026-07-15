"""Outer acceptance test for issue #188, Slice A (post-extract text
normalization, Tiers 1 + 2: whitespace + glyph repair).

Locked behavioral contract (DEC-1) -- do not edit once committed red.

Given a persisted-tree-shaped dict (root -> children, as emitted by
      `axial.extract._build_tree` on either the docling or the Unstructured
      fallback path) whose block `text` values carry decoding defects
      (soft-hyphens, whitespace damage, detached combining marks, PUA
      offset-glyph leaks, curated glyph-name leaks, dotless-i)
When  the tree is run through the normalization entry point
Then  each defect is repaired in the resulting `text`, the tree's shape and
      every node's `label`/`type`/`order` are byte-identical before and
      after, a clean-font tree (no defects, including the explicitly
      out-of-scope middle-dot / composed-accent / math-symbol characters and
      four legitimate slash-words) passes through with `text` materially
      unchanged, and glyph-name repair never strips a legitimate slash-word.

See specs/PRODUCT.md §5 stage 2 (the text-normalization-pass sentence),
§7.4 "Post-extract text normalization", and §8 acceptance criterion P0-2b
for the source of truth. See also plans/extract-normalization/01-whitespace-glyph.md
(Slice A plan) and docs/exploration/extract-text-normalization.md (six-book
finding/rationale this slice is built from).

Locked P0-2b invariants this test pins
---------------------------------------------------------------------------
1. The pass alters no block's `label`, `type`, or `order` and does not
   change the tree's shape (§7.4); only `text` is eligible to change.
2. Each transform is a no-op when its target defect is absent: a
   clean-font tree passes through with `text` materially unchanged.
3. Tier 1 whitespace (universal): soft-hyphens (U+00AD) stripped; runs of
   whitespace collapse to a single space; space-before-punctuation removed.
4. Tier 2 glyph repair (font-specific, no-op when absent): detached
   combining marks (Unicode category Sk) no longer survive verbatim in the
   output; recoverable Private-Use-Area offset glyphs
   (`chr(c - 0xF700)`) are decoded, unrecoverable ones are dropped; the
   curated glyph-name allowlist maps `asper`->`ʿ`, `lenis`->`ʾ`,
   and drops `H####`/`Q##` font-internal codes; dotless-i (`ı`)
   normalizes to `i`.
5. Glyph-name repair is a curated ALLOWLIST, never a blanket `/word`
   strip: `and/or`, `threat/opportunity`, `/reliefweb`, `/p111` survive
   verbatim.
6. Out of scope, left untouched: middle-dots (`·`), correctly-composed
   accents (e.g. `é`), and mathematical symbols (e.g. `∑`, `±`,
   `√`).
7. Tier 3 (small-caps letter-spacing repair) is NOT covered by this test --
   it is out of scope for Slice A (deferred to Slice B).

Entry-point decision (this test's locked contract; the implementer builds
to this shape)
---------------------------------------------------------------------------
`axial.extract.normalize_tree_text(tree: dict) -> dict`

Takes a tree dict in the locked `{children: [...]}` shape emitted by
`_build_tree` (nodes are dicts carrying some subset of `type`, `order`,
`label`, `text`, `children`) and returns a tree of the identical shape with
every node's `text` value normalized (defects repaired) and every other
field (`type`, `order`, `label`, the `children` nesting itself) preserved
exactly. This is a pure function over a tree dict -- no I/O, no docling/
Unstructured dependency -- so it is directly unit-testable against synthetic
fixtures without a real PDF (`data/` is gitignored; the repo holds no book
text). The implementer is responsible for wiring this function (or the
per-leaf transform it wraps) into BOTH extraction paths -- the docling
`normalize()` path and the Unstructured `_normalize_unstructured()` fallback
path -- before the tree is persisted (§7.4), so the persisted tree ends up
normalized regardless of which path produced it. That wiring is not
exercised at the subprocess/PDF level by this test; it is pinned here only
at the Python-level entry point, per the test-design decision for this
slice (synthetic trees, not a real-PDF end-to-end run).
"""

from __future__ import annotations

import copy
import unicodedata

import pytest

from axial.extract import normalize_tree_text

# ---------------------------------------------------------------------------
# Synthetic tree-fixture helpers (mirror the locked node shape emitted by
# axial.extract._build_tree: {type, order, label?, text?, children?}).
# ---------------------------------------------------------------------------


def _leaf(text: str, order: str, label: str = "text", node_type: str = "prose") -> dict:
    return {"type": node_type, "order": order, "label": label, "text": text}


def _section(order: str, label: str, children: list) -> dict:
    return {
        "type": "prose",
        "order": order,
        "label": label,
        "text": label,
        "children": children,
    }


def _single_leaf_tree(text: str) -> dict:
    """A minimal tree: root -> one section -> one leaf carrying `text`."""
    return {
        "children": [
            _section(
                "1",
                "Section One",
                [_leaf(text, "1.1")],
            )
        ]
    }


def _leaf_text_out(tree: dict) -> str:
    """Pull the single leaf's normalized text back out of a
    `_single_leaf_tree`-shaped result."""
    return tree["children"][0]["children"][0]["text"]


# ---------------------------------------------------------------------------
# Tier 1 -- whitespace (universal, zero-risk)
# ---------------------------------------------------------------------------


def test_soft_hyphen_is_stripped():
    raw = "the exam­ple sentence"
    out = _leaf_text_out(normalize_tree_text(_single_leaf_tree(raw)))
    assert "­" not in out, f"expected soft-hyphen (U+00AD) stripped, got {out!r}"
    assert out == "the example sentence", (
        f"expected the soft-hyphen removed with no residual gap, got {out!r}"
    )


def test_whitespace_runs_collapse_to_a_single_space():
    raw = "word1   word2 \t  word3"
    out = _leaf_text_out(normalize_tree_text(_single_leaf_tree(raw)))
    assert out == "word1 word2 word3", (
        f"expected runs of whitespace collapsed to a single space, got {out!r}"
    )


def test_space_before_punctuation_is_removed():
    raw = "hello , world . next ; item : done !"
    out = _leaf_text_out(normalize_tree_text(_single_leaf_tree(raw)))
    assert out == "hello, world. next; item: done!", (
        f"expected space-before-punctuation removed, got {out!r}"
    )


# ---------------------------------------------------------------------------
# Tier 2 -- glyph repair (font-specific, no-op when absent)
# ---------------------------------------------------------------------------


def test_detached_combining_mark_is_removed_from_output():
    """A detached (spacing-form) combining mark, category Sk -- e.g. a
    stranded macron -- fully isolated between spaces (nothing adjacent to
    reattach it to) must not survive verbatim in the output: it is either
    dropped or reattached (§7.4), and with nothing to reattach to, dropping
    is the only sensible outcome. This assertion is agnostic to the
    drop-vs-reattach implementation choice: it only requires the raw Sk
    codepoint itself is gone."""
    macron = "¯"  # detached MACRON, Unicode category Sk
    assert unicodedata.category(macron) == "Sk"
    raw = f"the region {macron} of interest"
    out = _leaf_text_out(normalize_tree_text(_single_leaf_tree(raw)))
    assert macron not in out, (
        f"expected the detached combining mark (U+00AF, category Sk) dropped "
        f"or reattached -- not present verbatim -- got {out!r}"
    )
    assert "  " not in out, (
        f"expected no double-space left behind after the detached mark was removed, got {out!r}"
    )
    assert "region" in out and "interest" in out


@pytest.mark.parametrize("mark", ["¯", "´", "¨", "¸"])
def test_each_detached_sk_mark_from_the_spec_list_is_repaired(mark):
    """§7.4 names macron, acute, diaeresis, and cedilla explicitly as
    example detached combining marks (category Sk) that get dropped or
    reattached."""
    assert unicodedata.category(mark) == "Sk"
    raw = f"before {mark} after"
    out = _leaf_text_out(normalize_tree_text(_single_leaf_tree(raw)))
    assert mark not in out, f"expected {mark!r} (Sk) repaired away, got {out!r}"


def test_recoverable_pua_offset_glyph_is_decoded():
    """A Private-Use-Area glyph whose offset from U+F700 lands on a
    printable character is decoded via `chr(c - 0xF700)` (§7.4)."""
    pua_e = chr(0xF700 + ord("e"))  # decodes to 'e'
    raw = f"t{pua_e}st"
    out = _leaf_text_out(normalize_tree_text(_single_leaf_tree(raw)))
    assert out == "test", (
        f"expected the recoverable PUA glyph U+{ord(pua_e):04X} decoded to "
        f"'e' via chr(c - 0xF700), got {out!r}"
    )


def test_unrecoverable_pua_offset_glyph_is_dropped():
    """A PUA glyph whose offset from U+F700 does not land on a usable
    character (e.g. a control code) is dropped, not left in the output."""
    pua_unrecoverable = chr(0xF700 + 0x01)  # offset -> U+0001, a control code
    raw = f"wo{pua_unrecoverable}rd"
    out = _leaf_text_out(normalize_tree_text(_single_leaf_tree(raw)))
    assert pua_unrecoverable not in out, (
        f"expected the unrecoverable PUA glyph dropped, got {out!r}"
    )
    assert out == "word", f"expected the unrecoverable PUA glyph dropped cleanly, got {out!r}"


def test_asper_glyph_name_leak_maps_to_ayn():
    raw = "region /asper called Alawite"
    out = _leaf_text_out(normalize_tree_text(_single_leaf_tree(raw)))
    assert out == "region ʿ called Alawite", (
        f"expected the curated allowlist to map the leaked glyph name "
        f"'/asper' to ayn (U+02BF), got {out!r}"
    )


def test_lenis_glyph_name_leak_maps_to_hamza():
    raw = "term /lenis meaning hamza"
    out = _leaf_text_out(normalize_tree_text(_single_leaf_tree(raw)))
    assert out == "term ʾ meaning hamza", (
        f"expected the curated allowlist to map the leaked glyph name "
        f"'/lenis' to hamza (U+02BE), got {out!r}"
    )


@pytest.mark.parametrize("code", ["H1234", "H0007", "Q12", "Q99"])
def test_font_internal_glyph_codes_are_dropped(code):
    raw = f"before {code} after"
    out = _leaf_text_out(normalize_tree_text(_single_leaf_tree(raw)))
    assert code not in out, f"expected font-internal code {code!r} dropped, got {out!r}"
    assert out == "before after", (
        f"expected the font-internal code {code!r} dropped cleanly with no "
        f"residual double space, got {out!r}"
    )


def test_dotless_i_normalizes_to_i():
    raw = "Alawı community"
    out = _leaf_text_out(normalize_tree_text(_single_leaf_tree(raw)))
    assert out == "Alawi community", f"expected dotless-i (U+0131) normalized to 'i', got {out!r}"


# ---------------------------------------------------------------------------
# Safety principle -- curated allowlist, never a blanket `/word` strip
# ---------------------------------------------------------------------------


def test_legitimate_slash_words_survive_verbatim():
    """§7.4's safety principle, named explicitly: `and/or`,
    `threat/opportunity`, `/reliefweb`, `/p111` are real prose and must
    never be corrupted by the glyph-name allowlist, which matches only its
    specific curated leaked names."""
    raw = (
        "choose and/or not; assessing threat/opportunity balance; "
        "source at /reliefweb; see page /p111 for detail"
    )
    out = _leaf_text_out(normalize_tree_text(_single_leaf_tree(raw)))
    assert out == raw, (
        f"expected legitimate slash-words preserved verbatim (no blanket "
        f"'/word' strip), got {out!r}"
    )


# ---------------------------------------------------------------------------
# Explicitly out of scope -- must be left untouched
# ---------------------------------------------------------------------------


def test_middle_dot_composed_accent_and_math_symbols_are_untouched():
    raw = "price · item café total ∑ ± √"
    out = _leaf_text_out(normalize_tree_text(_single_leaf_tree(raw)))
    assert out == raw, (
        f"expected middle-dot, composed accents, and math symbols left "
        f"untouched (explicitly out of scope, §7.4), got {out!r}"
    )


# ---------------------------------------------------------------------------
# Clean-font pass-through: every transform is a no-op when its target
# defect is absent (§7.4 P0-2b invariant 2)
# ---------------------------------------------------------------------------


def test_clean_font_tree_passes_through_materially_unchanged():
    clean_tree = {
        "children": [
            _section(
                "1",
                "Introduction",
                [
                    _leaf(
                        "This is a clean sentence with no decoding defects, "
                        "a café, a middle · dot, and math like "
                        "∑ ± √. It also has legitimate "
                        "slash-words: and/or, threat/opportunity, "
                        "/reliefweb, /p111.",
                        "1.1",
                    ),
                    _leaf("A second clean paragraph, nothing to repair.", "1.2"),
                ],
            ),
            _leaf("A top-level clean caption.", "2", label="caption", node_type="artifact"),
        ]
    }
    before = copy.deepcopy(clean_tree)
    out = normalize_tree_text(clean_tree)
    assert out == before, (
        f"expected a clean-font tree (no in-scope defects) to pass through "
        f"materially unchanged, got:\n{out!r}\nexpected:\n{before!r}"
    )


# ---------------------------------------------------------------------------
# Shape / provenance invariant (P0-2b invariant 1): only `text` may change
# ---------------------------------------------------------------------------


def test_tree_shape_and_type_order_label_are_preserved_only_text_changes():
    dirty_tree = {
        "children": [
            _section(
                "1",
                "Section One",
                [
                    _leaf("soft­hyphen  double  space", "1.1"),
                    _leaf("word H4242 dropped code", "1.2", label="list_item"),
                    _section(
                        "1.3",
                        "Nested Sub-section",
                        [
                            _leaf(
                                "Alawı /asper leak middle · dot",
                                "1.3.1",
                                label="text",
                            ),
                        ],
                    ),
                ],
            ),
            _leaf(
                "artifact caption text unaffected · fine",
                "2",
                label="caption",
                node_type="artifact",
            ),
        ]
    }
    before = copy.deepcopy(dirty_tree)
    out = normalize_tree_text(dirty_tree)

    def _walk(before_node, after_node, path):
        assert isinstance(after_node, dict), f"node at {path} is no longer a dict: {after_node!r}"
        for field in ("type", "order", "label"):
            if field in before_node:
                assert after_node.get(field) == before_node.get(field), (
                    f"expected `{field}` preserved byte-identical at {path} "
                    f"(P0-2b invariant 1), before={before_node.get(field)!r} "
                    f"after={after_node.get(field)!r}"
                )
        before_children = before_node.get("children")
        after_children = after_node.get("children")
        if before_children is None:
            assert after_children is None, (
                f"expected no `children` introduced at {path} where none existed before"
            )
        else:
            assert isinstance(after_children, list), (
                f"expected `children` to remain a list at {path}"
            )
            assert len(after_children) == len(before_children), (
                f"expected the same number of children at {path} "
                f"(tree shape must not change), before="
                f"{len(before_children)} after={len(after_children)}"
            )
            for i, (bc, ac) in enumerate(zip(before_children, after_children)):
                _walk(bc, ac, f"{path}.children[{i}]")

    _walk(before, out, "root")

    # And confirm real repair actually happened where defects existed --
    # this whole invariant test would be vacuous if `text` never changed.
    section = out["children"][0]
    leaf_1_1 = section["children"][0]
    leaf_1_2 = section["children"][1]
    nested_leaf = section["children"][2]["children"][0]
    caption = out["children"][1]

    assert leaf_1_1["text"] == "softhyphen double space", (
        f"expected 1.1's soft-hyphen and double-space defects repaired, got {leaf_1_1['text']!r}"
    )
    assert leaf_1_2["text"] == "word dropped code", (
        f"expected 1.2's font-internal glyph code dropped, got {leaf_1_2['text']!r}"
    )
    assert nested_leaf["text"] == "Alawi ʿ leak middle · dot", (
        f"expected the nested leaf's dotless-i and '/asper' leak repaired, "
        f"and its out-of-scope middle-dot left untouched, got "
        f"{nested_leaf['text']!r}"
    )
    assert caption["text"] == "artifact caption text unaffected · fine", (
        f"expected the artifact-typed caption node's clean text (and its "
        f"out-of-scope middle-dot) left unchanged, and the transform must "
        f"apply on artifact nodes' text too (only `label`/`type`/`order` "
        f"are protected from change, not artifact nodes' `text` itself), "
        f"got {caption['text']!r}"
    )
