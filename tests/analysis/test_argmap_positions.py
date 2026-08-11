"""Acceptance tests for issue #572, PR 1 of 4: the argument map's position
layer (`axial.argmap.build`) -- select, bag, extract, merge.

This is a port of scratchpad scripts already run and measured over the real
corpus (`stage1b_extract_positions.py`, `stage1_analyse.py`); these tests
pin the behavioral contract the port must preserve, not a new design.
Fixtures and a fake client throughout -- no real model call, no dependence
on `data/` (a worktree has none).

Covered here:

  - passage selection drops each of the three exclusion classes (abstained
    claim, back matter, silent on every §7.15 argument field) and keeps a
    normal passage;
  - the extraction prompt's rendered claim listing carries no author label
    (issue #572 kickoff rule 1 -- the one deliberate deviation from the
    scratchpad run);
  - a handle the model invents is dropped, never repaired;
  - merge folds two differently-worded namings of one argument into a
    single position carrying the union of chunk_ids and both variants;
  - `position_id`s are stable across two runs on identical input, regardless
    of arrival order;
  - resume: a populated `reads.jsonl` makes no call for a `(bag, slice)`
    already on disk.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from axial.llm import StubLLMClient
from axial.argmap.build import (
    ExtractJob,
    Passage,
    assign_position_ids,
    compute_corpus_pin,
    extract_positions_for_slice,
    merge_positions,
    render_claims_blind,
    run_extraction,
    run_map_build,
    select_passages,
)
from axial.envelope import compute_source_id


# ---------------------------------------------------------------------------
# select_passages
# ---------------------------------------------------------------------------


def _write_answers(answers_dir: Path, records: list[dict[str, Any]]) -> None:
    answers_dir.mkdir(parents=True, exist_ok=True)
    with (answers_dir / "alpha-2020-book.jsonl").open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")


def _record(chunk_id: str, claim: Any, **extra_answers: Any) -> dict[str, Any]:
    answers = {
        "claim": claim,
        "mechanism": "not-in-passage",
        "comparison": "not-in-passage",
        "concedes": "not-in-passage",
        "assumes": "not-in-passage",
        "position_of": "not-in-passage",
        "ranges_over": "not-in-passage",
    }
    answers.update(extra_answers)
    return {"source_id": "alpha-2020-book", "chunk_id": chunk_id, "answers": answers}


def test_select_passages_drops_each_exclusion_class_and_keeps_a_normal_passage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    answers_dir = tmp_path / "answers"
    records = [
        # Kept: a real claim, and it argues something (mechanism answered).
        _record(
            "alpha-2020-book_010_intro_001",
            "States extract resources through coercion.",
            mechanism="coercive taxation",
        ),
        # Dropped: abstained claim.
        _record("alpha-2020-book_020_body_001", "not-in-passage"),
        # Dropped: back matter (order key "999", marked cut below).
        _record(
            "alpha-2020-book_999_bib_001",
            "Smith, J. (2001). Some Book. Publisher.",
            mechanism="citation formatting",
        ),
        # Dropped: a real claim sentence, but silent on every §7.15 field --
        # method throat-clearing, not an argument.
        _record(
            "alpha-2020-book_030_body_001",
            "This paper relies exclusively on English-language secondary sources.",
        ),
    ]
    _write_answers(answers_dir, records)

    # `load_back_matter_sections` is patched at the point `select_passages`
    # calls it, so this test never has to fabricate a real structural tree.
    monkeypatch.setattr(
        "axial.argmap.build.load_back_matter_sections",
        lambda trees_dir: {"alpha-2020-book": frozenset({"999"})},
    )

    passages = select_passages(answers_dir, tmp_path / "trees")

    assert len(passages) == 1
    kept = passages[0]
    assert kept.chunk_id == "alpha-2020-book_010_intro_001"
    assert kept.source_id == "alpha-2020-book"
    assert kept.author == "alpha"
    assert kept.claim == "States extract resources through coercion."


# ---------------------------------------------------------------------------
# render_claims_blind
# ---------------------------------------------------------------------------


def test_extraction_prompt_carries_no_author_label() -> None:
    members = [
        Passage(
            chunk_id="c1", source_id="elcheroth-2017-abc", author="elcheroth", claim="Claim one."
        ),
        Passage(
            chunk_id="c2", source_id="malesevic-2010-xyz", author="malesevic", claim="Claim two."
        ),
    ]

    listing, handles = render_claims_blind(members)

    assert listing == "[p1] Claim one.\n[p2] Claim two."
    assert "elcheroth" not in listing
    assert "malesevic" not in listing
    assert handles == {"p1": members[0], "p2": members[1]}


# ---------------------------------------------------------------------------
# extract_positions_for_slice: an invented handle is dropped, never repaired
# ---------------------------------------------------------------------------


class _ScriptedClient(StubLLMClient):
    """A client whose response is scripted, mirroring
    `tests.test_interrogate._ScriptedClient`'s own local-fixture pattern."""

    def __init__(self, response: str) -> None:
        super().__init__()
        self._response = response

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        self.call_count += 1
        return self._response

    def model_for_pass(self, pass_name: str | None = None) -> str:
        return "scripted"


def _job(*claims: str) -> ExtractJob:
    members = tuple(
        Passage(chunk_id=f"c{i + 1}", source_id="alpha-2020-book", author="alpha", claim=claim)
        for i, claim in enumerate(claims)
    )
    return ExtractJob(bag=0, slice_index=0, members=members)


def test_an_invented_handle_is_dropped_never_repaired() -> None:
    job = _job("Claim one.", "Claim two.", "Claim three.")
    response = json.dumps(
        {
            "arguments": [
                # p99 does not exist -- dropped, p1/p2 still placed.
                {
                    "argument": "States extract resources through coercion.",
                    "handles": ["p1", "p2", "p99"],
                },
                # every handle here is invented -- the whole argument is dropped.
                {"argument": "A fully invented argument.", "handles": ["p99"]},
            ],
            "unassigned": ["p3", "p100"],
        }
    )
    client = _ScriptedClient(response)

    record = extract_positions_for_slice(job, client)

    assert len(record["positions"]) == 1
    position = record["positions"][0]
    assert position["argument"] == "States extract resources through coercion."
    assert position["chunk_ids"] == ["c1", "c2"]
    assert position["size"] == 2
    # p100 is invented and never counted; only p3 is a real unassigned handle.
    assert record["unassigned"] == 1


def test_a_malformed_non_object_response_is_recorded_as_a_failed_read_not_a_crash() -> None:
    job = _job("Claim one.")
    client = _ScriptedClient(json.dumps(["not", "the", "expected", "shape"]))

    record = extract_positions_for_slice(job, client)

    assert "error" in record
    assert record["positions"] == []


# ---------------------------------------------------------------------------
# merge_positions
# ---------------------------------------------------------------------------

_ARGUMENT_A = "States extract resources through coercion."
_ARGUMENT_B = "State extraction of resources is fundamentally coercive."
_ARGUMENT_C = "Ethnic identity is socially constructed."

_FAKE_VECTORS = {
    _ARGUMENT_A: [1.0, 0.0],
    _ARGUMENT_B: [1.0, 0.0],
    _ARGUMENT_C: [0.0, 1.0],
}


def _fake_encode(texts):
    return np.array([_FAKE_VECTORS[text] for text in texts])


def _fake_cluster_fn(vectors) -> list[int]:
    """Groups vectors by exact value into small integer labels -- mirrors
    `axial.test_names._fake_cluster_fn` exactly, so these tests never need
    scikit-learn (an optional `distill`-group dependency) installed."""
    labels: dict[tuple[float, ...], int] = {}
    result = []
    for vector in vectors:
        key = tuple(float(v) for v in vector)
        if key not in labels:
            labels[key] = len(labels)
        result.append(labels[key])
    return result


def _raw_positions() -> list[dict[str, Any]]:
    return [
        {
            "argument": _ARGUMENT_A,
            "chunk_ids": ["c1"],
            "sources": ["alpha-2020-book"],
            "authors": ["alpha"],
            "size": 1,
        },
        {
            "argument": _ARGUMENT_B,
            "chunk_ids": ["c2"],
            "sources": ["beta-2019-book"],
            "authors": ["beta"],
            "size": 1,
        },
        {
            "argument": _ARGUMENT_C,
            "chunk_ids": ["c3"],
            "sources": ["gamma-2018-book"],
            "authors": ["gamma"],
            "size": 1,
        },
    ]


def test_merge_folds_two_namings_of_one_argument_and_keeps_a_real_difference_apart() -> None:
    merged = merge_positions(_raw_positions(), _fake_encode, cluster_fn=_fake_cluster_fn)

    by_variant_count = sorted(merged, key=lambda p: -p["named_times"])
    folded = by_variant_count[0]
    apart = by_variant_count[1]

    assert folded["named_times"] == 2
    assert folded["chunk_ids"] == ["c1", "c2"]
    assert set(folded["variants"]) == {_ARGUMENT_A, _ARGUMENT_B}
    assert folded["sources"] == ["alpha-2020-book", "beta-2019-book"]
    assert folded["authors"] == ["alpha", "beta"]
    assert folded["size"] == 2

    assert apart["named_times"] == 1
    assert apart["argument"] == _ARGUMENT_C
    assert apart["chunk_ids"] == ["c3"]


# ---------------------------------------------------------------------------
# assign_position_ids: stable regardless of input order
# ---------------------------------------------------------------------------


def test_position_ids_are_stable_across_two_runs_on_identical_input() -> None:
    raw = _raw_positions()

    merged_first = merge_positions(raw, _fake_encode, cluster_fn=_fake_cluster_fn)
    stamped_first = assign_position_ids(merged_first)

    # A second run sees the same raw positions in a different order -- the
    # real pipeline's own arrival order is thread-completion order, which
    # varies run to run.
    reordered = [raw[2], raw[0], raw[1]]
    merged_second = merge_positions(reordered, _fake_encode, cluster_fn=_fake_cluster_fn)
    stamped_second = assign_position_ids(merged_second)

    def _id_for(stamped: list[dict[str, Any]], argument: str) -> str:
        # Looked up by variant membership, not the winning `argument` field:
        # which of two same-size phrasings wins the representative slot is
        # itself part of what must be deterministic, not an assumption this
        # helper should bake in.
        (match,) = [p["position_id"] for p in stamped if argument in p["variants"]]
        return match

    assert _id_for(stamped_first, _ARGUMENT_A) == _id_for(stamped_second, _ARGUMENT_A)
    assert _id_for(stamped_first, _ARGUMENT_C) == _id_for(stamped_second, _ARGUMENT_C)
    assert {p["position_id"] for p in stamped_first} == {"pos-0001", "pos-0002"}

    # The representative phrasing chosen for the folded group is itself
    # deterministic (alphabetical tiebreak on an equal-size group), not just
    # its id.
    folded_first = next(p for p in stamped_first if p["named_times"] == 2)
    folded_second = next(p for p in stamped_second if p["named_times"] == 2)
    assert folded_first["argument"] == folded_second["argument"]


# ---------------------------------------------------------------------------
# run_extraction: resume skips a (bag, slice) already on disk
# ---------------------------------------------------------------------------


class _CountingClient(StubLLMClient):
    def __init__(self) -> None:
        super().__init__()
        self.seen_prompts: list[str] = []

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        self.call_count += 1
        self.seen_prompts.append(prompt)
        return json.dumps({"arguments": [], "unassigned": []})

    def model_for_pass(self, pass_name: str | None = None) -> str:
        return "counting"


def test_resume_makes_no_call_for_a_bag_slice_already_on_disk(tmp_path: Path) -> None:
    reads_path = tmp_path / "reads.jsonl"
    # Job (bag=0, slice=0) is already on disk from an earlier, interrupted run.
    reads_path.write_text(
        json.dumps({"bag": 0, "slice": 0, "shown": 1, "positions": [], "unassigned": 0}) + "\n",
        encoding="utf-8",
    )

    job_done = ExtractJob(
        bag=0,
        slice_index=0,
        members=(
            Passage(chunk_id="c1", source_id="alpha-2020-book", author="alpha", claim="Claim one."),
        ),
    )
    job_pending = ExtractJob(
        bag=1,
        slice_index=0,
        members=(
            Passage(chunk_id="c2", source_id="beta-2019-book", author="beta", claim="Claim two."),
        ),
    )
    client = _CountingClient()

    reads = run_extraction(
        [job_done, job_pending],
        client=client,
        reads_path=reads_path,
        workers=2,
        log=lambda _msg: None,
    )

    assert client.call_count == 1
    assert len(reads) == 2
    keys = {(r["bag"], r["slice"]) for r in reads}
    assert keys == {(0, 0), (1, 0)}


# ---------------------------------------------------------------------------
# run_map_build: --force re-asks under the same pin, keeping the old ledger
# ---------------------------------------------------------------------------


def _write_one_answer(answers_dir: Path) -> None:
    answers_dir.mkdir(parents=True, exist_ok=True)
    record = _record(
        "alpha-2020-book_010_intro_001",
        "States extract resources through coercion.",
        mechanism="coercive taxation",
    )
    with (answers_dir / "alpha-2020-book.jsonl").open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")


def _fake_encode_any(texts: Any) -> np.ndarray:
    return np.zeros((len(texts), 2))


def _run_build(tmp_path: Path, *, client: Any, force: bool = False) -> Path:
    manifest = run_map_build(
        answers_dir=tmp_path / "answers",
        trees_dir=tmp_path / "trees",
        map_dir=tmp_path / "map",
        client=client,
        encode=_fake_encode_any,
        pin="testpin",
        guard=False,
        force=force,
        log=lambda _msg: None,
    )
    assert manifest["corpus_pin"] == "testpin"
    return tmp_path / "map" / "testpin"


def test_force_reasks_a_bag_slice_already_on_disk_and_keeps_the_prior_ledger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("axial.argmap.build.load_back_matter_sections", lambda trees_dir: {})
    _write_one_answer(tmp_path / "answers")

    first_client = _CountingClient()
    outdir = _run_build(tmp_path, client=first_client)
    reads_path = outdir / "reads.jsonl"
    assert first_client.call_count == 1
    prior_ledger = reads_path.read_text(encoding="utf-8")

    # Without --force, a second build resumes: no new call for the same
    # (bag, slice), and the ledger is untouched -- the existing contract.
    resumed_client = _CountingClient()
    _run_build(tmp_path, client=resumed_client)
    assert resumed_client.call_count == 0
    assert reads_path.read_text(encoding="utf-8") == prior_ledger

    # With --force, the same (bag, slice) is re-asked, and the prior ledger
    # survives on disk under a new name rather than being deleted.
    forced_client = _CountingClient()
    _run_build(tmp_path, client=forced_client, force=True)
    assert forced_client.call_count == 1

    siblings = list(outdir.glob("reads.*.jsonl"))
    assert len(siblings) == 1
    assert siblings[0].read_text(encoding="utf-8") == prior_ledger
    assert reads_path.exists()


# ---------------------------------------------------------------------------
# compute_corpus_pin: content-keyed, and nothing else
# ---------------------------------------------------------------------------


def _arrange_source(tmp_path: Path, name: str, text: str) -> tuple[Path, Path]:
    envelopes_dir = tmp_path / f"{name}-envelopes"
    sources_dir = tmp_path / f"{name}-sources"
    envelopes_dir.mkdir(parents=True, exist_ok=True)
    sources_dir.mkdir(parents=True, exist_ok=True)

    # `.pdf` name is nominal only (mirrors tests/analysis/test_corpus_pin.py's
    # own fixture): corpus_pin never parses the file, only hashes its raw
    # bytes, and SUPPORTED_EXTENSIONS requires one of .pdf/.docx.
    source_path = sources_dir / "alpha.pdf"
    source_path.write_text(text, encoding="utf-8")
    source_id = compute_source_id(source_path)
    (envelopes_dir / f"{source_id}.json").write_text(
        json.dumps({"source_id": source_id}), encoding="utf-8"
    )
    return envelopes_dir, sources_dir


def test_corpus_pin_changes_when_source_content_changes_and_is_otherwise_stable(
    tmp_path: Path,
) -> None:
    envelopes_dir, sources_dir = _arrange_source(tmp_path, "same", "original text")

    pin_first = compute_corpus_pin(envelopes_dir, sources_dir)
    pin_repeat = compute_corpus_pin(envelopes_dir, sources_dir)
    assert pin_first == pin_repeat

    envelopes_dir_changed, sources_dir_changed = _arrange_source(
        tmp_path, "changed", "different text"
    )
    pin_changed = compute_corpus_pin(envelopes_dir_changed, sources_dir_changed)
    assert pin_changed != pin_first
