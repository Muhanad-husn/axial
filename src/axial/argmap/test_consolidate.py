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
    RE_READ_MEMBERS,
    RE_READ_PROMPT,
    SENTENCE_RULE,
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


def _listed_arguments(prompt: str) -> list[str]:
    return [line.split("] ", 1)[1] for line in prompt.splitlines() if line.startswith("[a")]


def _is_re_read(prompt: str) -> bool:
    """The re-read call and the consolidation call share a pass name, so a
    fake client tells them apart by the answer shape each asks for."""
    return '"groups"' in prompt


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


# ---------------------------------------------------------------------------
# What the prompt says about SAMENESS, and about the sentence that stands for
# a group. A blind audit of the built variant's 25 most heavily folded
# positions read 7 wrong, 9 mixed, 9 sound (issue #830), and heavily-folded
# positions carry 64.2% of all passages: the pass was merging on rhetorical
# form, and the sentence standing for a group was adjudicating between its
# own members.
# ---------------------------------------------------------------------------


def test_the_prompt_makes_sameness_about_the_object_not_the_rhetorical_move() -> None:
    """The audit's worst fold put 32 arguments from 23 books together on the
    shape "some existing account is inadequate" -- irrigation despotism,
    rentier theory, national identity, the Great Depression. The inputs here
    are already abstract argument sentences, and at that altitude everything
    resembles everything, so the prompt names the failure: a shared move is
    not a shared claim, and the sentence you could write is the test."""
    assert "THE SAME THING ABOUT THE SAME THING" in PROMPT
    assert "moves, not claims" in PROMPT
    assert "does not name what the argument is about" in PROMPT
    # Sharpened, not replaced: every grouping rule the pass already had.
    assert "MERGE aggressively on substance" in PROMPT
    assert "SPLIT only where the arguments genuinely conflict" in PROMPT
    assert "never fuse contending positions into one sentence" in PROMPT
    assert "must survive as separate entries" in PROMPT
    assert "many genuinely different arguments is an ordinary outcome" in PROMPT
    assert "Each argument must be CONTESTABLE" in PROMPT
    assert "Every handle listed must appear in exactly one entry" in PROMPT


def test_the_prompt_binds_the_group_sentence_to_what_every_member_asserts() -> None:
    """The other half of the audit: one position stood for "repression
    radicalises opposition" and "indiscriminate violence succeeds when the
    target is unprotected" as "repressive violence is counterproductive",
    settling a live dispute in the corpus; another turned "Ibn Khaldun's
    sociology holds that tribal solidarity is the only true cohesion" into
    an assertion of fact. The no-fusing rule governs which arguments meet;
    these govern the sentence written once they have."""
    assert "states only what every argument in the group asserts" in PROMPT
    assert "never takes a side" in PROMPT
    assert "never settles a disagreement" in PROMPT
    assert "never drops an attribution" in PROMPT
    assert "widens into a generality" in PROMPT
    # And the loop back to the split rule: an unwritable sentence is the
    # signal that the group is not one argument.
    assert "cannot write one sentence every member" in PROMPT


class _KeepsEverythingApartClient(StubLLMClient):
    """What the move-versus-claim rule asks for on a slice whose arguments
    share only a rhetorical move: every handle in its own entry."""

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        self.call_count += 1
        handles = _argument_handles(prompt)
        return json.dumps(
            {
                "arguments": [
                    {"argument": f"Kept apart ({handle}).", "handles": [handle]}
                    for handle in handles
                ]
            }
        )

    def model_for_pass(self, pass_name: str | None = None) -> str:
        return "fake-model"


def test_arguments_the_model_keeps_apart_stay_one_position_each(tmp_path: Path) -> None:
    """The parser's contract under the sharpened rules: a call that folds
    nothing pools no chunk ids, sums no counts, and loses no naming. Its
    entries are the model's own sentences, one position each."""
    result = run_consolidation(
        _two_group_reads(),
        client=_KeepsEverythingApartClient(),
        reads_path=tmp_path / "consolidation_reads.jsonl",
        log=lambda _message: None,
    )

    assert sorted(p["argument"] for p in result.positions) == [
        "Kept apart (a1).",
        "Kept apart (a2).",
    ]
    assert {p["consolidated_from"] for p in result.positions} == {1}
    assert sorted(tuple(p["chunk_ids"]) for p in result.positions) == [
        (_chunk_id(ALPHA, 1),),
        (_chunk_id(BETA, 1),),
    ]
    assert sorted(tuple(p["sources"]) for p in result.positions) == [(ALPHA,), (BETA,)]


class _FoldsTheFirstTwoOnlyClient(StubLLMClient):
    """One group whose members assert the same thing about the same thing,
    and one argument left alone because no single sentence would cover it."""

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        self.call_count += 1
        handles = _argument_handles(prompt)
        return json.dumps(
            {
                "arguments": [
                    {"argument": "Coercion built the fiscal state.", "handles": handles[:2]},
                    {"argument": f"A different object ({handles[2]}).", "handles": [handles[2]]},
                ]
            }
        )

    def model_for_pass(self, pass_name: str | None = None) -> str:
        return "fake-model"


def test_a_partial_fold_pools_only_its_own_members(tmp_path: Path) -> None:
    """The other side of the same contract: a group that IS one argument
    gets one entry carrying every member's chunk ids, sources and authors
    and their summed `consolidated_from`, while the argument held apart from
    it keeps its own."""
    reads = [
        _extraction_read(f"{CAT_A}::{MECH_1}", [_raw("The first naming.", [_chunk_id(ALPHA, 1)])]),
        _extraction_read(f"{CAT_A}::{MECH_2}", [_raw("The second naming.", [_chunk_id(BETA, 1)])]),
        _extraction_read(f"{CAT_A}::{MECH_3}", [_raw("A third naming.", [_chunk_id(ALPHA, 2)])]),
    ]

    result = run_consolidation(
        reads,
        client=_FoldsTheFirstTwoOnlyClient(),
        reads_path=tmp_path / "consolidation_reads.jsonl",
        log=lambda _message: None,
    )

    folded = next(
        p for p in result.positions if p["argument"] == "Coercion built the fiscal state."
    )
    assert folded["consolidated_from"] == 2
    assert folded["chunk_ids"] == sorted([_chunk_id(ALPHA, 1), _chunk_id(BETA, 1)])
    assert folded["sources"] == [ALPHA, BETA]
    assert folded["authors"] == ["alpha", "beta"]
    standing = [p for p in result.positions if p is not folded]
    assert [p["consolidated_from"] for p in standing] == [1]
    assert standing[0]["chunk_ids"] == [_chunk_id(ALPHA, 2)]


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


class _FoldsRunsOfClient(StubLLMClient):
    """Folds each run of `run` handles it is shown into one entry, so a
    slice of 55 comes back as 11 at run=5 and a category shrinks round over
    round. On a re-read it stands by the group it is shown, so what it folds
    is unaffected and the re-reads themselves stay countable: `shown` holds
    the consolidation calls, `re_read_shown` the re-reads."""

    def __init__(self, run: int = 5) -> None:
        super().__init__()
        self.run = run
        self.shown: list[int] = []
        self.re_read_shown: list[int] = []
        self.re_read_prompts: list[str] = []

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        self.call_count += 1
        handles = _argument_handles(prompt)
        if _is_re_read(prompt):
            self.re_read_shown.append(len(handles))
            self.re_read_prompts.append(prompt)
            return json.dumps({"groups": [{"argument": "Stood by.", "handles": handles}]})
        self.shown.append(len(handles))
        return json.dumps(
            {
                "arguments": [
                    {
                        "argument": f"Folded {handles[offset]}.",
                        "handles": handles[offset : offset + self.run],
                    }
                    for offset in range(0, len(handles), self.run)
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
    client = _FoldsRunsOfClient()

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
        reads, client=_FoldsRunsOfClient(), reads_path=ledger, log=lambda _m: None
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
    # The re-read's own four numbers reach the manifest. Nothing here folds
    # ten arguments into one entry, so all four are zero and the keys are
    # what this asserts (the split itself is held by the unit tests below).
    assert counts["positions_re_read"] == 0
    assert counts["positions_split"] == 0
    assert counts["split_subgroups"] == 0
    assert counts["failed_re_reads"] == 0


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
    """Fails the READS whose 1-based ordinal is in `fail_calls` and folds
    every run of five handles otherwise. Run with `workers=1` so the
    ordinals are the job order. A re-read stands by and does not consume an
    ordinal, so adding one never renumbers the reads."""

    def __init__(self, fail_calls: set[int]) -> None:
        super().__init__()
        self.fail_calls = fail_calls
        self.reads = 0

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        self.call_count += 1
        if _is_re_read(prompt):
            return json.dumps(
                {"groups": [{"argument": "Stood by.", "handles": _argument_handles(prompt)}]}
            )
        self.reads += 1
        if self.reads in self.fail_calls:
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
        client=_FoldsRunsOfClient(),
        reads_path=ledger,
        workers=1,
        log=lines.append,
    )

    # The warning names the categories and the reads, and lands BEFORE any
    # call is made.
    warning = next(line for line in lines if "will spend" in line)
    assert CAT_A in warning
    # One failed read to re-ask, and ten later calls whose input it changes
    # -- three reads and seven re-reads, all already on disk and all now
    # answering a question nobody will ask again. An upper bound, since the
    # retry's own answer is not known until it is made.
    assert "up to 11" in warning
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


# ---------------------------------------------------------------------------
# The re-read (issue #830). Twenty-five heavily folded positions from the
# built variant were judged blind against their own members, and
# cross-tabulated by how many raw arguments each fold holds: at 10 or more,
# 3 wrong / 0 mixed / 0 sound; under 10, 4 / 9 / 9. A large fold is not a
# worse version of a small one, it is a heading. So a position standing for
# ten or more RAW arguments gets one more call over them before the round it
# came out of is finished.
#
# The trigger is the position's accumulated `consolidated_from`, and a probe
# is why. Triggered on the handles one call named, it fired ZERO times on
# `causal-argument-nationalism-or-identity` (158 raw positions, 3 rounds, 9
# calls) while leaving a 15-argument and an 11-argument fold in the output:
# large folds are assembled ACROSS rounds out of small entries, so no single
# call ever names ten handles. Round 1 is not where large folds form.
# Accumulated size is also the quantity the audit measured and the quantity
# that reaches the map.
#
# n=3 above the line -- the threshold is a measured starting point, and these
# tests hold the CONTRACT (no member lost, a genuine fold survives whole, a
# failure changes nothing) rather than the number.
# ---------------------------------------------------------------------------


def _one_category_of(count: int) -> list[dict]:
    """`count` raw positions in one category, dealt over two extraction
    groups so the category is consolidated rather than passed through."""
    half = count // 2
    return [
        _extraction_read(
            f"{CAT_A}::{mechanism}",
            [
                _raw(f"{mechanism} argument {i}.", [f"{ALPHA}_{group}{i:02d}_body_001"])
                for i in range(size)
            ],
        )
        for group, (mechanism, size) in enumerate(zip((MECH_1, MECH_2), (half, count - half)))
    ]


class _FoldsEverythingClient(StubLLMClient):
    """Folds every argument it is shown into ONE entry -- the heading the
    audit found -- and, when that entry comes back for a re-read, splits it
    into `parts` subgroups. `parts=1` is the re-read standing by the fold."""

    def __init__(self, parts: int = 3) -> None:
        super().__init__()
        self.parts = parts
        self.re_read_prompts: list[str] = []

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        self.call_count += 1
        handles = _argument_handles(prompt)
        if _is_re_read(prompt):
            self.re_read_prompts.append(prompt)
            size = len(handles) // self.parts
            cuts = [handles[i * size : (i + 1) * size] for i in range(self.parts - 1)]
            cuts.append(handles[(self.parts - 1) * size :])
            return json.dumps(
                {
                    "groups": [
                        {"argument": f"Subgroup {i + 1}.", "handles": cut}
                        for i, cut in enumerate(cuts)
                    ]
                }
            )
        return json.dumps({"arguments": [{"argument": "One folded argument.", "handles": handles}]})

    def model_for_pass(self, pass_name: str | None = None) -> str:
        return "fake-model"


def test_a_fold_over_the_threshold_is_re_read_and_split_without_losing_a_member(
    tmp_path: Path,
) -> None:
    """The split redistributes members across subgroups; it never invents or
    drops one. `sum(consolidated_from)` over the category's output still
    equals the raw positions it was given -- the invariant the manifest's
    headline number rests on."""
    client = _FoldsEverythingClient(parts=3)

    result = run_consolidation(
        _one_category_of(12),
        client=client,
        reads_path=tmp_path / "consolidation_reads.jsonl",
        log=lambda _message: None,
    )

    # One consolidation call, one re-read.
    assert client.call_count == 2
    assert sorted(p["argument"] for p in result.positions) == [
        "Subgroup 1.",
        "Subgroup 2.",
        "Subgroup 3.",
    ]
    assert [p["consolidated_from"] for p in result.positions] == [4, 4, 4]
    assert sum(p["consolidated_from"] for p in result.positions) == 12
    # Every raw position's chunk reaches exactly one subgroup.
    placed = [cid for p in result.positions for cid in p["chunk_ids"]]
    assert len(placed) == len(set(placed)) == 12
    # The re-read is blind, like every other call in this pass.
    assert ALPHA not in client.re_read_prompts[0]
    assert "alpha" not in client.re_read_prompts[0]
    # It is shown the members and the sentence written for them.
    assert "One folded argument." in client.re_read_prompts[0]
    assert len(_argument_handles(client.re_read_prompts[0])) == 12

    record = result.re_reads[0]
    assert record["split"] is True
    assert record["shown"] == 12
    assert len(record["positions"]) == 3
    # Every position says what it was folded from, and the list is exactly
    # as long as the count -- one entry per raw position, carrying the raw
    # sentence and the chunks behind it.
    folded = [m for position in result.positions for m in position["folded_from"]]
    assert [len(p["folded_from"]) for p in result.positions] == [4, 4, 4]
    assert sorted(m["argument"] for m in folded) == sorted(
        f"{mechanism} argument {i}." for mechanism in (MECH_1, MECH_2) for i in range(6)
    )
    assert sorted(cid for m in folded for cid in m["chunk_ids"]) == sorted(placed)


def test_a_re_read_that_stands_by_the_fold_leaves_it_one_position(
    tmp_path: Path,
) -> None:
    """A genuine large fold must survive. The pass is not allowed to break a
    32-member argument just because it is big: a re-read returning every
    member in one subgroup leaves the entry exactly as the consolidation
    call wrote it, sentence included, and is not counted as a split."""
    client = _FoldsEverythingClient(parts=1)

    result = run_consolidation(
        _one_category_of(12),
        client=client,
        reads_path=tmp_path / "consolidation_reads.jsonl",
        log=lambda _message: None,
    )

    assert client.call_count == 2
    assert [p["argument"] for p in result.positions] == ["One folded argument."]
    assert result.positions[0]["consolidated_from"] == 12
    assert result.re_reads[0]["split"] is False
    assert len(result.re_reads[0]["positions"]) == 1


def test_a_fold_under_the_threshold_is_never_re_read(tmp_path: Path) -> None:
    """Nine raw arguments is the band where the audit found the wrong folds
    indistinguishable from the sound ones by size, so no call is bought for
    them."""
    client = _FoldsEverythingClient(parts=3)

    result = run_consolidation(
        _one_category_of(RE_READ_MEMBERS - 1),
        client=client,
        reads_path=tmp_path / "consolidation_reads.jsonl",
        log=lambda _message: None,
    )

    assert client.call_count == 1
    assert client.re_read_prompts == []
    assert result.re_reads == ()
    assert [p["argument"] for p in result.positions] == ["One folded argument."]
    assert result.positions[0]["consolidated_from"] == RE_READ_MEMBERS - 1


class _FailsTheReReadClient(_FoldsEverythingClient):
    """Consolidates, then fails the re-read -- the fault-isolation case."""

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        if _is_re_read(prompt):
            self.call_count += 1
            raise LLMError("the re-read call failed")
        return super().complete(prompt, pass_name)


def test_a_failed_re_read_leaves_the_entry_intact_and_counts_the_failure(
    tmp_path: Path,
) -> None:
    """Same contract as every other call here: the failure is recorded, never
    raised, and no member is lost -- the entry stands exactly as the
    consolidation call wrote it."""
    result = run_consolidation(
        _one_category_of(12),
        client=_FailsTheReReadClient(),
        reads_path=tmp_path / "consolidation_reads.jsonl",
        log=lambda _message: None,
    )

    assert [p["argument"] for p in result.positions] == ["One folded argument."]
    assert result.positions[0]["consolidated_from"] == 12
    assert [("error" in record) for record in result.re_reads] == [True]
    assert result.re_reads[0]["split"] is False
    # The consolidation read itself did not fail.
    assert [("error" in record) for record in result.records] == [False]


def test_the_re_read_prompt_carries_the_same_sentence_rules_as_the_consolidation_prompt() -> None:
    """The rule is one string used by both prompts, so the two cannot drift.
    A subgroup's sentence is written under exactly the constraints the
    consolidation prompt now enforces -- the audit found the sentence
    standing for a group adjudicating between its own members, and a re-read
    that wrote a looser sentence would reintroduce that at the split."""
    assert SENTENCE_RULE in PROMPT
    assert SENTENCE_RULE in RE_READ_PROMPT
    assert "states only what every argument in the group asserts" in SENTENCE_RULE
    assert "never takes a side" in SENTENCE_RULE
    assert "never settles a disagreement" in SENTENCE_RULE
    assert "widens into a generality" in SENTENCE_RULE
    assert "never drops an attribution" in SENTENCE_RULE
    assert "cannot write one sentence every member" in SENTENCE_RULE
    # It says plainly what the call is for, and never asks for a count.
    assert "heading" in RE_READ_PROMPT
    assert "Every handle listed above must appear in exactly one group" in RE_READ_PROMPT


def test_a_resume_does_not_re_ask_a_completed_re_read(tmp_path: Path) -> None:
    """The re-read has its own ledger key, over the entry's own member
    arguments, so a killed run replays it off disk. Without one the whole
    entry would be re-read at full price every restart."""
    ledger = tmp_path / "consolidation_reads.jsonl"
    reads = _one_category_of(12)
    first = run_consolidation(
        reads, client=_FoldsEverythingClient(parts=3), reads_path=ledger, log=lambda _m: None
    )

    resumed = run_consolidation(
        reads, client=_RefusingClient(), reads_path=ledger, log=lambda _m: None
    )

    assert [p["argument"] for p in resumed.positions] == [p["argument"] for p in first.positions]
    assert [p["consolidated_from"] for p in resumed.positions] == [4, 4, 4]
    assert resumed.re_reads[0]["split"] is True


def test_a_fold_that_only_reaches_the_threshold_across_rounds_is_re_read(
    tmp_path: Path,
) -> None:
    """The case the first build missed, and the probe caught. Triggered on
    the handles ONE call names, this fires zero times: no call here ever
    names ten, because round 1 folds fives and round 2 folds five of those.
    Yet the positions that reach the map stand for 25 and 10 raw arguments,
    which is the size the audit judged. The trigger is accumulated
    `consolidated_from`, so round 1 buys nothing and round 2 re-reads every
    position it produced."""
    client = _FoldsRunsOfClient(run=5)

    result = run_consolidation(
        _two_groups_of(EXTRACT_SLICE),
        client=client,
        reads_path=tmp_path / "consolidation_reads.jsonl",
        log=lambda _message: None,
    )

    # Round 1 reads two slices of 55 and returns 22 entries of five; nothing
    # there is over the threshold. Round 2 folds those into 25s and a 10.
    assert client.shown == [EXTRACT_SLICE, EXTRACT_SLICE, 22]
    assert sorted(client.re_read_shown) == [10, 25, 25, 25, 25]
    assert sorted(p["consolidated_from"] for p in result.positions) == [10, 25, 25, 25, 25]
    assert sum(p["consolidated_from"] for p in result.positions) == 2 * EXTRACT_SLICE

    # The re-read is shown the RAW arguments the position stands for, not
    # the sentences the earlier rounds wrote for them. Without that it
    # cannot judge whether every member asserts the claim.
    listed = _listed_arguments(client.re_read_prompts[0])
    assert len(listed) == len(_argument_handles(client.re_read_prompts[0]))
    assert all(" argument " in argument for argument in listed)
    assert not any(argument.startswith("Folded ") for argument in listed)


def test_a_fold_that_never_reaches_the_threshold_across_rounds_is_never_re_read(
    tmp_path: Path,
) -> None:
    """The other half of the trigger. Two rounds, a category that shrinks
    110 raw positions to 13, and the largest fold reaches nine -- one under
    the line the audit drew. Not a call is bought."""
    client = _FoldsRunsOfClient(run=3)

    result = run_consolidation(
        _two_groups_of(EXTRACT_SLICE),
        client=client,
        reads_path=tmp_path / "consolidation_reads.jsonl",
        log=lambda _message: None,
    )

    assert result.outcomes[0].rounds == 2
    assert client.re_read_shown == []
    assert result.re_reads == ()
    assert max(p["consolidated_from"] for p in result.positions) == RE_READ_MEMBERS - 1
    assert sum(p["consolidated_from"] for p in result.positions) == 2 * EXTRACT_SLICE


def test_a_position_carries_the_raw_arguments_it_was_folded_from_across_rounds(
    tmp_path: Path,
) -> None:
    """A folded position must say what it is made of without anything
    having to be reconstructed from chunk-id containment. `folded_from`
    accumulates the way `consolidated_from` does -- a round-2 position
    folding five round-1 entries of five carries 25 raw arguments, not five
    round-1 sentences -- and it is what the re-read reads."""
    result = run_consolidation(
        _two_groups_of(EXTRACT_SLICE),
        client=_FoldsRunsOfClient(run=5),
        reads_path=tmp_path / "consolidation_reads.jsonl",
        log=lambda _message: None,
    )

    for position in result.positions:
        assert len(position["folded_from"]) == position["consolidated_from"]
        assert all(" argument " in member["argument"] for member in position["folded_from"])
        # The chunks of the members are exactly the position's own.
        assert sorted({cid for m in position["folded_from"] for cid in m["chunk_ids"]}) == sorted(
            position["chunk_ids"]
        )
    # Every raw position is accounted for exactly once across the map.
    folded = [m["argument"] for p in result.positions for m in p["folded_from"]]
    assert len(folded) == len(set(folded)) == 2 * EXTRACT_SLICE


def test_the_raw_arguments_a_position_was_folded_from_reach_positions_jsonl(
    spanning_corpus: dict,
) -> None:
    """The field survives the embedding merge and lands on the written
    position. `variants` is the merge's own field and holds the CONSOLIDATED
    sentences it folded; `folded_from` is the consolidation pass's and holds
    the raw arguments underneath them. They do not collide and neither
    replaces the other."""
    root = spanning_corpus["root"]
    _run(spanning_corpus, client=_FoldsFirstTwoClient())

    positions = _read_jsonl(root / "map" / "testpin-category" / "positions.jsonl")
    folded = [p for p in positions if p.get("consolidated_from", 1) > 1]
    assert folded
    for position in folded:
        assert len(position["folded_from"]) == position["consolidated_from"]
        assert "variants" in position


class _ReReadOnlyClient(StubLLMClient):
    """Stands by every re-read and refuses to answer a consolidation call at
    all -- the assertion that a resumed run buys nothing it already paid
    for."""

    def __init__(self) -> None:
        super().__init__()
        self.re_read_shown: list[int] = []
        self.re_read_prompts: list[str] = []

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        self.call_count += 1
        if not _is_re_read(prompt):
            raise AssertionError("a resumed build re-asked a completed consolidation read")
        self.re_read_shown.append(len(_argument_handles(prompt)))
        self.re_read_prompts.append(prompt)
        return json.dumps(
            {"groups": [{"argument": "Stood by.", "handles": _argument_handles(prompt)}]}
        )

    def model_for_pass(self, pass_name: str | None = None) -> str:
        return "fake-model"


def test_a_ledger_written_before_provenance_existed_is_still_re_read(tmp_path: Path) -> None:
    """The ledger the first trigger was probed on holds completed
    consolidation calls and no record of what each entry was folded from.
    Re-asking those calls to obtain it would cost the whole pass again, so
    the members are rebuilt from the handles the entries did record --
    round by round, since round 2's inputs are round 1's rebuilt outputs --
    and the re-read fires on the resumed positions with the raw arguments in
    front of it."""
    ledger = tmp_path / "consolidation_reads.jsonl"
    reads = _two_groups_of(EXTRACT_SLICE)
    run_consolidation(
        reads, client=_FoldsRunsOfClient(), reads_path=ledger, log=lambda _m: None
    )

    # Roll the ledger back to the shape the paid run left: completed reads
    # carrying the handles each entry named, and nothing else.
    records = [record for record in _read_jsonl(ledger) if record.get("kind") != "re_read"]
    for record in records:
        for position in record["positions"]:
            position.pop("folded_from", None)
    with ledger.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")

    client = _ReReadOnlyClient()
    result = run_consolidation(reads, client=client, reads_path=ledger, log=lambda _m: None)

    assert sorted(client.re_read_shown) == [10, 25, 25, 25, 25]
    listed = _listed_arguments(client.re_read_prompts[0])
    assert all(" argument " in argument for argument in listed)
    assert not any(argument.startswith("Folded ") for argument in listed)
    assert sum(p["consolidated_from"] for p in result.positions) == 2 * EXTRACT_SLICE
    assert all(
        len(p["folded_from"]) == p["consolidated_from"] for p in result.positions
    )
