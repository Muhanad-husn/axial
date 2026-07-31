"""Inner unit tests for the stage-5 counter-position validator (issues #259
and #490, specs/PHASE-B.md §7.8, §7.9). Co-located under src/axial/validators/
per the repo's existing test layout (mirrors src/axial/validators/
test_attribution.py).

Covers the contested predicate's two D3 signals (`opposed_positions` from
what the notes say, `gather_disagreement` from a name the answer rests on),
the literal-naming rule that makes the first one worth anything, the
abstention and `[]` rules that keep it from manufacturing a disagreement,
signal persistence, the presence-or-disclosure check's four combinations,
release blocking, and the steelman-quality check's present-only/
zero-model-calls-otherwise property, distinct-pass_name/same-model guard and
non-blocking strawman verdict.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from axial.llm import ExplodingLLMClient
from axial.query.names import DISAGREEMENT_HEADING
from axial.validators.counter_position import (
    REASON_CONTESTED_WITHOUT_COUNTER_POSITION,
    SIGNAL_GATHER_DISAGREEMENT,
    SIGNAL_NAMES_OPPONENT,
    SIGNAL_OPPOSED_POSITIONS,
    VERDICT_STRAWMAN,
    CounterPositionCheckFailedError,
    SamePassModelError,
    validate_counter_position,
)

TILLY_CHUNK = "tilly-1978_001_intro_001"
SKOCPOL_CHUNK = "skocpol-1979_001_intro_001"
TILLY_CHUNK_2 = "tilly-1978_002_intro_001"
SILENT_CHUNK = "silent-1990_001_intro_001"

TILLY_AUTHOR = "Charles Tilly"
SKOCPOL_AUTHOR = "Theda Skocpol"


def _chunk_frontmatter(
    chunk_id: str,
    *,
    author: str,
    title: str,
    position_of: Any = "the author",
    arguing_against: Any = None,
    names: list[str] | None = None,
) -> dict[str, Any]:
    """A prose note in the shape `axial.materialize` writes today: source
    metadata plus the nested §7.15 interrogation answer block. No tag axis
    appears -- every one of them was deleted with the tag pass, which is why
    the contested predicate had to be re-based (D3)."""
    answers: dict[str, Any] = {
        "claim": f"Claim of {chunk_id}.",
        "move": "stating a mechanism",
        "position_of": position_of,
        "names": [{"name": name, "kind": "person"} for name in (names or [])],
    }
    if arguing_against is not None:
        answers["arguing_against"] = arguing_against
    return {
        "chunk_id": chunk_id,
        "section": "Synthetic Section",
        "chunk_text": f"SENTINEL: synthetic prose for {chunk_id}.",
        "source_meta": {
            "author": author,
            "title": title,
            "date": 1979,
            "thesis": "X",
            "scope": "Y",
        },
        "frame_version": "0.1",
        "answers": answers,
    }


def _write_chunk(vault_dir: Path, chunk_id: str, **kwargs: Any) -> None:
    prose_dir = vault_dir / "prose"
    prose_dir.mkdir(parents=True, exist_ok=True)
    frontmatter = _chunk_frontmatter(chunk_id, **kwargs)
    text = "---\n" + yaml.safe_dump(frontmatter, sort_keys=False) + "---\nBody.\n"
    (prose_dir / f"{chunk_id}.md").write_text(text, encoding="utf-8")


def _write_tilly(vault_dir: Path, chunk_id: str = TILLY_CHUNK, **overrides: Any) -> None:
    kwargs: dict[str, Any] = {
        "author": TILLY_AUTHOR,
        "title": "From Mobilization to Revolution",
        "arguing_against": ["Skocpol"],
        "names": ["Skocpol"],
    }
    kwargs.update(overrides)
    _write_chunk(vault_dir, chunk_id, **kwargs)


def _write_skocpol(vault_dir: Path, chunk_id: str = SKOCPOL_CHUNK, **overrides: Any) -> None:
    kwargs: dict[str, Any] = {
        "author": SKOCPOL_AUTHOR,
        "title": "States and Social Revolutions",
        "arguing_against": [],
        "names": ["Charles Tilly"],
    }
    kwargs.update(overrides)
    _write_chunk(vault_dir, chunk_id, **kwargs)


def _write_name_page(
    vault_dir: Path, name: str, *, member_ids: list[str], disagreement: str | None = None
) -> None:
    names_dir = vault_dir / "names"
    names_dir.mkdir(parents=True, exist_ok=True)
    frontmatter = {
        "name": name,
        "kind": "person",
        "aliases": [],
        "member_count": len(member_ids),
    }
    lines = ["**Member notes:**"]
    lines += [f"- [[{chunk_id}]] — An Author (1979): A claim." for chunk_id in member_ids]
    if disagreement:
        lines += ["", DISAGREEMENT_HEADING, "", disagreement]
    body = yaml.safe_dump(frontmatter, sort_keys=False)
    (names_dir / f"{name}.md").write_text(
        "---\n" + body + "---\n" + "\n".join(lines) + "\n", encoding="utf-8"
    )


@pytest.fixture
def vault_dir(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    (vault / "prose").mkdir(parents=True, exist_ok=True)
    (vault / "artifacts").mkdir(parents=True, exist_ok=True)
    return vault


@pytest.fixture
def names_dir(tmp_path: Path) -> Path:
    """Reconcile's alias map and index (§7.16) -- the ONLY tier the contested
    predicate resolves a surface through. "Skocpol" is an alias of "Theda
    Skocpol", so the literal-naming rule is exercised across a real alias
    hop, not string equality against a full author name."""
    names = tmp_path / "names"
    names.mkdir(parents=True, exist_ok=True)
    (names / "alias_map.json").write_text(
        json.dumps(
            {
                "nodes": [
                    {"canonical": SKOCPOL_AUTHOR, "kind": "person", "aliases": ["Skocpol"]},
                    {"canonical": TILLY_AUTHOR, "kind": "person", "aliases": ["Tilly"]},
                ]
            }
        ),
        encoding="utf-8",
    )
    (names / "index.json").write_text(
        json.dumps({"names": [SKOCPOL_AUTHOR, TILLY_AUTHOR]}), encoding="utf-8"
    )
    return names


def _grounds(*chunk_ids: str) -> list[dict[str, str]]:
    return [{"ref_type": "chunk", "ref_id": chunk_id} for chunk_id in chunk_ids]


def _claim(
    claim_id: str, *chunk_ids: str, kind: str = "a", names_touched: list[str] | None = None
) -> dict[str, Any]:
    return {
        "claim_id": claim_id,
        "text": f"Text for {claim_id}.",
        "kind": kind,
        "grounds": _grounds(*chunk_ids),
        "names_touched": names_touched or [],
    }


def _no_counter_position() -> dict[str, Any]:
    return {
        "present": False,
        "stance": None,
        "grounds": [],
        "corpus_one_sided": False,
        "one_sided_reason": None,
    }


def _failed_counter_position(
    reason: str = "counter-position generation call failed: boom",
) -> dict[str, Any]:
    return {
        "present": False,
        "stance": None,
        "grounds": [],
        "corpus_one_sided": False,
        "one_sided_reason": None,
        "failed": True,
        "failure_reason": reason,
    }


def _present_counter_position(
    *chunk_ids: str, stance: str = "The opposing school holds..."
) -> dict[str, Any]:
    return {
        "present": True,
        "stance": stance,
        "grounds": _grounds(*chunk_ids),
        "corpus_one_sided": False,
        "one_sided_reason": None,
    }


def _disclosed_one_sided(
    reason: str = "corpus carries no opposing school on this case",
) -> dict[str, Any]:
    return {
        "present": False,
        "stance": None,
        "grounds": [],
        "corpus_one_sided": True,
        "one_sided_reason": reason,
    }


def _record(
    claims: list[dict[str, Any]],
    counter_position: dict[str, Any],
    trajectory: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "claims": claims,
        "counter_position": counter_position,
        "trajectory": trajectory or [],
    }


def _contested(vault_dir: Path) -> list[dict[str, Any]]:
    """The canonical contested fixture: Tilly argues against Skocpol by
    name, Skocpol's note is in the same evidence set."""
    _write_tilly(vault_dir)
    _write_skocpol(vault_dir)
    return [_claim("c-1", TILLY_CHUNK, SKOCPOL_CHUNK)]


class FakeClient:
    """Minimal `LLMClient` test double, mirroring `test_attribution
    .FakeClient` exactly: `model_for_pass` answers from a caller-supplied
    per-pass mapping, `complete` answers a scripted JSON string, recording
    every `pass_name` it was called with."""

    def __init__(self, *, model_by_pass: dict[str, str], response: str = ""):
        self._model_by_pass = model_by_pass
        self._response = response
        self.calls: list[str | None] = []

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        self.calls.append(pass_name)
        return self._response

    def model_for_pass(self, pass_name: str | None = None) -> str:
        return self._model_by_pass.get(pass_name, "unmapped")

    def complete_with_tools(
        self, prompt: str, tools: list[dict[str, Any]], pass_name: str | None = None
    ) -> dict[str, Any] | None:
        raise NotImplementedError("the counter-position validator never calls this")


# -- contested predicate: the notes disagree in their own words --------------


def test_a_note_naming_the_other_side_is_contested(vault_dir: Path, names_dir: Path):
    """§7.8 path 1: two notes from two books, one naming the other's author
    (through the alias map) in `arguing_against`. Zero reference to any tag
    axis -- neither fixture note carries one."""
    claims = _contested(vault_dir)
    report = validate_counter_position(
        _record(claims, _disclosed_one_sided()),
        client=ExplodingLLMClient(),
        vault_dir=vault_dir,
        names_dir=names_dir,
    )
    assert report.contested.contested is True
    assert report.contested.signal == SIGNAL_OPPOSED_POSITIONS


def test_a_note_naming_a_name_the_other_note_names_is_contested(vault_dir: Path, names_dir: Path):
    """§7.8's third disjunct: `arguing_against` names something the other
    side is a member of, not that side's author."""
    _write_tilly(vault_dir, arguing_against=["Skocpol"], names=[])
    _write_skocpol(vault_dir, author="An Editor", names=["Skocpol"])
    claims = [_claim("c-1", TILLY_CHUNK, SKOCPOL_CHUNK)]
    report = validate_counter_position(
        _record(claims, _disclosed_one_sided()),
        client=ExplodingLLMClient(),
        vault_dir=vault_dir,
        names_dir=names_dir,
    )
    assert report.contested.contested is True


def test_an_arguing_against_naming_nobody_in_the_evidence_fires_names_opponent(
    vault_dir: Path, names_dir: Path
):
    """Issue #550, re-basing D3's own measured heart: read loosely as "an
    `arguing_against` exists" the clause is still a 1.00x no-op for
    `opposed_positions` SPECIFICALLY -- pairing still requires the evidence
    to carry the other side. But the same loose reading is now `names_
    opponent`'s own path (S-04's shape: Caspersen states and rejects Pegg's
    position, and Pegg is not an author in this corpus), so the brief is
    contested via that signal instead of falling through to uncontested."""
    _write_tilly(vault_dir, arguing_against=["Some Absent Scholar"], names=[])
    _write_skocpol(vault_dir)
    claims = [_claim("c-1", TILLY_CHUNK, SKOCPOL_CHUNK)]
    report = validate_counter_position(
        _record(claims, _disclosed_one_sided()),
        client=ExplodingLLMClient(),
        vault_dir=vault_dir,
        names_dir=names_dir,
    )
    assert report.contested.contested is True
    assert report.contested.signal == SIGNAL_NAMES_OPPONENT


def test_an_empty_arguing_against_is_an_answer_not_an_abstention(vault_dir: Path, names_dir: Path):
    """`[]` is 19.3% of the live corpus and says the passage names no
    opponent. It must never be read as "unknown, so maybe contested"."""
    _write_tilly(vault_dir, arguing_against=[], names=[])
    _write_skocpol(vault_dir)
    claims = [_claim("c-1", TILLY_CHUNK, SKOCPOL_CHUNK)]
    report = validate_counter_position(
        _record(claims, _no_counter_position()),
        client=ExplodingLLMClient(),
        vault_dir=vault_dir,
        names_dir=names_dir,
    )
    assert report.contested.contested is False


def test_two_abstaining_notes_never_manufacture_a_disagreement(vault_dir: Path, names_dir: Path):
    """The failure D3's own measurement warns about: two abstentions read as
    two different positions. Both forms abstain here, and `arguing_against`
    abstains in the bare-string form on one side."""
    _write_tilly(
        vault_dir,
        position_of={"not-in-passage": "the passage does not say whose position this is"},
        arguing_against="not-in-passage",
        names=[],
    )
    _write_skocpol(
        vault_dir,
        position_of="not-in-passage",
        arguing_against=["not-in-passage"],
        names=[],
    )
    claims = [_claim("c-1", TILLY_CHUNK, SKOCPOL_CHUNK)]
    report = validate_counter_position(
        _record(claims, _no_counter_position()),
        client=ExplodingLLMClient(),
        vault_dir=vault_dir,
        names_dir=names_dir,
    )
    assert report.contested.contested is False


def test_a_note_arguing_against_its_own_book_does_not_pair_but_still_names_an_opponent(
    vault_dir: Path, names_dir: Path
):
    """Same source, same stated position: one passage's argument with
    itself is not `opposed_positions` -- there is no second, genuinely
    opposing side to pair with (`_different_sides`). Issue #550's
    `names_opponent` path carries no pairing requirement at all though, so
    the lone note's own non-empty `arguing_against` still fires it -- the
    founder's literal "no pairing required" rule, unguarded even here."""
    _write_tilly(vault_dir, TILLY_CHUNK, arguing_against=[TILLY_AUTHOR], names=[])
    _write_tilly(vault_dir, TILLY_CHUNK_2, arguing_against=[], names=[])
    claims = [_claim("c-1", TILLY_CHUNK, TILLY_CHUNK_2)]
    report = validate_counter_position(
        _record(claims, _disclosed_one_sided()),
        client=ExplodingLLMClient(),
        vault_dir=vault_dir,
        names_dir=names_dir,
    )
    assert report.contested.contested is True
    assert report.contested.signal == SIGNAL_NAMES_OPPONENT


def test_zero_evidence_is_not_contested(vault_dir: Path, names_dir: Path):
    report = validate_counter_position(
        _record([], _no_counter_position()),
        client=ExplodingLLMClient(),
        vault_dir=vault_dir,
        names_dir=names_dir,
    )
    assert report.contested.contested is False
    assert report.contested.signal is None


# -- contested predicate: a Gather disagreement at a name the answer rests on


def test_a_gather_disagreement_at_a_retrieved_name_is_contested(vault_dir: Path, names_dir: Path):
    """§7.8 path 2. The run retrieved on `Theda Skocpol`, a claim's grounds
    note is a member of it, and its page carries a Gather section."""
    _write_tilly(vault_dir, arguing_against=[], names=[])
    _write_skocpol(vault_dir, arguing_against=[], names=[])
    _write_name_page(
        vault_dir,
        SKOCPOL_AUTHOR,
        member_ids=[SKOCPOL_CHUNK],
        disagreement="These authors disagree about whether organization is required.",
    )
    claims = [_claim("c-1", TILLY_CHUNK, SKOCPOL_CHUNK, names_touched=[SKOCPOL_AUTHOR])]
    trajectory = [
        {
            "step": 1,
            "tool": "get_name",
            "args": {"canonical": SKOCPOL_AUTHOR},
            "result_ids": [SKOCPOL_CHUNK],
            "result_count": 1,
        }
    ]
    report = validate_counter_position(
        _record(claims, _disclosed_one_sided(), trajectory),
        client=ExplodingLLMClient(),
        vault_dir=vault_dir,
        names_dir=names_dir,
    )
    assert report.contested.contested is True
    assert report.contested.signal == SIGNAL_GATHER_DISAGREEMENT


def test_a_gather_disagreement_at_a_name_the_run_never_retrieved_is_not_contested(
    vault_dir: Path, names_dir: Path
):
    """A finding at a name the answer merely brushed past says nothing about
    whether the answer is contested -- a real evidence set's notes name 423
    distinct canonicals on average."""
    _write_tilly(vault_dir, arguing_against=[], names=[])
    _write_skocpol(vault_dir, arguing_against=[], names=[])
    _write_name_page(
        vault_dir,
        SKOCPOL_AUTHOR,
        member_ids=[SKOCPOL_CHUNK],
        disagreement="These authors disagree about whether organization is required.",
    )
    claims = [_claim("c-1", TILLY_CHUNK, SKOCPOL_CHUNK, names_touched=[SKOCPOL_AUTHOR])]
    report = validate_counter_position(
        _record(claims, _no_counter_position(), trajectory=[]),
        client=ExplodingLLMClient(),
        vault_dir=vault_dir,
        names_dir=names_dir,
    )
    assert report.contested.contested is False


def test_a_name_page_with_no_gather_section_is_not_contested(vault_dir: Path, names_dir: Path):
    _write_tilly(vault_dir, arguing_against=[], names=[])
    _write_skocpol(vault_dir, arguing_against=[], names=[])
    _write_name_page(vault_dir, SKOCPOL_AUTHOR, member_ids=[SKOCPOL_CHUNK])
    claims = [_claim("c-1", TILLY_CHUNK, SKOCPOL_CHUNK, names_touched=[SKOCPOL_AUTHOR])]
    trajectory = [
        {
            "step": 1,
            "tool": "get_name",
            "args": {"canonical": SKOCPOL_AUTHOR},
            "result_ids": [SKOCPOL_CHUNK],
            "result_count": 1,
        }
    ]
    report = validate_counter_position(
        _record(claims, _no_counter_position(), trajectory),
        client=ExplodingLLMClient(),
        vault_dir=vault_dir,
        names_dir=names_dir,
    )
    assert report.contested.contested is False


# -- presence-or-disclosure check --------------------------------------------


def test_present_true_with_nonempty_grounds_passes(vault_dir: Path, names_dir: Path):
    claims = _contested(vault_dir)
    client = FakeClient(
        model_by_pass={"synthesize": "model-a", "counter_position": "model-b"},
        response=json.dumps({"verdict": "steelman", "detail": "solid"}),
    )
    report = validate_counter_position(
        _record(claims, _present_counter_position(SKOCPOL_CHUNK)),
        client=client,
        vault_dir=vault_dir,
        names_dir=names_dir,
    )
    assert report.passed
    assert report.failures == []


def test_present_true_with_empty_grounds_fails(vault_dir: Path, names_dir: Path):
    claims = _contested(vault_dir)
    counter_position = {
        "present": True,
        "stance": "A stance with no grounds.",
        "grounds": [],
        "corpus_one_sided": False,
        "one_sided_reason": None,
    }
    report = validate_counter_position(
        _record(claims, counter_position),
        client=ExplodingLLMClient(),
        vault_dir=vault_dir,
        names_dir=names_dir,
    )
    assert not report.passed
    assert report.failures[0].reason == REASON_CONTESTED_WITHOUT_COUNTER_POSITION


def test_corpus_one_sided_with_reason_passes(vault_dir: Path, names_dir: Path):
    claims = _contested(vault_dir)
    report = validate_counter_position(
        _record(claims, _disclosed_one_sided()),
        client=ExplodingLLMClient(),
        vault_dir=vault_dir,
        names_dir=names_dir,
    )
    assert report.passed


def test_corpus_one_sided_with_empty_reason_fails(vault_dir: Path, names_dir: Path):
    claims = _contested(vault_dir)
    counter_position = {
        "present": False,
        "stance": None,
        "grounds": [],
        "corpus_one_sided": True,
        "one_sided_reason": None,
    }
    report = validate_counter_position(
        _record(claims, counter_position),
        client=ExplodingLLMClient(),
        vault_dir=vault_dir,
        names_dir=names_dir,
    )
    assert not report.passed
    assert report.failures[0].reason == REASON_CONTESTED_WITHOUT_COUNTER_POSITION


def test_neither_present_nor_disclosed_fails(vault_dir: Path, names_dir: Path):
    claims = _contested(vault_dir)
    report = validate_counter_position(
        _record(claims, _no_counter_position()),
        client=ExplodingLLMClient(),
        vault_dir=vault_dir,
        names_dir=names_dir,
    )
    assert not report.passed
    assert report.failures[0].reason == REASON_CONTESTED_WITHOUT_COUNTER_POSITION


def test_a_failed_generation_fails_the_presence_or_disclosure_check(
    vault_dir: Path, names_dir: Path
):
    """Issue #558: a section marked `failed` (counter-position GENERATION
    raised, and `build_record` persisted the record anyway) must not be
    silently treated as a satisfied counter-position -- it fails exactly
    like an unattempted absence, never like a real disclosure, and the
    detail names the actual failure reason so a triager is not misled into
    thinking nothing was ever attempted. `ExplodingLLMClient` also proves
    the steelman-quality check never spends a model call on a failed
    section."""
    claims = _contested(vault_dir)
    report = validate_counter_position(
        _record(claims, _failed_counter_position("counter-position generation call failed: boom")),
        client=ExplodingLLMClient(),
        vault_dir=vault_dir,
        names_dir=names_dir,
    )
    assert not report.passed
    assert report.failures[0].reason == REASON_CONTESTED_WITHOUT_COUNTER_POSITION
    assert "boom" in report.failures[0].detail
    assert report.steelman.ran is False


def test_uncontested_brief_never_requires_the_section(vault_dir: Path, names_dir: Path):
    _write_tilly(vault_dir, arguing_against=[], names=[])
    claims = [_claim("c-1", TILLY_CHUNK)]
    report = validate_counter_position(
        _record(claims, _no_counter_position()),
        client=ExplodingLLMClient(),
        vault_dir=vault_dir,
        names_dir=names_dir,
    )
    assert report.contested.contested is False
    assert report.passed


# -- steelman-quality check: present-only, zero calls otherwise -------------


def test_steelman_check_does_not_run_when_section_is_not_present(vault_dir: Path, names_dir: Path):
    claims = _contested(vault_dir)
    report = validate_counter_position(
        _record(claims, _disclosed_one_sided()),
        client=ExplodingLLMClient(),
        vault_dir=vault_dir,
        names_dir=names_dir,
    )
    assert report.steelman.ran is False
    assert report.steelman.verdict is None


def test_steelman_check_does_not_run_on_an_uncontested_brief_with_no_section(
    vault_dir: Path, names_dir: Path
):
    _write_tilly(vault_dir, arguing_against=[], names=[])
    claims = [_claim("c-1", TILLY_CHUNK)]
    report = validate_counter_position(
        _record(claims, _no_counter_position()),
        client=ExplodingLLMClient(),
        vault_dir=vault_dir,
        names_dir=names_dir,
    )
    assert report.steelman.ran is False


def test_steelman_check_runs_when_present_true_with_grounds(vault_dir: Path, names_dir: Path):
    claims = _contested(vault_dir)
    client = FakeClient(
        model_by_pass={"synthesize": "model-a", "counter_position": "model-b"},
        response=json.dumps({"verdict": "steelman", "detail": "genuinely strong"}),
    )
    report = validate_counter_position(
        _record(claims, _present_counter_position(SKOCPOL_CHUNK)),
        client=client,
        vault_dir=vault_dir,
        names_dir=names_dir,
    )
    assert report.steelman.ran is True
    assert report.steelman.verdict == "steelman"
    assert client.calls == ["counter_position"], "must run under its own distinct pass_name"


def test_scripted_strawman_is_recorded_but_does_not_block(vault_dir: Path, names_dir: Path):
    claims = _contested(vault_dir)
    client = FakeClient(
        model_by_pass={"synthesize": "model-a", "counter_position": "model-b"},
        response=json.dumps({"verdict": "strawman", "detail": "dismissive of the real position"}),
    )
    report = validate_counter_position(
        _record(claims, _present_counter_position(SKOCPOL_CHUNK)),
        client=client,
        vault_dir=vault_dir,
        names_dir=names_dir,
    )
    assert report.steelman.verdict == VERDICT_STRAWMAN
    assert report.passed, "a strawman verdict must not block release in this slice"


# -- steelman-quality check: same-model config guard -------------------------


def test_same_model_for_both_passes_raises_before_any_call(vault_dir: Path, names_dir: Path):
    claims = _contested(vault_dir)
    client = FakeClient(
        model_by_pass={"synthesize": "model-x", "counter_position": "model-x"},
        response=json.dumps({"verdict": "steelman", "detail": ""}),
    )
    with pytest.raises(SamePassModelError) as excinfo:
        validate_counter_position(
            _record(claims, _present_counter_position(SKOCPOL_CHUNK)),
            client=client,
            vault_dir=vault_dir,
            names_dir=names_dir,
        )
    assert "model-x" in str(excinfo.value)
    assert client.calls == [], "the guard must raise BEFORE any model call is made"


def test_steelman_response_missing_verdict_raises(vault_dir: Path, names_dir: Path):
    claims = _contested(vault_dir)
    client = FakeClient(
        model_by_pass={"synthesize": "model-a", "counter_position": "model-b"},
        response=json.dumps({"not_verdict": "steelman"}),
    )
    with pytest.raises(CounterPositionCheckFailedError):
        validate_counter_position(
            _record(claims, _present_counter_position(SKOCPOL_CHUNK)),
            client=client,
            vault_dir=vault_dir,
            names_dir=names_dir,
        )


# -- never edits the record ---------------------------------------------------


def test_never_mutates_the_input_record(vault_dir: Path, names_dir: Path):
    claims = _contested(vault_dir)
    record = _record(claims, _disclosed_one_sided())
    before = json.dumps(record, sort_keys=True)
    validate_counter_position(
        record, client=ExplodingLLMClient(), vault_dir=vault_dir, names_dir=names_dir
    )
    assert json.dumps(record, sort_keys=True) == before
