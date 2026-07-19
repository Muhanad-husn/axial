"""Outer acceptance test for issue #228 (envelope prompt: ground thesis on
the general argument, not an opening anecdote).

Locked behavioral contract (DEC-1) -- do not edit once committed red.

Given the envelope pass's `_PROMPT_TEMPLATE` (src/axial/envelope.py)
When  the user runs `axial envelope <source>` with the LLM provider
      configured to the `record` client
Then  the exact prompt handed to the LLM instructs the model to state the
      source's GENERAL / OVERALL argument, and explicitly NOT a specific
      illustrative example or opening anecdote

See specs/PRODUCT.md §7.3 ("Grounded by construction. The prompt instructs
the model to base thesis, scope, and stated_argument only on the supplied
source text ...") and §8 P0-3 ("the extraction is grounded by construction
... Observable: the envelope prompt carries that grounding instruction.")
for the source of truth. Issue #228 is an *implementation refinement* of
this existing mandate, not spec drift: "grounded by construction" already
requires the extracted fields to come only from the supplied text, but says
nothing about *which part* of that text the thesis should reflect. #228's
defect (observed on Tilly's *From Mobilization to Revolution*: the
regenerated envelope grounds its thesis on the opening 1765 poorhouse /
Stamp-Act vignette, not the book's mobilization -> collective-action ->
revolution argument) is "grounded-but-narrow" -- real text, wrong part --
distinct from #201's confabulation (ungrounded, invented text) and from
#222's bibliography-poisoning (grounded-but-shallow, no argument prose at
all). The fix this issue's brief proposes is a further directive in the
same prompt: state the GENERAL/OVERALL argument, not a specific illustrative
example or opening anecdote.

Why a deterministic prompt-content check, not a live Tilly regen
-----------------------------------------------------------------------
Issue #228's own "Acceptance shape" section asks for a live regenerate-and-
eyeball proof on Tilly (plus regression controls on Agamben/Bayat/
Chouliaraki/a born-digital source). That is real, paid, non-deterministic
LLM work the founder runs by hand once the fix lands -- it cannot be the
CI-gating outer contract, because a live-model thesis-quality judgment is
neither deterministic nor free, and re-running it on every test invocation
would be flaky-by-construction. The honest, deterministic, free contract
this test CAN lock is the one upstream cause #228's brief names directly:
"Prompt nudge: instruct the envelope pass to state the source's
general/overall argument ... File: src/axial/envelope.py --
_PROMPT_TEMPLATE." If the assembled prompt carries that instruction, the
model has been given what it needs to stop grounding on the anecdote; if it
doesn't, no live regen could possibly fix Tilly's thesis, because the
prompt never asked for anything else. This mirrors the exact seam already
locked by tests/ingestion/test_envelope_structural_grounding.py (#201) for
the same reason: that test does not judge the model's actual thesis text
either, it proves the prompt carries the instruction that makes a correct
thesis possible.

Seam decisions -- reused verbatim from
tests/ingestion/test_envelope_structural_grounding.py
-----------------------------------------------------------------------
This test invents no new production seam, no new fixture, and no new
capture mechanism. It reuses, unmodified:

  - the `record` LLM provider (`AXIAL_LLM_PROVIDER=record`,
    `AXIAL_LLM_RECORD_PATH=<path>`), the SAME mechanism already locked by
    tests/ingestion/test_envelope_structural_grounding.py,
    tests/ingestion/test_pipeline_rewire.py, and
    tests/ingestion/test_vault_resume.py;
  - the cheap, already-committed `topic_titled_paper.pdf` fixture and its
    real tree fixture `topic_titled_paper_tree.json` (no docling run, no
    LLM cost to construct evidence) -- the fixture choice is immaterial to
    this issue: the general-argument instruction this test asserts on is a
    fixed clause in `_PROMPT_TEMPLATE`, present or absent regardless of
    which source is envelope'd, so there is no reason to pay for a second
    fixture or to touch the real (large, copyrighted -- see repo
    convention: no book text committed) Tilly tree;
  - `_place_tree_fixture`, `_read_recorded_prompts`, and the
    argparse-fallback guard, copied verbatim from
    tests/ingestion/test_envelope_structural_grounding.py so this test's
    control flow is byte-for-byte the same shape as the locked #201 test it
    sits beside; this test does not alter, weaken, or duplicate that file's
    own assertions in any way.

The one addition beyond the #201 test is a THIRD assertion on the recorded
prompt (the #201 test's first two assertions -- the evidence-floor marker
and the four-part "grounded by construction" instruction -- are that test's
contract, not this one's, and are left untouched).

Seam decision -- the general-argument assertion is on REQUIRED MEANING,
not one locked sentence (mirrors #201's seam decision 3)
-----------------------------------------------------------------------
Issue #228's brief itself does not mandate exact wording -- it asks for "a
prompt nudge" -- so this test pins the required MEANING and leaves the
implementer free to phrase it. Two independent, flexible (case-insensitive)
keyword-set checks encode the two poles #228's brief names:

  (a) a positive instruction to prefer the GENERAL / OVERALL / MAIN /
      CENTRAL argument (or thesis/claim) -- e.g. "state the book's overall
      argument", "the general thesis", "the argument as a whole";
  (b) an explicit exclusion of a SPECIFIC illustrative example / opening
      anecdote / vignette -- e.g. "not a specific example", "not the
      opening anecdote", "not an illustrative vignette".

Both checks are small keyword-membership tests, not one exact string, so a
reasonable implementer rewording still passes. Verified by hand against
today's `_PROMPT_TEMPLATE` in src/axial/envelope.py: it contains neither
pole -- no occurrence of "general", "overall", "anecdote", "vignette", or
"illustrat" anywhere in the template -- so this assertion is non-vacuous,
proven by the actual subprocess run below failing on the genuine behavioral
reason (the instruction does not exist yet), not because the keyword sets
are contrived to be unmatchable by any reasonable phrasing. Deliberately NOT
locked as its own standing test: once the implementer adds the natural
instruction, the template WILL (and should) contain exactly these words
("state the book's overall argument, not an opening anecdote" is the most
natural phrasing #228's own brief suggests), so a permanent assertion that
today's template lacks them would flip to failing the moment the fix
lands -- a red-state precondition has no business being a green-state
requirement.

Test hygiene: subprocess/CLI outer test, same style as
tests/ingestion/test_envelope_structural_grounding.py and
tests/ingestion/test_envelope.py; uses `tmp_path` for the record-path
output and a `clean_envelopes`-style teardown so a real envelope file this
test causes to appear is removed afterward.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from axial.envelope import compute_source_id

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "envelope"
ENVELOPES_DIR = REPO_ROOT / "data" / "envelopes"
TREES_DIR = REPO_ROOT / "data" / "trees"

TOPIC_TITLED_PDF = FIXTURES_DIR / "topic_titled_paper.pdf"
TOPIC_TITLED_TREE_FIXTURE = FIXTURES_DIR / "topic_titled_paper_tree.json"

PROVIDER_ENV_VAR = "AXIAL_LLM_PROVIDER"
RECORD_PATH_ENV_VAR = "AXIAL_LLM_RECORD_PATH"

# argparse's fallback error for an as-yet-nonexistent subcommand/provider --
# reused verbatim from tests/ingestion/test_envelope_structural_grounding.py
# (itself reused from tests/ingestion/test_envelope.py).
ARGPARSE_FALLBACK_MARKERS = (
    "invalid choice",
    "unrecognized arguments",
)

# The two poles #228's brief names: (a) prefer the GENERAL/OVERALL argument,
# (b) exclude a SPECIFIC example/opening anecdote. Flexible keyword-set
# membership, not one locked sentence -- see module docstring.
GENERAL_ARGUMENT_SIGNALS = (
    "general argument",
    "overall argument",
    "main argument",
    "central argument",
    "general thesis",
    "overall thesis",
    "main thesis",
    "central thesis",
    "general claim",
    "overall claim",
    "argument as a whole",
    "argument overall",
    "book's overall",
    "source's overall",
    "overall thrust",
)

SPECIFIC_EXAMPLE_EXCLUSION_SIGNALS = (
    "specific example",
    "specific illustrative example",
    "illustrative example",
    "opening anecdote",
    "anecdote",
    "opening vignette",
    "vignette",
    "specific case",
    "specific instance",
    "illustrative anecdote",
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
    data/trees/<source_id>.json (mirrors
    tests/ingestion/test_envelope_structural_grounding.py's helper of the
    same name exactly)."""
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


def test_envelope_prompt_instructs_general_argument_not_opening_anecdote(clean_envelopes, tmp_path):
    # --- arrange: pre-place the real tree fixture (no docling run paid) ---
    _place_tree_fixture(TOPIC_TITLED_PDF, TOPIC_TITLED_TREE_FIXTURE)

    record_path = tmp_path / "envelope_prompts.jsonl"

    # --- act: run `axial envelope` with the `record` provider ---
    result = _run_envelope("record", TOPIC_TITLED_PDF, record_path)

    _assert_not_argparse_fallback(result)

    assert result.returncode == 0, (
        f"expected exit code 0 for `axial envelope` on a fixture source "
        f"with the `record` LLM provider configured, got "
        f"{result.returncode}\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    prompts = _read_recorded_prompts(record_path)
    assert len(prompts) == 1, (
        f"expected exactly ONE recorded prompt for a single `axial "
        f"envelope` run (PRD §5 stage 3: 'One API call per source'), got "
        f"{len(prompts)}: {prompts!r}"
    )
    prompt = prompts[0]
    lowered = prompt.lower()

    # --- assertion: the prompt carries #228's general-argument directive ---
    # Two independent poles, each a small flexible keyword-set membership
    # check (module docstring, "seam decision -- ... REQUIRED MEANING").
    general_argument_present = any(signal in lowered for signal in GENERAL_ARGUMENT_SIGNALS)
    assert general_argument_present, (
        f"expected the envelope prompt to instruct the model to state the "
        f"source's GENERAL/OVERALL argument (issue #228: 'instruct the "
        f"envelope pass to state the source's general/overall argument, "
        f"not a specific illustrative example or opening anecdote'), found "
        f"none of {GENERAL_ARGUMENT_SIGNALS!r} in the recorded prompt. "
        f"Without this instruction, a narrative-opening source (e.g. "
        f"Tilly's *From Mobilization to Revolution*) has no reason to stop "
        f"grounding its thesis on an opening historical anecdote instead of "
        f"the book's actual argument.\nFull recorded prompt:\n{prompt}"
    )

    specific_example_excluded = any(
        signal in lowered for signal in SPECIFIC_EXAMPLE_EXCLUSION_SIGNALS
    )
    assert specific_example_excluded, (
        f"expected the envelope prompt to explicitly instruct the model "
        f"NOT to ground the thesis on a specific illustrative example or "
        f"opening anecdote (issue #228), found none of "
        f"{SPECIFIC_EXAMPLE_EXCLUSION_SIGNALS!r} in the recorded prompt. "
        f"This is the exact #228 defect: 'grounded-but-narrow' -- real "
        f"source text, but the wrong part of it (an opening vignette) "
        f"rather than the book's general argument.\n"
        f"Full recorded prompt:\n{prompt}"
    )
