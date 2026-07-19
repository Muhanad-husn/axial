"""Outer acceptance test for issue #227 (envelope `toc` must be derived
structurally from the tree, not solely from the LLM's `parsed["toc"]`).

Locked behavioral contract (DEC-1) -- do not edit once committed red.

Given a source whose top-level structural tree opens with a front-matter
      region (an untagged title page, an author line, a copyright/ISBN
      block, publisher boilerplate, and a short "Contents" page that is the
      source's ONLY chapter listing) followed by three real top-level
      chapter headings (`section_header`-labelled, each with real chapter
      body prose)
And   the front-matter-region skip (`axial.envelope._front_matter_region_end`,
      #225) sweeps the WHOLE region -- including the "Contents" page --
      before the envelope prompt is composed, so the model is never shown
      the source's own chapter listing (verified directly below as a
      fixture sanity check via `compose_prompt`)
When  the user runs `axial envelope <source>` with the LLM provider
      configured to the `stub` client (a fixed, source-independent canned
      response, `["Introduction", "Comparative Cases", "Conclusion"]` for
      `toc` -- see src/axial/llm.py's `StubLLMClient`)
Then  the written envelope's `toc` field reflects the source's own three
      real chapter headings (drawn from the tree's top-level structure), not
      the stub's fixed, unrelated canned `toc` value

See specs/PRODUCT.md §7.3 ("Structural envelope": "One JSON per source ...
{source_id, author, title, date, thesis, toc[], scope, stated_argument}")
and §5 stage 3 ("table of contents") for the source of truth on `toc` being
a real property of the source's own structure, not an LLM guess.

The bug (PRD-relevant defect, not yet fixed)
-----------------------------------------------------------------------
`src/axial/envelope.py`'s `build_envelope` sets `envelope["toc"] =
parsed["toc"]` unconditionally -- `toc` is populated PURELY from whatever
the model returned for that key, with no structural grounding at all. #225
(the front-matter-region skip) fixed a real leak of front matter into the
head-of-tree evidence, but as an unintended side effect it also sweeps the
TOC page whenever that page is short and sits inside the leading
front-matter region (exactly the shape a real title page + copyright block
+ terse "Contents" page takes) -- so a source whose ONLY chapter listing
lived on that page now hands the model no toc source at all. On a stubbed
(or degenerate/free-associating) LLM response this regresses `toc` to
whatever unrelated content the model/stub happens to return, entirely
disconnected from the source's real chapters (the real-world instances:
Tilly and Chouliaraki both regressed to a garbled 1-entry `toc` after #225
landed).

The fix this test locks in (for the implementer, not built here)
-----------------------------------------------------------------------
`toc` must be derived STRUCTURALLY from the extraction tree's own top-level
chapter/section headings, independent of whether the TOC page survives into
the prompt slice -- preferring that structural list when non-empty, falling
back to the model's `parsed["toc"]` only when the tree yields nothing (so
`validate_envelope_fields`'s "toc must be non-empty" guarantee still holds
for a source with no discernible top-level heading structure at all).

Why the `stub` provider is sufficient (no custom poison client needed)
-----------------------------------------------------------------------
`StubLLMClient`'s canned envelope response already carries a FIXED,
source-independent `toc`: `["Introduction", "Comparative Cases",
"Conclusion"]` (src/axial/llm.py) -- content that has nothing to do with
this fixture's real chapter titles ("Chapter One: The Onset of
Contention", "Chapter Two: Escalation Dynamics", "Chapter Three: Settlement
and Aftermath"). That fixed mismatch is exactly the "deliberately WRONG
toc, but valid other fields" seam this test needs: the ONLY way the
assertions below can pass is if `toc` was derived from the tree's own
chapter headings, overriding whatever the stub returned. Reusing the
existing, already-locked `stub` provider (rather than inventing a new
poison client) keeps this test on the same seam every other envelope
acceptance test in this suite already relies on.

Seam decision -- fixture: a HAND-AUTHORED tree, mirroring
router_prose_filter_paper_tree.json's own precedent
-----------------------------------------------------------------------
tests/fixtures/envelope/structural_toc_paper.pdf (+ its hand-authored tree
fixture, structural_toc_tree.json -- see tests/fixtures/envelope/
_generate.py for the generation recipe and full rationale) is not expected
to reproduce this tree via a live docling extraction (same precedent as
router_prose_filter_paper_tree.json); the PDF exists only so
`axial.intake.intake`'s text-layer probe passes and
`axial.envelope.compute_source_id` has real file bytes to hash. The
hand-authored tree is pre-placed directly at `data/trees/<source_id>.json`.

None of the fixture's top-level headings match introduction/abstract/
conclusion (`select_envelope_nodes` returns `[]`, asserted directly below
as a fixture sanity check), so `compose_prompt` widens to the head-of-tree
slice -- the exact path the real Tilly/Chouliaraki regression traveled
through (a widened slice that, once the front-matter region including the
TOC page is skipped, starts at the source's real chapter prose instead of
its chapter listing).

Seam decision -- assertions are content-based, not brittle set-equality
-----------------------------------------------------------------------
This test asserts (a) every one of the fixture's three real chapter
headings appears verbatim in the written envelope's `toc` list, and (b)
none of the stub's fixed canned `toc` entries ("Introduction", "Comparative
Cases", "Conclusion" -- none of which exists anywhere in this fixture)
appear in it. It deliberately does NOT assert `toc` equals a single exact
list: whether a correct structural-derivation implementation also happens
to include, say, the book's own title as an extra entry is an
implementation choice this test does not need to pin to prove the real
behavior -- that `toc` reflects the source's own chapters rather than the
model's unrelated canned answer. Both directions together are required: a
test that only checked "the wrong entries are absent" could pass vacuously
on an empty-ish list, and a test that only checked "the real headings are
present" could pass if an implementation merely concatenated the model's
answer onto the real one without ever replacing the wrong content. Neither
loophole survives both assertions together.

Test hygiene: a subprocess/CLI outer test in the same style as
tests/ingestion/test_envelope.py, using the `clean_envelopes` fixture of the
same name/shape (any envelope file this test causes to appear is removed in
teardown) plus the shared, content-snapshot-based
`_isolate_persisted_tree_and_envelope_state` autouse fixture in
tests/conftest.py for data/trees/ isolation.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from axial.envelope import compose_prompt, compute_source_id, select_envelope_nodes

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "envelope"
ENVELOPES_DIR = REPO_ROOT / "data" / "envelopes"
TREES_DIR = REPO_ROOT / "data" / "trees"

STRUCTURAL_TOC_PDF = FIXTURES_DIR / "structural_toc_paper.pdf"
STRUCTURAL_TOC_TREE_FIXTURE = FIXTURES_DIR / "structural_toc_tree.json"

PROVIDER_ENV_VAR = "AXIAL_LLM_PROVIDER"

# The fixture's three real top-level chapter headings (verbatim node `text`
# in structural_toc_tree.json) -- the ONLY genuine "table of contents" this
# source has, once its dedicated Contents page is swept into the
# front-matter-region skip (see module docstring).
REAL_CHAPTER_HEADINGS = (
    "Chapter One: The Onset of Contention",
    "Chapter Two: Escalation Dynamics",
    "Chapter Three: Settlement and Aftermath",
)

# `StubLLMClient._CANNED_RESPONSE`'s fixed `toc` value (src/axial/llm.py) --
# unrelated to this fixture's real chapters by construction. If the written
# envelope's `toc` contains any of these, `toc` was populated straight from
# the stub's answer rather than derived from the tree.
STUB_CANNED_TOC_ENTRIES = ("Introduction", "Comparative Cases", "Conclusion")

# Distinctive marker text living ONLY on the fixture's "Contents" page
# (structural_toc_tree.json, top-level child index 4) -- the source's only
# literal chapter LISTING, sitting inside the front-matter region.
TOC_PAGE_MARKER = "Halvorne-6 pagination ledger"

# argparse's fallback error for an as-yet-nonexistent subcommand/provider --
# reused verbatim from tests/ingestion/test_envelope.py's identical guard.
ARGPARSE_FALLBACK_MARKERS = (
    "invalid choice",
    "unrecognized arguments",
)


def _run_envelope(provider: str, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env[PROVIDER_ENV_VAR] = provider
    return subprocess.run(
        ["uv", "run", "axial", "envelope", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=env,
    )


def _assert_not_argparse_fallback(result: subprocess.CompletedProcess) -> None:
    combined = result.stdout + result.stderr
    for marker in ARGPARSE_FALLBACK_MARKERS:
        assert marker not in combined, (
            f"expected a real `envelope` behavior path, not an argparse "
            f"fallback (found {marker!r}) -- this means the `envelope` "
            f"subcommand does not exist yet or was never reached:\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )


def _existing_envelope_files() -> set[Path]:
    if not ENVELOPES_DIR.exists():
        return set()
    return set(ENVELOPES_DIR.glob("*.json"))


def _place_tree_fixture(source_pdf: Path, tree_fixture_path: Path) -> Path:
    """Pre-place the hand-authored tree fixture at
    data/trees/<source_id>.json (mirrors tests/ingestion/
    test_envelope_router_prose_filter.py's helper of the same name)."""
    source_id = compute_source_id(source_pdf)
    tree_path = TREES_DIR / f"{source_id}.json"
    tree_path.parent.mkdir(parents=True, exist_ok=True)
    tree_path.write_bytes(tree_fixture_path.read_bytes())
    return tree_path


@pytest.fixture
def clean_envelopes():
    """Mirrors tests/ingestion/test_envelope.py's fixture of the same name:
    snapshot data/envelopes/*.json before the test and delete any file the
    test caused to appear."""
    before = _existing_envelope_files()
    yield
    after = _existing_envelope_files()
    for created in after - before:
        created.unlink()


def test_structural_toc_fixture_matches_no_envelope_heading():
    """Fixture sanity check: none of the fixture's top-level headings match
    introduction/abstract/conclusion, so `compose_prompt` widens to the
    head-of-tree slice -- the exact path the real Tilly/Chouliaraki
    regression travels through. If this fails, the rest of this test would
    not be exercising the real bug shape at all."""
    tree = json.loads(STRUCTURAL_TOC_TREE_FIXTURE.read_text(encoding="utf-8"))
    assert select_envelope_nodes(tree) == [], (
        "fixture sanity check failed: expected "
        "tests/fixtures/envelope/structural_toc_tree.json's top-level "
        "headings to match NONE of intro/abstract/conclusion, but "
        f"select_envelope_nodes returned a non-empty match: "
        f"{select_envelope_nodes(tree)!r}"
    )


def test_structural_toc_fixture_toc_page_is_skipped_from_the_prompt():
    """Fixture sanity check: the front-matter-region skip (#225) must sweep
    the fixture's "Contents" page -- the source's only literal chapter
    listing -- out of `compose_prompt`'s evidence, exactly the real-world
    precondition this issue's fix addresses. If the TOC page's marker still
    reached the prompt, this fixture would not be exercising the #227 gap:
    the model would have a real toc source to read after all."""
    tree = json.loads(STRUCTURAL_TOC_TREE_FIXTURE.read_text(encoding="utf-8"))
    evidence = compose_prompt(tree)
    assert TOC_PAGE_MARKER not in evidence, (
        f"expected the fixture's Contents-page marker {TOC_PAGE_MARKER!r} "
        f"to be ABSENT from compose_prompt's evidence (swept by the "
        f"front-matter-region skip, #225) -- its presence means this "
        f"fixture no longer reproduces the #227 precondition (the model "
        f"being handed no chapter-listing source at all).\n"
        f"Full composed evidence:\n{evidence}"
    )
    for heading in REAL_CHAPTER_HEADINGS:
        assert heading in evidence, (
            f"expected the fixture's real chapter heading {heading!r} to "
            f"reach compose_prompt's widened head-of-tree evidence (it "
            f"sits well within the slice cap, right after the "
            f"front-matter region) -- its absence would make this "
            f"fixture's own widen-path premise unsound.\n"
            f"Full composed evidence:\n{evidence}"
        )


def test_envelope_toc_reflects_real_chapters_not_the_stubbed_model_toc(clean_envelopes):
    # --- arrange: pre-place the hand-authored tree (no docling run paid,
    # and no live docling extraction is expected to reproduce this
    # hand-authored tree -- see tests/fixtures/envelope/_generate.py) ---
    _place_tree_fixture(STRUCTURAL_TOC_PDF, STRUCTURAL_TOC_TREE_FIXTURE)

    before_files = _existing_envelope_files()

    # --- act: run `axial envelope` with the `stub` LLM provider, whose
    # canned toc is fixed and unrelated to this fixture's real chapters
    # (module docstring, "Why the stub provider is sufficient") ---
    result = _run_envelope("stub", str(STRUCTURAL_TOC_PDF))

    _assert_not_argparse_fallback(result)

    assert result.returncode == 0, (
        f"expected exit code 0 for `axial envelope` on the structural-toc "
        f"fixture source with the stub LLM provider configured, got "
        f"{result.returncode}\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    after_files = _existing_envelope_files()
    new_files = after_files - before_files
    assert len(new_files) == 1, (
        f"expected exactly one new file under {ENVELOPES_DIR} after this "
        f"`axial envelope` run, got {len(new_files)}: {sorted(new_files)}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    envelope_path = next(iter(new_files))
    envelope = json.loads(envelope_path.read_text(encoding="utf-8"))

    assert "toc" in envelope, (
        f"expected the envelope at {envelope_path} to carry a `toc` field "
        f"(PRD §7.3), got keys: {sorted(envelope.keys())}"
    )
    toc = envelope["toc"]
    assert isinstance(toc, list) and len(toc) > 0, (
        f"expected envelope field `toc` to be a non-empty list, got "
        f"{toc!r} (full envelope: {envelope!r})"
    )

    # --- assertion 1: every one of the source's real chapter headings must
    # be present in `toc` (structurally derived from the tree) ---
    missing = [heading for heading in REAL_CHAPTER_HEADINGS if heading not in toc]
    assert not missing, (
        f"expected the written envelope's `toc` to contain every one of "
        f"this source's real top-level chapter headings "
        f"{REAL_CHAPTER_HEADINGS!r} (PRD §7.3: toc is the source's own "
        f"table of contents, derived structurally from the tree -- issue "
        f"#227), but {missing!r} {'is' if len(missing) == 1 else 'are'} "
        f"missing from the written toc {toc!r}. This means `toc` was "
        f"populated purely from the LLM/stub response instead of the "
        f"tree's own top-level chapter/section headings -- the fixture's "
        f"only literal chapter listing (its 'Contents' page) never even "
        f"reached the model (see "
        f"test_structural_toc_fixture_toc_page_is_skipped_from_the_prompt), "
        f"so a toc sourced from the model alone cannot correctly name "
        f"this source's real chapters.\nFull envelope: {envelope!r}"
    )

    # --- assertion 2: none of the stub's fixed, unrelated canned toc
    # entries may leak through -- guards against a toc that merely
    # concatenates the model's answer onto the real one, or that never
    # actually overrides the model's (wrong) answer at all ---
    leaked = [entry for entry in STUB_CANNED_TOC_ENTRIES if entry in toc]
    assert not leaked, (
        f"expected NONE of the stub LLM client's fixed, source-independent "
        f"canned `toc` entries {STUB_CANNED_TOC_ENTRIES!r} (src/axial/"
        f"llm.py's StubLLMClient, unrelated to this fixture's real "
        f"chapters by construction) to appear in the written envelope's "
        f"`toc`, but {leaked!r} did: {toc!r}. This means `toc` is still "
        f"(at least partly) the model's raw, structurally-ungrounded "
        f"answer rather than being derived from -- or at minimum "
        f"overridden by -- the tree's own top-level chapter headings "
        f"(issue #227, the real-world Tilly/Chouliaraki regression after "
        f"#225).\nFull envelope: {envelope!r}"
    )
