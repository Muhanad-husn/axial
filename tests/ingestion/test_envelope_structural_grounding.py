"""Outer acceptance test for issue #201 (structural-envelope
anti-confabulation, "Remedy A").

Locked behavioral contract (DEC-1) -- do not edit once committed red.

Given a source whose top-level structural-tree headings are all titled by
      TOPIC (none matches "introduction"/"abstract"/"conclusion" -- a
      normal document shape, not a malformed one)
When  the user runs `axial envelope <source>` with the LLM provider
      configured to the `record` client
Then  the exact prompt handed to the LLM carries a distinctive, unguessable
      substring drawn verbatim from the source's own prose (the "evidence
      floor": the heading heuristic matched nothing, yet the pass still
      widened its input to a substantive head-of-tree slice instead of
      sending an empty/near-empty evidence block)
And   that same prompt carries the "grounded by construction" instruction:
      base thesis/scope/stated_argument only on the supplied source text,
      never on the title, the filename, or outside knowledge

See specs/PRODUCT.md 7.3 ("Structural envelope") -- specifically:
  - "Evidence floor on the input. ... an empty evidence block is exactly
    what lets the model free-associate a plausible-but-wrong thesis (#201;
    the observed defect summarized Agamben's State of Exception as an
    internet-governance paper). So when the heuristic selects little or no
    text, the input widens to a substantive head-of-tree slice: a bounded
    prefix of the source's own prose, taken in tree order ... The guarantee
    is an observable minimum-evidence property: the evidence assembled for
    the envelope call always carries substantive source text, never an
    empty or whitespace-only section block, for every source, including one
    whose top-level headings match none of intro/abstract/conclusion."
  - "Grounded by construction. The prompt instructs the model to base
    thesis, scope, and stated_argument only on the supplied source text,
    and explicitly not to infer from the title, the filename, or outside
    knowledge."
and specs/PRODUCT.md 8 P0-3 ("The extraction is grounded by construction:
the prompt instructs the model to base thesis/scope/stated_argument only on
the supplied source text, and not to infer from the title, filename, or
outside knowledge. Observable: the envelope prompt carries that grounding
instruction.") for the source of truth.

This test does NOT touch the shape contract (`{source_id, author, title,
date, thesis, toc[], scope, stated_argument}`, non-empty strings, non-empty
toc) -- that is already locked, unweakened, by
tests/ingestion/test_envelope.py, which this test leaves entirely untouched
and does not duplicate.

Seam decision 1 -- observing "what the model was actually asked" via the
EXISTING `record` provider (no new production seam required)
-----------------------------------------------------------------------
`src/axial/llm.py` already ships a third `AXIAL_LLM_PROVIDER` value beyond
`stub`/`explode`: `record` (`RecordLLMClient`). It answers exactly like
`stub` (so the run still completes normally and writes a real envelope) but
also appends every raw prompt it receives, JSON-encoded on its own line, to
the path named by `AXIAL_LLM_RECORD_PATH`. This is not a seam this test
invents -- it is the SAME mechanism already locked and exercised by
tests/ingestion/test_pipeline_rewire.py and tests/ingestion/test_vault_resume.py
for exactly this purpose ("makes an assembled prompt observable black-box
from a subprocess test", per src/axial/llm.py's own module docstring). This
test reuses it verbatim rather than inventing a second capture mechanism:
the ONE prompt recorded for this run's single `axial envelope` LLM call is
the full, real prompt string `compose_prompt`/`run_envelope` assembled and
sent, with no seam-induced distortion.

Seam decision 2 -- the fixture: a normal, topic-titled document, not a
contrived edge case
-----------------------------------------------------------------------
tests/fixtures/envelope/topic_titled_paper.pdf (+ its committed real tree
fixture, topic_titled_paper_tree.json -- see tests/fixtures/envelope/
_generate.py for the generation/regeneration recipe, mirroring
thesis_paper_tree.json's own recipe exactly) has three top-level sections
headed "Border Enforcement Regimes", "Fiscal Extraction Networks", and
"Digital Surveillance Architecture" -- ordinary topic-titled headings, the
completely normal shape of a monograph chapter or a report, and NOT a
malformed/degenerate document. None matches
`axial.envelope._ENVELOPE_HEADINGS` ("introduction"/"abstract"/"conclusion",
case-insensitive substring): `select_envelope_nodes` returns an empty list
for this tree (asserted directly below as a fixture sanity check, using the
same public function `axial.envelope.compose_prompt` already imports/calls
internally -- not a new assertion surface). Today, `compose_prompt` builds
its "Sections:" block only from `select_envelope_nodes`'s output, so an
empty match means an EMPTY evidence block reaches the model -- the exact
precondition of the #201 defect (a real, observed run summarized Agamben's
*State of Exception* as an internet-governance paper from an empty/near-
empty envelope prompt).

The fixture's first body paragraph carries an invented, highly distinctive
marker phrase -- "Kestrel-7 checkpoint protocol" and "threshold-lattice
mechanism" -- fabricated specifically for this fixture and appearing nowhere
else in this repository, in any training corpus, or in the `record`/`stub`
canned response. A model (or a `record`/`stub` provider, which never
reasons about the prompt at all) cannot free-associate this exact phrase
from the title "topic_titled_paper" or from outside knowledge. If the
recorded prompt contains it, real source text reached the model despite the
heading heuristic matching nothing; if the recorded prompt lacks it, no
substantive source text reached the model for this source -- the evidence
floor is unmet. This is a genuine, non-tautological proof in both
directions, mirroring the sentinel-string technique already locked in
tests/ingestion/test_pipeline_rewire.py's module docstring, seam decision 1.

Seam decision 3 -- the grounding-instruction assertion is on REQUIRED
SEMANTIC CONTENT, not one locked sentence
-----------------------------------------------------------------------
PRD 7.3 names four distinct elements of the grounding instruction: (a) the
extracted fields are based ONLY on the supplied source text; (b) NOT on the
title; (c) NOT on the filename; (d) NOT on outside knowledge. Locking one
exact sentence as the contract would let a future refactor's rewording break
a test that never actually cared about the wording -- so this test instead
asserts, independently and via flexible substring/regex matching (case-
insensitive), that all four elements are present somewhere in the prompt.
This pins the required MEANING (every element PRD 7.3 names, all four) while
leaving the implementer free to phrase the instruction however reads best,
exactly the "least-invasive seam" this issue's brief asked for. It is
deliberately not vacuous: today's `_PROMPT_TEMPLATE` in src/axial/envelope.py
contains none of these four elements, so this assertion fails for the
behavioral reason (the grounding instruction does not exist yet), not
because the marker wording is contrived to be unmatchable.

Test hygiene: this test is a subprocess/CLI outer test in the same style as
tests/ingestion/test_envelope.py -- no unit-level import of `compose_prompt`
except as a documented fixture sanity check (see seam decision 2) -- and
uses `tmp_path` for the record-path output file plus the shared
`clean_envelopes`/data/trees isolation the rest of this suite already
relies on (tests/conftest.py's autouse
`_isolate_persisted_tree_and_envelope_state` fixture; this test also uses
its own `clean_envelopes`-style teardown, mirroring
tests/ingestion/test_envelope.py's fixture of the same name, so a real
envelope file this test causes to appear is removed afterward).
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

TOPIC_TITLED_PDF = FIXTURES_DIR / "topic_titled_paper.pdf"
TOPIC_TITLED_TREE_FIXTURE = FIXTURES_DIR / "topic_titled_paper_tree.json"

PROVIDER_ENV_VAR = "AXIAL_LLM_PROVIDER"
RECORD_PATH_ENV_VAR = "AXIAL_LLM_RECORD_PATH"

# Distinctive marker text drawn verbatim from
# tests/fixtures/envelope/topic_titled_paper.pdf's own first body paragraph
# (see module docstring, seam decision 2). Fabricated specifically for this
# fixture -- not a real-world term a model could plausibly already know or
# guess from the title/filename alone.
EVIDENCE_MARKER = "Kestrel-7 checkpoint protocol"

# argparse's fallback error for an as-yet-nonexistent subcommand/provider --
# reused verbatim from tests/ingestion/test_envelope.py's identical guard.
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
    """Pre-place the committed REAL tree fixture at
    data/trees/<source_id>.json (mirrors tests/ingestion/test_envelope.py's
    helper of the same name exactly)."""
    source_id = compute_source_id(source_pdf)
    tree_path = TREES_DIR / f"{source_id}.json"
    tree_path.parent.mkdir(parents=True, exist_ok=True)
    tree_path.write_bytes(tree_fixture_path.read_bytes())
    return tree_path


# `axial envelope` runs `extract()`, which since issue #303 makes intake's
# own stage-1 holdings/title-page model call for a source that has not been
# judged yet -- so the `record` transcript of one envelope run legitimately
# carries two prompts. That call is not the envelope pass, and the
# assertions below (including "exactly one call per source", PRD §5 stage 3)
# are about the envelope pass, so it is filtered out of the transcript here.
_HOLDINGS_PROMPT_MARKER = "carries the complete work it names"


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
        if _HOLDINGS_PROMPT_MARKER in prompt:
            # Not an envelope-pass prompt: see _HOLDINGS_PROMPT_MARKER.
            continue
        prompts.append(prompt)
    return prompts


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


def test_topic_titled_fixture_matches_no_envelope_heading():
    """Fixture sanity check (module docstring, seam decision 2): the
    heading heuristic this issue's evidence-floor fix widens past must
    genuinely match nothing on this fixture, or the rest of this test would
    not actually be exercising the #201 gap at all."""
    tree = json.loads(TOPIC_TITLED_TREE_FIXTURE.read_text(encoding="utf-8"))
    assert select_envelope_nodes(tree) == [], (
        "fixture sanity check failed: expected "
        "tests/fixtures/envelope/topic_titled_paper_tree.json's top-level "
        "headings to match NONE of intro/abstract/conclusion, but "
        f"select_envelope_nodes returned a non-empty match: "
        f"{select_envelope_nodes(tree)!r} -- this fixture no longer "
        "exercises the #201 gap this test is written against"
    )


def test_envelope_evidence_floor_and_grounding_instruction_on_topic_titled_source(
    clean_envelopes, tmp_path
):
    # --- arrange: pre-place the real tree fixture (no docling run paid) ---
    _place_tree_fixture(TOPIC_TITLED_PDF, TOPIC_TITLED_TREE_FIXTURE)

    record_path = tmp_path / "envelope_prompts.jsonl"

    # --- act: run `axial envelope` with the `record` provider ---
    result = _run_envelope("record", TOPIC_TITLED_PDF, record_path)

    _assert_not_argparse_fallback(result)

    assert result.returncode == 0, (
        f"expected exit code 0 for `axial envelope` on a topic-titled "
        f"fixture source with the `record` LLM provider configured, got "
        f"{result.returncode}\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
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
        f"envelope` run (PRD 5 stage 3: 'One API call per source'), got "
        f"{len(prompts)}: {prompts!r}"
    )
    prompt = prompts[0]

    # --- assertion 1: evidence floor (PRD 7.3 "Evidence floor on the
    # input" / PRD 8 P0-3 "minimum-evidence property") ---
    assert EVIDENCE_MARKER in prompt, (
        f"expected the envelope prompt to carry the distinctive source-text "
        f"marker {EVIDENCE_MARKER!r} from "
        f"tests/fixtures/envelope/topic_titled_paper.pdf's own first body "
        f"paragraph, even though this source's top-level headings match "
        f"NONE of intro/abstract/conclusion (PRD 7.3, 'Evidence floor on "
        f"the input': 'the input widens to a substantive head-of-tree "
        f"slice ... the evidence assembled for the envelope call always "
        f"carries substantive source text, never an empty or whitespace-"
        f"only section block'). This marker's absence means the pass sent "
        f"the model an empty or near-empty evidence block for this source "
        f"-- exactly the #201 defect (a real run summarized Agamben's "
        f"*State of Exception* as an internet-governance paper from an "
        f"empty envelope prompt).\nFull recorded prompt:\n{prompt}"
    )

    # --- assertion 2: grounded by construction (PRD 7.3 / PRD 8 P0-3) ---
    # Four independent, flexible (case-insensitive) checks for the four
    # elements PRD 7.3 names explicitly -- see module docstring, seam
    # decision 3, for why this is content-based, not one locked sentence.
    lowered = prompt.lower()

    only_source_text = "only" in lowered and (
        "source text" in lowered or "supplied text" in lowered or "provided text" in lowered
    )
    assert only_source_text, (
        f"expected the envelope prompt to instruct the model to base its "
        f"answer ONLY on the supplied source text (PRD 7.3, 'Grounded by "
        f"construction': 'base thesis, scope, and stated_argument only on "
        f"the supplied source text'), found no such instruction.\n"
        f"Full recorded prompt:\n{prompt}"
    )

    not_from_title = "title" in lowered
    assert not_from_title, (
        f"expected the envelope prompt to explicitly instruct the model "
        f"NOT to infer from the title (PRD 7.3, 'Grounded by "
        f"construction'), found no mention of 'title' as an excluded "
        f"basis.\nFull recorded prompt:\n{prompt}"
    )

    not_from_filename = "filename" in lowered or "file name" in lowered
    assert not_from_filename, (
        f"expected the envelope prompt to explicitly instruct the model "
        f"NOT to infer from the filename (PRD 7.3, 'Grounded by "
        f"construction'), found no mention of 'filename' as an excluded "
        f"basis.\nFull recorded prompt:\n{prompt}"
    )

    not_from_outside_knowledge = "outside knowledge" in lowered or "prior knowledge" in lowered
    assert not_from_outside_knowledge, (
        f"expected the envelope prompt to explicitly instruct the model "
        f"NOT to infer from outside knowledge (PRD 7.3, 'Grounded by "
        f"construction': 'explicitly not to infer from the title, the "
        f"filename, or outside knowledge'), found no such instruction.\n"
        f"Full recorded prompt:\n{prompt}"
    )
