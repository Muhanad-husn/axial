"""Outer acceptance test for issue #216 (envelope head-of-tree slice ignores
the §7.8 prose/artifact/apparatus router).

Locked behavioral contract (DEC-1) -- do not edit once committed red.

Given a source whose top-level structural-tree headings are all topic-titled
      (none matches "introduction"/"abstract"/"conclusion" -- the exact
      #201 precondition that makes `compose_prompt` widen to a head-of-tree
      slice, see tests/ingestion/test_envelope_structural_grounding.py)
And   the head-of-tree region contains BOTH a NON-PROSE block (a
      `document_index` node -- a TOC entry, §7.8 APPARATUS) carrying a
      distinctive "POISON" marker, AND a PROSE block (a `text` node, §7.8
      PROSE) carrying a distinctive "SIGNAL" marker
When  the user runs `axial envelope <source>` with the LLM provider
      configured to the `record` client
Then  the single recorded prompt MUST carry the PROSE SIGNAL marker (the
      evidence floor is still met from real prose, §7.3) AND MUST NOT carry
      the NON-PROSE POISON marker (the shared source router, §7.8, filtered
      the non-prose front matter out of the "substantive" slice).

See specs/PRODUCT.md §7.8 ("Source router") -- the single shared
classification (`axial.router.route_for`) that maps a structural `label` to
exactly one of PROSE / ARTIFACT / APPARATUS, so "no downstream pass ...
re-derives the prose/non-prose decision for itself" -- and §7.3 ("Structural
envelope")'s evidence-floor widening (the #201 fix this issue's gap sits
inside): "the input widens to a substantive head-of-tree slice: a bounded
prefix of the source's own prose, taken in tree order". The word "prose"
there is doing real work this test pins: today `_head_of_tree_lines` (and
`_matched_section_blocks`) collect every tree node's own `text` regardless
of its docling `label`, so a `document_index` (TOC), `table`, `caption`,
`footnote`, or `page_header`/`page_footer` block sitting ahead of the first
real prose is collected right alongside it, diluting the "substantive"
evidence with non-prose front matter the router (§7.8) already knows how to
recognize and exclude.

This test does NOT touch the #201 evidence-floor contract itself (that a
head-of-tree widen happens at all, and that it carries genuine source
prose) -- that is already locked, unweakened, by
tests/ingestion/test_envelope_structural_grounding.py, which this test
leaves entirely untouched and does not duplicate. This test instead pins
the NEXT layer: that the widened slice, once assembled, is filtered through
the router so only PROSE-routed blocks survive into it.

Seam decision 1 -- reuse of the #201 harness verbatim
-----------------------------------------------------------------------
Same `record` LLM-provider seam, same subprocess/CLI invocation style, same
`_place_tree_fixture`/`_read_recorded_prompts`/argparse-fallback-guard
helpers as tests/ingestion/test_envelope_structural_grounding.py -- no new
capture mechanism invented. See that test's own module docstring, seam
decision 1, for the full rationale (unchanged here).

Seam decision 2 -- the fixture: a hand-authored tree with one non-prose
block sitting ahead of the first prose
-----------------------------------------------------------------------
tests/fixtures/envelope/router_prose_filter_paper.pdf (+ its HAND-AUTHORED
tree fixture, router_prose_filter_paper_tree.json -- see
tests/fixtures/envelope/_generate.py for why this fixture's tree is
hand-authored rather than a committed real docling extraction, unlike
topic_titled_paper_tree.json) has the same topic-titled top-level-heading
shape as topic_titled_paper_tree.json ("Border Enforcement Regimes",
"Fiscal Extraction Networks", "Digital Surveillance Architecture" --
`select_envelope_nodes` matches nothing, asserted directly below as a
fixture sanity check), but with one addition: its VERY FIRST top-level tree
node, ahead of every section, is a `document_index` node (§7.8: TOC/index
routes to APPARATUS) whose text carries an invented, highly distinctive
marker phrase -- "Quillfeather-19 index locus" -- fabricated specifically
for this fixture and appearing nowhere else in this repository, in any
training corpus, or in the `record`/`stub` canned envelope response. The
first section's own prose (a `text`-labeled node, §7.8: routes to PROSE)
carries a second, independent marker -- "Draubourne-4 escrow directive".

Both markers sit well within `_HEAD_OF_TREE_SLICE_CHARS` (6000) of the tree
root, so today's unfiltered `_head_of_tree_lines` walk collects BOTH of them
into the widened slice (verified by running this test against today's
code -- the POISON assertion below is what fails, for the real behavioral
reason: no router filter exists yet on this path). Once the implementer
filters the head-of-tree walk (and the matched-section-block walk) through
`axial.router.route_for`, the `document_index` node routes to APPARATUS and
is dropped from the slice, while the `text`/`section_header` nodes route to
PROSE and remain -- the SIGNAL marker keeps meeting the evidence floor, and
the POISON marker no longer reaches the prompt. This is a genuine,
non-tautological, two-direction proof: a test that merely asserted the
SIGNAL marker's presence (mirroring #201 alone) would not distinguish "the
router filter exists" from "the router filter doesn't exist yet", and a
test that merely asserted the POISON marker's absence, on a fixture with no
real prose to fall back on, could pass vacuously with an empty or
near-empty prompt. Both assertions together are required to pin the actual
issue #216 behavior.

Test hygiene: same as tests/ingestion/test_envelope_structural_grounding.py
-- a subprocess/CLI outer test, `tmp_path` for the record-path output file,
and a `clean_envelopes` fixture mirroring that test's (and
tests/ingestion/test_envelope.py's) fixture of the same name.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from axial.envelope import compute_source_id, select_envelope_nodes

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "envelope"
ENVELOPES_DIR = REPO_ROOT / "data" / "envelopes"
TREES_DIR = REPO_ROOT / "data" / "trees"

ROUTER_FIXTURE_PDF = FIXTURES_DIR / "router_prose_filter_paper.pdf"
ROUTER_FIXTURE_TREE = FIXTURES_DIR / "router_prose_filter_paper_tree.json"

PROVIDER_ENV_VAR = "AXIAL_LLM_PROVIDER"
RECORD_PATH_ENV_VAR = "AXIAL_LLM_RECORD_PATH"

# The NON-PROSE marker: lives on a `document_index` (TOC) node -- §7.8
# APPARATUS -- sitting at the very head of the tree, ahead of every section.
# Fabricated specifically for this fixture; see module docstring, seam
# decision 2.
POISON_MARKER = "Quillfeather-19 index locus"

# The PROSE marker: lives on the first section's own `text`-labeled body
# node -- §7.8 PROSE. Independent of POISON_MARKER; see module docstring,
# seam decision 2.
SIGNAL_MARKER = "Draubourne-4 escrow directive"

# argparse's fallback error for an as-yet-nonexistent subcommand/provider --
# reused verbatim from tests/ingestion/test_envelope_structural_grounding.py's
# identical guard.
ARGPARSE_FALLBACK_MARKERS = (
    "invalid choice",
    "unrecognized arguments",
)


def _run_envelope(provider: str, source: Path, record_path: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env[PROVIDER_ENV_VAR] = provider
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
            f"subcommand or the `record` provider does not exist yet or was "
            f"never reached:\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )


def _existing_envelope_files() -> set[Path]:
    if not ENVELOPES_DIR.exists():
        return set()
    return set(ENVELOPES_DIR.glob("*.json"))


def _place_tree_fixture(source_pdf: Path, tree_fixture_path: Path) -> Path:
    """Pre-place the committed tree fixture at data/trees/<source_id>.json
    (mirrors tests/ingestion/test_envelope_structural_grounding.py's helper
    of the same name exactly)."""
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


@pytest.fixture
def clean_envelopes():
    """Mirrors tests/ingestion/test_envelope_structural_grounding.py's
    fixture of the same name: snapshot data/envelopes/*.json before the
    test and delete any file the test caused to appear."""
    before = _existing_envelope_files()
    yield
    after = _existing_envelope_files()
    for created in after - before:
        created.unlink()


def test_router_prose_filter_fixture_matches_no_envelope_heading():
    """Fixture sanity check (module docstring, seam decision 2): the
    heading heuristic the #201 evidence-floor widen falls back past must
    genuinely match nothing on this fixture, or the rest of this test would
    not actually be exercising the head-of-tree widen path at all."""
    tree = json.loads(ROUTER_FIXTURE_TREE.read_text(encoding="utf-8"))
    assert select_envelope_nodes(tree) == [], (
        "fixture sanity check failed: expected "
        "tests/fixtures/envelope/router_prose_filter_paper_tree.json's "
        "top-level headings to match NONE of intro/abstract/conclusion, but "
        f"select_envelope_nodes returned a non-empty match: "
        f"{select_envelope_nodes(tree)!r} -- this fixture no longer "
        "exercises the head-of-tree widen path issue #216 is written against"
    )


def test_envelope_head_of_tree_slice_keeps_prose_drops_non_prose(clean_envelopes, tmp_path):
    # --- arrange: pre-place the hand-authored tree fixture (no docling
    # run paid, and no live docling extraction is expected to reproduce
    # this hand-authored tree -- see tests/fixtures/envelope/_generate.py) ---
    _place_tree_fixture(ROUTER_FIXTURE_PDF, ROUTER_FIXTURE_TREE)

    record_path = tmp_path / "envelope_prompts.jsonl"

    # --- act: run `axial envelope` with the `record` provider ---
    result = _run_envelope("record", ROUTER_FIXTURE_PDF, record_path)

    _assert_not_argparse_fallback(result)

    assert result.returncode == 0, (
        f"expected exit code 0 for `axial envelope` on the router-prose-"
        f"filter fixture source with the `record` LLM provider configured, "
        f"got {result.returncode}\nstdout: {result.stdout!r}\n"
        f"stderr: {result.stderr!r}"
    )

    prompts = _read_recorded_prompts(record_path)
    assert len(prompts) >= 1, (
        f"expected at least one prompt recorded to {record_path} by the "
        f"`record` LLM provider for this `axial envelope` run -- a zero "
        f"count means the envelope pass never actually called the LLM, "
        f"making every assertion below vacuous.\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    # The envelope pass makes exactly one LLM call per source -- assert
    # that directly rather than silently picking prompts[0] and hiding a
    # surprise second call.
    assert len(prompts) == 1, (
        f"expected exactly ONE recorded prompt for a single `axial "
        f"envelope` run (PRD §5 stage 3: 'One API call per source'), got "
        f"{len(prompts)}: {prompts!r}"
    )
    prompt = prompts[0]

    # --- assertion 1: the evidence floor is still met from REAL PROSE
    # (§7.3's widen behavior must survive the router filter this issue
    # adds -- the fix must not accidentally widen the router filter into
    # dropping genuine prose too) ---
    assert SIGNAL_MARKER in prompt, (
        f"expected the envelope prompt to carry the distinctive PROSE "
        f"marker {SIGNAL_MARKER!r} from "
        f"tests/fixtures/envelope/router_prose_filter_paper_tree.json's "
        f"first section body (a `text`-labeled node -- §7.8 PROSE), even "
        f"after the router filters non-prose blocks out of the "
        f"head-of-tree slice (PRD §7.3, 'evidence floor on the input'; "
        f"§7.8, source router). This marker's absence would mean the "
        f"router filter over-corrected and dropped genuine prose too, "
        f"re-creating the #201 empty-evidence defect by a different "
        f"route.\nFull recorded prompt:\n{prompt}"
    )

    # --- assertion 2: non-prose front matter is filtered OUT (the actual
    # issue #216 behavior this test is written to pin) ---
    assert POISON_MARKER not in prompt, (
        f"expected the envelope prompt to NOT carry the distinctive "
        f"NON-PROSE marker {POISON_MARKER!r}, which lives on "
        f"tests/fixtures/envelope/router_prose_filter_paper_tree.json's "
        f"leading `document_index` node (a TOC entry -- §7.8 classifies "
        f"`document_index` as APPARATUS, never PROSE). Its presence means "
        f"the envelope pass's head-of-tree slice "
        f"(`axial.envelope._head_of_tree_lines` / `_matched_section_blocks`) "
        f"is still collecting every tree node's own text regardless of "
        f"its docling `label`, instead of filtering each block through "
        f"the shared source router (`axial.router.route_for`, §7.8) and "
        f"keeping only PROSE-routed blocks -- exactly the issue #216 gap: "
        f"'non-prose front matter ... can be pulled into the substantive "
        f"head-of-tree slice ... and dilute the evidence with non-prose "
        f"text'.\nFull recorded prompt:\n{prompt}"
    )
