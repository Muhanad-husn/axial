"""Outer acceptance test for issue #231 (envelope `toc` must be the model's
SELECTED chapter subset of the tree's flattened heading list, not the raw
structural dump of every top-level `section_header`).

Locked behavioral contract (DEC-1) -- do not edit once committed red.

Given a source whose structural tree opens with a small front-matter region
      followed by ELEVEN top-level `section_header` siblings, all flattened
      to the same nesting depth -- the exact shape a real book produces
      after docling extraction (70-260 such siblings on a real source,
      mixing real chapters, subsection headings, OCR-garble fragments, and
      body sentences mislabelled as headings). Four of the eleven are
      genuine chapter titles; the other seven are non-chapters: four
      subsection-style headings, one OCR-garble fragment
      ("lalrodac:lioo"), one body sentence mislabelled as a heading ("A
      successful program does all of them at once."), and one appendix
      heading.
When  the user runs the structural-envelope pass on this source with an
      LLM client whose toc-selection answer names exactly the four real
      chapters (a strict subset of the eleven headings, excluding every
      non-chapter)
Then  the written envelope's `toc` field is that SELECTED subset -- not the
      raw structural dump of all eleven headings -- and in particular the
      OCR-garble fragment and the mislabelled body sentence, both genuinely
      present in the source tree, are absent from the written `toc`.

See specs/PRODUCT.md §7.3 ("Structural envelope": `toc` is a non-empty
list, part of the envelope's locked shape) and §5 stage 3 ("One API call
per source extracts ... table of contents ..."). Issue #227 (already
shipped, tests/ingestion/test_envelope_structural_toc.py) established that
`toc` must be grounded in the tree's own structure rather than an
ungrounded model guess, by deriving it as the raw list of every top-level
`section_header` heading (`axial.envelope._toc_from_tree`). On a real
source that raw list is 70-260 entries mixing genuine chapters with
subsection headings, OCR-garble fragments, and mislabelled body sentences
-- not a usable table of contents. #231 is the NEXT layer: feed that
flattened heading list to the model and use the model's own SELECTED
chapter subset as `toc`, rather than handing every one of those 70-260
entries through verbatim. This test does not touch or weaken #227's own
locked contract (that `toc` must be tree-grounded, not model-confabulated)
-- it adds the requirement that the tree-grounded candidates are then
narrowed by the model's selection before being written.

The bug (PRD-relevant gap, not yet fixed) this test is written against
-----------------------------------------------------------------------
`axial.envelope.build_envelope` currently prefers `_toc_from_tree(tree)` --
the unfiltered raw list of every top-level `section_header` heading -- over
anything the model returns, whenever that list is non-empty
(`toc = structural_toc if structural_toc else parsed["toc"]`). No
mechanism today ever narrows that list down to a genuine chapter subset:
the model's own answer for `toc` is silently discarded outright as long as
the tree yields ANY top-level headings at all. On this fixture, that means
the written `toc` today is the full eleven-entry dump -- OCR garble,
mislabelled sentence, and all -- regardless of what the LLM client
returns.

Seam decision 1 -- drive `run_envelope` in-process with a custom fake
client, not the subprocess/env-var `stub`/`record` seam
-----------------------------------------------------------------------
Every other envelope acceptance test in this suite drives `axial envelope`
as a subprocess with `AXIAL_LLM_PROVIDER` selecting `stub`/`record`/
`explode`. Those three canned clients (src/axial/llm.py) each return
exactly ONE fixed response body regardless of prompt content, dispatched
only by `pass_name` -- they cannot express "the toc-selection call (whose
`pass_name` and prompt shape are the IMPLEMENTER's design choice, not yet
built) answers with this specific chosen subset `S`, while the main
envelope call still answers with a fully valid thesis/scope/
stated_argument". `axial.envelope.run_envelope` already accepts an
optional `client: LLMClient | None` parameter for exactly this kind of
direct dependency injection (no subprocess needed), so this test calls it
in-process with a small, purpose-built fake client
(`_SelectingRecordingLLMClient` below) that implements the same
single-method `LLMClient` protocol (`complete(self, prompt, pass_name=...)
-> str`) every real/stub/record client in src/axial/llm.py implements, and
additionally RECORDS every prompt (and its `pass_name`) it receives, so
assertion 1 below can inspect exactly what the model was asked.

Seam decision 2 -- the fake client's response shape, and its honest limit
-----------------------------------------------------------------------
The implementer may fold toc-selection into the SAME envelope call (one
`complete()` call whose prompt carries both the intro/head-of-tree evidence
AND the heading list, and whose response's `toc` key IS the selected
subset), or add a genuinely SEPARATE toc-selection call with its own
prompt and its own response shape. This test cannot know in advance which
design will be chosen, or -- in the two-call case -- what key name a new,
not-yet-written parser will look for in the second call's response. To
stay robust to both designs, the fake client returns the SAME JSON object
for EVERY `complete()` call it receives, regardless of prompt or
`pass_name`: `{"thesis": <valid>, "scope": <valid>, "stated_argument":
<valid>, "toc": S, "selected_toc": S, "chapters": S, "selected_headings":
S}` -- a single well-formed JSON object (matching the convention every
other pass in src/axial/llm.py already follows: `_CANNED_CHUNK_RESPONSE`,
`_CANNED_TAG_RESPONSE`, `_canned_xref_response`, and
`_canned_content_apparatus_response` are ALL JSON objects, never a bare
array) carrying the SAME selected subset `S` under `"toc"` plus three
plausible alias keys a second call's parser might look for instead. This
covers: (a) a single folded call, where the one response's `toc` key IS
the answer; (b) a two-call design where the SECOND call's parser reads a
`"toc"`-keyed (or one of the aliased) JSON object exactly like every other
pass in this codebase already does. It does NOT cover a second-call design
whose parser expects a bare JSON array (`["Chapter One: ...", ...]`)
instead of a JSON object, or a key name not among the four covered here --
if the implementer chooses that shape, `complete_json`'s bounded re-ask
budget will exhaust and `run_envelope` will raise instead of writing an
envelope, and this test will need a follow-up adjustment to its fake
client (not to its own locked assertions below, which describe the
observable envelope contract, not the wire shape of any one call).

Because the fake client returns EXACTLY `S` for every call's `"toc"` key
(and its three aliases), regardless of how many calls `run_envelope` ends
up making or in what order, `envelope["toc"] == S` is the ONLY value this
fixture's `toc` field can ever end up holding once #231 is correctly
wired -- there is no other candidate value the fix could accidentally
satisfy this assertion with.

Seam decision 3 -- assertion 1 (headings reach the model) is a genuine,
non-tautological observable, but a WEAK precondition today
-----------------------------------------------------------------------
Assertion 1 below asserts every one of the fixture's eleven headings
appears in at least one prompt the fake client recorded. This is the
"the tree's heading list is presented to the model" contract #231 adds.
Note honestly: today, PRE-#231, this assertion already holds -- `docling`'s
`section_header` label already routes to PROSE (`axial.router.route_for`),
so `axial.envelope._head_of_tree_lines`'s EXISTING head-of-tree widen
already collects every one of this fixture's eleven headings as ordinary
prose lines into the one existing envelope prompt (verified directly: see
`test_llm_toc_selection_fixture_headings_reach_compose_prompt` below). This
assertion therefore does not, by itself, distinguish "the #231 selection
mechanism is built" from "the ordinary head-of-tree widen already existed"
-- it is included because the issue explicitly asks the observable
contract to be pinned, and it remains a genuine (not vacuous) proof that
the model is shown the source's real heading vocabulary, in whatever prompt
shape the implementer chooses (a folded prompt or a dedicated
toc-selection prompt) -- the REAL, un-fakeable proof of #231's behavior is
assertion 2, which today's code (see "The bug" above) cannot pass no
matter what the LLM returns.

Seam decision 4 -- fixture: a HAND-AUTHORED tree, mirroring
structural_toc_tree.json's own precedent
-----------------------------------------------------------------------
tests/fixtures/envelope/llm_toc_selection_paper.pdf (+ its hand-authored
tree fixture, llm_toc_selection_tree.json -- see tests/fixtures/envelope/
_generate.py for the generation recipe and full rationale) is not expected
to reproduce this tree via a live docling extraction (same precedent as
router_prose_filter_paper_tree.json and structural_toc_tree.json); the PDF
exists only so `axial.envelope.compute_source_id` has real file bytes to
hash. The hand-authored tree is pre-placed directly at
`data/trees/<source_id>.json`. No real book text is used anywhere in this
fixture (DEC-23).

Test hygiene: the shared, content-snapshot-based
`_isolate_persisted_tree_and_envelope_state` autouse fixture in
tests/conftest.py protects `data/trees/` (this test writes the hand-authored
tree fixture there); `envelopes_dir` is pointed at a private `tmp_path`
subdirectory so this test never touches the real `data/envelopes/` at all.
"""

from __future__ import annotations

import json
from pathlib import Path

from axial.envelope import compute_source_id, compose_prompt, run_envelope, select_envelope_nodes

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "envelope"
TREES_DIR = REPO_ROOT / "data" / "trees"

LLM_TOC_PDF = FIXTURES_DIR / "llm_toc_selection_paper.pdf"
LLM_TOC_TREE_FIXTURE = FIXTURES_DIR / "llm_toc_selection_tree.json"

# The fixture's four genuine chapter headings (verbatim node `text` in
# llm_toc_selection_tree.json), in tree order.
REAL_CHAPTER_HEADINGS = (
    "Chapter One: The Onset of Contention",
    "Chapter Two: Escalation Dynamics",
    "Chapter Three: Settlement and Aftermath",
    "Chapter Four: Comparative Synthesis",
)

# The fixture's seven non-chapter top-level headings: four subsection-style
# headings, one OCR-garble fragment, one body sentence mislabelled as a
# heading, and one appendix heading -- everything a genuine "selection"
# must exclude.
NON_CHAPTER_HEADINGS = (
    "1.1 Grievance Recognition and Framing",
    "lalrodac:lioo",
    "2.1 Informal Gatherings to Semi-Formal Assemblies",
    "A successful program does all of them at once.",
    "3.1 Negotiated Concession Pathways",
    "4.1 Cross-Case Convergence Patterns",
    "Appendix A: Supplementary Tables",
)

# All eleven top-level headings, in tree order -- the full flattened
# structural dump `_toc_from_tree` returns today (the #231 defect target).
ALL_HEADINGS = (
    "Chapter One: The Onset of Contention",
    "1.1 Grievance Recognition and Framing",
    "lalrodac:lioo",
    "Chapter Two: Escalation Dynamics",
    "2.1 Informal Gatherings to Semi-Formal Assemblies",
    "A successful program does all of them at once.",
    "Chapter Three: Settlement and Aftermath",
    "3.1 Negotiated Concession Pathways",
    "Chapter Four: Comparative Synthesis",
    "4.1 Cross-Case Convergence Patterns",
    "Appendix A: Supplementary Tables",
)

OCR_GARBLE_HEADING = "lalrodac:lioo"
MISLABELLED_SENTENCE_HEADING = "A successful program does all of them at once."

# The model's selected chapter subset ("S" in this test's/the issue's own
# terms): a strict subset of ALL_HEADINGS naming only the four genuine
# chapters, in the same order they appear in the source.
SELECTED_TOC = list(REAL_CHAPTER_HEADINGS)


class _SelectingRecordingLLMClient:
    """A small, purpose-built fake `LLMClient` (mirrors the single-method
    protocol every client in src/axial/llm.py implements:
    `complete(self, prompt, pass_name=None) -> str`), built for this test
    because no existing stub/record client can express "return the chosen
    subset `S` for a not-yet-designed toc-selection call while also
    answering the main envelope call validly" -- see module docstring, seam
    decisions 1-2, for the full design-robustness rationale and its honest
    limitation."""

    def __init__(self, selected_toc: list[str]):
        self._selected_toc = list(selected_toc)
        # Every (prompt, pass_name) this client was ever asked, in call
        # order -- the observable assertion 1 below inspects.
        self.calls: list[tuple[str, str | None]] = []

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        self.calls.append((prompt, pass_name))
        return json.dumps(
            {
                "thesis": (
                    "Contentious episodes escalate through a predictable "
                    "sequence from recognition to settlement."
                ),
                "scope": "A comparative survey of contentious episodes and their aftermaths.",
                "stated_argument": (
                    "Escalation and settlement both follow a recurring "
                    "sequence across the episodes surveyed."
                ),
                "toc": self._selected_toc,
                # Aliases hedging against a not-yet-designed second call
                # whose parser looks for a differently-named key -- see
                # module docstring, seam decision 2.
                "selected_toc": self._selected_toc,
                "chapters": self._selected_toc,
                "selected_headings": self._selected_toc,
            }
        )


def _place_tree_fixture(source_pdf: Path, tree_fixture_path: Path) -> Path:
    """Pre-place the hand-authored tree fixture at
    data/trees/<source_id>.json (mirrors tests/ingestion/
    test_envelope_structural_toc.py's helper of the same name)."""
    source_id = compute_source_id(source_pdf)
    tree_path = TREES_DIR / f"{source_id}.json"
    tree_path.parent.mkdir(parents=True, exist_ok=True)
    tree_path.write_bytes(tree_fixture_path.read_bytes())
    return tree_path


def test_llm_toc_selection_fixture_matches_no_envelope_heading():
    """Fixture sanity check: none of the fixture's top-level headings match
    introduction/abstract/conclusion, so `compose_prompt` widens to the
    head-of-tree slice -- the exact path a real flattened-heading source
    travels through. If this fails, the rest of this test would not be
    exercising the real #231 precondition at all."""
    tree = json.loads(LLM_TOC_TREE_FIXTURE.read_text(encoding="utf-8"))
    assert select_envelope_nodes(tree) == [], (
        "fixture sanity check failed: expected "
        "tests/fixtures/envelope/llm_toc_selection_tree.json's top-level "
        "headings to match NONE of intro/abstract/conclusion, but "
        f"select_envelope_nodes returned a non-empty match: "
        f"{select_envelope_nodes(tree)!r}"
    )


def test_llm_toc_selection_fixture_headings_reach_compose_prompt():
    """Fixture sanity check (see module docstring, seam decision 3): every
    one of the fixture's eleven headings must reach the assembled envelope
    prompt via the existing head-of-tree widen, so this fixture actually
    gives the (as-yet-unbuilt) #231 selection mechanism real heading
    vocabulary to select from."""
    tree = json.loads(LLM_TOC_TREE_FIXTURE.read_text(encoding="utf-8"))
    evidence = compose_prompt(tree)
    missing = [heading for heading in ALL_HEADINGS if heading not in evidence]
    assert not missing, (
        f"expected every one of this fixture's eleven top-level headings to "
        f"reach compose_prompt's widened head-of-tree evidence, but "
        f"{missing!r} did not.\nFull composed evidence:\n{evidence}"
    )


def test_envelope_toc_is_the_selected_chapter_subset_not_the_raw_dump(tmp_path):
    # --- arrange: pre-place the hand-authored tree (no docling run paid) ---
    _place_tree_fixture(LLM_TOC_PDF, LLM_TOC_TREE_FIXTURE)

    client = _SelectingRecordingLLMClient(SELECTED_TOC)
    envelopes_dir = tmp_path / "envelopes"

    # --- act: run the structural-envelope pass in-process, injecting the
    # fake client directly (seam decision 1) ---
    envelope = run_envelope(LLM_TOC_PDF, client=client, envelopes_dir=envelopes_dir)

    # --- sanity: the LLM was actually called at least once, or every
    # assertion below would be vacuous ---
    assert client.calls, (
        "expected the fake LLM client to have been called at least once by "
        "run_envelope -- zero calls means the envelope pass never reached "
        "any model at all, making the assertions below vacuous"
    )

    # --- assertion 1: the tree's flattened heading list is presented to
    # the model (see module docstring, seam decision 3, for this
    # assertion's honest scope) ---
    all_prompts = "\n".join(prompt for prompt, _pass_name in client.calls)
    missing_from_prompts = [heading for heading in ALL_HEADINGS if heading not in all_prompts]
    assert not missing_from_prompts, (
        f"expected every one of this fixture's eleven top-level headings to "
        f"appear in at least one prompt sent to the LLM client (PRD §7.3/§5 "
        f"stage 3, issue #231: the heading list must be presented to the "
        f"model for selection), but {missing_from_prompts!r} did not appear "
        f"in any recorded prompt.\nAll recorded prompts:\n{all_prompts}"
    )

    # --- shape: toc stays a non-empty list (PRD §7.3's locked envelope
    # shape) ---
    toc = envelope["toc"]
    assert isinstance(toc, list) and len(toc) > 0, (
        f"expected envelope field `toc` to be a non-empty list, got "
        f"{toc!r} (full envelope: {envelope!r})"
    )

    # --- assertion 2: the written toc is the model's SELECTED subset,
    # exactly -- not the tree's raw structural dump of all eleven headings.
    # Because the fake client returns exactly SELECTED_TOC for every call's
    # "toc" key (and its aliases) regardless of call count/order (seam
    # decision 2), this is the ONLY value `toc` can end up holding once
    # #231 is correctly wired end to end. ---
    assert toc == SELECTED_TOC, (
        f"expected the written envelope's `toc` to be exactly the model's "
        f"selected chapter subset {SELECTED_TOC!r} (PRD §7.3/§5 stage 3, "
        f"issue #231: `toc` must be the model's SELECTED subset of the "
        f"tree's flattened heading list, not the raw structural dump of "
        f"every top-level `section_header` heading), got {toc!r}. This "
        f"means `toc` is still populated from `axial.envelope._toc_from_tree`'s "
        f"unfiltered structural dump (issue #227's own fix, which this "
        f"issue narrows further) rather than from the model's own "
        f"selection.\nFull envelope: {envelope!r}"
    )

    # --- assertion 2b: specifically, the OCR-garble fragment and the
    # mislabelled body sentence -- both genuinely present in the source
    # tree (test_llm_toc_selection_fixture_headings_reach_compose_prompt
    # above proves they even reach the model) -- must be ABSENT from the
    # written toc. This is the concrete, human-legible failure this issue
    # exists to fix: a real book's flattened heading list mixes exactly
    # these kinds of non-chapter entries into a raw structural dump. ---
    assert OCR_GARBLE_HEADING not in toc, (
        f"expected the OCR-garble fragment {OCR_GARBLE_HEADING!r} -- "
        f"present in the source tree's top-level headings but excluded "
        f"from the model's selected subset -- to be ABSENT from the "
        f"written envelope's `toc`, but it was present: {toc!r}"
    )
    assert MISLABELLED_SENTENCE_HEADING not in toc, (
        f"expected the body sentence mislabelled as a heading "
        f"{MISLABELLED_SENTENCE_HEADING!r} -- present in the source tree's "
        f"top-level headings but excluded from the model's selected "
        f"subset -- to be ABSENT from the written envelope's `toc`, but it "
        f"was present: {toc!r}"
    )

    # --- assertion 2c: every genuine chapter the model selected is present
    # (guards against a `toc` that ended up empty or partial rather than
    # correctly excluding only the non-chapters) ---
    missing_chapters = [heading for heading in REAL_CHAPTER_HEADINGS if heading not in toc]
    assert not missing_chapters, (
        f"expected every one of the model's selected real chapter headings "
        f"{REAL_CHAPTER_HEADINGS!r} to be present in the written envelope's "
        f"`toc`, but {missing_chapters!r} {'is' if len(missing_chapters) == 1 else 'are'} "
        f"missing from {toc!r}"
    )
