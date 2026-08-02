"""Acceptance tests for issue #572, PR 4 of 4: the corridor and the
assembly order (`axial.argmap.ask.build_corridor`/`round_robin_by_source`/
`assemble_map_evidence`), plus the opt-in wiring into `axial brief run`
(`axial.answer.record.run_brief(use_map=True)`).

A port of the scratchpad's own measured `stage3_brief_on_map.py` (its
corridor and assembly-order sections), not a redesign. Fixtures and fake
clients throughout -- no real model call, no dependence on `data/`, which a
worktree does not have.

Covered here:

  - a relation touching a landed position pulls its counterpart into the
    corridor, in both directions, and a position already landed never
    appears in the corridor (a relation between two landed positions
    contributes nothing);
  - corridor order follows relation count, descending;
  - assembly alternates across positions before taking a second note from
    any one of them, and within a position alternates across sources;
  - a chunk id reachable from two positions is emitted once;
  - the cap is respected, and a short queue draining does not stall the
    rotation;
  - `run_brief(use_map=True)` calls the shipped `assemble_evidence`/
    `synthesize` with the map's own ordered ids, records `map_retrieval`
    (never a fabricated trajectory) and an empty `trajectory`, and the
    default (`use_map=False`) path is unchanged and never touches the map;
  - the empty trajectory's downstream effect (issue #584): `coverage_map`
    is empty and `confidence.overall_band` is `not_measured`, never a
    measured `low`, and `source_usage`'s per-source `available_chunk_count`/
    `available_share` are `None`, not a measured `0`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

import axial.answer.record as record_module
from axial.argmap.ask import (
    DECOMPOSE_PASS_NAME,
    AskResult,
    CorridorPosition,
    LandedPosition,
    assemble_map_evidence,
    build_corridor,
    round_robin_by_source,
)
from axial.brief.intake import Brief
from axial.llm import INTERROGATE_PASS_NAME, RETRIEVE_PASS_NAME, SYNTHESIZE_PASS_NAME
from axial.retrieve.loop import RetrievalResult
from axial.validators.coverage import NOT_MEASURED_BAND

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
LENSES_DIR = REPO_ROOT / "config" / "lenses"


def _position(position_id: str, **overrides: Any) -> dict[str, Any]:
    base = {
        "position_id": position_id,
        "argument": f"Argument of {position_id}.",
        "size": 1,
        "sources": [f"{position_id}-source"],
        "authors": [f"{position_id}-author"],
        "chunk_ids": [f"{position_id}-c1"],
    }
    base.update(overrides)
    return base


def _landed(position_id: str, score: float = 0.9, **overrides: Any) -> LandedPosition:
    position = _position(position_id, **overrides)
    return LandedPosition(
        position_id=position["position_id"],
        score=score,
        argument=position["argument"],
        size=position["size"],
        sources=tuple(position["sources"]),
        authors=tuple(position["authors"]),
        chunk_ids=tuple(position["chunk_ids"]),
    )


def _relation(from_id: str, to_id: str, label: str = "qualifies") -> dict[str, Any]:
    return {"from_position_id": from_id, "to_position_id": to_id, "relation": label}


# ---------------------------------------------------------------------------
# build_corridor: both directions reach, landed never re-appears
# ---------------------------------------------------------------------------


def test_relation_pulls_counterpart_into_corridor_in_both_directions():
    positions_by_id = {
        "pos-A": _position("pos-A"),
        "pos-B": _position("pos-B"),
        "pos-C": _position("pos-C"),
        "pos-D": _position("pos-D"),
    }
    landed = [_landed("pos-A"), _landed("pos-C")]
    relations = [
        # pos-A (landed) -> pos-B (not landed): reached going OUT of landed.
        _relation("pos-A", "pos-B", "qualifies"),
        # pos-D (not landed) -> pos-A (landed): reached going INTO landed.
        _relation("pos-D", "pos-A", "contradicts"),
        # Both ends already landed: must contribute nothing to the corridor.
        _relation("pos-C", "pos-A", "supports"),
    ]

    corridor = build_corridor(landed, positions_by_id, relations)

    ids = {position.position_id for position in corridor}
    assert ids == {"pos-B", "pos-D"}

    by_id = {position.position_id: position for position in corridor}
    assert by_id["pos-B"].labels == ("qualifies ->",)
    assert by_id["pos-D"].labels == ("contradicts <-",)


def test_a_landed_position_never_also_appears_in_the_corridor():
    positions_by_id = {"pos-A": _position("pos-A"), "pos-B": _position("pos-B")}
    landed = [_landed("pos-A"), _landed("pos-B")]
    relations = [_relation("pos-A", "pos-B", "supports"), _relation("pos-B", "pos-A", "restates")]

    corridor = build_corridor(landed, positions_by_id, relations)

    assert corridor == []


# ---------------------------------------------------------------------------
# build_corridor: ordered by relation count, descending
# ---------------------------------------------------------------------------


def test_corridor_order_follows_relation_count_descending():
    positions_by_id = {
        "pos-A": _position("pos-A"),
        "pos-X": _position("pos-X"),
        "pos-Y": _position("pos-Y"),
        "pos-Z": _position("pos-Z"),
    }
    landed = [_landed("pos-A")]
    relations = [
        _relation("pos-A", "pos-X", "supports"),
        _relation("pos-A", "pos-X", "sharpens"),
        _relation("pos-A", "pos-X", "restates"),
        _relation("pos-A", "pos-Y", "supports"),
        _relation("pos-A", "pos-Z", "supports"),
        _relation("pos-A", "pos-Z", "qualifies"),
    ]

    corridor = build_corridor(landed, positions_by_id, relations)

    assert [position.position_id for position in corridor] == ["pos-X", "pos-Z", "pos-Y"]
    assert [position.relation_count for position in corridor] == [3, 2, 1]


# ---------------------------------------------------------------------------
# round_robin_by_source: one id per source per turn
# ---------------------------------------------------------------------------


def test_round_robin_by_source_interleaves_across_sources():
    chunk_ids = [
        "alpha-2020-x_1_s_001",
        "alpha-2020-x_1_s_002",
        "beta-2019-y_1_s_001",
    ]

    ordered = round_robin_by_source(chunk_ids)

    assert ordered == ["alpha-2020-x_1_s_001", "beta-2019-y_1_s_001", "alpha-2020-x_1_s_002"]


def test_round_robin_by_source_groups_a_malformed_id_under_the_empty_string():
    # A chunk_id with fewer than four `_`-delimited segments does not parse
    # (`source_id_from_chunk_id`'s own contract) -- it must still be
    # reachable, grouped under `""`, which sorts first.
    chunk_ids = ["not-a-real-id", "alpha-2020-x_1_s_001"]

    ordered = round_robin_by_source(chunk_ids)

    assert ordered[0] == "not-a-real-id"
    assert set(ordered) == set(chunk_ids)


# ---------------------------------------------------------------------------
# assemble_map_evidence: cross-position, cross-source alternation, dedup, cap
# ---------------------------------------------------------------------------


def test_assembly_alternates_positions_before_a_second_note_from_either():
    position_a = _landed(
        "pos-A", chunk_ids=["alpha-2020-x_1_s_001", "alpha-2020-x_1_s_002", "beta-2019-y_1_s_001"]
    )
    position_b = _landed("pos-B", chunk_ids=["gamma-2021-z_1_s_001", "gamma-2021-z_1_s_002"])

    assembled = assemble_map_evidence([position_a, position_b], cap=10)

    assert assembled == [
        "alpha-2020-x_1_s_001",
        "gamma-2021-z_1_s_001",
        "beta-2019-y_1_s_001",
        "gamma-2021-z_1_s_002",
        "alpha-2020-x_1_s_002",
    ]
    # The first two ids come from two DIFFERENT positions -- cross-position
    # alternation before either position gets a second turn.
    assert assembled[0].startswith("alpha") and assembled[1].startswith("gamma")
    # Position A's own three ids, in the order they were emitted, alternate
    # sources (alpha, beta, alpha) rather than running alpha, alpha, beta.
    a_ids_in_emission_order = [cid for cid in assembled if not cid.startswith("gamma")]
    assert a_ids_in_emission_order == [
        "alpha-2020-x_1_s_001",
        "beta-2019-y_1_s_001",
        "alpha-2020-x_1_s_002",
    ]


def test_assembly_deduplicates_a_chunk_id_reachable_from_two_positions():
    position_a = _landed("pos-A", chunk_ids=["shared-2020-c_1_s_001", "alpha-2020-x_1_s_001"])
    position_b = _landed("pos-B", chunk_ids=["shared-2020-c_1_s_001", "beta-2019-y_1_s_001"])

    assembled = assemble_map_evidence([position_a, position_b], cap=10)

    assert assembled.count("shared-2020-c_1_s_001") == 1
    assert set(assembled) == {
        "shared-2020-c_1_s_001",
        "alpha-2020-x_1_s_001",
        "beta-2019-y_1_s_001",
    }


def test_assembly_respects_the_cap_and_a_short_queue_draining_does_not_stall():
    position_a = _landed(
        "pos-A",
        chunk_ids=[f"alpha-2020-x_1_s_{n:03d}" for n in range(5)],
    )
    position_b = _landed("pos-B", chunk_ids=["beta-2019-y_1_s_001"])

    assembled = assemble_map_evidence([position_a, position_b], cap=3)

    # position_b's one-item queue drains after the first turn and drops out
    # of rotation; position_a's own queue keeps turning to fill the cap
    # rather than the whole walk stalling once one queue empties.
    assert assembled == [
        "alpha-2020-x_1_s_000",
        "beta-2019-y_1_s_001",
        "alpha-2020-x_1_s_001",
    ]


def test_assembly_skips_a_position_with_no_chunk_ids_without_crashing():
    empty_position = _landed("pos-empty", chunk_ids=[])
    real_position = _landed("pos-real", chunk_ids=["alpha-2020-x_1_s_001"])

    assembled = assemble_map_evidence([empty_position, real_position], cap=10)

    assert assembled == ["alpha-2020-x_1_s_001"]


def test_assembly_walks_corridor_positions_after_landed_ones():
    corridor_position = CorridorPosition(
        position_id="pos-corridor",
        relation_count=1,
        labels=("qualifies ->",),
        argument="Argument of pos-corridor.",
        size=1,
        sources=("pos-corridor-source",),
        authors=("pos-corridor-author",),
        chunk_ids=("corridor-2020-x_1_s_001",),
    )
    landed_position = _landed("pos-landed", chunk_ids=["landed-2020-x_1_s_001"])

    assembled = assemble_map_evidence([landed_position, corridor_position], cap=10)

    assert assembled == ["landed-2020-x_1_s_001", "corridor-2020-x_1_s_001"]


# ---------------------------------------------------------------------------
# run_brief(use_map=...): wiring into the shipped assemble_evidence/synthesize
# ---------------------------------------------------------------------------


def _chunk_frontmatter(chunk_id: str) -> dict[str, Any]:
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
        "frame_version": "0.1",
        "answers": {"claim": f"Claim of {chunk_id}.", "move": "stating a mechanism"},
    }


def _write_vault(root: Path, chunk_ids: list[str]) -> Path:
    prose_dir = root / "vault" / "prose"
    prose_dir.mkdir(parents=True, exist_ok=True)
    for chunk_id in chunk_ids:
        frontmatter = _chunk_frontmatter(chunk_id)
        text = "---\n" + yaml.safe_dump(frontmatter, sort_keys=False) + "---\nBody.\n"
        (prose_dir / f"{chunk_id}.md").write_text(text, encoding="utf-8")
    return root / "vault"


class _ScriptedClient:
    """A minimal `LLMClient` double keyed by pass name -- the interrogation
    call always resolves `proceed`, and the synthesis call cites whatever
    handle the test wires in. `model_for_pass`/`usage_for_pass` answer every
    pass name uniformly; `build_record`'s cost accounting never asserts on
    them here."""

    def __init__(self, synthesize_response: str) -> None:
        self._synthesize_response = synthesize_response
        self.calls: list[str] = []

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        self.calls.append(pass_name or "")
        if pass_name == INTERROGATE_PASS_NAME:
            return json.dumps({"premises_found": [], "bounds_applied": [], "refusal": None})
        if pass_name == SYNTHESIZE_PASS_NAME:
            return self._synthesize_response
        raise AssertionError(f"unexpected pass_name in this fixture: {pass_name!r}")

    def model_for_pass(self, pass_name: str | None = None) -> str:
        return "test-double-model"

    def usage_for_pass(self, pass_name: str | None = None) -> dict[str, int] | None:
        return None


def _brief() -> Brief:
    return Brief(brief_id="corridor_wiring_001", case="A case.", request="A question?")


def test_run_brief_use_map_calls_shipped_assemble_evidence_and_synthesize_with_map_ids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    chunk_ids = ["fixmap-2021-a_1_s_001", "fixmap-2021-a_1_s_002"]
    vault_dir = _write_vault(tmp_path, chunk_ids)

    fake_ask_result = AskResult(
        brief=_brief(),
        asks=("States extract resources through coercion.",),
        landed=(
            LandedPosition(
                position_id="pos-0001",
                score=0.87,
                argument="States extract resources through coercion.",
                size=2,
                sources=("fixmap-2021-a",),
                authors=("fixmap",),
                chunk_ids=tuple(chunk_ids),
            ),
        ),
        corridor=(
            CorridorPosition(
                position_id="pos-0002",
                relation_count=1,
                labels=("qualifies ->",),
                argument="A counterpart argument.",
                size=1,
                sources=("fixmap-2021-a",),
                authors=("fixmap",),
                chunk_ids=(),
            ),
        ),
        assembled_chunk_ids=tuple(chunk_ids),
        pin="fixmap-pin-001",
    )

    def _fake_run_map_ask_for_brief(brief: Brief, **_kwargs: Any) -> AskResult:
        return fake_ask_result

    monkeypatch.setattr(record_module, "run_map_ask_for_brief", _fake_run_map_ask_for_brief)

    synthesize_response = json.dumps(
        {
            "claims": [
                {
                    "text": "The corpus states that states extract resources through coercion.",
                    "kind": "a",
                    "grounds": [{"ref_type": "chunk", "ref_id": "[c1]"}],
                    "confidence": "medium",
                }
            ]
        }
    )
    client = _ScriptedClient(synthesize_response)

    result = record_module.run_brief(
        _brief(),
        client=client,
        vault_dir=vault_dir,
        lenses_dir=LENSES_DIR,
        use_map=True,
    )

    record = result.record
    # The claim's grounds resolve to the map's OWN first assembled id --
    # proof `assemble_evidence`/`synthesize` read the map's ordered ids,
    # not some other evidence set.
    assert record["claims"][0]["grounds"][0]["ref_id"] == chunk_ids[0]
    assert record["evidence"]["assembled_count"] == len(chunk_ids)

    # No name-layer trajectory -- an honest empty list, never fabricated.
    assert record["trajectory"] == []

    # What the map path did IS recorded, in its own terms.
    assert record["map_retrieval"] == {
        "used": True,
        "pin": "fixmap-pin-001",
        "asks": ["States extract resources through coercion."],
        "landed": [{"position_id": "pos-0001", "score": 0.87}],
        "corridor": [{"position_id": "pos-0002", "labels": ["qualifies ->"]}],
        "assembled_chunk_ids": list(chunk_ids),
    }
    assert DECOMPOSE_PASS_NAME in record["model_by_pass"]
    assert RETRIEVE_PASS_NAME not in record["model_by_pass"]

    # Issue #584: an empty trajectory means an empty coverage_map (§7.7
    # scope is keyed to the name-layer tools the map path never calls), and
    # that must read as NOT MEASURED, never as a measured `low` -- the map
    # arm and a thin-corpus name-arm run must not wear the same word.
    assert record["coverage_map"] == {}
    assert record["confidence"]["overall_band"] == NOT_MEASURED_BAND
    assert record["confidence"]["overall_band"] != "low"

    # The companion defect (issue #584): no name was queried at all, so the
    # source-usage denominator is unknown, not a measured zero.
    for entry in record["source_usage"]["sources"]:
        assert entry["available_chunk_count"] is None
        assert entry["available_share"] is None
        assert entry["usage_ratio"] is None


def test_run_brief_default_path_never_touches_the_map(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    chunk_ids = ["fixdef-2021-a_1_s_001"]
    vault_dir = _write_vault(tmp_path, chunk_ids)

    def _explode_if_called(*_args: Any, **_kwargs: Any) -> AskResult:
        raise AssertionError("the default path must never call the map")

    monkeypatch.setattr(record_module, "run_map_ask_for_brief", _explode_if_called)

    trajectory = [
        {
            "step": 1,
            "tool": "get_name",
            "args": {"canonical": "Fixture Name"},
            "result_ids": chunk_ids,
            "result_count": 1,
        }
    ]

    def _fake_run_planned_retrieval(*_args: Any, **_kwargs: Any) -> RetrievalResult:
        return RetrievalResult(trajectory=trajectory, evidence_ids=list(chunk_ids))

    monkeypatch.setattr(record_module, "run_planned_retrieval", _fake_run_planned_retrieval)

    synthesize_response = json.dumps(
        {
            "claims": [
                {
                    "text": "The corpus states a fixture claim.",
                    "kind": "a",
                    "grounds": [{"ref_type": "chunk", "ref_id": "[c1]"}],
                    "confidence": "medium",
                }
            ]
        }
    )
    client = _ScriptedClient(synthesize_response)

    result = record_module.run_brief(
        _brief(), client=client, vault_dir=vault_dir, lenses_dir=LENSES_DIR
    )

    record = result.record
    assert record["map_retrieval"] is None
    assert record["trajectory"] == trajectory
    assert record["claims"][0]["grounds"][0]["ref_id"] == chunk_ids[0]
    assert RETRIEVE_PASS_NAME in record["model_by_pass"]
    assert DECOMPOSE_PASS_NAME not in record["model_by_pass"]
