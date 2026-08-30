"""Inner unit tests for `axial.argmap.ask.positions_on` and
`resolve_pinned_map_dir` (issue #650): the argument map's positions as a
retrieval target, joined to a name through the note store rather than
through the encoder.

No encoder is built and no model call is made -- that is the point of this
route: `positions.jsonl` already records which passages stand behind each
position, and `note_names` already records which notes carry a name, so the
join is a table lookup.
"""

from __future__ import annotations

import collections
import hashlib
import json
import os
from pathlib import Path

import numpy as np
import pytest

from axial.argmap.ask import positions_on, resolve_pinned_map_dir
from axial.argmap.build import (
    PASS_NAME,
    Passage,
    SchemeVersionMismatchError,
    _bag_state_path,
    _bag_state_reusable,
    _members_key,
    _prior_pin_dir,
    _write_bag_state,
    run_map_build,
)
from axial.argmap.consolidate import PASS_NAME as CONSOLIDATE_PASS_NAME
from axial.argmap.grouping import group_by_intersection, group_by_intersection_with_claim_fallback
from axial.llm import LLMError, StubLLMClient
from axial.query import store as note_store

MANN = "mann-2012-aaaaaaaaaaaa"
HALL = "hall-2006-bbbbbbbbbbbb"

MANN_NOTES = [f"{MANN}_00{i}_intro_00{i}" for i in (1, 2, 3)]
HALL_NOTES = [f"{HALL}_00{i}_intro_00{i}" for i in (1, 2)]


@pytest.fixture
def vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    # `positions_on` reads the store through `axial.query.relations`, whose
    # own default `vault_dir` is cwd-relative -- every call here passes one
    # explicitly, and this closes the default anyway (issue #657). The same
    # close for `names_dir`, which matters more since #650's follow-up: a
    # name argument now falls through to `find_names`, whose embedding tier
    # would read the operator's live `data/names/` -- vectors and a
    # sentence-transformer -- for a phrase this fixture's own store cannot
    # resolve.
    from axial.query import names as names_module
    from axial.query import relations as relations_module

    empty = tmp_path / "vault-default"
    empty.mkdir()
    empty_names = tmp_path / "names-default"
    empty_names.mkdir()
    monkeypatch.setattr(relations_module, "default_vault_dir", lambda *a, **k: empty)
    monkeypatch.setattr(names_module, "default_vault_dir", lambda *a, **k: empty)
    monkeypatch.setattr(names_module, "default_names_dir", lambda *a, **k: empty_names)

    vault_dir = tmp_path / "vault"
    note_store.write_store(
        note_store.store_path(vault_dir),
        sources=[
            (MANN, "Mann", "The Sources of Social Power", "2012", 2012),
            (HALL, "Hall", "An Anatomy of Power", "2006", 2006),
        ],
        notes=[
            (chunk_id, source_id, "Introduction", None, "A claim.", None)
            for source_id, ids in ((MANN, MANN_NOTES), (HALL, HALL_NOTES))
            for chunk_id in ids
        ],
        names=[("the state", "concept", "the state")],
        note_names=[
            (chunk_id, source_id, "the state", "concept")
            for source_id, ids in ((MANN, MANN_NOTES), (HALL, HALL_NOTES))
            for chunk_id in ids
        ],
        note_arguing_against=[],
        note_citations=[],
    )
    return vault_dir


def _write_map(map_dir: Path, positions: list[dict]) -> Path:
    map_dir.mkdir(parents=True, exist_ok=True)
    (map_dir / "map.json").write_text(json.dumps({"encoder": "x"}), encoding="utf-8")
    (map_dir / "positions.jsonl").write_text(
        "\n".join(json.dumps(position) for position in positions), encoding="utf-8"
    )
    return map_dir


def _position(position_id: str, chunk_ids: list[str], argument: str) -> dict:
    return {
        "position_id": position_id,
        "argument": argument,
        "size": len(chunk_ids),
        "sources": sorted({chunk_id.rsplit("_", 3)[0] for chunk_id in chunk_ids}),
        "authors": ["Mann", "Hall"],
        "chunk_ids": chunk_ids,
    }


def test_positions_a_name_reaches_rank_by_how_many_of_their_passages_carry_it(
    vault: Path, tmp_path: Path
):
    map_dir = _write_map(
        tmp_path / "map" / "pin",
        [
            _position("p-0001", [MANN_NOTES[0]], "One passage names the state."),
            _position("p-0002", MANN_NOTES + HALL_NOTES, "The state is a protection racket."),
            _position("p-0003", ["other-1999-dddddddddddd_001_a_001"], "Unrelated."),
        ],
    )

    positions, ids, total, _ = positions_on("the state", 10, map_dir=map_dir, vault_dir=vault)

    assert [p.position_id for p in positions] == ["p-0002", "p-0001"]
    assert positions[0].matched_note_count == 5
    assert positions[0].argument == "The state is a protection racket."
    # Every passage of every matched position is reachable; the unrelated
    # position contributes nothing.
    assert set(ids) == set(MANN_NOTES + HALL_NOTES)
    assert total == 5


def test_a_descriptive_phrase_reaches_the_positions_a_bare_canonical_does(
    vault: Path, tmp_path: Path
):
    """`positions_on` took the same exact-only resolution `find_notes` did
    (issue #650's follow-up): a live run asked `positions_on(name=
    "bellicist")` and got `0/0`. The phrase resolves the way `find_names`
    resolves it now, and the resolution comes back so an empty result can
    say what it looked for."""
    map_dir = _write_map(
        tmp_path / "map" / "pin",
        [_position("p-0002", MANN_NOTES + HALL_NOTES, "The state is a protection racket.")],
    )

    positions, ids, _total, resolution = positions_on(
        "what the modern state is", 10, map_dir=map_dir, vault_dir=vault
    )

    assert resolution.canonical == "the state"
    assert [p.position_id for p in positions] == ["p-0002"]
    assert set(ids) == set(MANN_NOTES + HALL_NOTES)


def test_a_capped_window_spreads_across_positions_and_sources(vault: Path, tmp_path: Path):
    map_dir = _write_map(
        tmp_path / "map" / "pin",
        [
            _position("p-0002", MANN_NOTES + HALL_NOTES, "The state is a protection racket."),
            _position("p-0001", [MANN_NOTES[0]], "One passage names the state."),
        ],
    )

    _positions, ids, total, _ = positions_on("the state", 2, map_dir=map_dir, vault_dir=vault)

    assert len(ids) == 2
    assert total == 5
    # One id per source in rotation inside the big position, so a two-id
    # window is not two notes of the same book.
    assert len({chunk_id.rsplit("-", 1)[0] for chunk_id in ids}) == 2
    again = positions_on("the state", 2, map_dir=map_dir, vault_dir=vault)[1]
    assert ids == again


def test_no_map_and_no_match_are_both_empty_answers_not_errors(vault: Path, tmp_path: Path):
    # No map: nothing was resolved either, and the result says so with a
    # `None` resolution rather than claiming the name matched nothing.
    assert positions_on("the state", 10, map_dir=None, vault_dir=vault) == ([], [], 0, None)
    assert positions_on("the state", 10, map_dir=tmp_path / "absent", vault_dir=vault) == (
        [],
        [],
        0,
        None,
    )
    map_dir = _write_map(
        tmp_path / "map" / "pin", [_position("p-0001", MANN_NOTES, "An argument.")]
    )
    positions, ids, total, resolution = positions_on(
        "nobody home", 10, map_dir=map_dir, vault_dir=vault
    )
    assert (positions, ids, total) == ([], [], 0)
    assert resolution is not None and not resolution.resolved


def test_resolve_pinned_map_dir_is_none_when_nothing_is_built(tmp_path: Path):
    assert resolve_pinned_map_dir(map_dir=tmp_path / "absent") is None
    root = tmp_path / "map"
    root.mkdir()
    assert resolve_pinned_map_dir(map_dir=root, pin="nope") is None
    _write_map(root / "real-pin", [_position("p-0001", MANN_NOTES, "An argument.")])
    assert resolve_pinned_map_dir(map_dir=root, pin="real-pin") == root / "real-pin"


def test_a_corpus_whose_pin_cannot_be_computed_resolves_to_no_map_rather_than_raising(
    tmp_path: Path,
):
    """No envelopes directory means there is no corpus to verify a built map
    against -- an optional capability check answering "no map", never an
    exception thrown through a paid brief run."""
    root = tmp_path / "map"
    _write_map(root / "some-pin", [_position("p-0001", MANN_NOTES, "An argument.")])
    assert (
        resolve_pinned_map_dir(
            map_dir=root,
            envelopes_dir=tmp_path / "no-envelopes",
            sources_dir=tmp_path / "no-sources",
        )
        is None
    )


# ---------------------------------------------------------------------------
# `axial map build --grouping category` (issue #829, positions-not-names slice
# 04): the same selection/extraction/merge machinery run over slice 03's
# chosen inner split (`grouping.group_by_intersection`, decided on measurement
# in #828) instead of wording bags, into its own variant directory.
#
# These live here rather than in `test_grouping.py` because the slice declared
# this file as its test home: the behaviours below are build-level, and the two
# grouping-level ones (the claim-only fallback's own edge cases) are kept next
# to the build tests that consume them rather than split across two files for
# one slice.
# ---------------------------------------------------------------------------

CAT_A = "causal-argument-state-formation-or-power"
CAT_B = "empirical-finding-without-causal-claim"
MECH_1 = "war-and-state-formation"
MECH_2 = "elite-competition-and-coalition-formation"

CLAIM_SCHEME_VERSION = "2026-08-28-claim-v1"
MECHANISM_SCHEME_VERSION = "2026-08-28-mechanism-v1"


def _answer_record(chunk_id: str, claim: str) -> dict:
    """One `data/answers/` record `select_passages` keeps: a real claim and a
    non-abstained `mechanism`, so it is argument-bearing on both counts."""
    return {
        "source_id": chunk_id.rsplit("_", 3)[0],
        "chunk_id": chunk_id,
        "answers": {
            "claim": claim,
            "mechanism": "coercive taxation",
            "comparison": "not-in-passage",
            "concedes": "not-in-passage",
            "assumes": "not-in-passage",
            "position_of": "not-in-passage",
            "ranges_over": "not-in-passage",
        },
    }


def _write_answers(answers_dir: Path, chunk_ids: list[str]) -> None:
    answers_dir.mkdir(parents=True, exist_ok=True)
    by_source: dict[str, list[dict]] = {}
    for index, chunk_id in enumerate(chunk_ids):
        record = _answer_record(chunk_id, f"Claim number {index}.")
        by_source.setdefault(record["source_id"], []).append(record)
    for source_id, records in by_source.items():
        with (answers_dir / f"{source_id}.jsonl").open("w", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record) + "\n")


def _write_column(
    vocabulary_dir: Path,
    column: str,
    scheme_version: str,
    category_by_chunk: dict,
) -> None:
    """A built vocabulary column: the manifest `run_map_build` reads
    `scheme_version` off, and one level-1 assignment record per chunk. A
    `None` category is a refusal -- the record exists, `category_id` does
    not."""
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


def _hash_tree(root: Path) -> dict:
    """Every file under `root`, by relative path -> sha256 of its bytes --
    the "byte-identical" the acceptance criterion means."""
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


class _OneArgumentClient(StubLLMClient):
    """Answers every extraction call with a single argument holding every
    handle it was shown, and records the prompts so a test can see which
    passages were read together. `calls_by_pass` counts them per pass: a
    category-grouped build now makes consolidation calls too (issue #830),
    so a bare `call_count` no longer says how many reads step 3 made."""

    def __init__(self) -> None:
        super().__init__()
        self.seen_prompts: list[str] = []
        self.calls_by_pass: collections.Counter[str] = collections.Counter()

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        self.call_count += 1
        self.calls_by_pass[pass_name or ""] += 1
        self.seen_prompts.append(prompt)
        return json.dumps(
            {"arguments": [{"argument": "An argument.", "handles": _handles(prompt)}]}
        )

    def model_for_pass(self, pass_name: str | None = None) -> str:
        return "fake-model"


class _RefusingClient(StubLLMClient):
    """Raises on any call at all -- the resume assertion: a re-run over a
    complete ledger must not reach the model."""

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        raise AssertionError("a resumed build re-asked a slice already on disk")

    def model_for_pass(self, pass_name: str | None = None) -> str:
        return "fake-model"


def _handles(prompt: str) -> list[str]:
    """Every handle `render_claims_blind` (`p1`, `p2`, ...) or
    `render_arguments_blind` (`a1`, `a2`, ..., issue #830) put in `prompt`,
    so a fake client can answer about exactly what it was shown."""
    return [
        line.split("]")[0][1:]
        for line in prompt.splitlines()
        if line.startswith("[p") or line.startswith("[a")
    ]


def _fake_encode(texts):
    return np.zeros((len(texts), 2))


@pytest.fixture
def category_corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    """Four selected passages across two books, with `claim` and `mechanism`
    columns built over them:

      c1, c2 -> CAT_A x MECH_1        one full cell
      c3     -> CAT_A, no mechanism   the claim-only fallback
      c4     -> no claim, MECH_2      genuinely ungrouped

    `_agglomerative_cluster` is faked to one cluster so neither the default
    bagging nor the merge needs scikit-learn (an optional `distill`-group
    dependency this suite does not require)."""
    monkeypatch.setattr("axial.argmap.build.load_back_matter_sections", lambda trees_dir: {})
    monkeypatch.setattr(
        "axial.argmap.build._agglomerative_cluster",
        lambda vectors, threshold: [0] * len(vectors),
    )
    chunk_ids = [
        "alpha-2020-book_010_intro_001",
        "alpha-2020-book_020_body_001",
        "beta-2021-book_010_intro_001",
        "beta-2021-book_020_body_001",
    ]
    _write_answers(tmp_path / "answers", chunk_ids)
    vocabulary_dir = tmp_path / "vocabulary"
    _write_column(
        vocabulary_dir,
        "claim",
        CLAIM_SCHEME_VERSION,
        {chunk_ids[0]: CAT_A, chunk_ids[1]: CAT_A, chunk_ids[2]: CAT_A, chunk_ids[3]: None},
    )
    _write_column(
        vocabulary_dir,
        "mechanism",
        MECHANISM_SCHEME_VERSION,
        {chunk_ids[0]: MECH_1, chunk_ids[1]: MECH_1, chunk_ids[2]: None, chunk_ids[3]: MECH_2},
    )
    return {"root": tmp_path, "chunk_ids": chunk_ids, "vocabulary_dir": vocabulary_dir}


def _run_map_build(corpus: dict, *, client, grouping: str = "bag", log=None, **kwargs):
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


def test_grouping_category_writes_a_variant_set_and_leaves_the_default_build_byte_identical(
    category_corpus: dict,
) -> None:
    """The acceptance criterion of issue #829, end to end."""
    root = category_corpus["root"]
    default_dir = root / "map" / "testpin"
    variant_dir = root / "map" / "testpin-category"

    _run_map_build(category_corpus, client=_OneArgumentClient())
    before = _hash_tree(default_dir)
    assert before

    manifest = _run_map_build(category_corpus, client=_OneArgumentClient(), grouping="category")

    for name in ("reads.jsonl", "positions.jsonl", "map.json"):
        assert (variant_dir / name).is_file()
    assert manifest["grouping"]["mode"] == "category"
    assert manifest["grouping"]["scheme_versions"] == {
        "claim": CLAIM_SCHEME_VERSION,
        "mechanism": MECHANISM_SCHEME_VERSION,
    }
    # c4 holds no claim category at all, so it reaches no group -- counted,
    # never silently dropped, and never confused with `passages_unassigned`
    # (handles the model itself called argument-less).
    assert manifest["counts"]["passages_ungrouped"] == 1
    assert "passages_unassigned" in manifest["counts"]
    # Relations are slice 07's, not this one's: the variant manifest carries
    # no relations block at all.
    assert "relations" not in manifest

    assert _hash_tree(default_dir) == before

    # Resume: the whole variant ledger is on disk, so a second run reaches
    # the model for nothing.
    resumed = _run_map_build(category_corpus, client=_RefusingClient(), grouping="category")
    assert resumed["counts"]["units_reused"] == resumed["counts"]["units_total"]
    assert _hash_tree(default_dir) == before


def test_category_groups_are_the_extraction_unit_and_a_claim_only_passage_still_lands(
    category_corpus: dict,
) -> None:
    """`--grouping category` routes step 2 through slice 03's chosen split:
    the ledger is keyed by the group label, and the 780-passage real-corpus
    case -- a claim with no mechanism -- lands in its own claim-only group
    rather than going ungrouped (founder ruling, 2026-08-29)."""
    root = category_corpus["root"]
    client = _OneArgumentClient()
    _run_map_build(category_corpus, client=client, grouping="category")

    reads = _read_jsonl(root / "map" / "testpin-category" / "reads.jsonl")
    assert sorted(read["bag"] for read in reads) == [
        f"{CAT_A}::(no mechanism)",
        f"{CAT_A}::{MECH_1}",
    ]
    # Two groups, two extraction calls -- the full cell and the claim-only
    # fallback. The consolidation pass (issue #830) reads the same category
    # once more, under its own pass name.
    assert client.calls_by_pass[PASS_NAME] == 2
    assert client.calls_by_pass[CONSOLIDATE_PASS_NAME] == 1


def _passage(chunk_id: str, index: int) -> Passage:
    """One selected passage as `select_passages` builds it from
    `_answer_record` -- same claim text, so `_members_key` over these is
    exactly what a real build computes for the same chunks."""
    source_id = chunk_id.rsplit("_", 3)[0]
    return Passage(
        chunk_id=chunk_id,
        source_id=source_id,
        author=source_id.split("-")[0],
        claim=f"Claim number {index}.",
    )


def test_the_variant_build_never_seeds_from_a_prior_pins_ledger(category_corpus: dict) -> None:
    """The single most expensive way this slice could go wrong: the variant
    silently reproducing the default map because `_seed_reads_from_prior_pin`
    refilled its ledger from a prior pin's reads.

    The prior pin here is loaded so that seeding fires if it is consulted at
    all: `_prior_pin_dir` resolves it, its bag state matches this run's
    encoder/threshold/library version, and it holds a read whose
    `members_key` is exactly the one the variant's `claim x mechanism` group
    computes. A seeded variant would report that read reused and never call
    the model for it."""
    root = category_corpus["root"]
    chunk_ids = category_corpus["chunk_ids"]
    passages = [_passage(chunk_id, index) for index, chunk_id in enumerate(chunk_ids)]
    map_dir = root / "map"
    prior = map_dir / "otherpin"
    prior.mkdir(parents=True)
    (prior / "map.json").write_text(json.dumps({"corpus_pin": "otherpin"}), encoding="utf-8")
    _write_bag_state(_bag_state_path(prior), {0: passages}, {0: np.zeros(2)})
    (prior / "reads.jsonl").write_text(
        json.dumps(
            {
                "bag": 0,
                "slice": 0,
                "members_key": _members_key(passages[:2]),
                "shown": 2,
                "positions": [],
                "unassigned": 0,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    # The prior pin really is the one a seeding build would reach for, and
    # its bag state really is one an incremental build would accept.
    assert _prior_pin_dir(map_dir, "testpin") == prior
    assert _bag_state_reusable(json.loads(_bag_state_path(prior).read_text(encoding="utf-8")))

    variant_client = _OneArgumentClient()
    manifest = _run_map_build(category_corpus, client=variant_client, grouping="category")

    assert manifest["counts"]["units_reused"] == 0
    assert variant_client.calls_by_pass[PASS_NAME] == manifest["counts"]["units_total"]
    # And the variant's own state is a category grouping, never a bag fit a
    # later run could reuse.
    state = json.loads((map_dir / "testpin-category" / "bag_state.json").read_text("utf-8"))
    assert state["config"]["grouping"] == "category"
    assert not _bag_state_reusable(state)


def test_a_scheme_version_change_refuses_a_resumed_variant_build(category_corpus: dict) -> None:
    _run_map_build(category_corpus, client=_OneArgumentClient(), grouping="category")

    _write_column(
        category_corpus["vocabulary_dir"],
        "claim",
        "2026-09-01-claim-v2",
        {chunk_id: CAT_A for chunk_id in category_corpus["chunk_ids"][:3]},
    )

    with pytest.raises(SchemeVersionMismatchError) as excinfo:
        _run_map_build(category_corpus, client=_RefusingClient(), grouping="category")
    assert "claim" in str(excinfo.value)

    # `--force` is the deliberate act the refusal asks for: it sets the prior
    # ledger aside and re-asks every group under the scheme now on disk.
    #
    # The v2 column keeps the same category ids, so every group label is
    # unchanged and a ledger left in place would match on `members_key` and
    # be reused in silence -- producing exactly the half-and-half map the
    # refusal exists to prevent. Recording the new scheme version in the
    # manifest passes either way, so the ledger itself is what is asserted:
    # nothing reused, and one model call per group.
    forced_client = _OneArgumentClient()
    forced = _run_map_build(category_corpus, client=forced_client, grouping="category", force=True)
    assert forced["grouping"]["scheme_versions"]["claim"] == "2026-09-01-claim-v2"
    assert forced["counts"]["units_total"] == 2
    assert forced["counts"]["units_reused"] == 0
    assert forced_client.calls_by_pass[PASS_NAME] == forced["counts"]["units_total"]


class _OneFailingReadClient(StubLLMClient):
    """Fails the single-passage read and answers the rest. A transport
    failure is recorded as `error` on the read rather than raised
    (`extract_positions_for_slice`'s fault-isolation contract), so the build
    completes carrying exactly one failed read."""

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        self.call_count += 1
        handles = _handles(prompt)
        if len(handles) == 1:
            raise LLMError("the model call failed")
        return json.dumps({"arguments": [{"argument": "An argument.", "handles": handles}]})

    def model_for_pass(self, pass_name: str | None = None) -> str:
        return "fake-model"


def test_the_grouping_unit_is_named_by_mode_in_the_manifest_and_the_log(
    category_corpus: dict,
) -> None:
    """Both manifests are written to be read side by side, so the unit count
    cannot share a key: 660 wording bags and 176 category cells under one
    `bags` key read as a single quantity changing. Same defect the slice
    already split `passages_placed` for. The progress log has the mirror
    problem -- printing "bag" while `--grouping category` runs names the
    other value of the flag the operator just set."""
    default_log: list[str] = []
    variant_log: list[str] = []
    default = _run_map_build(category_corpus, client=_OneArgumentClient(), log=default_log.append)
    variant = _run_map_build(
        category_corpus,
        client=_OneArgumentClient(),
        grouping="category",
        log=variant_log.append,
    )

    assert default["counts"]["bags"] == 1
    assert "groups" not in default["counts"]
    assert variant["counts"]["groups"] == 2
    assert "bags" not in variant["counts"]

    assert any(line.startswith("  read 1/1 (bag ") for line in default_log)
    assert any("(group " in line for line in variant_log if line.startswith("  read "))

    # "every passage shown once" read as a coverage guarantee one line under
    # "17 passage(s) reached no group". It never meant that.
    assert not any("every passage shown once" in line for line in default_log + variant_log)
    assert any(line.startswith("reads 1 over 1 bag(s)") for line in default_log)
    assert any(line.startswith("reads 2 over 2 group(s)") for line in variant_log)

    # And the summary line carries the denominator, so a reader never has to
    # open the manifest to know what 4 placed passages is out of.
    assert any("distinct passages placed 4 of 4 selected" in line for line in default_log)


def test_the_manifests_passage_arithmetic_closes_over_a_failed_read(
    category_corpus: dict,
) -> None:
    """`failed_reads` counts READS, so selected minus ungrouped minus placed
    minus unassigned left a remainder a reader could only guess at.
    `passages_in_failed_reads` names it, in both modes."""
    variant = _run_map_build(category_corpus, client=_OneFailingReadClient(), grouping="category")
    counts = variant["counts"]
    assert counts["failed_reads"] == 1
    assert counts["passages_in_failed_reads"] == 1
    assert (
        counts["passages_selected"]
        - counts["passages_ungrouped"]
        - counts["passages_placed_distinct"]
        - counts["passages_unassigned"]
        - counts["passages_in_failed_reads"]
    ) == 0

    default = _run_map_build(category_corpus, client=_OneArgumentClient())
    assert default["counts"]["passages_in_failed_reads"] == 0


def test_distinct_placed_passages_are_counted_below_the_slot_sum(category_corpus: dict) -> None:
    """Issue #829's folded-in defect: `placed` summed member SLOTS over RAW
    positions, so a passage named in two raw positions counted twice and the
    live build printed 6,070 placed against 6,010 selected."""

    class _TwiceNamingClient(StubLLMClient):
        def complete(self, prompt: str, pass_name: str | None = None) -> str:
            self.call_count += 1
            handles = _handles(prompt)
            return json.dumps(
                {
                    "arguments": [
                        {"argument": "One naming.", "handles": handles},
                        {"argument": "Another naming.", "handles": handles[:1]},
                    ]
                }
            )

        def model_for_pass(self, pass_name: str | None = None) -> str:
            return "fake-model"

    logged: list[str] = []
    manifest = _run_map_build(category_corpus, client=_TwiceNamingClient(), log=logged.append)

    counts = manifest["counts"]
    assert counts["passages_placed_slots"] > counts["passages_placed_distinct"]
    assert counts["passages_placed_distinct"] <= counts["passages_selected"]
    line = next(line for line in logged if line.startswith("raw positions"))
    assert "placed slots" in line and "distinct passages placed" in line


def test_a_later_default_build_never_treats_a_category_variant_as_a_prior_pin(
    tmp_path: Path,
) -> None:
    """`_prior_pin_dir` picks the newest sibling by `map.json` mtime, and
    would otherwise offer a category variant's own reads to a default
    rebuild at a new pin.

    The variant's `map.json` is aged strictly NEWER than the default's, so
    the exclusion is the only thing that can produce this answer. Left to a
    timestamp tie -- coarse mtime granularity, or `max()` keeping the first
    of two equals -- the assertion would hold with the filter deleted."""
    map_dir = tmp_path / "map"
    for name in ("oldpin", "oldpin-category"):
        (map_dir / name).mkdir(parents=True)
        (map_dir / name / "map.json").write_text("{}", encoding="utf-8")
    default_mtime = (map_dir / "oldpin" / "map.json").stat().st_mtime
    os.utime(map_dir / "oldpin-category" / "map.json", (default_mtime + 60, default_mtime + 60))

    assert _prior_pin_dir(map_dir, "newpin") == map_dir / "oldpin"


# ---------------------------------------------------------------------------
# The claim-only fallback itself (`axial.argmap.grouping`), whose real-corpus
# case is 780 of 6,010 selected passages holding a `claim` category and no
# `mechanism` one (founder ruling, 2026-08-29).
# ---------------------------------------------------------------------------


def test_the_claim_only_fallback_places_a_mechanism_less_passage_and_leaves_the_rest_ungrouped():
    result = group_by_intersection_with_claim_fallback(
        ["c1", "c2", "c3", "c4"],
        {"c1": CAT_A, "c2": CAT_A, "c3": CAT_B},
        {"c1": MECH_1, "c4": MECH_2},
    )

    assert {group.label: group.chunk_ids for group in result.groups} == {
        f"{CAT_A}::{MECH_1}": ("c1",),
        f"{CAT_A}::(no mechanism)": ("c2",),
        f"{CAT_B}::(no mechanism)": ("c3",),
    }
    # c4 has no claim category, so no claim-only cell exists for it.
    assert result.ungrouped_chunk_ids == ("c4",)
    assert result.missing_axis_counts.mechanism_only == 0
    assert result.missing_axis_counts.claim_only == 1


def test_the_fallback_does_not_change_group_by_intersections_own_behaviour():
    """Slice 03's report (167 groups / 797 ungrouped) calls
    `group_by_intersection` directly and its measured numbers must stay
    reproducible."""
    args = (["c1", "c2"], {"c1": CAT_A, "c2": CAT_A}, {"c1": MECH_1})

    plain = group_by_intersection(*args)

    assert [group.label for group in plain.groups] == [f"{CAT_A}::{MECH_1}"]
    assert plain.ungrouped_chunk_ids == ("c2",)
