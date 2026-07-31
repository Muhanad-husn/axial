"""Inner unit tests for the stage-4 counter-position GENERATION function
(issues #399 and #490, specs/PHASE-B.md §7.8). Co-located under
src/axial/analyze/, mirroring src/axial/analyze/test_synthesis.py's own
layout, but split into its own file since it exercises a distinct model call
under its own pass_name and its own anti-fabrication whitelist -- not the
claim-graph parsing test_synthesis.py already covers.

Covers issue #399's three acceptance scenarios (a contested brief with
genuine opposing evidence produces `present: true` with resolvable grounds;
a contested brief whose evidence is genuinely one-sided produces the
disclosure; an uncontested brief requires neither and costs zero model
calls), the anti-fabrication design (a response cannot ground the section in
a real vault id that was never among the candidates offered), and #490's own
two additions: the whitelist reaches a Gather finding's own member notes,
and the empty-candidates disclosure states what is actually true of the path
that fired rather than a false "nothing resolved".
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from axial.analyze.synthesis import (
    MAX_COUNTER_POSITION_CANDIDATES,
    CounterPositionGroundNotOfferedError,
    InvalidCounterPositionResponseError,
    UnresolvableCounterPositionGroundError,
    generate_counter_position,
)
from axial.brief.intake import Brief
from axial.llm import COUNTER_POSITION_GENERATE_PASS_NAME
from axial.query.names import DISAGREEMENT_HEADING

MAIN_CHUNK = "tilly-1978_001_intro_001"
COUNTER_CHUNK = "skocpol-1979_001_intro_001"
BYSTANDER_CHUNK = "tilly-1978_002_intro_001"

TILLY_AUTHOR = "Charles Tilly"
SKOCPOL_AUTHOR = "Theda Skocpol"


def _chunk_frontmatter(
    *,
    chunk_id: str,
    author: str,
    title: str,
    position_of: Any = "the author",
    arguing_against: Any = None,
    names: list[str] | None = None,
) -> dict[str, Any]:
    """A prose note in the shape `axial.materialize` writes today: source
    metadata plus the nested §7.15 answer block. No tag axis appears -- every
    one of them was deleted with the tag pass (D3)."""
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
        "chunk_text": f"SENTINEL_{chunk_id}: synthetic prose.",
        "source_meta": {
            "author": author,
            "title": title,
            "date": 1979,
            "thesis": "Synthetic thesis.",
            "scope": "Synthetic scope.",
        },
        "frame_version": "0.1",
        "answers": answers,
    }


def _tilly(chunk_id: str = MAIN_CHUNK, **overrides: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "chunk_id": chunk_id,
        "author": TILLY_AUTHOR,
        "title": "From Mobilization to Revolution",
        "arguing_against": ["Skocpol"],
        "names": ["Skocpol"],
    }
    kwargs.update(overrides)
    return _chunk_frontmatter(**kwargs)


def _skocpol(chunk_id: str = COUNTER_CHUNK, **overrides: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "chunk_id": chunk_id,
        "author": SKOCPOL_AUTHOR,
        "title": "States and Social Revolutions",
        "arguing_against": [],
        "names": [TILLY_AUTHOR],
    }
    kwargs.update(overrides)
    return _chunk_frontmatter(**kwargs)


def _write_vault(root: Path, chunks: list[dict[str, Any]]) -> Path:
    prose_dir = root / "vault" / "prose"
    prose_dir.mkdir(parents=True, exist_ok=True)
    for frontmatter in chunks:
        text = "---\n" + yaml.safe_dump(frontmatter, sort_keys=False) + "---\nBody.\n"
        (prose_dir / f"{frontmatter['chunk_id']}.md").write_text(text, encoding="utf-8")
    return root / "vault"


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
def names_dir(tmp_path: Path) -> Path:
    """Reconcile's alias map and index (§7.16): "Skocpol" is an alias of
    "Theda Skocpol", so the literal-naming rule is exercised across a real
    alias hop rather than string equality against a full author name."""
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


@pytest.fixture
def contested_vault_dir(tmp_path: Path) -> Path:
    """Two notes from two books, one naming the other's author in
    `arguing_against` -- the minimal fixture that fires the §7.8
    `opposed_positions` signal, with no tag axis anywhere."""
    return _write_vault(tmp_path, [_tilly(), _skocpol()])


def _claim(
    claim_id: str, *chunk_ids: str, names_touched: list[str] | None = None
) -> dict[str, Any]:
    return {
        "claim_id": claim_id,
        "text": f"Text for {claim_id}.",
        "kind": "a" if len(chunk_ids) == 1 else "b",
        "grounds": [{"ref_type": "chunk", "ref_id": chunk_id} for chunk_id in chunk_ids],
        "confidence": "medium",
        "names_touched": names_touched or [],
    }


def _contested_claims() -> list[dict[str, Any]]:
    return [_claim("c1", MAIN_CHUNK), _claim("c2", MAIN_CHUNK, COUNTER_CHUNK)]


def _uncontested_claims() -> list[dict[str, Any]]:
    return [_claim("c1", MAIN_CHUNK)]


def _brief() -> Brief:
    return Brief(
        brief_id="cpfix-brief",
        case="Syria",
        request="Did organization convert mobilization into a revolutionary outcome?",
    )


def _get_name_call(canonical: str) -> dict[str, Any]:
    return {
        "step": 1,
        "tool": "get_name",
        "args": {"canonical": canonical},
        "result_ids": [],
        "result_count": 0,
    }


class _ScriptedClient:
    """A minimal `LLMClient` double for `generate_counter_position`: scripts
    exactly one raw response, and asserts it is called under
    `COUNTER_POSITION_GENERATE_PASS_NAME` and never any other pass."""

    def __init__(self, response: str | None = None):
        self._response = response
        self.calls: list[tuple[str, str | None]] = []

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        assert pass_name == COUNTER_POSITION_GENERATE_PASS_NAME, (
            f"expected pass_name={COUNTER_POSITION_GENERATE_PASS_NAME!r}, got {pass_name!r}"
        )
        self.calls.append((prompt, pass_name))
        assert self._response is not None, "no response was scripted for this call"
        return self._response

    def model_for_pass(self, pass_name: str | None = None) -> str:
        return "test-double-model"


class _ForbiddenClient:
    """A double that fails the test loudly if `.complete()` is ever called --
    proves an uncontested brief makes ZERO counter-position model calls."""

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        raise AssertionError(f"unexpected model call under pass_name={pass_name!r}")

    def model_for_pass(self, pass_name: str | None = None) -> str:
        raise AssertionError("model_for_pass should never be consulted here")


# ---------------------------------------------------------------------------
# Acceptance scenario 1: uncontested brief requires neither, zero model calls
# ---------------------------------------------------------------------------


def test_uncontested_brief_returns_empty_section_with_zero_model_calls(
    tmp_path: Path, names_dir: Path
):
    vault_dir = _write_vault(tmp_path, [_tilly(arguing_against=[], names=[])])
    result = generate_counter_position(
        _uncontested_claims(),
        _brief(),
        client=_ForbiddenClient(),
        vault_dir=vault_dir,
        names_dir=names_dir,
    )
    assert result.model_called is False
    assert result.section == {
        "present": False,
        "stance": None,
        "grounds": [],
        "corpus_one_sided": False,
        "one_sided_reason": None,
    }


# ---------------------------------------------------------------------------
# Acceptance scenario 2: contested + genuine opposing evidence -> present
# ---------------------------------------------------------------------------


def test_contested_brief_with_genuine_opposing_evidence_produces_present_with_resolvable_grounds(
    contested_vault_dir: Path, names_dir: Path
):
    response = json.dumps(
        {
            "present": True,
            "stance": "Skocpol's material argues structural crisis, not organization, "
            "converts a revolutionary situation.",
            "grounds": [{"ref_type": "chunk", "ref_id": COUNTER_CHUNK}],
            "corpus_one_sided": False,
            "one_sided_reason": None,
        }
    )
    client = _ScriptedClient(response)

    result = generate_counter_position(
        _contested_claims(),
        _brief(),
        client=client,
        vault_dir=contested_vault_dir,
        names_dir=names_dir,
    )

    assert result.model_called is True
    assert len(client.calls) == 1
    assert result.section["present"] is True
    assert result.section["corpus_one_sided"] is False
    assert result.section["stance"]
    assert result.section["grounds"] == [{"ref_type": "chunk", "ref_id": COUNTER_CHUNK}]

    prompt = client.calls[0][0]
    assert COUNTER_CHUNK in prompt
    # The prompt describes candidates in the corpus's own words, never a
    # retired tag axis (D3): no `theory_school`, no `role_in_argument`.
    assert "theory_school" not in prompt
    assert "role_in_argument" not in prompt
    assert "stated position" in prompt
    # Issue #550: the prompt states WHICH signal fired, never the old
    # "mechanically flagged CONTESTED" wording -- that phrasing reads as
    # selective now that 86% of grounds notes name an opponent.
    assert "mechanically flagged" not in prompt
    assert "two of this run's own cited passages state opposing positions" in prompt


# ---------------------------------------------------------------------------
# Issue #550: a grounds note whose `arguing_against` names an opponent that
# is not itself a note in this run's evidence (no pairing possible) is still
# offered as candidate material, and the prompt states the signal that fired
# rather than a generic "mechanically flagged" claim.
# ---------------------------------------------------------------------------


def test_an_unpaired_named_opposition_becomes_a_whitelisted_candidate(
    tmp_path: Path, names_dir: Path
):
    """The S-04 shape from the smoke-v4 measurement: Caspersen's own passage
    states and rejects Pegg's position, and Pegg is not an author in this
    corpus, so no second note ever pairs with it. The lone note's own
    `arguing_against` still puts it on the whitelist (§7.8 `names_opponent`),
    and the prompt names that signal rather than claiming a generic
    mechanical flag."""
    vault_dir = _write_vault(tmp_path, [_tilly(arguing_against=["An Absent Scholar"], names=[])])
    claims = [_claim("c1", MAIN_CHUNK)]
    response = json.dumps(
        {
            "present": True,
            "stance": "Tilly's own passage states and rejects the absent scholar's position.",
            "grounds": [{"ref_type": "chunk", "ref_id": MAIN_CHUNK}],
            "corpus_one_sided": False,
            "one_sided_reason": None,
        }
    )
    client = _ScriptedClient(response)

    result = generate_counter_position(
        claims, _brief(), client=client, vault_dir=vault_dir, names_dir=names_dir
    )

    assert result.model_called is True
    assert result.section["present"] is True
    assert result.section["grounds"] == [{"ref_type": "chunk", "ref_id": MAIN_CHUNK}]

    prompt = client.calls[0][0]
    assert MAIN_CHUNK in prompt
    assert "mechanically flagged" not in prompt
    assert "no note on that other side is itself part of this run's own evidence" in prompt


def test_candidate_ordering_paired_opposition_before_unpaired_named_opposition(
    tmp_path: Path, names_dir: Path
):
    """Issue #550's stated candidate order: paired oppositions first, then
    notes naming an opponent unpaired. Both fire here -- Tilly/Skocpol pair,
    and a third note (same book as Tilly) names an absent scholar on its
    own -- and only the paired pair is a REAL vault id the response may cite
    without the unpaired note ALSO being offered; this proves the unpaired
    note is offered too, distinctly ordered after the pair."""
    unpaired_chunk = "tilly-1978_003_intro_001"
    vault_dir = _write_vault(
        tmp_path,
        [
            _tilly(),
            _skocpol(),
            _tilly(unpaired_chunk, arguing_against=["Some Other Absent Scholar"], names=[]),
        ],
    )
    claims = [_claim("c1", MAIN_CHUNK, COUNTER_CHUNK, unpaired_chunk)]
    response = json.dumps(
        {
            "present": True,
            "stance": "Both the paired and unpaired opposition are cited.",
            "grounds": [
                {"ref_type": "chunk", "ref_id": COUNTER_CHUNK},
                {"ref_type": "chunk", "ref_id": unpaired_chunk},
            ],
            "corpus_one_sided": False,
            "one_sided_reason": None,
        }
    )
    client = _ScriptedClient(response)

    result = generate_counter_position(
        claims, _brief(), client=client, vault_dir=vault_dir, names_dir=names_dir
    )

    assert result.section["grounds"] == [
        {"ref_type": "chunk", "ref_id": COUNTER_CHUNK},
        {"ref_type": "chunk", "ref_id": unpaired_chunk},
    ]
    prompt = client.calls[0][0]
    idx_paired = prompt.index(COUNTER_CHUNK)
    idx_unpaired = prompt.index(unpaired_chunk)
    assert idx_paired < idx_unpaired, (
        "the paired opposition must be offered before the unpaired named opposition"
    )


def test_a_grounds_note_outside_the_opposition_is_never_offered(tmp_path: Path, names_dir: Path):
    """A same-side note that names nobody is not opposing material, so it
    never reaches the whitelist even though it is cited evidence."""
    vault_dir = _write_vault(
        tmp_path,
        [_tilly(), _skocpol(), _tilly(BYSTANDER_CHUNK, arguing_against=[], names=[])],
    )
    response = json.dumps(
        {
            "present": True,
            "stance": "A stance grounded in the bystander note.",
            "grounds": [{"ref_type": "chunk", "ref_id": BYSTANDER_CHUNK}],
            "corpus_one_sided": False,
            "one_sided_reason": None,
        }
    )
    client = _ScriptedClient(response)
    claims = [_claim("c1", MAIN_CHUNK, COUNTER_CHUNK, BYSTANDER_CHUNK)]

    with pytest.raises(CounterPositionGroundNotOfferedError):
        generate_counter_position(
            claims, _brief(), client=client, vault_dir=vault_dir, names_dir=names_dir
        )
    assert BYSTANDER_CHUNK not in client.calls[0][0]


# ---------------------------------------------------------------------------
# Acceptance scenario 3: contested + genuinely one-sided evidence -> disclosure
# ---------------------------------------------------------------------------


def test_contested_brief_with_thin_opposing_evidence_produces_one_sided_disclosure(
    contested_vault_dir: Path, names_dir: Path
):
    response = json.dumps(
        {
            "present": False,
            "stance": None,
            "grounds": [],
            "corpus_one_sided": True,
            "one_sided_reason": "the opposing note is a passing aside, not a developed "
            "opposing argument",
        }
    )
    client = _ScriptedClient(response)

    result = generate_counter_position(
        _contested_claims(),
        _brief(),
        client=client,
        vault_dir=contested_vault_dir,
        names_dir=names_dir,
    )

    assert result.model_called is True
    assert result.section["present"] is False
    assert result.section["corpus_one_sided"] is True
    assert result.section["one_sided_reason"]
    assert result.section["grounds"] == []


# ---------------------------------------------------------------------------
# #490: the whitelist reaches a Gather finding's own member notes (D4)
# ---------------------------------------------------------------------------


def test_a_gather_finding_puts_its_own_member_notes_on_the_whitelist(
    tmp_path: Path, names_dir: Path
):
    """Contested fires on path 2 alone -- no grounds note states an
    opposition -- and the finding's page member notes are what the model may
    cite. The finding's own TEXT is a pointer and is never offered (D4)."""
    vault_dir = _write_vault(
        tmp_path,
        [
            _tilly(arguing_against=[], names=[]),
            _skocpol(arguing_against=[], names=[]),
        ],
    )
    _write_name_page(
        vault_dir,
        SKOCPOL_AUTHOR,
        member_ids=[COUNTER_CHUNK],
        disagreement="SENTINEL_FINDING_TEXT: they disagree about what organization is for.",
    )
    claims = [_claim("c1", MAIN_CHUNK, names_touched=[SKOCPOL_AUTHOR])]
    response = json.dumps(
        {
            "present": True,
            "stance": "Skocpol's own note states the opposing account.",
            "grounds": [{"ref_type": "chunk", "ref_id": COUNTER_CHUNK}],
            "corpus_one_sided": False,
            "one_sided_reason": None,
        }
    )
    client = _ScriptedClient(response)

    result = generate_counter_position(
        claims,
        _brief(),
        client=client,
        trajectory=[_get_name_call(SKOCPOL_AUTHOR)],
        vault_dir=vault_dir,
        names_dir=names_dir,
    )

    assert result.section["present"] is True
    assert result.section["grounds"] == [{"ref_type": "chunk", "ref_id": COUNTER_CHUNK}]
    prompt = client.calls[0][0]
    assert COUNTER_CHUNK in prompt
    assert "SENTINEL_FINDING_TEXT" not in prompt, (
        "D4: a Gather finding is a retrieval hint, never quotable material"
    )


def test_the_empty_candidate_disclosure_never_claims_the_grounds_failed_to_resolve(
    tmp_path: Path, names_dir: Path
):
    """The clause #490 owes §7.8. Contested fires on path 2 while the
    whitelist finds nothing, and the old guard wrote "none of the underlying
    grounds chunks resolved in the vault" -- which is false: they resolved
    and simply carry no opposing position."""
    vault_dir = _write_vault(tmp_path, [_tilly(arguing_against=[], names=[])])
    # A page carrying a finding but no reachable member note of its own.
    _write_name_page(
        vault_dir,
        SKOCPOL_AUTHOR,
        member_ids=["not-a-real-chunk-id"],
        disagreement="They disagree about what organization is for.",
    )
    claims = [_claim("c1", MAIN_CHUNK, names_touched=[SKOCPOL_AUTHOR])]

    result = generate_counter_position(
        claims,
        _brief(),
        client=_ForbiddenClient(),
        trajectory=[_get_name_call(SKOCPOL_AUTHOR)],
        vault_dir=vault_dir,
        names_dir=names_dir,
    )

    assert result.model_called is False
    assert result.section["corpus_one_sided"] is True
    reason = result.section["one_sided_reason"]
    assert "resolved in the vault" not in reason
    assert "recorded disagreement" in reason


# ---------------------------------------------------------------------------
# Anti-fabrication: grounds must come from the offered whitelist
# ---------------------------------------------------------------------------


def test_present_response_citing_a_real_id_outside_the_candidate_whitelist_is_rejected(
    tmp_path: Path, names_dir: Path
):
    """BYSTANDER_CHUNK is a REAL vault id that no claim even cites. A
    response grounding the section in it must be rejected, not silently
    accepted because the id happens to resolve."""
    vault_dir = _write_vault(
        tmp_path,
        [_tilly(), _skocpol(), _tilly(BYSTANDER_CHUNK, arguing_against=[], names=[])],
    )
    response = json.dumps(
        {
            "present": True,
            "stance": "A fabricated 'opposing' stance grounded in an unoffered chunk.",
            "grounds": [{"ref_type": "chunk", "ref_id": BYSTANDER_CHUNK}],
            "corpus_one_sided": False,
            "one_sided_reason": None,
        }
    )
    client = _ScriptedClient(response)

    with pytest.raises(CounterPositionGroundNotOfferedError) as exc_info:
        generate_counter_position(
            _contested_claims(),
            _brief(),
            client=client,
            vault_dir=vault_dir,
            names_dir=names_dir,
        )
    assert BYSTANDER_CHUNK in str(exc_info.value)


def test_present_response_citing_a_wholly_invented_id_is_rejected(
    contested_vault_dir: Path, names_dir: Path
):
    response = json.dumps(
        {
            "present": True,
            "stance": "A fabricated stance citing a chunk that does not exist.",
            "grounds": [{"ref_type": "chunk", "ref_id": "zzz_totally_invented_999"}],
            "corpus_one_sided": False,
            "one_sided_reason": None,
        }
    )
    client = _ScriptedClient(response)

    with pytest.raises(UnresolvableCounterPositionGroundError) as exc_info:
        generate_counter_position(
            _contested_claims(),
            _brief(),
            client=client,
            vault_dir=contested_vault_dir,
            names_dir=names_dir,
        )
    assert "zzz_totally_invented_999" in str(exc_info.value)


def test_response_naming_both_present_and_one_sided_is_rejected(
    contested_vault_dir: Path, names_dir: Path
):
    response = json.dumps(
        {
            "present": True,
            "stance": "Ambiguous.",
            "grounds": [{"ref_type": "chunk", "ref_id": COUNTER_CHUNK}],
            "corpus_one_sided": True,
            "one_sided_reason": "Contradicts present=true.",
        }
    )
    client = _ScriptedClient(response)

    with pytest.raises(InvalidCounterPositionResponseError):
        generate_counter_position(
            _contested_claims(),
            _brief(),
            client=client,
            vault_dir=contested_vault_dir,
            names_dir=names_dir,
        )


def test_response_naming_neither_present_nor_one_sided_is_rejected(
    contested_vault_dir: Path, names_dir: Path
):
    response = json.dumps(
        {
            "present": False,
            "stance": None,
            "grounds": [],
            "corpus_one_sided": False,
            "one_sided_reason": None,
        }
    )
    client = _ScriptedClient(response)

    with pytest.raises(InvalidCounterPositionResponseError):
        generate_counter_position(
            _contested_claims(),
            _brief(),
            client=client,
            vault_dir=contested_vault_dir,
            names_dir=names_dir,
        )


def test_present_response_with_empty_grounds_is_rejected(
    contested_vault_dir: Path, names_dir: Path
):
    response = json.dumps(
        {
            "present": True,
            "stance": "A stance with nothing backing it.",
            "grounds": [],
            "corpus_one_sided": False,
            "one_sided_reason": None,
        }
    )
    client = _ScriptedClient(response)

    with pytest.raises(InvalidCounterPositionResponseError):
        generate_counter_position(
            _contested_claims(),
            _brief(),
            client=client,
            vault_dir=contested_vault_dir,
            names_dir=names_dir,
        )


# ---------------------------------------------------------------------------
# The prompt is bounded (issue #505)
# ---------------------------------------------------------------------------


def test_the_candidate_pool_is_capped(tmp_path: Path, names_dir: Path):
    """A name page's member list is unbounded on the real corpus (`Syria`
    alone has 962). The cap keeps one prompt bounded; the run's own grounds
    notes are ordered first, so what it ever drops is the vault-wide tail."""
    members = [f"skocpol-1979_{index:03d}_body_001" for index in range(40)]
    vault_dir = _write_vault(
        tmp_path,
        [_tilly(arguing_against=[], names=[])]
        + [_skocpol(chunk_id=member, arguing_against=[], names=[]) for member in members],
    )
    _write_name_page(
        vault_dir,
        SKOCPOL_AUTHOR,
        member_ids=members,
        disagreement="They disagree about what organization is for.",
    )
    claims = [_claim("c1", MAIN_CHUNK, names_touched=[SKOCPOL_AUTHOR])]
    response = json.dumps(
        {
            "present": True,
            "stance": "The opposing account.",
            "grounds": [{"ref_type": "chunk", "ref_id": members[0]}],
            "corpus_one_sided": False,
            "one_sided_reason": None,
        }
    )
    client = _ScriptedClient(response)

    generate_counter_position(
        claims,
        _brief(),
        client=client,
        trajectory=[_get_name_call(SKOCPOL_AUTHOR)],
        vault_dir=vault_dir,
        names_dir=names_dir,
    )

    prompt = client.calls[0][0]
    offered = sum(1 for member in members if member in prompt)
    assert offered == MAX_COUNTER_POSITION_CANDIDATES


# ---------------------------------------------------------------------------
# Truncated-citation repair: mirrors test_synthesis.py's own DEC-42 coverage.
# ---------------------------------------------------------------------------


def test_a_truncated_ref_id_is_repaired_to_the_full_candidate_id(tmp_path: Path, names_dir: Path):
    full_counter_id = (
        "Some Long Human-Readable Title - libgen.li-5f35a47d9657_25_counter-argument_001"
    )
    truncated_tail = "libgen.li-5f35a47d9657_25_counter-argument_001"
    vault_dir = _write_vault(tmp_path, [_tilly(), _skocpol(chunk_id=full_counter_id)])
    claims = [_claim("c1", MAIN_CHUNK, full_counter_id)]
    response = json.dumps(
        {
            "present": True,
            "stance": "The opposing account.",
            "grounds": [{"ref_type": "chunk", "ref_id": truncated_tail}],
            "corpus_one_sided": False,
            "one_sided_reason": None,
        }
    )
    client = _ScriptedClient(response)

    result = generate_counter_position(
        claims, _brief(), client=client, vault_dir=vault_dir, names_dir=names_dir
    )

    assert result.section["grounds"] == [{"ref_type": "chunk", "ref_id": full_counter_id}]


# ---------------------------------------------------------------------------
# Head-truncated citation repair (issue #524): the mirror image of the tail
# case above. S-05 died after 998.6s of real spend on
# `caspersen-2012-fbc0efe4fffc_18` -- the model emitted the head of a real id
# and dropped the slug and index. The prefix carries a component separator, so
# `_18` can never reach `_180`.
# ---------------------------------------------------------------------------

HEAD = "caspersen-2012-fbc0efe4fffc_18"
FULL_HEAD_ID = f"{HEAD}_unrecognized-states-in-the-modern-international-system_001"


def _present_response(ref_id: str) -> str:
    return json.dumps(
        {
            "present": True,
            "stance": "The opposing account.",
            "grounds": [{"ref_type": "chunk", "ref_id": ref_id}],
            "corpus_one_sided": False,
            "one_sided_reason": None,
        }
    )


def test_a_head_truncated_ref_id_is_repaired_to_the_full_candidate_id(
    tmp_path: Path, names_dir: Path
):
    vault_dir = _write_vault(tmp_path, [_tilly(), _skocpol(chunk_id=FULL_HEAD_ID)])
    claims = [_claim("c1", MAIN_CHUNK, FULL_HEAD_ID)]
    client = _ScriptedClient(_present_response(HEAD))

    result = generate_counter_position(
        claims, _brief(), client=client, vault_dir=vault_dir, names_dir=names_dir
    )

    assert result.section["grounds"] == [{"ref_type": "chunk", "ref_id": FULL_HEAD_ID}]


def test_a_head_truncated_ref_id_never_reaches_a_longer_section_number(
    tmp_path: Path, names_dir: Path
):
    """The `_18` vs `_180` boundary: both sections exist, and the repair
    still resolves to section 18's note rather than raising on a spurious
    second match."""
    sibling_id = "caspersen-2012-fbc0efe4fffc_180_a-much-later-section_001"
    vault_dir = _write_vault(
        tmp_path,
        [_tilly(), _skocpol(chunk_id=FULL_HEAD_ID), _skocpol(chunk_id=sibling_id)],
    )
    claims = [_claim("c1", MAIN_CHUNK, FULL_HEAD_ID)]
    client = _ScriptedClient(_present_response(HEAD))

    result = generate_counter_position(
        claims, _brief(), client=client, vault_dir=vault_dir, names_dir=names_dir
    )

    assert result.section["grounds"] == [{"ref_type": "chunk", "ref_id": FULL_HEAD_ID}]


def test_a_head_truncated_ref_id_matching_two_real_ids_still_raises(
    tmp_path: Path, names_dir: Path
):
    """Two chunks of the SAME section share the head, so the citation is
    genuinely ambiguous. Ambiguity stays as fatal as it is for the tail
    repair -- never guessed at."""
    second_chunk = f"{HEAD}_unrecognized-states-in-the-modern-international-system_002"
    vault_dir = _write_vault(
        tmp_path,
        [_tilly(), _skocpol(chunk_id=FULL_HEAD_ID), _skocpol(chunk_id=second_chunk)],
    )
    claims = [_claim("c1", MAIN_CHUNK, FULL_HEAD_ID, second_chunk)]
    client = _ScriptedClient(_present_response(HEAD))

    with pytest.raises(UnresolvableCounterPositionGroundError) as exc_info:
        generate_counter_position(
            claims, _brief(), client=client, vault_dir=vault_dir, names_dir=names_dir
        )
    assert HEAD in str(exc_info.value)


def test_an_exact_match_wins_over_a_note_that_extends_it(tmp_path: Path, names_dir: Path):
    """Resolution order is exact -> suffix -> prefix. A cited id that is
    itself a real note AND the head of a longer one resolves to the note
    that matches exactly, never to its extension."""
    extension_id = f"{COUNTER_CHUNK}_a-longer-tail_002"
    vault_dir = _write_vault(tmp_path, [_tilly(), _skocpol(), _skocpol(chunk_id=extension_id)])
    claims = [_claim("c1", MAIN_CHUNK, COUNTER_CHUNK, extension_id)]
    client = _ScriptedClient(_present_response(COUNTER_CHUNK))

    result = generate_counter_position(
        claims, _brief(), client=client, vault_dir=vault_dir, names_dir=names_dir
    )

    assert result.section["grounds"] == [{"ref_type": "chunk", "ref_id": COUNTER_CHUNK}]


def test_counter_position_generate_pass_name_is_the_stable_dispatch_key():
    # Pins the pass_name literal itself -- model_by_pass/reasoning_by_pass
    # config routing (config/pipeline.yaml) depends on this string never
    # drifting silently, and it must stay distinct from SYNTHESIZE_PASS_NAME
    # so the stub/record dispatch can tell the two calls apart.
    assert COUNTER_POSITION_GENERATE_PASS_NAME == "counter_position_generate"
