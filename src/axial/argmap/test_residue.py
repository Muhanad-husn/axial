"""Unit tests for `axial.argmap.residue` (issue #651): section blocking,
prompt rendering, and the content-keyed decision log. Offline throughout --
a fake encoder (a fixed-width hashed bag-of-words, no sentence-transformers
dependency) and a scripted stub client, mirroring
`tests.analysis.test_argmap_positions._ScriptedClient`'s own local-fixture
pattern. No `data/` dependence: every fixture builds its own tiny corpus.
"""

from __future__ import annotations

import json
import zlib
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from axial.llm import StubLLMClient
from axial.argmap.residue import (
    CANDIDATE_TOP_K,
    ModeResult,
    UnresolvedTarget,
    build_section_index,
    decision_key,
    embed_positions,
    find_unresolved_targets,
    load_decisions,
    render_residue_prompt,
    resolve_target,
    run_residue_sample,
    seeded_sample_targets,
    select_candidates,
)

# ---------------------------------------------------------------------------
# A fake encoder: a fixed-width hashed bag-of-words. Unlike a vocabulary
# built fresh from whatever batch is passed, this is comparable ACROSS
# separate calls -- which the real code relies on, since
# `embed_positions`/`_nearest_candidates` embed the position pool and each
# target's text in separate `encode` calls that must land in the same
# vector space.
#
# **`zlib.crc32`, never the builtin `hash()`.** `hash()` on a `str` is salted
# per interpreter process (`PYTHONHASHSEED`, randomized by default since
# Python 3.3) precisely so untrusted input can't be hash-flooded -- which
# means a test asserting a specific bucket a word lands in
# (`test_select_candidates_narrows_to_top_k`) passed or failed depending on
# nothing this test controlled, roughly 1 run in 3-4. `crc32` is a fixed,
# unsalted function of the bytes alone: the same word lands in the same
# bucket in every process, forever.
# ---------------------------------------------------------------------------

_HASH_DIM = 64


def _hashing_encode(texts: Sequence[str]) -> np.ndarray:
    vectors = np.zeros((len(texts), _HASH_DIM), dtype=float)
    for row, text in enumerate(texts):
        for word in text.lower().split():
            bucket = zlib.crc32(word.encode("utf-8")) % _HASH_DIM
            vectors[row, bucket] += 1.0
    return vectors


class _ScriptedClient(StubLLMClient):
    """Mirrors `tests.analysis.test_argmap_positions._ScriptedClient`: a
    fixed response (or one popped per call), never a real request."""

    def __init__(self, responses: str | list[str]) -> None:
        super().__init__()
        self._responses = [responses] if isinstance(responses, str) else list(responses)
        self.prompts: list[str] = []

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        self.prompts.append(prompt)
        response = self._responses[min(self.call_count, len(self._responses) - 1)]
        self.call_count += 1
        return response

    def model_for_pass(self, pass_name: str | None = None) -> str:
        return "scripted"

    def usage_for_pass(self, pass_name: str | None = None) -> dict[str, int] | None:
        return {"prompt_tokens": 10 * self.call_count, "completion_tokens": self.call_count}


def _select(
    target: UnresolvedTarget,
    positions_by_id: dict[str, dict[str, Any]],
    section_index: dict[str, list[str]],
    *,
    use_section_blocking: bool,
    top_k: int = CANDIDATE_TOP_K,
) -> list[dict[str, Any]]:
    """Test-local shorthand: builds `position_vectors` from
    `positions_by_id` and calls `select_candidates` -- every real caller
    (`run_residue_sample`) builds this map once up front too."""
    vectors = embed_positions(list(positions_by_id.values()), _hashing_encode)
    return select_candidates(
        target,
        positions_by_id,
        section_index,
        vectors,
        _hashing_encode,
        use_section_blocking=use_section_blocking,
        top_k=top_k,
    )


# ---------------------------------------------------------------------------
# find_unresolved_targets
# ---------------------------------------------------------------------------


def _write_answers(answers_dir: Path, source_id: str, records: list[dict[str, Any]]) -> None:
    answers_dir.mkdir(parents=True, exist_ok=True)
    with (answers_dir / f"{source_id}.jsonl").open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")


def _write_names(names_dir: Path, nodes: list[dict[str, Any]]) -> None:
    names_dir.mkdir(parents=True, exist_ok=True)
    (names_dir / "alias_map.json").write_text(
        json.dumps({"version": 1, "nodes": nodes}), encoding="utf-8"
    )


def test_find_unresolved_targets_keeps_only_targets_with_no_phrase_join(tmp_path: Path) -> None:
    answers_dir = tmp_path / "answers"
    names_dir = tmp_path / "names"
    _write_names(names_dir, [{"canonical": "Michael Mann", "kind": "person", "aliases": []}])
    _write_answers(
        answers_dir,
        "alpha-2020-book",
        [
            {
                "source_id": "alpha-2020-book",
                "chunk_id": "alpha-2020-book_001_intro_001",
                "section": "Introduction",
                "answers": {"arguing_against": ["the argument Michael Mann makes about power"]},
            },
            {
                "source_id": "alpha-2020-book",
                "chunk_id": "alpha-2020-book_002_intro_002",
                "section": "Introduction",
                "answers": {"arguing_against": ["the single right-left continuum of regimes"]},
            },
        ],
    )

    unresolved, sections = find_unresolved_targets(answers_dir, names_dir)

    assert [target.target for target in unresolved] == [
        "the single right-left continuum of regimes"
    ]
    assert unresolved[0].chunk_id == "alpha-2020-book_002_intro_002"
    assert unresolved[0].section == "Introduction"
    assert sections["alpha-2020-book_001_intro_001"] == "Introduction"


def test_find_unresolved_targets_ignores_abstained_and_malformed_records(tmp_path: Path) -> None:
    answers_dir = tmp_path / "answers"
    names_dir = tmp_path / "names"
    _write_names(names_dir, [])
    _write_answers(
        answers_dir,
        "alpha-2020-book",
        [
            {
                "source_id": "alpha-2020-book",
                "chunk_id": "alpha-2020-book_001_intro_001",
                "answers": {"arguing_against": "not-in-passage"},
            },
            {"source_id": "alpha-2020-book", "chunk_id": "alpha-2020-book_002_intro_002"},
            {
                "source_id": "alpha-2020-book",
                "chunk_id": "alpha-2020-book_003_intro_003",
                "answers": {"arguing_against": ["a genuinely unjoinable claim"]},
            },
        ],
    )

    unresolved, _sections = find_unresolved_targets(answers_dir, names_dir)

    assert len(unresolved) == 1
    assert unresolved[0].target == "a genuinely unjoinable claim"


# ---------------------------------------------------------------------------
# seeded_sample_targets
# ---------------------------------------------------------------------------


def _targets(n: int) -> list[UnresolvedTarget]:
    return [
        UnresolvedTarget(f"c{i:03d}", "alpha-2020-book", f"target {i}", "Introduction")
        for i in range(n)
    ]


def test_seeded_sample_is_deterministic_and_size_bounded() -> None:
    pool = _targets(20)

    first = seeded_sample_targets(pool, size=5, seed=7)
    second = seeded_sample_targets(pool, size=5, seed=7)
    different_seed = seeded_sample_targets(pool, size=5, seed=8)

    assert first == second
    assert len(first) == 5
    assert first != different_seed


def test_seeded_sample_never_exceeds_the_pool() -> None:
    pool = _targets(3)
    assert len(seeded_sample_targets(pool, size=100, seed=1)) == 3


# ---------------------------------------------------------------------------
# embed_positions
# ---------------------------------------------------------------------------


def test_embed_positions_is_keyed_by_position_id_and_normalized() -> None:
    positions = [
        {"position_id": "pos-0002", "argument": "ethnicity is constructed"},
        {"position_id": "pos-0001", "argument": "states extract resources"},
    ]

    vectors = embed_positions(positions, _hashing_encode)

    assert set(vectors) == {"pos-0001", "pos-0002"}
    for vector in vectors.values():
        assert abs(float(np.linalg.norm(vector)) - 1.0) < 1e-9


# ---------------------------------------------------------------------------
# Section blocking
# ---------------------------------------------------------------------------


def test_build_section_index_groups_positions_by_member_section() -> None:
    positions = [
        {"position_id": "pos-0001", "argument": "A", "chunk_ids": ["c1", "c2"]},
        {"position_id": "pos-0002", "argument": "B", "chunk_ids": ["c3"]},
    ]
    chunk_sections = {"c1": "Introduction", "c2": "Conclusion", "c3": "Introduction"}

    index = build_section_index(positions, chunk_sections)

    assert index["Introduction"] == ["pos-0001", "pos-0002"]
    assert index["Conclusion"] == ["pos-0001"]


def test_select_candidates_falls_back_to_full_set_when_bucket_is_empty() -> None:
    positions_by_id = {
        "pos-0001": {"position_id": "pos-0001", "argument": "states extract resources"},
        "pos-0002": {"position_id": "pos-0002", "argument": "ethnicity is constructed"},
    }
    section_index: dict[str, list[str]] = {}  # no section carries any position
    target = UnresolvedTarget("c1", "alpha-2020-book", "states extract resources by force", "Notes")

    candidates = _select(target, positions_by_id, section_index, use_section_blocking=True)

    assert {c["position_id"] for c in candidates} == {"pos-0001", "pos-0002"}


def test_select_candidates_restricts_to_the_section_bucket_when_blocking_is_on() -> None:
    positions_by_id = {
        "pos-0001": {"position_id": "pos-0001", "argument": "states extract resources"},
        "pos-0002": {"position_id": "pos-0002", "argument": "ethnicity is constructed"},
    }
    section_index = {"Introduction": ["pos-0001"]}
    target = UnresolvedTarget(
        "c1", "alpha-2020-book", "ethnicity is constructed socially", "Introduction"
    )

    blocked = _select(target, positions_by_id, section_index, use_section_blocking=True)
    unblocked = _select(target, positions_by_id, section_index, use_section_blocking=False)

    # Blocked: only the bucketed position is ever offered, even though it is
    # not the better semantic match -- blocking narrows before matching, it
    # does not itself decide.
    assert [c["position_id"] for c in blocked] == ["pos-0001"]
    # Unblocked: the closer match (shares three of four words) ranks first.
    assert unblocked[0]["position_id"] == "pos-0002"


def test_select_candidates_narrows_to_top_k() -> None:
    positions_by_id = {
        f"pos-{i:04d}": {"position_id": f"pos-{i:04d}", "argument": f"argument number {i}"}
        for i in range(50)
    }
    target = UnresolvedTarget("c1", "alpha-2020-book", "argument number 7", None)

    candidates = _select(target, positions_by_id, {}, use_section_blocking=False, top_k=5)

    assert len(candidates) == 5
    assert candidates[0]["position_id"] == "pos-0007"


def test_candidate_top_k_constant_is_reasonable() -> None:
    # The module docstring's own cost arithmetic caps this in the tens, not
    # hundreds -- a regression here (someone widening it back toward the
    # full map) would silently blow the cost model this module documents.
    assert 1 <= CANDIDATE_TOP_K <= 50


# ---------------------------------------------------------------------------
# Prompt rendering
# ---------------------------------------------------------------------------


def test_render_residue_prompt_lists_every_candidate_by_handle() -> None:
    candidates = [
        {"position_id": "pos-0001", "argument": "States extract resources through coercion."},
        {"position_id": "pos-0002", "argument": "Ethnicity is socially constructed."},
    ]

    prompt = render_residue_prompt("a target claim", candidates)

    assert '"a target claim"' in prompt
    assert "[pos-0001] States extract resources through coercion." in prompt
    assert "[pos-0002] Ethnicity is socially constructed." in prompt


def test_render_residue_prompt_handles_no_candidates() -> None:
    prompt = render_residue_prompt("a target claim", [])
    assert "(no candidates)" in prompt


# ---------------------------------------------------------------------------
# Decision-log keying
# ---------------------------------------------------------------------------


def test_decision_key_is_content_addressed_on_the_rendered_prompt() -> None:
    same_a = render_residue_prompt("x", [{"position_id": "pos-0001", "argument": "A"}])
    same_b = render_residue_prompt("x", [{"position_id": "pos-0001", "argument": "A"}])
    different_target = render_residue_prompt("y", [{"position_id": "pos-0001", "argument": "A"}])
    different_candidates = render_residue_prompt(
        "x", [{"position_id": "pos-0002", "argument": "B"}]
    )

    assert decision_key(same_a) == decision_key(same_b)
    assert decision_key(same_a) != decision_key(different_target)
    assert decision_key(same_a) != decision_key(different_candidates)


def test_resolve_target_drops_an_invented_position_id() -> None:
    target = UnresolvedTarget("c1", "alpha-2020-book", "a target claim", "Introduction")
    candidates = [{"position_id": "pos-0001", "argument": "A real position."}]
    client = _ScriptedClient(json.dumps({"matches": ["pos-0001", "pos-9999"]}))

    record = resolve_target(target, candidates, client, mode="blocked")

    assert record["matches"] == ["pos-0001"]
    assert record["key"] == decision_key(render_residue_prompt("a target claim", candidates))


def test_resolve_target_records_an_error_without_raising() -> None:
    target = UnresolvedTarget("c1", "alpha-2020-book", "a target claim", None)
    client = _ScriptedClient("not json at all")

    record = resolve_target(target, [], client, mode="unblocked")

    assert record["matches"] == []
    assert "error" in record


def test_run_residue_sample_reuses_a_decision_already_on_disk(tmp_path: Path) -> None:
    positions = [{"position_id": "pos-0001", "argument": "states extract resources"}]
    chunk_sections: dict[str, str] = {}
    targets = [UnresolvedTarget("c1", "alpha-2020-book", "states extract resources by force", None)]
    decisions_path = tmp_path / "residue_decisions.jsonl"
    client = _ScriptedClient(json.dumps({"matches": ["pos-0001"]}))

    first = run_residue_sample(
        targets,
        positions,
        chunk_sections,
        client=client,
        decisions_path=decisions_path,
        encode=_hashing_encode,
        modes=("unblocked",),
    )
    assert first["unblocked"].calls_made == 1
    assert client.call_count == 1

    second = run_residue_sample(
        targets,
        positions,
        chunk_sections,
        client=client,
        decisions_path=decisions_path,
        encode=_hashing_encode,
        modes=("unblocked",),
    )

    assert second["unblocked"].calls_reused == 1
    assert client.call_count == 1  # no new call made
    assert second["unblocked"].resolved == 1


def test_load_decisions_is_empty_before_any_run(tmp_path: Path) -> None:
    assert load_decisions(tmp_path / "does-not-exist.jsonl") == {}


# ---------------------------------------------------------------------------
# Threading (issue #651 follow-up): the pool must not change WHAT gets
# decided or how many calls a resumed run makes, only how fast it happens.
# ---------------------------------------------------------------------------


class _CountingScriptedClient(StubLLMClient):
    """Like `_ScriptedClient`, but `call_count` is incremented under a lock
    -- several worker threads call `complete` concurrently here, and a bare
    `+= 1` is not guaranteed atomic."""

    def __init__(self, response: str) -> None:
        import threading

        super().__init__()
        self._response = response
        self._lock = threading.Lock()

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        with self._lock:
            self.call_count += 1
        return self._response

    def model_for_pass(self, pass_name: str | None = None) -> str:
        return "scripted"

    def usage_for_pass(self, pass_name: str | None = None) -> dict[str, int] | None:
        return {"prompt_tokens": 10, "completion_tokens": 1}


def _many_targets(n: int) -> list[UnresolvedTarget]:
    return [
        UnresolvedTarget(f"c{i:03d}", "alpha-2020-book", f"a distinct target claim {i}", None)
        for i in range(n)
    ]


def test_threaded_run_makes_exactly_one_call_per_target(tmp_path: Path) -> None:
    positions = [{"position_id": "pos-0001", "argument": "states extract resources"}]
    targets = _many_targets(30)
    decisions_path = tmp_path / "residue_decisions.jsonl"
    client = _CountingScriptedClient(json.dumps({"matches": []}))

    result = run_residue_sample(
        targets,
        positions,
        {},
        client=client,
        decisions_path=decisions_path,
        encode=_hashing_encode,
        modes=("unblocked",),
        workers=8,
    )["unblocked"]

    assert result.calls_made == 30
    assert client.call_count == 30
    decided = load_decisions(decisions_path)
    assert len(decided) == 30  # one line per target, no duplicate/dropped keys


def test_threaded_run_preserves_records_in_target_order(tmp_path: Path) -> None:
    positions = [{"position_id": "pos-0001", "argument": "states extract resources"}]
    targets = _many_targets(20)
    decisions_path = tmp_path / "residue_decisions.jsonl"
    client = _CountingScriptedClient(json.dumps({"matches": []}))

    result = run_residue_sample(
        targets,
        positions,
        {},
        client=client,
        decisions_path=decisions_path,
        encode=_hashing_encode,
        modes=("unblocked",),
        workers=8,
    )["unblocked"]

    assert [record["chunk_id"] for record in result.records] == [t.chunk_id for t in targets]


def test_a_threaded_resume_reasks_nothing_already_decided(tmp_path: Path) -> None:
    """Mirrors the shipped sample's own live demonstration (issue #651,
    `data/logs/2026-08-04-651-residue-sample/`): a run interrupted after
    some targets were decided resumes and re-asks zero of them, even with
    several worker threads racing to check the decision log at once."""
    positions = [{"position_id": "pos-0001", "argument": "states extract resources"}]
    targets = _many_targets(40)
    decisions_path = tmp_path / "residue_decisions.jsonl"
    client = _CountingScriptedClient(json.dumps({"matches": []}))

    # Simulate a run that was killed partway: decide the first half only.
    first_half = run_residue_sample(
        targets[:20],
        positions,
        {},
        client=client,
        decisions_path=decisions_path,
        encode=_hashing_encode,
        modes=("unblocked",),
        workers=8,
    )["unblocked"]
    assert first_half.calls_made == 20
    calls_before_resume = client.call_count

    # Resume over the FULL target list with a different worker count.
    resumed = run_residue_sample(
        targets,
        positions,
        {},
        client=client,
        decisions_path=decisions_path,
        encode=_hashing_encode,
        modes=("unblocked",),
        workers=5,
    )["unblocked"]

    assert resumed.calls_reused == 20
    assert resumed.calls_made == 20
    assert client.call_count == calls_before_resume + 20  # exactly the new half
    assert len(load_decisions(decisions_path)) == 40


def test_workers_default_matches_argmap_build(tmp_path: Path) -> None:
    # Issue #651: "default worker count should match what this repo already
    # uses elsewhere" -- the same I/O-bound call shape
    # `axial.argmap.build.run_extraction` already tuned.
    from axial.argmap.build import WORKERS as BUILD_WORKERS

    from axial.argmap.residue import WORKERS as RESIDUE_WORKERS

    assert RESIDUE_WORKERS == BUILD_WORKERS


def test_mode_result_reports_are_separated_per_mode(tmp_path: Path) -> None:
    # Two positions in different sections, so the blocked arm's bucket
    # ("Introduction" -> pos-0001 only) actually differs from the unblocked
    # arm's full pool -- otherwise both arms render the same prompt and the
    # second reuses the first's decision (a real, documented behavior, but
    # not what this test means to exercise).
    positions = [
        {"position_id": "pos-0001", "argument": "states extract resources"},
        {"position_id": "pos-0002", "argument": "ethnicity is constructed"},
    ]
    chunk_sections = {"m1": "Introduction", "m2": "Conclusion"}
    section_index_positions = [
        {**positions[0], "chunk_ids": ["m1"]},
        {**positions[1], "chunk_ids": ["m2"]},
    ]
    targets = [
        UnresolvedTarget(
            "c1", "alpha-2020-book", "states extract resources by force", "Introduction"
        )
    ]
    decisions_path = tmp_path / "residue_decisions.jsonl"
    client = _ScriptedClient(json.dumps({"matches": []}))

    results = run_residue_sample(
        targets,
        section_index_positions,
        chunk_sections,
        client=client,
        decisions_path=decisions_path,
        encode=_hashing_encode,
        modes=("blocked", "unblocked"),
    )

    assert set(results) == {"blocked", "unblocked"}
    assert isinstance(results["blocked"], ModeResult)
    assert results["blocked"].calls_made == 1
    assert results["unblocked"].calls_made == 1
