"""Outer acceptance test for issue #235 (envelope `toc` becomes a
hybrid TWO-SIGNAL structured reconstruction, superseding #231/#232's
verbatim-intersection salvage stack).

Locked behavioral contract (DEC-1) -- do not edit once committed red.

Given a source's cached structural tree
When  the structural-envelope pass composes its single once-per-source
      prompt and calls the model
Then  the model is handed exactly TWO signals read from the tree and
      nothing else -- Signal A, a front-matter-INCLUSIVE head-of-tree
      slice (so a printed table-of-contents page, when the source has
      one, survives into the prompt), and Signal B, the flattened list of
      the tree's detected top-level headings (`_toc_from_tree`) -- inside
      an explicit instruction to reconstruct the toc grounded ONLY in
      those two signals
And   the model's nested `{title, children[]}` answer becomes `toc`
      directly (no more post-hoc verbatim-intersection narrowing against
      Signal B, #231/#232's now-superseded mechanism)
And   the printed-TOC-page text that Signal A deliberately keeps stays
      OUT of the front-matter-skipped thesis/scope/stated_argument
      evidence the pass already assembles (#201/#216/#222/#224/#225,
      kept and untouched by this issue) -- the "dual role" resolution
      that also closes #229 with no router change
And   on reconstruction-failure validation, the pass falls back
      deterministically to the tree's own detected heading list
      (`_toc_from_tree`), reshaped into the same non-empty nested
      `{title, children[]}` list, so the non-empty guarantee never lapses

See specs/PRODUCT.md §7.3, the paragraph "Table of contents by two-signal
reconstruction" (added by #235's spec-mode amendment, commit 71ceaf7), and
§8 P0-3's toc-quality bullet: "The `toc` is a reconstructed nested
`{title, children[]}` hierarchy grounded only in two signals read from the
cached tree ... It stays a non-empty list, with a deterministic fallback
to the tree's detected heading list on reconstruction failure. The
printed-TOC page is kept out of the thesis evidence ... yet still
populates `toc` -- the dual-role resolution." Also §7.3's amended locked
shape sentence: `toc` is now "a non-empty list of `{title, children[]}`
objects, each object's `title` a non-empty string and its `children` a
list of strings (possibly empty)".

Why this test does NOT attempt to lock reconstruction QUALITY
-----------------------------------------------------------------------
Issue #235's own "Acceptance shape" list (Tilly compact and clean; Bayat/
Agamben's printed TOC fully recovered, not collapsed to one entry; Hall
real chapter titles, not contributor names; Zaum no `Index`/bibliography
apparatus) is a REAL-MODEL property -- the founder validated it in
throwaway experiments against `deepseek-v4-pro` (DEC-26), and it is
RE-CHECKED at corpus regen against the real cached trees, not provable by
a `stub`/`record` client that never actually reasons about prompt
content. Asserting reconstruction quality here would either be vacuous
(the stub/record clients return a fixed canned answer regardless of what
they were asked) or would require this outer test to embed a live paid
LLM call, which no other test in this suite does. This test instead locks
the MECHANICAL contract every stub/record run can prove deterministically
today: (1) the written envelope's `toc` validates against the new nested
shape; (2) both signals -- and only a two-signals-only grounding
instruction -- reach the ONE prompt the pass sends; (3) the dual-role
split (printed-TOC marker in, thesis evidence still without it); (4) the
deterministic nested fallback on reconstruction failure. Corpus-quality
regen against Tilly/Bayat/Agamben/Hall/Zaum is a separate, real-model
step outside this test's reach (issue #235, "Rollout").

Why the stub's CURRENT canned `toc` will need to change (not this test)
-----------------------------------------------------------------------
`StubLLMClient._CANNED_RESPONSE`'s `toc` value is, as of this commit,
still the OLD flat `["Introduction", "Comparative Cases", "Conclusion"]`
(src/axial/llm.py) -- a leftover from before #235. This test never
depends on that value's specific CONTENTS anywhere; it only asserts the
CONTRACT (shape, both signals, one call, dual role, fallback). The
implementer updates the stub's canned response to the new nested shape as
part of greening this test -- that update is implementation work, not a
test-authoring concern.

Seam decision 1 -- three fixture-driven observations, choosing `stub` vs
`record` per what each needs to prove
-----------------------------------------------------------------------
- The WRITTEN-ENVELOPE nested-shape observation (test A) and the
  deterministic-fallback observation (test D) need a real WRITTEN
  envelope to inspect -- `stub` (test A, via the CLI subprocess, same
  style as every `stub`-driven test in this suite) and a custom
  in-process fake client (test D, `run_envelope(client=...)`, the same
  direct-injection seam #231's own now-retired test used) respectively.
- The PROMPT-SHAPE observations (tests B and C) need to see the actual
  assembled prompt, not just the written output -- `record`
  (`AXIAL_LLM_PROVIDER=record` + `AXIAL_LLM_RECORD_PATH`), the same
  seam tests/ingestion/test_envelope_structural_grounding.py and
  tests/ingestion/test_envelope_router_prose_filter.py already lock (see
  those tests' own module docstrings, seam decision 1, for the full
  rationale -- reused verbatim here, no new capture mechanism invented).

Seam decision 2 -- fixtures REUSED verbatim from the two retired tests,
not reinvented
-----------------------------------------------------------------------
tests/fixtures/envelope/llm_toc_selection_paper.pdf (+
llm_toc_selection_tree.json, issue #231's own fixture) and
tests/fixtures/envelope/structural_toc_paper.pdf (+
structural_toc_tree.json, issue #227's own fixture) are NOT deleted by
this issue -- only the three TEST FILES that exercised the now-superseded
mechanism are retired (module docstring's own list, and see git history).
Both fixture trees remain exactly the right shape for this issue's own
contract:

- llm_toc_selection_tree.json's ELEVEN flattened top-level `section_header`
  headings (four genuine chapters, four subsection-style headings, one
  OCR-garble fragment, one mislabelled body sentence, one appendix
  heading) are precisely Signal B's own target shape -- "docling has
  flattened the heading hierarchy into one `section_header` level, mixing
  genuine chapter titles with subsection headings, OCR-garble fragments,
  and body sentences mislabelled as headings" (§7.3). Test B uses this
  fixture to prove every one of the eleven reaches the model as Signal B
  -- the reconstruction, not code-side filtering, is now responsible for
  excluding the noise (the #231/#232 salvage-stack removal this issue's
  own scope names explicitly).
- structural_toc_tree.json's front-matter region -- title page, author
  line, copyright/ISBN block, "All rights reserved" boilerplate, and a
  short "Contents" page listing the source's three real chapters, itself
  carrying a distinctive "Halvorne-6 pagination ledger" marker -- followed
  by three real `section_header` chapters, is precisely the dual-role
  shape #235/#229 exists to fix: a printed TOC page sitting INSIDE the
  region the existing (kept, unchanged) front-matter-skip machinery
  sweeps out of thesis evidence. Tests C's own two fixture-sanity checks
  below re-verify this fixture's shape directly (its own preconditions
  do not depend on anything #235 changes).

Neither fixture's PDF is expected to reproduce its tree via a live
docling extraction (same precedent as every hand-authored tree fixture in
this suite, e.g. router_prose_filter_paper_tree.json) -- each PDF exists
only so `axial.intake.intake`'s text-layer probe passes and
`axial.envelope.compute_source_id` has real file bytes to hash. The
hand-authored tree is pre-placed directly at `data/trees/<source_id>.json`
(`_place_tree_fixture`, mirroring every other envelope acceptance test's
helper of the same name).

Seam decision 3 -- the "two-signals-only grounding" assertion is on
required SEMANTIC CONTENT, not one locked sentence
-----------------------------------------------------------------------
Mirroring tests/ingestion/test_envelope_structural_grounding.py's own
seam decision 3: PRD §7.3 states the toc-reconstruction grounding as
"grounded in exactly two signals ... and nothing else" and "the prompt
instructs the model to use ONLY the two supplied signals" -- a MEANING,
not one exact wording. Test B checks, via flexible case-insensitive
regex, that the prompt (a) mentions "two ... signal(s)" together, (b)
carries an explicit ONLY-style restriction near "signal(s)", and (c)
mentions reconstruction of the toc (some form of "reconstruct") -- three
independent, non-tautological checks, none of which today's
`_PROMPT_TEMPLATE`/`_TOC_CANDIDATES_BLOCK` text satisfies (today's prompt
never uses the words "two signals" or "reconstruct" anywhere), so this is
a genuine red today, not a wording accident.

Seam decision 4 -- the dual-role assertion combines a black-box positive
(the `record` seam) with a private-function negative control
-----------------------------------------------------------------------
Proving "the printed-TOC-page marker reaches the model" is a genuine
black-box observable via the `record` seam (test C, assertion 1) -- it is
what makes this test RED today, since no Signal A exists yet and the
marker never reaches the prompt through any channel today (verified
directly below as a fixture-sanity re-check, mirroring the now-retired
test_envelope_structural_toc.py's own equivalent check). Proving "the
marker is NOT part of the thesis-evidence assembly" cannot be observed
from a `stub`/`record` client's own fixed canned answer (it never
reasons about what it was fed) -- the only way to pin this half of the
contract is to call the EXACT machinery issue #235 itself names as KEPT
and UNTOUCHED ("the entire front-matter-region-skip / evidence-floor /
bibliography-aggregate machinery (#201/#216/#222/#224/#225) ... still
grounds thesis/scope/stated_argument. Orthogonal to toc; untouched")
directly: `axial.envelope._head_of_tree_lines`, referenced by name via
`getattr` (mirroring test_envelope_toc_candidates_bound.py's own
`_TOC_CANDIDATES_MAX` precedent) rather than a hardcoded assumption, so a
missing/renamed function fails with a clean, legible message instead of a
bare `AttributeError`. This is a deliberate, spec-anchored exception to
"assert the public seam, not internals": the issue's own text makes this
specific private function part of the locked, unchanged behavioral
contract, not an accidental implementation detail. Honest limitation: if
the implementer legitimately renames this function while faithfully
preserving front-matter-skip behavior for thesis evidence, this one
sub-assertion needs a narrow follow-up rename (not a weakening of what it
proves).

Test hygiene: subprocess/CLI outer tests in the same style as
tests/ingestion/test_envelope.py, using a `clean_envelopes` fixture of the
same name/shape (any envelope file a test causes to appear is removed in
teardown), the shared content-snapshot-based
`_isolate_persisted_tree_and_envelope_state` autouse fixture in
tests/conftest.py for `data/trees/` isolation, and `tmp_path` for the
`record` provider's output file and for test D's in-process
`envelopes_dir` override.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import axial.envelope as envelope_module
from axial.envelope import compute_source_id, run_envelope, select_envelope_nodes

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "envelope"
ENVELOPES_DIR = REPO_ROOT / "data" / "envelopes"
TREES_DIR = REPO_ROOT / "data" / "trees"

# --- Reused fixtures (issue #235 module docstring, seam decision 2) --------

STRUCTURAL_TOC_PDF = FIXTURES_DIR / "structural_toc_paper.pdf"
STRUCTURAL_TOC_TREE_FIXTURE = FIXTURES_DIR / "structural_toc_tree.json"

LLM_TOC_PDF = FIXTURES_DIR / "llm_toc_selection_paper.pdf"
LLM_TOC_TREE_FIXTURE = FIXTURES_DIR / "llm_toc_selection_tree.json"

PROVIDER_ENV_VAR = "AXIAL_LLM_PROVIDER"
RECORD_PATH_ENV_VAR = "AXIAL_LLM_RECORD_PATH"

# structural_toc_tree.json's three genuine top-level chapter headings
# (verbatim node `text`), in tree order.
STRUCTURAL_TOC_REAL_CHAPTERS = (
    "Chapter One: The Onset of Contention",
    "Chapter Two: Escalation Dynamics",
    "Chapter Three: Settlement and Aftermath",
)

# The distinctive marker living ONLY on structural_toc_tree.json's
# "Contents" page (top-level child index 4) -- the source's only literal
# printed chapter LISTING, sitting inside the front-matter region the
# existing (kept, unchanged) front-matter-skip machinery sweeps out of
# thesis evidence.
TOC_PAGE_MARKER = "Halvorne-6 pagination ledger"

# llm_toc_selection_tree.json's eleven flattened top-level `section_header`
# headings, in tree order -- Signal B's own target shape (module docstring,
# seam decision 2): four genuine chapters, four subsection-style headings,
# one OCR-garble fragment, one mislabelled body sentence, one appendix
# heading.
LLM_TOC_ALL_HEADINGS = (
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

# argparse's fallback error for an as-yet-nonexistent subcommand/provider --
# reused verbatim from every other envelope acceptance test in this suite.
ARGPARSE_FALLBACK_MARKERS = (
    "invalid choice",
    "unrecognized arguments",
)

# Two-signals-only grounding language (module docstring, seam decision 3):
# flexible, meaning-based, case-insensitive checks -- never one locked
# sentence.
_TWO_SIGNALS_RE = re.compile(r"\btwo\b(?:\s+\S+){0,6}?\s+signals?\b", re.IGNORECASE)
_ONLY_SIGNALS_RE = re.compile(r"\bonly\b(?:\s+\S+){0,10}?\s+signals?\b", re.IGNORECASE)
_RECONSTRUCT_RE = re.compile(r"\breconstruct", re.IGNORECASE)


def _run_envelope(
    provider: str, source: Path, record_path: Path | None = None
) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env[PROVIDER_ENV_VAR] = provider
    if record_path is not None:
        env[RECORD_PATH_ENV_VAR] = str(record_path)
    return subprocess.run(
        ["uv", "run", "axial", "envelope", str(source)],
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
            f"subcommand or the configured provider does not exist yet or "
            f"was never reached:\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )


def _existing_envelope_files() -> set[Path]:
    if not ENVELOPES_DIR.exists():
        return set()
    return set(ENVELOPES_DIR.glob("*.json"))


def _place_tree_fixture(source_pdf: Path, tree_fixture_path: Path) -> Path:
    """Pre-place a hand-authored tree fixture at data/trees/<source_id>.json
    (mirrors every other envelope acceptance test's helper of the same
    name)."""
    source_id = compute_source_id(source_pdf)
    tree_path = TREES_DIR / f"{source_id}.json"
    tree_path.parent.mkdir(parents=True, exist_ok=True)
    tree_path.write_bytes(tree_fixture_path.read_bytes())
    return tree_path


def _read_recorded_prompts(record_path: Path) -> list[str]:
    """Parse `AXIAL_LLM_RECORD_PATH`'s content: one JSON-encoded prompt
    string per line (RecordLLMClient's own contract, src/axial/llm.py)."""
    if not record_path.exists():
        return []
    prompts = []
    for line in record_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        prompt = json.loads(line)
        assert isinstance(prompt, str), (
            f"expected {record_path} to hold one JSON-encoded prompt string "
            f"per line (RecordLLMClient's own contract), got a "
            f"{type(prompt).__name__}: {prompt!r}"
        )
        prompts.append(prompt)
    return prompts


def _assert_valid_nested_toc(toc) -> None:
    """PRD §7.3's amended locked shape: `toc` is a non-empty list of
    `{title, children[]}` objects, each `title` a non-empty string and each
    `children` a (possibly empty) list of strings -- one level of nesting,
    never deeper (§7.3: "parts hold chapters and chapters hold sections",
    but the wire shape itself is flat objects with a string-list
    `children`, not further nested dicts)."""
    assert isinstance(toc, list) and len(toc) > 0, (
        f"expected envelope field `toc` to be a non-empty list (PRD §7.3), got {toc!r}"
    )
    for entry in toc:
        assert isinstance(entry, dict), (
            f"expected every `toc` entry to be a `{{title, children[]}}` "
            f"object (PRD §7.3's #235 amendment: 'toc is a non-empty list "
            f"of {{title, children[]}} objects'), but found a "
            f"{type(entry).__name__}: {entry!r} -- this means `toc` is "
            f"still the OLD flat list-of-strings shape.\nFull toc: {toc!r}"
        )
        title = entry.get("title")
        assert isinstance(title, str) and title.strip(), (
            f"expected every `toc` entry's `title` to be a non-empty "
            f"string, got {title!r} in entry {entry!r}.\nFull toc: {toc!r}"
        )
        children = entry.get("children")
        assert isinstance(children, list), (
            f"expected every `toc` entry's `children` to be a list "
            f"(possibly empty), got {children!r} in entry {entry!r}.\n"
            f"Full toc: {toc!r}"
        )
        for child in children:
            assert isinstance(child, str), (
                f"expected every `children` entry to be a string, got a "
                f"{type(child).__name__}: {child!r} in entry {entry!r}.\n"
                f"Full toc: {toc!r}"
            )


def _flatten_toc_strings(toc) -> list[str]:
    """Every string this nested `toc` carries -- each entry's `title` plus
    every one of its `children` -- flattened into one list, tolerant of
    either the new nested shape or (defensively) the old flat shape. Used
    only to check "did some real detected heading survive the fallback",
    never to pin the fallback's exact nesting choice."""
    collected: list[str] = []
    for entry in toc:
        if isinstance(entry, dict):
            title = entry.get("title")
            if isinstance(title, str):
                collected.append(title)
            for child in entry.get("children") or []:
                if isinstance(child, str):
                    collected.append(child)
        elif isinstance(entry, str):
            collected.append(entry)
    return collected


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


# --- Fixture sanity checks (both fixtures unaffected by anything #235
# changes -- re-verified directly, mirroring every other envelope
# acceptance test's own sanity-check precedent) --------------------------


def test_structural_toc_fixture_matches_no_envelope_heading():
    tree = json.loads(STRUCTURAL_TOC_TREE_FIXTURE.read_text(encoding="utf-8"))
    assert select_envelope_nodes(tree) == [], (
        "fixture sanity check failed: expected "
        "tests/fixtures/envelope/structural_toc_tree.json's top-level "
        "headings to match NONE of intro/abstract/conclusion, but "
        f"select_envelope_nodes returned a non-empty match: "
        f"{select_envelope_nodes(tree)!r}"
    )


def test_llm_toc_selection_fixture_matches_no_envelope_heading():
    tree = json.loads(LLM_TOC_TREE_FIXTURE.read_text(encoding="utf-8"))
    assert select_envelope_nodes(tree) == [], (
        "fixture sanity check failed: expected "
        "tests/fixtures/envelope/llm_toc_selection_tree.json's top-level "
        "headings to match NONE of intro/abstract/conclusion, but "
        f"select_envelope_nodes returned a non-empty match: "
        f"{select_envelope_nodes(tree)!r}"
    )


def test_structural_toc_fixture_toc_page_marker_is_not_signal_b():
    """Fixture sanity check: the TOC-page marker lives on a `text`-labelled
    node, not a `section_header` -- so it can never reach the model via
    Signal B (`_toc_from_tree`, unaffected by front matter). The ONLY
    channel that can ever carry it into the prompt is the NEW
    front-matter-inclusive Signal A this issue adds -- confirming test C's
    own premise that the marker's presence in the recorded prompt is not
    explainable by Signal B alone."""
    tree = json.loads(STRUCTURAL_TOC_TREE_FIXTURE.read_text(encoding="utf-8"))
    structural_toc = envelope_module._toc_from_tree(tree)
    assert TOC_PAGE_MARKER not in "\n".join(structural_toc), (
        f"expected {TOC_PAGE_MARKER!r} to be absent from "
        f"_toc_from_tree(tree)'s output {structural_toc!r} -- its presence "
        f"would mean the marker lives on a `section_header` node (Signal "
        f"B), undermining this fixture's own premise that the marker can "
        f"only reach the model via the NEW front-matter-inclusive Signal A"
    )


# --- Test A: nested shape produced & validated (stub) -----------------------


def test_envelope_toc_is_nested_shape_with_stub_provider(clean_envelopes):
    """The written envelope's `toc` validates against PRD §7.3's amended
    locked shape -- a non-empty list of `{title, children[]}` objects --
    regardless of what any one LLM provider happens to answer. Uses `stub`
    (module docstring, seam decision 1): a real `axial envelope` CLI run,
    same style as every other `stub`-driven envelope acceptance test."""
    _place_tree_fixture(STRUCTURAL_TOC_PDF, STRUCTURAL_TOC_TREE_FIXTURE)

    before_files = _existing_envelope_files()
    result = _run_envelope("stub", STRUCTURAL_TOC_PDF)
    _assert_not_argparse_fallback(result)

    assert result.returncode == 0, (
        f"expected exit code 0 for `axial envelope` on the structural-toc "
        f"fixture source with the `stub` LLM provider configured, got "
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
    _assert_valid_nested_toc(envelope["toc"])


# --- Test B: both signals present in ONE prompt, grounded (record) ----------


def test_envelope_prompt_carries_both_signals_and_two_signal_grounding(clean_envelopes, tmp_path):
    """The single recorded prompt carries Signal B's detected headings (the
    fixture's full flattened eleven-heading dump, noise included -- the
    reconstruction, not code-side filtering, now excludes the noise) AND a
    two-signals-only grounding instruction (module docstring, seam decision
    3), and exactly ONE prompt is recorded for the run (PRD §5: one API
    call per source)."""
    _place_tree_fixture(LLM_TOC_PDF, LLM_TOC_TREE_FIXTURE)

    record_path = tmp_path / "envelope_prompts.jsonl"
    result = _run_envelope("record", LLM_TOC_PDF, record_path)
    _assert_not_argparse_fallback(result)

    assert result.returncode == 0, (
        f"expected exit code 0 for `axial envelope` on the llm-toc-selection "
        f"fixture source with the `record` LLM provider configured, got "
        f"{result.returncode}\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    prompts = _read_recorded_prompts(record_path)
    assert len(prompts) >= 1, (
        f"expected at least one prompt recorded to {record_path} -- a zero "
        f"count means the envelope pass never actually called the LLM, "
        f"making every assertion below vacuous.\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    assert len(prompts) == 1, (
        f"expected exactly ONE recorded prompt for a single `axial "
        f"envelope` run (PRD §5: 'One API call per source' -- #235 folds "
        f"toc reconstruction into this SAME call rather than a second "
        f"one), got {len(prompts)}: {prompts!r}"
    )
    prompt = prompts[0]

    # --- assertion 1: Signal B -- every one of the fixture's eleven
    # flattened top-level headings (noise included) reaches the model ---
    missing_headings = [h for h in LLM_TOC_ALL_HEADINGS if h not in prompt]
    assert not missing_headings, (
        f"expected every one of this fixture's eleven flattened top-level "
        f"headings (Signal B, PRD §7.3: 'the flattened list of the tree's "
        f"detected top-level headings') to appear in the single recorded "
        f"prompt, but {missing_headings!r} did not. This means Signal B "
        f"never reached the model, so the reconstruction has no real "
        f"heading vocabulary to prefer/exclude from.\nFull prompt:\n{prompt}"
    )

    # --- assertion 2: two-signals-only grounding instruction (module
    # docstring, seam decision 3 -- three independent, meaning-based
    # checks) ---
    assert _TWO_SIGNALS_RE.search(prompt), (
        f"expected the prompt to mention reconstructing the toc from "
        f"exactly TWO signals (PRD §7.3: 'grounded in exactly two signals "
        f"read from the cached structural tree and nothing else'), but no "
        f"'two ... signal(s)' phrasing was found.\nFull prompt:\n{prompt}"
    )
    assert _ONLY_SIGNALS_RE.search(prompt), (
        f"expected the prompt to explicitly restrict the reconstruction to "
        f"ONLY the two supplied signals (PRD §7.3, 'Grounding is by "
        f"construction ... the prompt instructs the model to use ONLY the "
        f"two supplied signals'), but no 'only ... signal(s)' restriction "
        f"language was found.\nFull prompt:\n{prompt}"
    )
    assert _RECONSTRUCT_RE.search(prompt), (
        f"expected the prompt to instruct the model to RECONSTRUCT the toc "
        f"(PRD §7.3: 'the model reconstructs the source's real table of "
        f"contents'), not merely select or dump headings, but no form of "
        f"'reconstruct' was found.\nFull prompt:\n{prompt}"
    )


# --- Test C: dual-role slice (record + kept-machinery negative control) -----


def test_envelope_toc_page_marker_reaches_prompt_but_not_thesis_evidence(clean_envelopes, tmp_path):
    """The dual-role resolution (PRD §7.3, #229): the printed-TOC-page
    marker must reach the model (via the NEW front-matter-inclusive Signal
    A) while staying OUT of the thesis/scope/stated_argument evidence (the
    KEPT, unchanged front-matter-skip machinery, module docstring seam
    decision 4)."""
    tree = json.loads(STRUCTURAL_TOC_TREE_FIXTURE.read_text(encoding="utf-8"))
    _place_tree_fixture(STRUCTURAL_TOC_PDF, STRUCTURAL_TOC_TREE_FIXTURE)

    record_path = tmp_path / "envelope_prompts.jsonl"
    result = _run_envelope("record", STRUCTURAL_TOC_PDF, record_path)
    _assert_not_argparse_fallback(result)

    assert result.returncode == 0, (
        f"expected exit code 0 for `axial envelope` on the structural-toc "
        f"fixture source with the `record` LLM provider configured, got "
        f"{result.returncode}\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    prompts = _read_recorded_prompts(record_path)
    assert len(prompts) >= 1, (
        f"expected at least one prompt recorded to {record_path} -- a zero "
        f"count means the envelope pass never actually called the LLM, "
        f"making the assertions below vacuous.\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    assert len(prompts) == 1, (
        f"expected exactly ONE recorded prompt for a single `axial "
        f"envelope` run (PRD §5: 'One API call per source'), got "
        f"{len(prompts)}: {prompts!r}"
    )
    prompt = prompts[0]

    # --- assertion 1 (the RED-making assertion): the printed-TOC-page
    # marker reaches the model -- today it reaches NO part of the prompt at
    # all (the marker sits inside the front-matter region, which the
    # existing skip sweeps whole, and it is not a `section_header` node so
    # Signal B never carries it either -- test_structural_toc_fixture_
    # toc_page_marker_is_not_signal_b above). Only a NEW front-matter-
    # INCLUSIVE Signal A can ever put it in the prompt. ---
    assert TOC_PAGE_MARKER in prompt, (
        f"expected the printed-TOC-page marker {TOC_PAGE_MARKER!r} (from "
        f"tests/fixtures/envelope/structural_toc_tree.json's 'Contents' "
        f"page, sitting inside the leading front-matter region) to reach "
        f"the model via Signal A (PRD §7.3: 'Signal A is the source's "
        f"opening pages, read as a front-matter-inclusive head-of-tree "
        f"slice: it deliberately keeps the printed table-of-contents page "
        f"when the source prints one'), but it does not appear anywhere "
        f"in the single recorded prompt -- Signal A does not exist yet.\n"
        f"Full prompt:\n{prompt}"
    )

    # --- assertion 2 (stable control, holds both before and after the fix
    # -- module docstring, seam decision 4): the marker is still excluded
    # from the KEPT, unchanged thesis-evidence assembly ---
    head_of_tree_fn = getattr(envelope_module, "_head_of_tree_lines", None)
    assert head_of_tree_fn is not None, (
        "expected axial.envelope to still define `_head_of_tree_lines` "
        "(PRD §7.3/#235: 'the entire front-matter-region-skip / "
        "evidence-floor / bibliography-aggregate machinery ... still "
        "grounds thesis/scope/stated_argument. Orthogonal to toc; "
        "untouched') -- it does not exist, so this test cannot verify the "
        "dual-role split's thesis-evidence half. If the implementer "
        "legitimately renamed this function while faithfully preserving "
        "its front-matter-skip behavior, this assertion needs a narrow "
        "follow-up rename."
    )
    thesis_evidence_lines = head_of_tree_fn(tree)
    thesis_evidence = "\n".join(thesis_evidence_lines)
    assert TOC_PAGE_MARKER not in thesis_evidence, (
        f"expected the printed-TOC-page marker {TOC_PAGE_MARKER!r} to stay "
        f"OUT of the thesis/scope/stated_argument evidence (PRD §7.3: "
        f"'the printed TOC page is noise for the thesis ... so it is kept "
        f"out of the thesis evidence and fed only to the toc "
        f"reconstruction'), but it appeared in "
        f"`_head_of_tree_lines(tree)`'s own output -- this is the KEPT, "
        f"unchanged machinery (#201/#216/#222/#224/#225), so its presence "
        f"here would mean this issue's own front-matter-skip contract "
        f"regressed, not merely that #235 isn't built yet.\n"
        f"Thesis evidence:\n{thesis_evidence}"
    )

    # --- sanity: the real chapters this fixture's evidence widen must
    # still carry (unaffected by anything #235 changes) ---
    missing_chapters = [h for h in STRUCTURAL_TOC_REAL_CHAPTERS if h not in thesis_evidence]
    assert not missing_chapters, (
        f"expected the fixture's real chapter headings "
        f"{STRUCTURAL_TOC_REAL_CHAPTERS!r} to still reach the thesis "
        f"evidence via the unchanged head-of-tree widen, but "
        f"{missing_chapters!r} did not -- this fixture's own widen-path "
        f"premise would be unsound.\nThesis evidence:\n{thesis_evidence}"
    )


# --- Test D: deterministic nested fallback on reconstruction failure --------


class _AlwaysEmptyTocLLMClient:
    """A small, purpose-built fake `LLMClient` (the same single-method
    `complete(self, prompt, pass_name=None) -> str` protocol every
    stub/record/real client in src/axial/llm.py implements, injected the
    same way #231's own now-retired test injected its fake client --
    `run_envelope`'s `client` parameter) that answers every call with a
    VALID thesis/scope/stated_argument but a persistently EMPTY `toc`, so
    every one of `complete_json`'s bounded re-ask attempts keeps failing
    toc validation -- the reconstruction-failure precondition PRD §7.3's
    fallback sentence describes ("If the reconstruction fails validation,
    the pass falls back deterministically to the tree's own detected
    heading list"). An empty list fails ANY reasonable non-empty/shape
    check, old or new, so this fixture stays valid regardless of the exact
    nested-shape validation the implementer writes."""

    def __init__(self) -> None:
        self.call_count = 0

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        self.call_count += 1
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
                "toc": [],
            }
        )


def test_envelope_deterministic_nested_fallback_on_reconstruction_failure(tmp_path):
    """When the model's toc answer never validates (module docstring,
    `_AlwaysEmptyTocLLMClient`), `run_envelope` must NOT raise -- it falls
    back deterministically to the tree's own detected heading list
    (`_toc_from_tree`), reshaped into the same non-empty nested
    `{title, children[]}` shape every other envelope must carry (PRD §7.3:
    'preserving the non-empty guarantee'). Today, with no fallback built,
    this raises `EnvelopeValidationError` once `complete_json`'s bounded
    re-ask budget exhausts -- a genuine red, not a wording accident."""
    _place_tree_fixture(LLM_TOC_PDF, LLM_TOC_TREE_FIXTURE)
    tree = json.loads(LLM_TOC_TREE_FIXTURE.read_text(encoding="utf-8"))

    client = _AlwaysEmptyTocLLMClient()
    envelopes_dir = tmp_path / "envelopes"

    envelope = run_envelope(LLM_TOC_PDF, client=client, envelopes_dir=envelopes_dir)

    assert client.call_count >= 1, (
        "expected the fake LLM client to have been called at least once by "
        "run_envelope -- zero calls means the envelope pass never reached "
        "any model at all, making the assertions below vacuous"
    )

    assert "toc" in envelope, (
        f"expected the written envelope to carry a `toc` field (PRD §7.3), "
        f"got keys: {sorted(envelope.keys())}"
    )
    _assert_valid_nested_toc(envelope["toc"])

    # --- the fallback must be DERIVED from the tree's own detected
    # headings (_toc_from_tree), not an arbitrary/empty placeholder ---
    structural_headings = envelope_module._toc_from_tree(tree)
    assert structural_headings, (
        "fixture sanity check failed: expected "
        "tests/fixtures/envelope/llm_toc_selection_tree.json to yield a "
        "non-empty _toc_from_tree(tree) result -- otherwise this test "
        "cannot distinguish a real fallback from an empty one"
    )
    fallback_strings = _flatten_toc_strings(envelope["toc"])
    missing = [h for h in structural_headings if h not in fallback_strings]
    assert not missing, (
        f"expected the deterministic fallback toc to be derived from the "
        f"tree's own detected heading list (PRD §7.3: 'falls back "
        f"deterministically to the tree's own detected heading list'), so "
        f"every one of {structural_headings!r} should appear (as a title "
        f"or a child) somewhere in the written envelope's `toc`, but "
        f"{missing!r} did not. Full toc: {envelope['toc']!r}"
    )
