"""Inner unit tests for the stage-5 coverage/confidence validator (issues
#260 and #490, specs/PHASE-B.md §7.7, §7.9). Co-located under
src/axial/validators/ per the repo's existing test layout (mirrors
src/axial/validators/test_attribution.py).

Covers the map's scope rule (a name the run retrieved on AND a claim's
grounds note is a member of), `corpus_note_count` sourced from
`coverage_count` (never a recount), `evidence_note_count` as the intersection
with the page's own member list, the null-denominator case, band-boundary
derivation, config-driven overriding, determinism, zero model calls, the
three release-gate checks, the vacuous refuse-disposition pass, and the
fourth, non-blocking per-claim confidence-ceiling check (issue #550).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from axial.validators.coverage import (
    NOT_MEASURED_BAND,
    REASON_CONFIDENCE_EXCEEDS_COVERAGE,
    REASON_MISSING_CONFIDENCE_DISCLOSURE,
    REASON_MISSING_COVERAGE_ENTRY,
    compute_confidence,
    compute_coverage_map,
    confidence_ceiling_for_claim,
    coverage_band_for,
    coverage_scope,
    format_coverage_map,
    intersected_names,
    retrieved_names,
    validate_coverage_and_confidence,
)

TILLY_CHUNK_1 = "tilly-1978_001_intro_001"
TILLY_CHUNK_2 = "tilly-1978_002_intro_001"
BAYAT_CHUNK = "bayat-2017_001_intro_001"

TILLY = "Charles Tilly"
BAYAT = "Asef Bayat"
UNPAGED = "Revolution"


def _write_chunk(root: Path, chunk_id: str) -> None:
    prose_dir = root / "vault" / "prose"
    prose_dir.mkdir(parents=True, exist_ok=True)
    frontmatter = {
        "chunk_id": chunk_id,
        "section": "Synthetic Section",
        "chunk_text": "SENTINEL: synthetic prose.",
        "source_meta": {"author": "A", "title": "T", "date": 2020, "thesis": "X", "scope": "Y"},
        "schema_version": "0.1",
        "frame_version": "0.1",
        "answers": {"claim": f"Claim of {chunk_id}.", "position_of": "the author"},
    }
    text = "---\n" + yaml.safe_dump(frontmatter, sort_keys=False) + "---\nBody.\n"
    (prose_dir / f"{chunk_id}.md").write_text(text, encoding="utf-8")


def _write_name_page(root: Path, name: str, *, member_ids: list[str], member_count: int) -> None:
    """One name page carrying the `member_count` `coverage_count` reads and
    the member list `evidence_note_count` intersects with (§7.17). The two
    are deliberately separable here: the real corpus's page for a dense name
    carries a `member_count` far larger than any evidence set."""
    names_dir = root / "vault" / "names"
    names_dir.mkdir(parents=True, exist_ok=True)
    frontmatter = {"name": name, "kind": "person", "aliases": [], "member_count": member_count}
    lines = ["**Member notes:**"]
    lines += [f"- [[{chunk_id}]] — An Author (1978): A claim." for chunk_id in member_ids]
    body = yaml.safe_dump(frontmatter, sort_keys=False)
    (names_dir / f"{name}.md").write_text(
        "---\n" + body + "---\n" + "\n".join(lines) + "\n", encoding="utf-8"
    )


@pytest.fixture
def vault_dir(tmp_path: Path) -> Path:
    _write_chunk(tmp_path, TILLY_CHUNK_1)
    _write_chunk(tmp_path, TILLY_CHUNK_2)
    _write_chunk(tmp_path, BAYAT_CHUNK)
    # 240 corpus notes on Tilly, of which this fixture holds two; 6 on Bayat.
    _write_name_page(tmp_path, TILLY, member_ids=[TILLY_CHUNK_1, TILLY_CHUNK_2], member_count=240)
    _write_name_page(tmp_path, BAYAT, member_ids=[BAYAT_CHUNK], member_count=6)
    return tmp_path / "vault"


def _claim(
    claim_id: str,
    *,
    names_touched: list[str],
    grounds: list[dict[str, Any]],
    confidence: Any = "medium",
) -> dict[str, Any]:
    return {
        "claim_id": claim_id,
        "text": f"Text for {claim_id}.",
        "kind": "a",
        "grounds": grounds,
        "confidence": confidence,
        "names_touched": names_touched,
    }


def _get_name_call(canonical: str) -> dict[str, Any]:
    return {
        "step": 1,
        "tool": "get_name",
        "args": {"canonical": canonical},
        "result_ids": [],
        "result_count": 0,
    }


def _chunk_grounds(*chunk_ids: str) -> list[dict[str, Any]]:
    return [{"ref_type": "chunk", "ref_id": chunk_id} for chunk_id in chunk_ids]


def _where_names_meet_call(canonical: str, other: str) -> dict[str, Any]:
    return {
        "step": 1,
        "tool": "where_names_meet",
        "args": {"canonical": canonical, "other": other},
        "result_ids": [],
        "result_count": 0,
    }


# -- the map's scope: retrieved AND touched ----------------------------------


def test_retrieved_names_reads_both_the_canonical_arg_and_find_names_results():
    trajectory = [
        {"step": 1, "tool": "find_names", "args": {"query": "Tilly"}, "result_ids": [TILLY]},
        _get_name_call(BAYAT),
        {
            "step": 3,
            "tool": "get_chunk",
            "args": {"chunk_id": TILLY_CHUNK_1},
            "result_ids": [TILLY_CHUNK_1],
        },
    ]
    assert retrieved_names(trajectory) == {TILLY, BAYAT}


def test_intersected_names_reads_both_canonical_and_other():
    """Issue #550: `where_names_meet` takes TWO name arguments, and neither
    is folded into `NAME_ARG_TOOLS` -- a frozenset membership test there
    reads `args["canonical"]` alone and would silently drop `other`."""
    trajectory = [_where_names_meet_call(TILLY, BAYAT)]
    assert intersected_names(trajectory) == {TILLY, BAYAT}


def test_retrieved_names_includes_both_names_of_a_where_names_meet_call():
    trajectory = [_where_names_meet_call(TILLY, BAYAT)]
    assert retrieved_names(trajectory) == {TILLY, BAYAT}


def test_an_intersection_alone_puts_both_names_in_the_coverage_scope(vault_dir: Path):
    """Issue #550's own named acceptance scenario: a trajectory with one
    `where_names_meet` and no other name query still puts both names in the
    §7.7 coverage scope -- a claim resting on notes found only at an
    intersection must not go undisclosed."""
    claims = [_claim("c-1", names_touched=[TILLY, BAYAT], grounds=_chunk_grounds(TILLY_CHUNK_1))]
    trajectory = [_where_names_meet_call(TILLY, BAYAT)]
    assert coverage_scope(claims, trajectory) == sorted([TILLY, BAYAT])


def test_compute_coverage_map_covers_a_name_reached_only_via_intersection(vault_dir: Path):
    claims = [_claim("c-1", names_touched=[TILLY, BAYAT], grounds=_chunk_grounds(TILLY_CHUNK_1))]
    trajectory = [_where_names_meet_call(TILLY, BAYAT)]
    coverage_map = compute_coverage_map(claims, trajectory=trajectory, vault_dir=vault_dir)
    assert set(coverage_map) == {TILLY, BAYAT}


def test_coverage_count_tool_results_never_enter_the_scope():
    """As a §7.5 tool `coverage_count` returns EVERY canonical in the index
    (62,821 on the real corpus). That is the whole-index table §7.2 rules
    out, so it is never a retrieved name."""
    trajectory = [
        {"step": 1, "tool": "coverage_count", "args": {}, "result_ids": [TILLY, BAYAT, UNPAGED]}
    ]
    assert retrieved_names(trajectory) == set()


def test_a_name_touched_but_never_retrieved_on_is_out_of_scope(vault_dir: Path):
    """The measured reason the map is not keyed on `names_touched` alone: a
    real 24-note evidence set's grounds notes name 423 distinct canonicals on
    average, mostly one-off mentions, and keying on all of them pins overall
    confidence to `low` on every brief."""
    claims = [_claim("c-1", names_touched=[TILLY, BAYAT], grounds=_chunk_grounds(TILLY_CHUNK_1))]
    trajectory = [_get_name_call(TILLY)]
    assert coverage_scope(claims, trajectory) == [TILLY]
    assert list(compute_coverage_map(claims, trajectory=trajectory, vault_dir=vault_dir)) == [TILLY]


def test_a_name_retrieved_on_but_touched_by_no_claim_is_out_of_scope(vault_dir: Path):
    claims = [_claim("c-1", names_touched=[TILLY], grounds=_chunk_grounds(TILLY_CHUNK_1))]
    trajectory = [_get_name_call(TILLY), _get_name_call(BAYAT)]
    assert coverage_scope(claims, trajectory) == [TILLY]


def test_a_name_in_five_claims_yields_one_map_entry(vault_dir: Path):
    grounds = _chunk_grounds(TILLY_CHUNK_1)
    claims = [_claim(f"c-{i}", names_touched=[TILLY], grounds=grounds) for i in range(5)]
    coverage_map = compute_coverage_map(
        claims, trajectory=[_get_name_call(TILLY)], vault_dir=vault_dir
    )
    assert list(coverage_map) == [TILLY]


def test_no_claims_yields_empty_map(vault_dir: Path):
    assert compute_coverage_map([], trajectory=[_get_name_call(TILLY)], vault_dir=vault_dir) == {}


def test_no_trajectory_yields_empty_map(vault_dir: Path):
    claims = [_claim("c-1", names_touched=[TILLY], grounds=_chunk_grounds(TILLY_CHUNK_1))]
    assert compute_coverage_map(claims, vault_dir=vault_dir) == {}


# -- corpus_note_count: from coverage_count, never a recount -----------------


def test_corpus_note_count_comes_from_coverage_count_not_a_recount(
    vault_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    calls: list[Path | None] = []
    import axial.validators.coverage as coverage_module

    real_coverage_count = coverage_module.coverage_count

    def spy_coverage_count(*, vault_dir=None):
        calls.append(vault_dir)
        return real_coverage_count(vault_dir=vault_dir)

    monkeypatch.setattr(coverage_module, "coverage_count", spy_coverage_count)

    claims = [_claim("c-1", names_touched=[TILLY], grounds=_chunk_grounds(TILLY_CHUNK_1))]
    coverage_map = compute_coverage_map(
        claims, trajectory=[_get_name_call(TILLY)], vault_dir=vault_dir
    )

    assert calls == [vault_dir], "corpus_note_count must call coverage_count, not recount"
    # The page's own member_count (240), not the two members this fixture
    # vault happens to hold.
    assert coverage_map[TILLY]["corpus_note_count"] == 240


def test_a_name_with_no_page_carries_a_null_count_and_the_most_conservative_band(
    vault_dir: Path,
):
    """The live index really does carry names the vault holds no page for
    (`Revolution`, measured 2026-07-30). §7.5 refuses to fill that in with a
    0 that would read as real, thin coverage -- so the count stays `null`
    and the band is `thin`, the most conservative reading, never dressed up
    as a number."""
    claims = [_claim("c-1", names_touched=[UNPAGED], grounds=_chunk_grounds(TILLY_CHUNK_1))]
    coverage_map = compute_coverage_map(
        claims, trajectory=[_get_name_call(UNPAGED)], vault_dir=vault_dir
    )
    assert coverage_map[UNPAGED]["corpus_note_count"] is None
    assert coverage_map[UNPAGED]["coverage_band"] == "thin"
    assert coverage_map[UNPAGED]["evidence_note_count"] == 0


# -- evidence_note_count: the intersection with the page's member list -------


def test_evidence_note_count_is_the_intersection_with_the_pages_members(vault_dir: Path):
    claims = [
        _claim(
            "c-1",
            names_touched=[TILLY],
            grounds=_chunk_grounds(TILLY_CHUNK_1, TILLY_CHUNK_2, BAYAT_CHUNK),
        )
    ]
    coverage_map = compute_coverage_map(
        claims, trajectory=[_get_name_call(TILLY)], vault_dir=vault_dir
    )
    # Three grounds notes, two of them members of the Tilly page.
    assert coverage_map[TILLY]["evidence_note_count"] == 2


def test_evidence_note_count_dedupes_the_same_chunk_cited_by_two_claims(vault_dir: Path):
    grounds = _chunk_grounds(TILLY_CHUNK_1)
    claims = [
        _claim("c-1", names_touched=[TILLY], grounds=grounds),
        _claim("c-2", names_touched=[TILLY], grounds=grounds),
    ]
    coverage_map = compute_coverage_map(
        claims, trajectory=[_get_name_call(TILLY)], vault_dir=vault_dir
    )
    assert coverage_map[TILLY]["evidence_note_count"] == 1


def test_evidence_note_count_sees_a_member_past_get_names_own_cap(tmp_path: Path):
    """issue #505: `get_name` now defaults to a `limit` of 10. This
    intersection is correctness-critical -- unlike a retrieval-loop caller
    that can deliberately re-ask, `_evidence_note_count` must never silently
    undercount a real member past the cap, or a run's own grounds would read
    as uncovered. Twelve real members, and the grounds note is the 11th."""
    member_ids = [f"tilly-1978_{i:03d}_intro_001" for i in range(1, 13)]
    for chunk_id in member_ids:
        _write_chunk(tmp_path, chunk_id)
    _write_name_page(tmp_path, TILLY, member_ids=member_ids, member_count=len(member_ids))
    vault = tmp_path / "vault"

    eleventh = member_ids[10]
    claims = [_claim("c-1", names_touched=[TILLY], grounds=_chunk_grounds(eleventh))]
    coverage_map = compute_coverage_map(claims, trajectory=[_get_name_call(TILLY)], vault_dir=vault)

    assert coverage_map[TILLY]["evidence_note_count"] == 1, (
        "a member past get_name's default cap must still be found, not silently undercounted"
    )


def test_artifact_grounds_never_contribute_to_evidence_count(vault_dir: Path):
    claims = [
        _claim(
            "c-1",
            names_touched=[TILLY],
            grounds=[{"ref_type": "artifact", "ref_id": "some-artifact"}],
        )
    ]
    coverage_map = compute_coverage_map(
        claims, trajectory=[_get_name_call(TILLY)], vault_dir=vault_dir
    )
    assert coverage_map[TILLY]["evidence_note_count"] == 0


# -- band derivation at the boundaries ---------------------------------------


@pytest.mark.parametrize(
    "count,expected",
    [
        (None, "thin"),
        (0, "thin"),
        (19, "thin"),
        (20, "moderate"),
        (99, "moderate"),
        (100, "dense"),
        (1000, "dense"),
    ],
)
def test_band_boundaries(count: int | None, expected: str):
    assert coverage_band_for(count, moderate_floor=20, dense_floor=100) == expected


def test_overriding_coverage_bands_config_changes_the_band(vault_dir: Path, tmp_path: Path):
    config_path = tmp_path / "pipeline.yaml"
    config_path.write_text(
        yaml.safe_dump({"coverage_bands": {"moderate_floor": 300, "dense_floor": 900}}),
        encoding="utf-8",
    )
    claims = [_claim("c-1", names_touched=[TILLY], grounds=_chunk_grounds(TILLY_CHUNK_1))]
    trajectory = [_get_name_call(TILLY)]
    # 240 corpus notes on Tilly -- "thin" under the overridden thresholds,
    # "dense" under the module defaults.
    coverage_map = compute_coverage_map(
        claims, trajectory=trajectory, vault_dir=vault_dir, config_path=config_path
    )
    assert coverage_map[TILLY]["coverage_band"] == "thin"

    default_map = compute_coverage_map(claims, trajectory=trajectory, vault_dir=vault_dir)
    assert default_map[TILLY]["coverage_band"] == "dense"


# -- determinism --------------------------------------------------------------


def test_same_record_over_same_vault_yields_byte_identical_map(vault_dir: Path):
    claims = [
        _claim(
            "c-1",
            names_touched=[TILLY, BAYAT],
            grounds=_chunk_grounds(TILLY_CHUNK_1, BAYAT_CHUNK),
        )
    ]
    trajectory = [_get_name_call(TILLY), _get_name_call(BAYAT)]
    first = compute_coverage_map(claims, trajectory=trajectory, vault_dir=vault_dir)
    second = compute_coverage_map(claims, trajectory=trajectory, vault_dir=vault_dir)
    assert first == second
    assert list(first.keys()) == sorted(first.keys())


# -- inspection affordance formatting ----------------------------------------


def test_format_coverage_map_prints_every_name():
    rendered = format_coverage_map(
        {
            TILLY: {
                "corpus_note_count": 240,
                "evidence_note_count": 5,
                "coverage_band": "dense",
            },
            BAYAT: {"corpus_note_count": 6, "evidence_note_count": 1, "coverage_band": "thin"},
        }
    )
    assert TILLY in rendered
    assert BAYAT in rendered
    assert "240" in rendered
    assert "thin" in rendered


def test_format_coverage_map_empty_is_not_blank():
    assert format_coverage_map({}) != ""


# -- compute_confidence: derived deterministically from coverage_map ---------


def test_all_dense_yields_high_overall_band():
    coverage_map = {
        TILLY: {"corpus_note_count": 240, "evidence_note_count": 5, "coverage_band": "dense"}
    }
    confidence = compute_confidence(coverage_map)
    assert confidence["overall_band"] == "high"
    assert TILLY in confidence["rationale"]
    assert "240" in confidence["rationale"]


def test_thin_name_never_yields_high_overall_band():
    """The release gate's own `confidence_exceeds_coverage` invariant: a thin
    name in the map must never coexist with a top-band overall confidence --
    `compute_confidence` must satisfy this by construction."""
    coverage_map = {
        TILLY: {"corpus_note_count": 240, "evidence_note_count": 5, "coverage_band": "dense"},
        BAYAT: {"corpus_note_count": 6, "evidence_note_count": 1, "coverage_band": "thin"},
    }
    confidence = compute_confidence(coverage_map)
    assert confidence["overall_band"] != "high"
    assert BAYAT in confidence["rationale"]


def test_overall_band_is_bounded_by_the_worst_touched_name():
    coverage_map = {
        TILLY: {"corpus_note_count": 50, "evidence_note_count": 5, "coverage_band": "moderate"},
        BAYAT: {"corpus_note_count": 6, "evidence_note_count": 1, "coverage_band": "thin"},
    }
    assert compute_confidence(coverage_map)["overall_band"] == "low"


def test_the_rationale_carries_every_mapped_names_counts():
    """§7.4/§7.10: a band is never rendered without the counts that justify
    it, and that binds the rationale too."""
    coverage_map = {
        TILLY: {"corpus_note_count": 240, "evidence_note_count": 5, "coverage_band": "dense"},
        BAYAT: {"corpus_note_count": 6, "evidence_note_count": 1, "coverage_band": "thin"},
    }
    rationale = compute_confidence(coverage_map)["rationale"]
    for token in (TILLY, BAYAT, "240", "6", "dense", "thin"):
        assert token in rationale


def test_empty_coverage_map_yields_not_measured_band_with_a_plain_rationale():
    """Issue #584: an empty map is the absence of a measurement, not a
    measured `low` -- `overall_band` says so in its own vocabulary, and the
    rationale states plainly that nothing was measured."""
    confidence = compute_confidence({})
    assert confidence["overall_band"] == NOT_MEASURED_BAND
    assert confidence["overall_band"] != "low"
    assert confidence["rationale"]
    assert (
        "not measured" in confidence["rationale"]
        or "nothing was measured" in confidence["rationale"]
    )


def test_not_measured_and_measured_thin_are_distinguishable():
    """A coverage map whose worst entry is `thin` still yields a MEASURED
    `low`, never collapsed with the not-measured band an empty map yields
    (issue #584): the two must be tellable apart by a reader or a gate."""
    thin_map = {BAYAT: {"corpus_note_count": 6, "evidence_note_count": 1, "coverage_band": "thin"}}
    measured = compute_confidence(thin_map)
    not_measured = compute_confidence({})

    assert measured["overall_band"] == "low"
    assert not_measured["overall_band"] == NOT_MEASURED_BAND
    assert measured["overall_band"] != not_measured["overall_band"]


def test_confidence_disclosure_is_never_nullable():
    for coverage_map in ({}, {TILLY: {"corpus_note_count": 1, "coverage_band": "thin"}}):
        confidence = compute_confidence(coverage_map)
        assert confidence["overall_band"]
        assert confidence["rationale"]


def test_not_measured_band_is_outside_the_ranked_vocabulary():
    """The not-measured band is not a rung on the three-band ordinal (issue
    #584): nothing in the module's own rank tables recognizes it as a
    measured band."""
    from axial.validators.coverage import _CONFIDENCE_BAND_BY_COVERAGE_RANK, _CONFIDENCE_BAND_RANK

    assert NOT_MEASURED_BAND not in _CONFIDENCE_BAND_BY_COVERAGE_RANK.values()
    assert NOT_MEASURED_BAND not in _CONFIDENCE_BAND_RANK


# -- validate_coverage_and_confidence: presence checks -----------------------


def _record(
    *,
    claims: list[dict[str, Any]],
    coverage_map: dict[str, Any],
    confidence: Any,
    trajectory: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "claims": claims,
        "coverage_map": coverage_map,
        "confidence": confidence,
        "trajectory": trajectory or [],
    }


def test_name_in_scope_but_absent_from_map_fails():
    claims = [_claim("c-1", names_touched=[BAYAT], grounds=[])]
    record = _record(
        claims=claims,
        coverage_map={},
        confidence={"overall_band": "medium", "rationale": "x"},
        trajectory=[_get_name_call(BAYAT)],
    )
    report = validate_coverage_and_confidence(record)
    assert not report.passed
    assert report.failures[0].reason == REASON_MISSING_COVERAGE_ENTRY
    assert BAYAT in report.failures[0].detail


def test_complete_map_and_valid_confidence_passes():
    claims = [_claim("c-1", names_touched=[TILLY], grounds=[])]
    record = _record(
        claims=claims,
        coverage_map={
            TILLY: {"corpus_note_count": 240, "evidence_note_count": 5, "coverage_band": "dense"}
        },
        confidence={"overall_band": "medium", "rationale": "240 corpus notes, 5 evidence notes"},
        trajectory=[_get_name_call(TILLY)],
    )
    report = validate_coverage_and_confidence(record)
    assert report.passed, report.failures


def test_not_measured_band_passes_the_release_gate():
    """A record whose `coverage_map` is empty by construction (a `refuse`
    disposition, or a run whose retrieval path queries no name) still
    releases: check 2 only requires a non-blank `overall_band` and a
    non-empty `rationale`, and check 3 keys on `== TOP_CONFIDENCE_BAND`,
    which `not_measured` is not (issue #584)."""
    record = _record(
        claims=[],
        coverage_map={},
        confidence=compute_confidence({}),
    )
    report = validate_coverage_and_confidence(record)
    assert report.passed, report.failures


@pytest.mark.parametrize(
    "confidence",
    [
        {"overall_band": None, "rationale": ""},
        {"overall_band": "", "rationale": "x"},
        {"overall_band": "medium", "rationale": ""},
        {"overall_band": "medium", "rationale": "   "},
        {},
        None,
    ],
)
def test_absent_null_or_empty_confidence_fails(confidence: Any):
    record = _record(claims=[], coverage_map={}, confidence=confidence)
    report = validate_coverage_and_confidence(record)
    assert not report.passed
    assert report.failures[0].reason == REASON_MISSING_CONFIDENCE_DISCLOSURE


# -- validate_coverage_and_confidence: confidence-vs-coverage check ----------


def test_top_band_confidence_with_thin_name_fails():
    claims = [_claim("c-1", names_touched=[BAYAT], grounds=[])]
    record = _record(
        claims=claims,
        coverage_map={
            BAYAT: {"corpus_note_count": 6, "evidence_note_count": 1, "coverage_band": "thin"}
        },
        confidence={"overall_band": "high", "rationale": "6 corpus notes"},
        trajectory=[_get_name_call(BAYAT)],
    )
    report = validate_coverage_and_confidence(record)
    assert not report.passed
    assert report.failures[0].reason == REASON_CONFIDENCE_EXCEEDS_COVERAGE
    assert BAYAT in report.failures[0].detail


def test_top_band_confidence_with_no_thin_name_passes():
    claims = [_claim("c-1", names_touched=[TILLY], grounds=[])]
    record = _record(
        claims=claims,
        coverage_map={
            TILLY: {"corpus_note_count": 240, "evidence_note_count": 5, "coverage_band": "dense"}
        },
        confidence={"overall_band": "high", "rationale": "240 corpus notes"},
        trajectory=[_get_name_call(TILLY)],
    )
    report = validate_coverage_and_confidence(record)
    assert report.passed, report.failures


def test_lower_band_confidence_with_thin_name_passes():
    claims = [_claim("c-1", names_touched=[BAYAT], grounds=[])]
    record = _record(
        claims=claims,
        coverage_map={
            BAYAT: {"corpus_note_count": 6, "evidence_note_count": 1, "coverage_band": "thin"}
        },
        confidence={"overall_band": "low", "rationale": "6 corpus notes"},
        trajectory=[_get_name_call(BAYAT)],
    )
    report = validate_coverage_and_confidence(record)
    assert report.passed, report.failures


# -- refuse disposition: vacuous pass -----------------------------------------


def test_refuse_disposition_empty_claims_yields_empty_map_and_passes_vacuously():
    record = _record(
        claims=[],
        coverage_map={},
        confidence={"overall_band": "low", "rationale": "refused; no synthesis was attempted"},
    )
    report = validate_coverage_and_confidence(record)
    assert report.passed
    assert report.failures == []


def test_claims_key_absent_passes_vacuously_for_the_coverage_check():
    # Only the coverage-entry check is vacuous on absent claims; confidence
    # is still required (§7.3 marks it non-nullable even on refusal).
    report = validate_coverage_and_confidence(
        {"confidence": {"overall_band": "low", "rationale": "x"}}
    )
    assert report.passed


# -- per-claim confidence ceiling: clamp, never fail (issue #550) -----------


def test_confidence_ceiling_is_the_worst_touched_names_coverage_band():
    coverage_map = {
        TILLY: {"corpus_note_count": 240, "evidence_note_count": 5, "coverage_band": "dense"},
        BAYAT: {"corpus_note_count": 6, "evidence_note_count": 1, "coverage_band": "thin"},
    }
    claim = _claim("c-1", names_touched=[TILLY, BAYAT], grounds=[], confidence="high")
    result = confidence_ceiling_for_claim(claim, coverage_map)
    assert result.ceiling == "low"
    assert result.emitted == "high"
    assert result.effective_band == "low"
    assert result.clamped is True


def test_confidence_within_its_own_ceiling_is_not_clamped():
    coverage_map = {
        TILLY: {"corpus_note_count": 240, "evidence_note_count": 5, "coverage_band": "dense"}
    }
    claim = _claim("c-1", names_touched=[TILLY], grounds=[], confidence="medium")
    result = confidence_ceiling_for_claim(claim, coverage_map)
    assert result.ceiling == "high"
    assert result.effective_band == "medium"
    assert result.clamped is False


def test_a_dense_claim_ignores_a_thin_name_some_OTHER_claim_touches():
    """The measured reason the RUN band is useless as a per-claim ceiling
    (issue #550): a claim resting only on its own dense names must not be
    dragged down by a thin name elsewhere in the SAME answer's coverage_map,
    the way `compute_confidence`'s run-level derivation is."""
    coverage_map = {
        TILLY: {"corpus_note_count": 240, "evidence_note_count": 5, "coverage_band": "dense"},
        BAYAT: {"corpus_note_count": 6, "evidence_note_count": 1, "coverage_band": "thin"},
    }
    claim = _claim("c-1", names_touched=[TILLY], grounds=[], confidence="high")
    result = confidence_ceiling_for_claim(claim, coverage_map)
    assert result.ceiling == "high"
    assert result.clamped is False


def test_no_touched_name_in_the_coverage_map_leaves_the_ceiling_undecided():
    """A claim whose own `names_touched` are all absent from `coverage_map`
    (the run never retrieved on any of them) has no denominator to derive a
    ceiling from -- left unclamped rather than guessed at, never a
    fabricated `low`."""
    claim = _claim("c-1", names_touched=["Some Untouched Name"], grounds=[], confidence="high")
    result = confidence_ceiling_for_claim(claim, {})
    assert result.ceiling is None
    assert result.effective_band == "high"
    assert result.clamped is False


def test_an_invalid_emitted_confidence_passes_through_unclamped():
    coverage_map = {
        BAYAT: {"corpus_note_count": 6, "evidence_note_count": 1, "coverage_band": "thin"}
    }
    claim = _claim("c-1", names_touched=[BAYAT], grounds=[], confidence="medium-high")
    result = confidence_ceiling_for_claim(claim, coverage_map)
    assert result.ceiling == "low"
    assert result.effective_band == "medium-high"
    assert result.clamped is False


def test_validate_coverage_and_confidence_reports_the_clamped_count_without_failing():
    claims = [
        _claim("c-1", names_touched=[BAYAT], grounds=[], confidence="high"),
        _claim("c-2", names_touched=[TILLY], grounds=[], confidence="medium"),
    ]
    record = _record(
        claims=claims,
        coverage_map={
            TILLY: {"corpus_note_count": 240, "evidence_note_count": 5, "coverage_band": "dense"},
            BAYAT: {"corpus_note_count": 6, "evidence_note_count": 1, "coverage_band": "thin"},
        },
        confidence={"overall_band": "low", "rationale": "x"},
        trajectory=[_get_name_call(TILLY), _get_name_call(BAYAT)],
    )
    report = validate_coverage_and_confidence(record)
    assert report.passed, report.failures
    assert report.clamped_claim_ids == ["c-1"]
    assert report.clamped_count == 1


def test_no_claim_is_clamped_yields_an_empty_list_not_none():
    record = _record(
        claims=[],
        coverage_map={},
        confidence={"overall_band": "low", "rationale": "refused; no synthesis was attempted"},
    )
    report = validate_coverage_and_confidence(record)
    assert report.clamped_claim_ids == []
    assert report.clamped_count == 0


# -- model-free by construction -----------------------------------------------


def test_validate_and_compute_take_no_llm_client_at_all():
    """`validate_coverage_and_confidence` and `compute_coverage_map` accept
    no client parameter -- nothing here can make a model call, so the
    `explode` provider installed at the CLI layer never fires by
    construction, not by a check that happens not to trip it."""
    import inspect

    assert "client" not in inspect.signature(validate_coverage_and_confidence).parameters
    assert "client" not in inspect.signature(compute_coverage_map).parameters
