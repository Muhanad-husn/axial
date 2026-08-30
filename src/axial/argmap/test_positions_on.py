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

import json
import os
from pathlib import Path

import numpy as np
import pytest

from axial.argmap.ask import positions_on, resolve_pinned_map_dir
from axial.argmap.build import (
    _prior_pin_dir,
    run_map_build,
)
from axial.llm import StubLLMClient
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
# Build-level accounting over a small fixture corpus (the category-grouped
# variant these fixtures once exercised was deleted -- issue #850; what
# survives below tests the default build's own behaviour).
# ---------------------------------------------------------------------------


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
def build_corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    """Four selected passages across two books. `_agglomerative_cluster` is
    faked to one cluster so neither the bagging nor the merge needs
    scikit-learn (an optional `distill`-group dependency this suite does not
    require)."""
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
    return {"root": tmp_path, "chunk_ids": chunk_ids}


def _run_map_build(corpus: dict, *, client, log=None, **kwargs):
    root = corpus["root"]
    return run_map_build(
        answers_dir=root / "answers",
        trees_dir=root / "trees",
        map_dir=root / "map",
        client=client,
        encode=_fake_encode,
        pin="testpin",
        guard=False,
        log=log if log is not None else (lambda _message: None),
        **kwargs,
    )


def test_distinct_placed_passages_are_counted_below_the_slot_sum(build_corpus: dict) -> None:
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
    manifest = _run_map_build(build_corpus, client=_TwiceNamingClient(), log=logged.append)

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
