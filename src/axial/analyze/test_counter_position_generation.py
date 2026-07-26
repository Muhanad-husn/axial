"""Inner unit tests for the stage-4 counter-position GENERATION function
(issue #399, specs/PHASE-B.md §7.8). Co-located under src/axial/analyze/,
mirroring src/axial/analyze/test_synthesis.py's own layout, but split into
its own file since it exercises a distinct model call under its own
pass_name and its own anti-fabrication whitelist -- not the claim-graph
parsing test_synthesis.py already covers.

Covers issue #399's three acceptance scenarios (a contested brief with
genuine opposing evidence produces `present: true` with resolvable grounds;
a contested brief whose evidence is genuinely one-sided produces the
disclosure; an uncontested brief requires neither and costs zero model
calls) plus the anti-fabrication design: a response cannot ground the
section in a real vault id that was never among the candidates offered.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from axial.analyze.synthesis import (
    CounterPositionGroundNotOfferedError,
    InvalidCounterPositionResponseError,
    UnresolvableCounterPositionGroundError,
    generate_counter_position,
)
from axial.brief.intake import Brief
from axial.llm import COUNTER_POSITION_GENERATE_PASS_NAME


def _chunk_frontmatter(
    *,
    chunk_id: str,
    theory_school_primary: str,
    role_in_argument: str = "role:claim",
    polities_touched: list[str] | None = None,
) -> dict[str, Any]:
    polities = polities_touched if polities_touched is not None else ["Syria"]
    return {
        "chunk_id": chunk_id,
        "section": "Synthetic Section",
        "chunk_text": f"SENTINEL_{chunk_id}: synthetic prose.",
        "source_meta": {
            "author": "A. Synthetic Author",
            "title": "A Synthetic Fixture Source",
            "date": 2021,
            "thesis": "Synthetic thesis.",
            "scope": "Synthetic scope.",
        },
        "schema_version": "0.1",
        "role_in_argument": role_in_argument,
        "field": {"primary": "field:political-sociology", "secondary": []},
        "claim_type": {"primary": "claim:causal", "secondary": None, "subtags": []},
        "theory_school": {
            "primary": theory_school_primary,
            "secondary": None,
            "status": "candidate",
        },
        "empirical_scope": {
            "value": "scope:country-case",
            "polity": polities[0] if polities else None,
        },
        "polities_touched": polities,
        "artifact_refs": [],
    }


def _write_vault(root: Path, chunks: list[dict[str, Any]]) -> Path:
    prose_dir = root / "vault" / "prose"
    prose_dir.mkdir(parents=True, exist_ok=True)
    for frontmatter in chunks:
        text = "---\n" + yaml.safe_dump(frontmatter, sort_keys=False) + "---\nBody.\n"
        (prose_dir / f"{frontmatter['chunk_id']}.md").write_text(text, encoding="utf-8")
    return root / "vault"


MAIN_CHUNK = "cpfix_main_bellicist"  # theory_school: bellicist -- the primary claims' own school
COUNTER_CHUNK = "cpfix_counter_marxist"  # theory_school: marxist-political-economy


@pytest.fixture
def contested_vault_dir(tmp_path: Path) -> Path:
    """Two chunks, two distinct substantive theory_school values -- the
    minimal fixture that fires `_detect_contested`'s theory_school_spread
    signal (the ONLY signal the real slice-1 sweep ever observed firing,
    per issue #399's own measured context)."""
    return _write_vault(
        tmp_path,
        [
            _chunk_frontmatter(chunk_id=MAIN_CHUNK, theory_school_primary="school:bellicist"),
            _chunk_frontmatter(
                chunk_id=COUNTER_CHUNK, theory_school_primary="school:marxist-political-economy"
            ),
        ],
    )


def _contested_claims() -> list[dict[str, Any]]:
    """A claim graph citing both chunks -- MAIN_CHUNK once (so it is the
    first-seen, and therefore the majority, school on a tie), COUNTER_CHUNK
    once, matching `_evidence_chunk_ids`' own dedup-by-grounds-union
    contract."""
    return [
        {
            "claim_id": "c1",
            "text": "The corpus states that war consolidated state authority.",
            "kind": "a",
            "grounds": [{"ref_type": "chunk", "ref_id": MAIN_CHUNK}],
            "confidence": "medium",
            "polities_touched": ["Syria"],
        },
        {
            "claim_id": "c2",
            "text": "A cross-source inference drawing on both schools' material.",
            "kind": "b",
            "grounds": [
                {"ref_type": "chunk", "ref_id": MAIN_CHUNK},
                {"ref_type": "chunk", "ref_id": COUNTER_CHUNK},
            ],
            "confidence": "low",
            "polities_touched": ["Syria"],
        },
    ]


def _uncontested_claims() -> list[dict[str, Any]]:
    return [
        {
            "claim_id": "c1",
            "text": "The corpus states that war consolidated state authority.",
            "kind": "a",
            "grounds": [{"ref_type": "chunk", "ref_id": MAIN_CHUNK}],
            "confidence": "medium",
            "polities_touched": ["Syria"],
        }
    ]


def _brief() -> Brief:
    return Brief(
        brief_id="cpfix-brief",
        case="Syria",
        request="Did war consolidate or erode state authority?",
    )


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


def test_uncontested_brief_returns_empty_section_with_zero_model_calls(tmp_path: Path):
    vault_dir = _write_vault(
        tmp_path,
        [_chunk_frontmatter(chunk_id=MAIN_CHUNK, theory_school_primary="school:bellicist")],
    )
    result = generate_counter_position(
        _uncontested_claims(), _brief(), client=_ForbiddenClient(), vault_dir=vault_dir
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
    contested_vault_dir: Path,
):
    response = json.dumps(
        {
            "present": True,
            "stance": "The marxist-political-economy material argues war eroded, not "
            "consolidated, state capacity.",
            "grounds": [{"ref_type": "chunk", "ref_id": COUNTER_CHUNK}],
            "corpus_one_sided": False,
            "one_sided_reason": None,
        }
    )
    client = _ScriptedClient(response)

    result = generate_counter_position(
        _contested_claims(), _brief(), client=client, vault_dir=contested_vault_dir
    )

    assert result.model_called is True
    assert len(client.calls) == 1
    assert result.section["present"] is True
    assert result.section["corpus_one_sided"] is False
    assert result.section["stance"]
    assert result.section["grounds"] == [{"ref_type": "chunk", "ref_id": COUNTER_CHUNK}]
    # The prompt offered ONLY the minority-school chunk as a candidate --
    # the majority-school chunk (MAIN_CHUNK) must never appear as citable.
    prompt = client.calls[0][0]
    assert COUNTER_CHUNK in prompt


# ---------------------------------------------------------------------------
# Acceptance scenario 3: contested + genuinely one-sided evidence -> disclosure
# ---------------------------------------------------------------------------


def test_contested_brief_with_thin_opposing_evidence_produces_one_sided_disclosure(
    contested_vault_dir: Path,
):
    response = json.dumps(
        {
            "present": False,
            "stance": None,
            "grounds": [],
            "corpus_one_sided": True,
            "one_sided_reason": "the single marxist-tagged chunk is a passing aside, not a "
            "developed opposing argument",
        }
    )
    client = _ScriptedClient(response)

    result = generate_counter_position(
        _contested_claims(), _brief(), client=client, vault_dir=contested_vault_dir
    )

    assert result.model_called is True
    assert result.section["present"] is False
    assert result.section["corpus_one_sided"] is True
    assert result.section["one_sided_reason"]
    assert result.section["grounds"] == []


# ---------------------------------------------------------------------------
# Anti-fabrication: grounds must come from the offered whitelist
# ---------------------------------------------------------------------------


def test_present_response_citing_a_real_id_outside_the_candidate_whitelist_is_rejected(
    contested_vault_dir: Path,
):
    """MAIN_CHUNK is a REAL vault id, but it is the MAJORITY school -- never
    offered as a candidate. A response citing it as opposing grounds must be
    rejected, not silently accepted because the id happens to resolve."""
    response = json.dumps(
        {
            "present": True,
            "stance": "A fabricated 'opposing' stance grounded in the same-side chunk.",
            "grounds": [{"ref_type": "chunk", "ref_id": MAIN_CHUNK}],
            "corpus_one_sided": False,
            "one_sided_reason": None,
        }
    )
    client = _ScriptedClient(response)

    with pytest.raises(CounterPositionGroundNotOfferedError) as exc_info:
        generate_counter_position(
            _contested_claims(), _brief(), client=client, vault_dir=contested_vault_dir
        )
    assert MAIN_CHUNK in str(exc_info.value)


def test_present_response_citing_a_wholly_invented_id_is_rejected(contested_vault_dir: Path):
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
            _contested_claims(), _brief(), client=client, vault_dir=contested_vault_dir
        )
    assert "zzz_totally_invented_999" in str(exc_info.value)


def test_response_naming_both_present_and_one_sided_is_rejected(contested_vault_dir: Path):
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
            _contested_claims(), _brief(), client=client, vault_dir=contested_vault_dir
        )


def test_response_naming_neither_present_nor_one_sided_is_rejected(contested_vault_dir: Path):
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
            _contested_claims(), _brief(), client=client, vault_dir=contested_vault_dir
        )


def test_present_response_with_empty_grounds_is_rejected(contested_vault_dir: Path):
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
            _contested_claims(), _brief(), client=client, vault_dir=contested_vault_dir
        )


# ---------------------------------------------------------------------------
# Truncated-citation repair: mirrors test_synthesis.py's own DEC-42 coverage,
# since the counter-position grounds resolution path repairs suffix-only
# citations the same way claim grounds do.
# ---------------------------------------------------------------------------


def test_a_truncated_ref_id_is_repaired_to_the_full_candidate_id(tmp_path: Path):
    full_counter_id = (
        "Some Long Human-Readable Title - libgen.li-5f35a47d9657_25_counter-argument_001"
    )
    truncated_tail = "libgen.li-5f35a47d9657_25_counter-argument_001"
    vault_dir = _write_vault(
        tmp_path,
        [
            _chunk_frontmatter(chunk_id=MAIN_CHUNK, theory_school_primary="school:bellicist"),
            _chunk_frontmatter(
                chunk_id=full_counter_id, theory_school_primary="school:marxist-political-economy"
            ),
        ],
    )
    claims = [
        {
            "claim_id": "c1",
            "text": "Primary claim.",
            "kind": "a",
            "grounds": [
                {"ref_type": "chunk", "ref_id": MAIN_CHUNK},
                {"ref_type": "chunk", "ref_id": full_counter_id},
            ],
            "confidence": "medium",
            "polities_touched": ["Syria"],
        }
    ]
    response = json.dumps(
        {
            "present": True,
            "stance": "The opposing marxist-political-economy stance.",
            "grounds": [{"ref_type": "chunk", "ref_id": truncated_tail}],
            "corpus_one_sided": False,
            "one_sided_reason": None,
        }
    )
    client = _ScriptedClient(response)

    result = generate_counter_position(claims, _brief(), client=client, vault_dir=vault_dir)

    assert result.section["grounds"] == [{"ref_type": "chunk", "ref_id": full_counter_id}]


def test_counter_position_generate_pass_name_is_the_stable_dispatch_key():
    # Pins the pass_name literal itself -- model_by_pass/reasoning_by_pass
    # config routing (config/pipeline.yaml) depends on this string never
    # drifting silently, and it must stay distinct from SYNTHESIZE_PASS_NAME
    # so the stub/record dispatch can tell the two calls apart (module
    # docstring).
    assert COUNTER_POSITION_GENERATE_PASS_NAME == "counter_position_generate"
