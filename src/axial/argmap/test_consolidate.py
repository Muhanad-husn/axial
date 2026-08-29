"""The consolidation pass (issue #830, positions-not-names slice 05): a
second model pass that reads one category's per-group namings and says what
recurs among them -- the same judgment extraction makes, one level up.

CLI-level, through `run_map_build`'s own injection seams (`client`,
`encode`, `pin`, the directory overrides), because the acceptance criterion
is about what `axial map build --grouping category` writes to
`positions.jsonl` and `map.json`, not about a function's return value.

No encoder is built and no network is touched: `_fake_encode` stands in for
MiniLM and `_agglomerative_cluster` is patched to put every row in its own
cluster, so the embedding merge folds nothing unless a test asks it to and
the consolidation pass's own output reaches `positions.jsonl` unchanged.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from axial.argmap.build import (
    EXTRACT_SLICE,
    RELATE_PASS_NAME,
    _accumulated_totals,
    merge_positions,
    run_map_build,
)
from axial.argmap.consolidate import (
    STOPPED_CONVERGED,
    STOPPED_FINAL_ROUND_FAILED,
    STOPPED_NO_PROGRESS,
    STOPPED_ROUND_CAP,
    PASS_NAME as CONSOLIDATE_PASS_NAME,
    PROMPT,
    build_round_jobs,
    partition_by_category,
    run_consolidation,
)
from axial.llm import MAX_ATTEMPTS, LLMError, StubLLMClient

ALPHA = "alpha-2020-book"
BETA = "beta-2021-book"

CAT_A = "causal-argument-state-formation-or-power"
CAT_B = "empirical-finding-without-causal-claim"
# Deliberately in alphabetical order: `group_spread` rotates a category's
# groups by sorted label, so MECH_1's naming is the first handle the
# consolidation prompt offers and MECH_3's is the third.
MECH_1 = "coercion-and-extraction"
MECH_2 = "elite-competition-and-coalition-formation"
MECH_3 = "war-and-state-formation"

CLAIM_SCHEME_VERSION = "2026-08-29-claim-v1"
MECHANISM_SCHEME_VERSION = "2026-08-29-mechanism-v1"


def _chunk_id(source_id: str, index: int) -> str:
    return f"{source_id}_0{index}0_body_001"


def _write_answers(answers_dir: Path, chunk_ids: list[str]) -> None:
    """One argument-bearing `data/answers/` record per chunk, grouped into
    the per-source files `load_answer_records` walks."""
    answers_dir.mkdir(parents=True, exist_ok=True)
    by_source: dict[str, list[dict]] = {}
    for index, chunk_id in enumerate(chunk_ids):
        record = {
            "source_id": chunk_id.rsplit("_", 3)[0],
            "chunk_id": chunk_id,
            "answers": {
                "claim": f"Claim number {index}.",
                "mechanism": "coercive taxation",
                "comparison": "not-in-passage",
                "concedes": "not-in-passage",
                "assumes": "not-in-passage",
                "position_of": "not-in-passage",
                "ranges_over": "not-in-passage",
            },
        }
        by_source.setdefault(record["source_id"], []).append(record)
    for source_id, records in by_source.items():
        with (answers_dir / f"{source_id}.jsonl").open("w", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record) + "\n")


def _write_column(
    vocabulary_dir: Path, column: str, scheme_version: str, category_by_chunk: dict
) -> None:
    """A built vocabulary column: the manifest `run_map_build` reads
    `scheme_version` off, plus one level-1 assignment per chunk."""
    column_dir = vocabulary_dir / column
    column_dir.mkdir(parents=True, exist_ok=True)
    (column_dir / "manifest.json").write_text(
        json.dumps({"column": column, "scheme_version": scheme_version, "max_level": 1}),
        encoding="utf-8",
    )
    with (column_dir / "assignments.jsonl").open("w", encoding="utf-8") as handle:
        for chunk_id, category_id in category_by_chunk.items():
            handle.write(
                json.dumps(
                    {
                        "chunk_id": chunk_id,
                        "level": 1,
                        "value": f"a sentence for {chunk_id}",
                        "category_id": category_id,
                        "refused": category_id is None,
                    }
                )
                + "\n"
            )


def _fake_encode(texts):
    return np.zeros((len(texts), 2))


def _extraction_handles(prompt: str) -> list[str]:
    return [line.split("]")[0][1:] for line in prompt.splitlines() if line.startswith("[p")]


def _argument_handles(prompt: str) -> list[str]:
    return [line.split("]")[0][1:] for line in prompt.splitlines() if line.startswith("[a")]


class _FoldsFirstTwoClient(StubLLMClient):
    """Names one argument per extraction group -- the claim it was shown
    first, so every group's naming is distinguishable -- and, on a
    consolidation call, folds the first two namings it is offered while
    leaving every other one standing on its own. The standing ones are the
    acceptance criterion's genuinely opposed accounts: a category's
    arguments do not all collapse into one."""

    def __init__(self) -> None:
        super().__init__()
        self.prompts_by_pass: dict[str, list[str]] = {}

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        self.call_count += 1
        self.prompts_by_pass.setdefault(pass_name or "", []).append(prompt)
        if pass_name == RELATE_PASS_NAME:
            return json.dumps({"relations": []})
        if pass_name == CONSOLIDATE_PASS_NAME:
            handles = _argument_handles(prompt)
            entries = [{"argument": "The consolidated argument.", "handles": handles[:2]}]
            entries += [
                {"argument": f"A standing argument ({handle}).", "handles": [handle]}
                for handle in handles[2:]
            ]
            return json.dumps({"arguments": entries})
        shown = _extraction_handles(prompt)
        first_claim = next(line for line in prompt.splitlines() if line.startswith("[p"))
        return json.dumps(
            {"arguments": [{"argument": first_claim.split("] ", 1)[1], "handles": shown}]}
        )

    def model_for_pass(self, pass_name: str | None = None) -> str:
        return "fake-model"


class _RefusingClient(StubLLMClient):
    """Raises on any call at all -- the resume assertion."""

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        raise AssertionError(f"a resumed build re-asked the model ({pass_name})")

    def model_for_pass(self, pass_name: str | None = None) -> str:
        return "fake-model"


@pytest.fixture
def spanning_corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    """Eight passages over two books, forming four groups:

      CAT_A::MECH_1   alpha 1, beta 1
      CAT_A::MECH_2   alpha 2, beta 2
      CAT_A::MECH_3   alpha 3, beta 3
      CAT_B::MECH_1   alpha 4, beta 4

    So `CAT_A`'s reads span three groups -- the acceptance criterion's "a
    variant build whose reads span multiple groups inside one category" --
    and `CAT_B`'s span one, the pass-through case.

    `_agglomerative_cluster` is faked to one cluster per row so the
    embedding merge folds nothing here (and no scikit-learn is needed): what
    reaches `positions.jsonl` is the consolidation pass's own answer, not
    the merge's."""
    monkeypatch.setattr("axial.argmap.build.load_back_matter_sections", lambda trees_dir: {})
    monkeypatch.setattr(
        "axial.argmap.build._agglomerative_cluster",
        lambda vectors, threshold: list(range(len(vectors))),
    )
    # The default build's relate stage clusters by COUNT, through a
    # different function that would reach the real scikit-learn on these
    # zero vectors. One neighbourhood, no split, one relate call.
    monkeypatch.setattr(
        "axial.argmap.build._agglomerative_cluster_by_count",
        lambda vectors, n_clusters: [0] * len(vectors),
    )
    chunk_ids = [_chunk_id(source, index) for source in (ALPHA, BETA) for index in (1, 2, 3, 4)]
    _write_answers(tmp_path / "answers", chunk_ids)
    vocabulary_dir = tmp_path / "vocabulary"
    claims = {chunk_id: CAT_A for chunk_id in chunk_ids}
    mechanisms = {}
    for source in (ALPHA, BETA):
        mechanisms[_chunk_id(source, 1)] = MECH_1
        mechanisms[_chunk_id(source, 2)] = MECH_2
        mechanisms[_chunk_id(source, 3)] = MECH_3
        mechanisms[_chunk_id(source, 4)] = MECH_1
        claims[_chunk_id(source, 4)] = CAT_B
    _write_column(vocabulary_dir, "claim", CLAIM_SCHEME_VERSION, claims)
    _write_column(vocabulary_dir, "mechanism", MECHANISM_SCHEME_VERSION, mechanisms)
    return {"root": tmp_path, "chunk_ids": chunk_ids, "vocabulary_dir": vocabulary_dir}


def _run(corpus: dict, *, client, grouping: str = "category", log=None, **kwargs):
    root = corpus["root"]
    return run_map_build(
        answers_dir=root / "answers",
        trees_dir=root / "trees",
        map_dir=root / "map",
        vocabulary_dir=corpus["vocabulary_dir"],
        client=client,
        encode=_fake_encode,
        pin="testpin",
        guard=False,
        grouping=grouping,
        log=log if log is not None else (lambda _message: None),
        **kwargs,
    )


def _read_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def test_the_consolidation_stage_reunites_one_categorys_arguments_and_reports_its_own_counts(
    spanning_corpus: dict,
) -> None:
    """The acceptance criterion of issue #830, end to end."""
    root = spanning_corpus["root"]
    variant_dir = root / "map" / "testpin-category"
    client = _FoldsFirstTwoClient()

    manifest = _run(spanning_corpus, client=client)

    positions = _read_jsonl(variant_dir / "positions.jsonl")

    # One position was named from several groups of the same category: the
    # union of their chunk_ids, and a count of how many namings folded in.
    folded = [position for position in positions if position["consolidated_from"] > 1]
    assert len(folded) == 1
    assert folded[0]["consolidated_from"] == 2
    assert set(folded[0]["chunk_ids"]) == {
        _chunk_id(source, index) for source in (ALPHA, BETA) for index in (1, 2)
    }
    assert folded[0]["sources"] == [ALPHA, BETA]

    # Genuinely opposed arguments inside one category survive as separate
    # positions: CAT_A's third naming stood on its own, and so did CAT_B's.
    assert len(positions) == 3

    # Raw, consolidated and merged are three separate counts.
    counts = manifest["counts"]
    assert counts["raw_positions"] == 4
    assert counts["consolidated_positions"] == 3
    assert counts["merged_positions"] == 3

    # The consolidation pass's own folds, reported the way the default
    # build's merge is, and separately from the embedding merge's.
    consolidation = manifest["consolidation"]["counts"]
    assert consolidation["folds"] == 1
    assert consolidation["positions_with_more_than_one_naming"] == 1
    assert consolidation["folds_per_final_position"] == pytest.approx(1 / 3)
    assert manifest["embedding_merge"]["folds"] == 0

    # CAT_B came from one group, so it was never asked about at all.
    assert len(client.prompts_by_pass[CONSOLIDATE_PASS_NAME]) == 1
    assert consolidation["categories_passed_through"] == 1

    # Its own resume ledger: a kill mid-pass never re-asks a completed
    # category, and a complete ledger reaches the model for nothing.
    ledger = _read_jsonl(variant_dir / "consolidation_reads.jsonl")
    assert [record["category"] for record in ledger] == [CAT_A]
    resumed = _run(spanning_corpus, client=_RefusingClient())
    assert resumed["counts"]["consolidated_positions"] == 3


# ---------------------------------------------------------------------------
# The pass's own mechanics, at the seams `run_consolidation` and
# `build_consolidation_jobs` expose, with no build around them.
# ---------------------------------------------------------------------------


def _raw(argument: str, chunk_ids: list[str]) -> dict:
    """One raw position as `extract_positions_for_slice` writes it."""
    sources = sorted({chunk_id.rsplit("_", 3)[0] for chunk_id in chunk_ids})
    return {
        "argument": argument,
        "chunk_ids": chunk_ids,
        "sources": sources,
        "authors": sorted({source.split("-")[0] for source in sources}),
        "size": len(chunk_ids),
    }


def _extraction_read(group_label: str, positions: list[dict]) -> dict:
    return {
        "bag": group_label,
        "slice": 0,
        "shown": len(positions),
        "positions": positions,
        "unassigned": 0,
    }


def test_a_category_that_spans_one_group_is_passed_through_without_a_model_call() -> None:
    """There is no second naming of anything to reunite, so the call would
    buy nothing. The passed-through positions still carry
    `consolidated_from: 1`, so every position in the map is countable the
    same way."""
    to_consolidate, passed_through, passed_count = partition_by_category(
        [
            _extraction_read(
                f"{CAT_B}::{MECH_1}",
                [
                    _raw("One naming.", [_chunk_id(ALPHA, 1)]),
                    _raw("Another.", [_chunk_id(BETA, 1)]),
                ],
            )
        ]
    )

    assert to_consolidate == {}
    assert passed_count == 1
    assert [position["consolidated_from"] for position in passed_through] == [1, 1]
    assert {position["category"] for position in passed_through} == {CAT_B}


def test_a_round_is_cut_at_the_extraction_slice_and_spread_across_its_units() -> None:
    """The slice cap reuses `EXTRACT_SLICE` rather than adding a second
    tuned number -- both listings are one sentence per line under a bare
    handle. Ordering rotates the units a position could have been named
    from, so a slice sees as many of them as it can."""
    per_group = EXTRACT_SLICE - 5
    reads = [
        _extraction_read(
            f"{CAT_A}::{mechanism}",
            [
                _raw(f"{mechanism} argument {i}.", [f"{ALPHA}_{i:03d}_body_001"])
                for i in range(per_group)
            ],
        )
        for mechanism in (MECH_1, MECH_2)
    ]
    to_consolidate, _passed_through, _passed_count = partition_by_category(reads)

    jobs = build_round_jobs(CAT_A, to_consolidate[CAT_A], 1)

    assert [len(job.members) for job in jobs] == [EXTRACT_SLICE, per_group * 2 - EXTRACT_SLICE]
    assert {job.round for job in jobs} == {1}
    assert {member["unit"] for member in jobs[0].members} == {
        f"{CAT_A}::{MECH_1}",
        f"{CAT_A}::{MECH_2}",
    }


class _InventingClient(StubLLMClient):
    """Names one real handle and one the prompt never offered."""

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        self.call_count += 1
        handles = _argument_handles(prompt)
        return json.dumps(
            {"arguments": [{"argument": "A folded argument.", "handles": [handles[0], "a99"]}]}
        )

    def model_for_pass(self, pass_name: str | None = None) -> str:
        return "fake-model"


def _two_group_reads() -> list[dict]:
    return [
        _extraction_read(f"{CAT_A}::{MECH_1}", [_raw("The first naming.", [_chunk_id(ALPHA, 1)])]),
        _extraction_read(f"{CAT_A}::{MECH_2}", [_raw("The second naming.", [_chunk_id(BETA, 1)])]),
    ]


def test_an_invented_handle_is_dropped_and_counted_never_repaired(tmp_path: Path) -> None:
    """Extraction's own contract, mirrored: the model naming something it
    was not offered loses that handle and nothing else."""
    result = run_consolidation(
        _two_group_reads(),
        client=_InventingClient(),
        reads_path=tmp_path / "consolidation_reads.jsonl",
        log=lambda _message: None,
    )

    assert [record["dropped_handles"] for record in result.records] == [1]
    folded = next(p for p in result.positions if p["argument"] == "A folded argument.")
    assert folded["consolidated_from"] == 1
    assert folded["chunk_ids"] == [_chunk_id(ALPHA, 1)]
    # The naming the model never mentioned survives on its own rather than
    # vanishing -- its extraction call is already paid for.
    assert sorted(p["argument"] for p in result.positions) == [
        "A folded argument.",
        "The second naming.",
    ]


class _FailingClient(StubLLMClient):
    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        self.call_count += 1
        raise LLMError("the model call failed")

    def model_for_pass(self, pass_name: str | None = None) -> str:
        return "fake-model"


def test_a_failed_consolidation_call_is_recorded_and_its_slice_survives(tmp_path: Path) -> None:
    """The fault-isolation contract: the failure is recorded on the read,
    never raised, and the slice's raw positions pass through unconsolidated
    rather than falling out of the map."""
    result = run_consolidation(
        _two_group_reads(),
        client=_FailingClient(),
        reads_path=tmp_path / "consolidation_reads.jsonl",
        log=lambda _message: None,
    )

    assert [("error" in record) for record in result.records] == [True]
    assert sorted(p["argument"] for p in result.positions) == [
        "The first naming.",
        "The second naming.",
    ]
    assert {p["consolidated_from"] for p in result.positions} == {1}


class _RecordingClient(StubLLMClient):
    """Folds nothing and records every prompt it was shown."""

    def __init__(self) -> None:
        super().__init__()
        self.prompts: list[str] = []

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        self.call_count += 1
        self.prompts.append(prompt)
        return json.dumps({"arguments": []})

    def model_for_pass(self, pass_name: str | None = None) -> str:
        return "fake-model"


def test_the_listing_is_blind_and_the_prompt_forbids_fusing_opposed_accounts(
    tmp_path: Path,
) -> None:
    """Blind is the same rule extraction's `render_claims_blind` applies:
    the arguments carry authors and sources in the record, and none of it
    reaches the model. The no-fusing rule is the one the whole pass exists
    to keep -- reuniting namings must not become fusing accounts."""
    client = _RecordingClient()
    run_consolidation(
        _two_group_reads(),
        client=client,
        reads_path=tmp_path / "consolidation_reads.jsonl",
        log=lambda _message: None,
    )

    listing = client.prompts[0]
    assert "[a1] The first naming." in listing
    assert "[a2] The second naming." in listing
    for leak in (ALPHA, BETA, "alpha", "beta", "2020", "2021"):
        assert leak not in listing
    assert "never fuse contending positions into one sentence" in PROMPT
    assert "must survive as separate entries" in PROMPT


def test_the_ledger_is_keyed_by_category_and_content_so_a_changed_argument_is_re_asked(
    tmp_path: Path,
) -> None:
    """A completed category costs no call on restart. But this pass's input
    is the extraction pass's OUTPUT, so the key covers the arguments
    themselves: an extraction read that came back different is a different
    question, and a ledger keyed by category alone would answer it from the
    old record."""
    ledger = tmp_path / "consolidation_reads.jsonl"
    reads = _two_group_reads()
    first = _RecordingClient()
    run_consolidation(reads, client=first, reads_path=ledger, log=lambda _m: None)
    assert first.call_count == 1

    resumed = _RecordingClient()
    run_consolidation(reads, client=resumed, reads_path=ledger, log=lambda _m: None)
    assert resumed.call_count == 0

    reads[1]["positions"][0]["argument"] = "The second naming, re-asked."
    after_change = _RecordingClient()
    result = run_consolidation(reads, client=after_change, reads_path=ledger, log=lambda _m: None)
    assert after_change.call_count == 1
    # And the stale record is not folded in alongside the new one.
    assert len(result.records) == 1


def _categorised(argument: str, category: str) -> dict:
    return {
        "argument": argument,
        "chunk_ids": [f"{ALPHA}_{argument}_body_001"],
        "sources": [ALPHA],
        "authors": ["alpha"],
        "size": 1,
        "category": category,
        "consolidated_from": 1,
    }


def _one_cluster(vectors):
    return [0] * len(vectors)


def test_the_embedding_merge_folds_across_categories_and_never_inside_one() -> None:
    """The restriction that arrives with this pass: consolidation has
    already judged a category's arguments, and wording similarity is not
    entitled to overrule it. Across categories the merge keeps its original
    job."""
    positions = [
        _categorised("a1", CAT_A),
        _categorised("a2", CAT_A),
        _categorised("b1", CAT_B),
    ]

    restricted = merge_positions(positions, _fake_encode, _one_cluster, cross_category_only=True)

    assert len(restricted) == 2
    for record in restricted:
        assert len(record["categories"]) == len(set(record["categories"]))
    # The cross-category fold still happened -- the restriction removed the
    # same-category one only.
    assert sorted(record["named_times"] for record in restricted) == [1, 2]

    # And the default build, which has no consolidation pass and no
    # categories, is untouched: one cluster is still one position.
    unrestricted = merge_positions(positions, _fake_encode, _one_cluster)
    assert len(unrestricted) == 1


# ---------------------------------------------------------------------------
# Part B (issue #830, folded in 2026-08-29): a resume must not erase the
# build's recorded cost. Measured live -- `9b796b3a6312b329-category` was
# rewritten with `cost_usd: null` / `wall_time_sec: 34.37` over a paid run of
# $0.7052 / 2,466s, thirty minutes later, by a resume that made no call.
# ---------------------------------------------------------------------------


class _PayingClient(_FoldsFirstTwoClient):
    """`_FoldsFirstTwoClient` that reports token usage under a model the
    price table knows, so the manifest carries a real `cost_usd` for a later
    resume to be measured against."""

    MODEL = "z-ai/glm-5.2"

    def __init__(self) -> None:
        super().__init__()
        self.usage: dict[str, dict[str, int]] = {}

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        answer = super().complete(prompt, pass_name)
        totals = self.usage.setdefault(
            pass_name or "", {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        )
        totals["prompt_tokens"] += 1_000
        totals["completion_tokens"] += 500
        totals["total_tokens"] += 1_500
        return answer

    def usage_for_pass(self, pass_name: str | None = None) -> dict[str, int] | None:
        return self.usage.get(pass_name or "")

    def model_for_pass(self, pass_name: str | None = None) -> str:
        return self.MODEL


@pytest.mark.parametrize("grouping", ["bag", "category"])
def test_a_resumed_build_never_erases_the_paid_runs_cost(
    spanning_corpus: dict, grouping: str
) -> None:
    """`usage_for_pass` reports what THIS process spent, and a resume spends
    nothing -- so the paid run's figures were overwritten with `null`. They
    accumulate under the pin instead. Both grouping modes: the defect was
    found on the variant, but it is the same code path in both."""
    paid = _run(spanning_corpus, client=_PayingClient(), grouping=grouping)
    assert paid["cost_usd"] > 0
    assert paid["runs"] == 1

    resumed = _run(spanning_corpus, client=_RefusingClient(), grouping=grouping)

    assert resumed["cost_usd"] >= paid["cost_usd"]
    assert resumed["wall_time_sec"] >= paid["wall_time_sec"]
    assert resumed["usage"]["total_tokens"] == paid["usage"]["total_tokens"]
    assert resumed["runs"] == 2

    stage = "consolidation" if grouping == "category" else "relations"
    assert paid[stage]["cost_usd"] > 0
    assert resumed[stage]["cost_usd"] >= paid[stage]["cost_usd"]
    assert resumed[stage]["runs"] == 2


# ---------------------------------------------------------------------------
# The fixed point (issue #830, coordinator's correction 2026-08-29). Counted
# on the live variant's own extraction ledger: 8 of 9 categories are cut into
# 2-9 slices and hold 98.6% of all 2,036 raw positions. One round therefore
# reunites only inside a 55-argument window -- and since this slice also stops
# the embedding merge folding inside a category, two namings that land in
# different slices of one category would be reunited by NOTHING. So
# consolidation iterates per category until the category fits one call.
# ---------------------------------------------------------------------------


class _FoldsEveryFiveClient(StubLLMClient):
    """Folds each run of five handles it is shown into one entry, so a slice
    of 55 comes back as 11 and a category shrinks round over round."""

    def __init__(self) -> None:
        super().__init__()
        self.shown: list[int] = []

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        self.call_count += 1
        handles = _argument_handles(prompt)
        self.shown.append(len(handles))
        return json.dumps(
            {
                "arguments": [
                    {
                        "argument": f"Folded {handles[offset]}.",
                        "handles": handles[offset : offset + 5],
                    }
                    for offset in range(0, len(handles), 5)
                ]
            }
        )

    def model_for_pass(self, pass_name: str | None = None) -> str:
        return "fake-model"


def _two_groups_of(count: int) -> list[dict]:
    """One category over two groups, `count` raw positions each."""
    return [
        _extraction_read(
            f"{CAT_A}::{mechanism}",
            [
                _raw(f"{mechanism} argument {i}.", [f"{ALPHA}_{i:03d}_body_00{group}"])
                for i in range(count)
            ],
        )
        for group, mechanism in enumerate((MECH_1, MECH_2))
    ]


def test_a_category_too_big_for_one_call_is_consolidated_to_a_fixed_point(
    tmp_path: Path,
) -> None:
    """The whole point of the pass: by the time it stops, one call has read
    everything the category has left. One round over slices leaves namings
    in different slices reunited by nothing at all, which is the failure
    mode moved one level up rather than closed."""
    reads = _two_groups_of(EXTRACT_SLICE)
    client = _FoldsEveryFiveClient()

    result = run_consolidation(
        reads,
        client=client,
        reads_path=tmp_path / "consolidation_reads.jsonl",
        log=lambda _message: None,
    )

    # Round 1 reads the category in two slices of 55; round 2 reads all 22
    # of their outputs in ONE call.
    assert client.shown == [EXTRACT_SLICE, EXTRACT_SLICE, 22]
    assert sorted(record["round"] for record in result.records) == [1, 1, 2]

    outcome = result.outcomes[0]
    assert outcome.category == CAT_A
    assert outcome.rounds == 2
    assert outcome.stopped == STOPPED_CONVERGED
    assert outcome.final_positions == len(result.positions) == 5

    # `consolidated_from` counts RAW positions folded in, accumulated across
    # rounds -- not entries the last round happened to fold.
    assert sum(p["consolidated_from"] for p in result.positions) == 2 * EXTRACT_SLICE
    assert max(p["consolidated_from"] for p in result.positions) == 25


class _FoldsNothingClient(StubLLMClient):
    """Returns every handle as its own entry: the model folded nothing, so
    another round buys nothing."""

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        self.call_count += 1
        return json.dumps(
            {
                "arguments": [
                    {"argument": f"Standing {handle}.", "handles": [handle]}
                    for handle in _argument_handles(prompt)
                ]
            }
        )

    def model_for_pass(self, pass_name: str | None = None) -> str:
        return "fake-model"


def test_a_round_that_folds_nothing_stops_the_category_rather_than_looping(
    tmp_path: Path,
) -> None:
    """A round returning as many positions as it was given has told us the
    model will not fold this set; paying for another pass over it is money
    for nothing. The category is still counted, and its stopping reason
    named, because it never reunited its whole set."""
    reads = _two_groups_of(EXTRACT_SLICE)
    client = _FoldsNothingClient()

    result = run_consolidation(
        reads,
        client=client,
        reads_path=tmp_path / "consolidation_reads.jsonl",
        log=lambda _message: None,
    )

    assert client.call_count == 2
    outcome = result.outcomes[0]
    assert outcome.rounds == 1
    assert outcome.stopped == STOPPED_NO_PROGRESS
    assert len(result.positions) == 2 * EXTRACT_SLICE


class _FoldsOnePairClient(StubLLMClient):
    """Folds exactly the first two handles of every slice and leaves the
    rest standing -- progress every round, far too slowly to reach a single
    slice. The pathological case the round cap exists for."""

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        self.call_count += 1
        handles = _argument_handles(prompt)
        entries = [{"argument": "Folded pair.", "handles": handles[:2]}]
        entries += [
            {"argument": f"Standing {handle}.", "handles": [handle]} for handle in handles[2:]
        ]
        return json.dumps({"arguments": entries})

    def model_for_pass(self, pass_name: str | None = None) -> str:
        return "fake-model"


def test_a_category_that_never_converges_stops_at_the_round_cap(tmp_path: Path) -> None:
    """The loop already terminates -- a round that does not shrink the set
    stops it -- so the cap is a COST guard, not a correctness one, and it is
    derived rather than picked: a category gets as many rounds as it needed
    slices to be read once. Round 1's call count is the whole envelope this
    can double."""
    reads = _two_groups_of(EXTRACT_SLICE)
    client = _FoldsOnePairClient()

    result = run_consolidation(
        reads,
        client=client,
        reads_path=tmp_path / "consolidation_reads.jsonl",
        log=lambda _message: None,
    )

    outcome = result.outcomes[0]
    assert outcome.stopped == STOPPED_ROUND_CAP
    # Round 1 needed two slices, so the category gets two rounds.
    assert outcome.rounds == 2
    assert len(result.positions) > EXTRACT_SLICE


def test_the_rounds_resume_from_the_ledger_without_a_single_call(tmp_path: Path) -> None:
    """Every round's slice is keyed by its own argument content, so a re-run
    replays the whole chain off disk -- a later round's input is the earlier
    round's recorded output, not something only a live client could
    produce."""
    ledger = tmp_path / "consolidation_reads.jsonl"
    reads = _two_groups_of(EXTRACT_SLICE)
    first = run_consolidation(
        reads, client=_FoldsEveryFiveClient(), reads_path=ledger, log=lambda _m: None
    )

    resumed = run_consolidation(
        reads, client=_RefusingClient(), reads_path=ledger, log=lambda _m: None
    )

    assert [p["argument"] for p in resumed.positions] == [p["argument"] for p in first.positions]
    assert resumed.outcomes[0].rounds == 2
    assert resumed.outcomes[0].stopped == STOPPED_CONVERGED


def test_the_manifest_reports_the_rounds_and_how_each_category_stopped(
    spanning_corpus: dict,
) -> None:
    """A category that never reunites its whole set must stay visible; it
    just must not be the normal case."""
    manifest = _run(spanning_corpus, client=_FoldsFirstTwoClient())

    counts = manifest["consolidation"]["counts"]
    assert counts["rounds"] == 1
    assert counts["categories_converged"] == 1
    assert counts["categories_stopped_no_progress"] == 0
    assert counts["categories_stopped_at_round_cap"] == 0
    # Nothing failed, so nothing was retried, re-asked or abandoned.
    assert counts["reads_retried"] == 0
    assert counts["reads_reasked_after_retry"] == 0
    assert counts["reads_abandoned"] == 0
    # One round, so nothing needed slicing.
    assert counts["categories_sliced"] == 0


# ---------------------------------------------------------------------------
# Reviewer findings on the staged instrument, before the paid pass
# (issue #830, 2026-08-29). Each of these is a way the pass would have
# reported a number that was not true of the run that produced it.
# ---------------------------------------------------------------------------


class _NamesEveryHandleTwiceClient(StubLLMClient):
    """Puts one handle in two entries -- the shape the prompt forbids and
    nothing enforced. `a2` is named by both."""

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        self.call_count += 1
        handles = _argument_handles(prompt)
        return json.dumps(
            {
                "arguments": [
                    {"argument": "A.", "handles": handles[:2]},
                    {"argument": "B.", "handles": handles[1:3]},
                ]
            }
        )

    def model_for_pass(self, pass_name: str | None = None) -> str:
        return "fake-model"


def _three_positions_over_two_groups() -> list[dict]:
    return [
        _extraction_read(
            f"{CAT_A}::{MECH_1}",
            [
                _raw("First naming.", [_chunk_id(ALPHA, 1)]),
                _raw("Second naming.", [_chunk_id(ALPHA, 2)]),
            ],
        ),
        _extraction_read(f"{CAT_A}::{MECH_2}", [_raw("Third naming.", [_chunk_id(BETA, 1)])]),
    ]


def test_a_handle_named_in_two_entries_is_placed_once_and_the_repeat_counted(
    tmp_path: Path,
) -> None:
    """`consolidated_from` is this slice's headline number, so it must not
    double-count. A handle in two entries would otherwise land in both, each
    summing its raw count and carrying its chunk ids, and it compounds round
    over round. First entry wins; the repeat joins the dropped count, the
    same place an invented handle goes."""
    result = run_consolidation(
        _three_positions_over_two_groups(),
        client=_NamesEveryHandleTwiceClient(),
        reads_path=tmp_path / "consolidation_reads.jsonl",
        log=lambda _message: None,
    )

    assert sum(p["consolidated_from"] for p in result.positions) == 3
    all_chunk_ids = [cid for p in result.positions for cid in p["chunk_ids"]]
    assert len(all_chunk_ids) == len(set(all_chunk_ids)) == 3
    assert [record["dropped_handles"] for record in result.records] == [1]


def test_a_failed_final_call_is_not_reported_as_converged(tmp_path: Path) -> None:
    """`categories_converged` is the number the manifest offers as the
    answer -- one call read everything this category had left. A single call
    that failed read nothing; its slice passed through untouched."""
    result = run_consolidation(
        _two_group_reads(),
        client=_FailingClient(),
        reads_path=tmp_path / "consolidation_reads.jsonl",
        log=lambda _message: None,
    )

    assert result.outcomes[0].stopped == STOPPED_FINAL_ROUND_FAILED


class _FailsOnceThenFoldsClient(StubLLMClient):
    """Fails every call until `stop_failing` is set -- the transport blip a
    41-to-260-call pass against a real API will actually see."""

    def __init__(self) -> None:
        super().__init__()
        self.stop_failing = False

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        self.call_count += 1
        if not self.stop_failing:
            raise LLMError("the model call failed")
        handles = _argument_handles(prompt)
        return json.dumps({"arguments": [{"argument": "Folded.", "handles": handles}]})

    def model_for_pass(self, pass_name: str | None = None) -> str:
        return "fake-model"


def test_a_slice_that_failed_on_an_earlier_run_is_re_asked_not_replayed(
    tmp_path: Path,
) -> None:
    """An error record is not a completed call. Left as one it is permanent:
    a failed slice passes its members through unchanged, which can trip the
    no-progress rule and end the category, and every restart replays the
    same error and ends it identically -- only `--force`, at full price,
    would recover. The resume contract is never re-ask a COMPLETED call."""
    ledger = tmp_path / "consolidation_reads.jsonl"
    client = _FailsOnceThenFoldsClient()

    failed = run_consolidation(
        _two_group_reads(), client=client, reads_path=ledger, log=lambda _m: None
    )
    assert failed.outcomes[0].stopped == STOPPED_FINAL_ROUND_FAILED

    client.stop_failing = True
    recovered = run_consolidation(
        _two_group_reads(), client=client, reads_path=ledger, log=lambda _m: None
    )

    assert recovered.outcomes[0].stopped == STOPPED_CONVERGED
    assert [p["argument"] for p in recovered.positions] == ["Folded."]
    # And a successful record is still never re-asked.
    settled = _RefusingClient()
    run_consolidation(_two_group_reads(), client=settled, reads_path=ledger, log=lambda _m: None)


def test_a_category_cut_into_slices_is_counted_sliced_even_when_it_folds_nothing(
    tmp_path: Path,
) -> None:
    """`categories_sliced` answers "was this category ever too big for one
    call". A category that folds nothing stops after round 1, so counting
    rounds instead answers a different question and reports it as never
    sliced."""
    result = run_consolidation(
        _two_groups_of(EXTRACT_SLICE),
        client=_FoldsNothingClient(),
        reads_path=tmp_path / "consolidation_reads.jsonl",
        log=lambda _message: None,
    )

    outcome = result.outcomes[0]
    assert outcome.rounds == 1
    assert outcome.round_one_slices == 2


def _any_handles(prompt: str) -> list[str]:
    return [
        line.split("]")[0][1:]
        for line in prompt.splitlines()
        if line.startswith("[p") or line.startswith("[a")
    ]


class _NamesEachHandleClient(StubLLMClient):
    """Names one argument per handle, in both passes: extraction produces a
    position per passage, and consolidation folds none of them."""

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        self.call_count += 1
        return json.dumps(
            {
                "arguments": [
                    {"argument": f"Argument {handle} of {len(prompt)}.", "handles": [handle]}
                    for handle in _any_handles(prompt)
                ]
            }
        )

    def model_for_pass(self, pass_name: str | None = None) -> str:
        return "fake-model"


@pytest.fixture
def sliced_corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    """Sixty passages in ONE claim category over two mechanism cells, so
    consolidation's round 1 is two slices -- the live shape, where 8 of 9
    categories are cut into 2-9 slices."""
    monkeypatch.setattr("axial.argmap.build.load_back_matter_sections", lambda trees_dir: {})
    monkeypatch.setattr(
        "axial.argmap.build._agglomerative_cluster",
        lambda vectors, threshold: list(range(len(vectors))),
    )
    chunk_ids = [f"{ALPHA}_{i:03d}_body_001" for i in range(30)]
    chunk_ids += [f"{BETA}_{i:03d}_body_001" for i in range(30)]
    _write_answers(tmp_path / "answers", chunk_ids)
    vocabulary_dir = tmp_path / "vocabulary"
    _write_column(
        vocabulary_dir, "claim", CLAIM_SCHEME_VERSION, {c: CAT_A for c in chunk_ids}
    )
    _write_column(
        vocabulary_dir,
        "mechanism",
        MECHANISM_SCHEME_VERSION,
        {c: (MECH_1 if c.startswith(ALPHA) else MECH_2) for c in chunk_ids},
    )
    return {"root": tmp_path, "chunk_ids": chunk_ids, "vocabulary_dir": vocabulary_dir}


def test_the_manifest_counts_a_sliced_category_that_folded_nothing(sliced_corpus: dict) -> None:
    """The build-level half of the same finding: 60 raw positions over two
    groups, one round, nothing folded -- sliced, and not converged."""
    manifest = _run(sliced_corpus, client=_NamesEachHandleClient())

    counts = manifest["consolidation"]["counts"]
    assert counts["raw_positions"] == 60
    assert counts["rounds"] == 1
    assert counts["categories_sliced"] == 1
    assert counts["categories_stopped_no_progress"] == 1
    assert counts["categories_converged"] == 0


def test_a_default_build_never_accumulates_a_prior_pins_cost(spanning_corpus: dict) -> None:
    """Two different manifests, one name. The accumulation must read THIS
    outdir's own `map.json`; the prior PIN's is read for its `source_ids`
    and nothing else. Reading the wrong one makes a first build under a new
    pin report the previous pin's dollars as its own -- and, when that
    manifest will not parse, erases this pin's real figures to `null`, which
    is the very defect the accumulation was added to fix."""
    root = spanning_corpus["root"]
    prior = root / "map" / "otherpin"
    prior.mkdir(parents=True)
    (prior / "map.json").write_text(
        json.dumps(
            {
                "corpus_pin": "otherpin",
                "source_ids": [ALPHA],
                "cost_usd": 9.99,
                "wall_time_sec": 5_000.0,
                "runs": 3,
                "usage": {"prompt_tokens": 9, "completion_tokens": 9, "total_tokens": 18},
            }
        ),
        encoding="utf-8",
    )

    client = _PayingClient()
    manifest = _run(spanning_corpus, client=client, grouping="bag")

    # Exactly what this run spent, and not one token or cent of the other
    # pin's.
    assert manifest["usage"] == client.usage_for_pass("position_extract")
    assert manifest["cost_usd"] < 1.0
    assert manifest["wall_time_sec"] < 5_000.0
    assert manifest["runs"] == 1
    # The prior pin is still read for what it IS read for: which sources it
    # covered, so an asked read touching a new book can be told apart.
    assert manifest["counts"]["units_asked_touching_new"] == 4


def test_a_prior_cost_survives_a_prior_manifest_that_recorded_no_usage() -> None:
    """The paid variant build's figures are being patched back by hand and
    the token totals were never recorded anywhere -- only the dollars were.
    A missing `usage` is not a reason to drop a cost that is right there."""
    totals = _accumulated_totals(
        {"cost_usd": 0.7052, "wall_time_sec": 2_466.0, "usage": None}, None, None, 34.0
    )

    assert totals["cost_usd"] == pytest.approx(0.7052)
    assert totals["wall_time_sec"] == pytest.approx(2_500.0)
    assert totals["usage"] is None
    # A manifest written before `runs` existed still stands for a run that
    # happened, so this is the second, not the first.
    assert totals["runs"] == 2


def test_no_prior_manifest_leaves_an_unpriced_run_null_rather_than_zero() -> None:
    """`None` and `0.0` are different claims. An unpriced model must not
    read as a free build."""
    assert _accumulated_totals(None, None, None, 1.0)["cost_usd"] is None
    assert _accumulated_totals(None, None, None, 1.0)["runs"] == 1


# ---------------------------------------------------------------------------
# What a resume costs, and what it can never buy (issue #830, found while
# capturing evidence on the real corpus).
# ---------------------------------------------------------------------------


class _FailsChosenCallsThenFoldsClient(StubLLMClient):
    """Fails the calls whose 1-based ordinal is in `fail_calls` and folds
    every run of five handles otherwise. Run with `workers=1` so the
    ordinals are the job order."""

    def __init__(self, fail_calls: set[int]) -> None:
        super().__init__()
        self.fail_calls = fail_calls

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        self.call_count += 1
        if self.call_count in self.fail_calls:
            raise LLMError("the model call failed")
        handles = _argument_handles(prompt)
        return json.dumps(
            {
                "arguments": [
                    {
                        "argument": f"Folded {handles[offset]}.",
                        "handles": handles[offset : offset + 5],
                    }
                    for offset in range(0, len(handles), 5)
                ]
            }
        )

    def model_for_pass(self, pass_name: str | None = None) -> str:
        return "fake-model"


def test_a_resume_says_what_a_retry_will_cost_downstream_before_it_spends(
    tmp_path: Path,
) -> None:
    """A retry that succeeds returns different positions than the error
    record's pass-through, so every later round for that category is asked a
    different question and re-asked at full price. That is right, and it must
    not be silent: a resume of a completed pass began re-asking round 2 with
    no warning that it was about to spend anything."""
    ledger = tmp_path / "consolidation_reads.jsonl"
    reads = _two_groups_of(EXTRACT_SLICE)

    first = run_consolidation(
        reads,
        client=_FailsChosenCallsThenFoldsClient({1}),
        reads_path=ledger,
        workers=1,
        log=lambda _m: None,
    )
    assert first.outcomes[0].rounds == 3

    lines: list[str] = []
    resumed = run_consolidation(
        reads,
        client=_FoldsEveryFiveClient(),
        reads_path=ledger,
        workers=1,
        log=lines.append,
    )

    # The warning names the categories and the reads, and lands BEFORE any
    # call is made.
    warning = next(line for line in lines if "will spend" in line)
    assert CAT_A in warning
    # One failed read to re-ask, and three later reads whose input it
    # changes -- an upper bound, since the retry's own answer is not known
    # until it is made.
    assert "up to 4" in warning
    assert lines.index(warning) < min(
        index for index, line in enumerate(lines) if "consolidated 1/" in line
    )

    # And the manifest's own figures are the actuals, not the projection.
    assert resumed.reads_retried == 1
    assert resumed.reads_reasked_after_retry == 1
    assert resumed.outcomes[0].stopped == STOPPED_CONVERGED


def test_a_read_that_cannot_succeed_is_abandoned_at_the_clients_own_attempt_budget(
    tmp_path: Path,
) -> None:
    """One slice exceeded the 600s deadline, was retried three times inside
    the client at 600s each, and landed on the ledger as an error. Retrying
    an error record then meant every future resume spent thirty minutes
    rediscovering the same failure. A read that failed as many times as the
    client itself would attempt one is not transient; it is abandoned, its
    members pass through as they already did, and `--force` remains the way
    to ask it again."""
    ledger = tmp_path / "consolidation_reads.jsonl"
    reads = _two_group_reads()
    client = _FailingClient()

    for _run_number in range(MAX_ATTEMPTS + 2):
        result = run_consolidation(reads, client=client, reads_path=ledger, log=lambda _m: None)

    # Tried exactly as many times as the client's own budget, then never
    # again -- the extra runs above cost nothing.
    assert client.call_count == MAX_ATTEMPTS
    assert result.reads_abandoned == 1
    assert result.records[0]["attempts"] == MAX_ATTEMPTS
    assert result.outcomes[0].stopped == STOPPED_FINAL_ROUND_FAILED
    # The members are still in the map, exactly as the failure path already
    # left them.
    assert sorted(p["argument"] for p in result.positions) == [
        "The first naming.",
        "The second naming.",
    ]

    # A settled run makes no call at all, and says so without a spend warning.
    lines: list[str] = []
    run_consolidation(
        reads, client=_RefusingClient(), reads_path=ledger, log=lines.append
    )
    assert not any("will spend" in line for line in lines)


# ---------------------------------------------------------------------------
# The echo, and why it stays (issue #830). `PROMPT` makes a call folding two
# of fifty-five arguments retype all fifty-five, and the first real-corpus
# pass showed what that costs: 2.4M completion tokens against 400k prompt, 29
# of 218 attempts (13%) hitting the 600s deadline. Asking for the merges alone
# was built and PROBED on `methodological-preconditions` (98 raw positions),
# and it lost on both counts -- 15,972 completion tokens a call against
# 8,000-13,000, one call at 42,909 over 418s, and 98 -> 66 where the echo
# prompt reached 51 and converged. Reverted. What these two tests hold is the
# part that is true either way: what the model does not name survives, and the
# raw positions offered are closed under the output.
# ---------------------------------------------------------------------------


class _FoldsOnePairOfThreeClient(StubLLMClient):
    """Merges the first two of the three arguments it is shown and names the
    third in no entry at all."""

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        self.call_count += 1
        handles = _argument_handles(prompt)
        return json.dumps(
            {"arguments": [{"argument": "The merged argument.", "handles": handles[:2]}]}
        )

    def model_for_pass(self, pass_name: str | None = None) -> str:
        return "fake-model"


def test_a_handle_the_model_never_names_passes_through_with_its_own_sentence(
    tmp_path: Path,
) -> None:
    """Silence about an argument is not a refusal to keep it. It survives
    with the sentence extraction already paid for, and its
    `consolidated_from` intact."""
    result = run_consolidation(
        _three_positions_over_two_groups(),
        client=_FoldsOnePairOfThreeClient(),
        reads_path=tmp_path / "consolidation_reads.jsonl",
        log=lambda _message: None,
    )

    assert sorted(p["argument"] for p in result.positions) == [
        "Second naming.",
        "The merged argument.",
    ]
    merged = next(p for p in result.positions if p["argument"] == "The merged argument.")
    assert merged["consolidated_from"] == 2
    standing = next(p for p in result.positions if p["argument"] == "Second naming.")
    assert standing["consolidated_from"] == 1
    assert standing["chunk_ids"] == [_chunk_id(ALPHA, 2)]
    # The invariant the manifest's headline number rests on, and which a
    # real-corpus check reads (2,036 exactly): every raw position offered is
    # accounted for exactly once.
    assert sum(p["consolidated_from"] for p in result.positions) == 3


def test_an_empty_answer_passes_every_position_through_and_loses_none(
    tmp_path: Path,
) -> None:
    """A call that names nothing at all is a degenerate answer, not a
    licence to drop the slice: every position stands in its own words and
    the raw count still closes."""
    client = _RecordingClient()
    result = run_consolidation(
        _three_positions_over_two_groups(),
        client=client,
        reads_path=tmp_path / "consolidation_reads.jsonl",
        log=lambda _message: None,
    )

    assert client.call_count == 1
    assert sorted(p["argument"] for p in result.positions) == [
        "First naming.",
        "Second naming.",
        "Third naming.",
    ]
    assert sum(p["consolidated_from"] for p in result.positions) == 3
