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
from pathlib import Path

import pytest

from axial.argmap.ask import positions_on, resolve_pinned_map_dir
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
