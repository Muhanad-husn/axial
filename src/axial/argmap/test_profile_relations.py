"""Issue #858: relation candidates proposed from the vocabulary profile.

A second generator for the argument map's relate call: same `mechanism`
category, different books, different `position` category. The relate call
is the one `axial map build` already makes; only which positions it is
shown together changes, and the pass runs over an existing build without
touching the default build's files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence

import numpy as np
import pytest

from axial.argmap.ask import MapNotBuiltError
from axial.argmap.build import MAX_NEIGHBOURHOOD
from axial.argmap.profile_relations import (
    GENERATOR,
    PROFILE_MANIFEST_FILENAME,
    PROFILE_RELATIONS_FILENAME,
    pack_pairs,
    position_profiles,
    propose_pairs,
    run_profile_relations,
)
from axial.argmap.vocabulary_join import NoVocabularyError
from axial.llm import StubLLMClient

MECH = "mechanism"
STANCE = "position"


def _position(pid: str, chunk: str, source: str, argument: str | None = None) -> dict:
    return {
        "position_id": pid,
        "argument": argument or f"arg {pid}",
        "size": 1,
        "sources": [source],
        "authors": [f"{source}-author"],
        "chunk_ids": [chunk],
    }


def _assign(chunk: str, source: str, column: str, category: str | None) -> dict:
    return {
        "chunk_id": chunk,
        "source_id": source,
        "column": column,
        "level": 1,
        "category_id": category,
        "refused": category is None,
    }


def _write_vocab(root: Path, column: str, records: list[dict]) -> None:
    column_dir = root / column
    column_dir.mkdir(parents=True, exist_ok=True)
    (column_dir / "manifest.json").write_text(
        json.dumps({"column": column, "max_level": 1, "categories": []}), encoding="utf-8"
    )
    (column_dir / "assignments.jsonl").write_text(
        "\n".join(json.dumps(r) for r in records), encoding="utf-8"
    )


def _encode_from(table: dict[str, tuple[float, float]]):
    def encode(texts: Sequence[str]) -> np.ndarray:
        vectors = np.array([table[t] for t in texts], dtype=float)
        return vectors / np.linalg.norm(vectors, axis=1, keepdims=True)

    return encode


# Four positions in one mechanism, two per stance, four different books.
# a1/a2 hold stance X, b1/b2 stance Y. The vectors make a1~b1 and a2~b2 close.
FOUR = [
    _position("a1", "ca1", "S1"),
    _position("a2", "ca2", "S2"),
    _position("b1", "cb1", "S3"),
    _position("b2", "cb2", "S4"),
]
FOUR_ENCODE = _encode_from(
    {"arg a1": (1, 0), "arg a2": (0, 1), "arg b1": (1, 0.1), "arg b2": (0.1, 1)}
)


def _four_vocab(root: Path) -> None:
    _write_vocab(
        root,
        MECH,
        [_assign(p["chunk_ids"][0], p["sources"][0], MECH, "m1") for p in FOUR],
    )
    stances = {"a1": "x", "a2": "x", "b1": "y", "b2": "y"}
    _write_vocab(
        root,
        STANCE,
        [_assign(p["chunk_ids"][0], p["sources"][0], STANCE, stances[p["position_id"]]) for p in FOUR],
    )


def _write_map(map_root: Path, positions: list[dict], relations: list[dict] | None = None) -> Path:
    outdir = map_root / "pin"
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "map.json").write_text(json.dumps({"corpus_pin": "pin"}), encoding="utf-8")
    (outdir / "positions.jsonl").write_text(
        "\n".join(json.dumps(p) for p in positions), encoding="utf-8"
    )
    (outdir / "relations.jsonl").write_text(
        "\n".join(json.dumps(r) for r in relations or []), encoding="utf-8"
    )
    return outdir


class _ScriptedClient(StubLLMClient):
    """Answers every relate call with `relations` for whatever handles the
    listing carries, resolved from the argument text it shows."""

    def __init__(self, pairs: list[tuple[str, str, str]]) -> None:
        super().__init__()
        self.pairs = pairs
        self.calls = 0

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        self.calls += 1
        handles = {}
        for line in prompt.splitlines():
            if line.startswith("[a") and "] arg " in line:
                handle, rest = line[1:].split("] ", 1)
                handles[rest.removeprefix("arg ")] = handle
        relations = [
            {"from": handles[a], "to": handles[b], "relation": label, "says": f"{a} {label} {b}"}
            for a, b, label in self.pairs
            if a in handles and b in handles
        ]
        return json.dumps({"relations": relations})

    def model_for_pass(self, pass_name: str | None = None) -> str:
        return "stub-model"


def _run(tmp_path: Path, client, positions=FOUR, encode=FOUR_ENCODE, relations=None, **kwargs):
    map_root = tmp_path / "maps"
    outdir = _write_map(map_root, positions, relations)
    vocab = tmp_path / "vocab"
    if not (vocab / MECH).exists():
        _four_vocab(vocab)
    manifest = run_profile_relations(
        map_dir=map_root,
        pin="pin",
        vocabulary_dir=vocab,
        client=client,
        encode=encode,
        guard=False,
        log=lambda _m: None,
        **kwargs,
    )
    return outdir, manifest


# ---------------------------------------------------------------------------
# The profile
# ---------------------------------------------------------------------------


def test_a_position_takes_the_category_most_of_its_notes_were_filed_under():
    position = {
        "position_id": "p", "argument": "x", "sources": ["S"], "chunk_ids": ["c1", "c2", "c3"],
    }
    mech = {"c1": "m1", "c2": "m2", "c3": "m2"}
    stance = {"c1": "x", "c2": "x", "c3": "x"}

    profiles = position_profiles([position], mech, stance)

    assert profiles["p"].mechanism == "m2"
    assert profiles["p"].stance == "x"


def test_a_tied_position_takes_the_lowest_category_id_not_file_order():
    position = {"position_id": "p", "argument": "x", "sources": ["S"], "chunk_ids": ["c1", "c2"]}

    first = position_profiles([position], {"c1": "m9", "c2": "m1"}, {"c1": "x", "c2": "x"})
    second = position_profiles(
        [{**position, "chunk_ids": ["c2", "c1"]}], {"c1": "m9", "c2": "m1"}, {"c1": "x", "c2": "x"}
    )

    assert first["p"].mechanism == second["p"].mechanism == "m1"


def test_a_position_none_of_whose_notes_were_filed_has_no_profile():
    position = {"position_id": "p", "argument": "x", "sources": ["S"], "chunk_ids": ["c1"]}

    assert position_profiles([position], {}, {"c1": "x"}) == {}
    assert position_profiles([position], {"c1": "m1"}, {}) == {}


# ---------------------------------------------------------------------------
# The candidate rule
# ---------------------------------------------------------------------------


def _profiled(rows: list[tuple[str, str, str, str]]):
    """(position_id, source, mechanism, stance) -> positions + profiles."""
    positions, mech, stance = [], {}, {}
    for pid, source, m, s in rows:
        positions.append(_position(pid, f"c-{pid}", source))
        mech[f"c-{pid}"] = m
        stance[f"c-{pid}"] = s
    return positions, position_profiles(positions, mech, stance)


def test_same_mechanism_different_books_different_position_is_a_candidate():
    positions, profiles = _profiled([("p1", "S1", "m", "x"), ("p2", "S2", "m", "y")])
    encode = _encode_from({"arg p1": (1, 0), "arg p2": (0, 1)})

    pairs, candidates = propose_pairs(positions, profiles, encode)

    assert candidates == 1
    assert pairs == [("p1", "p2")]


@pytest.mark.parametrize(
    "rows",
    [
        # different mechanism
        [("p1", "S1", "m1", "x"), ("p2", "S2", "m2", "y")],
        # same book
        [("p1", "S1", "m", "x"), ("p2", "S1", "m", "y")],
        # same position category: agreeing, not opposed
        [("p1", "S1", "m", "x"), ("p2", "S2", "m", "x")],
    ],
)
def test_a_pair_failing_any_one_condition_is_not_a_candidate(rows):
    positions, profiles = _profiled(rows)
    encode = _encode_from({"arg p1": (1, 0), "arg p2": (0, 1)})

    assert propose_pairs(positions, profiles, encode) == ([], 0)


def test_a_position_sharing_any_book_with_the_other_is_excluded():
    positions = [
        {**_position("p1", "c-p1", "S1"), "sources": ["S1", "S2"]},
        _position("p2", "c-p2", "S2"),
    ]
    profiles = position_profiles(
        positions, {"c-p1": "m", "c-p2": "m"}, {"c-p1": "x", "c-p2": "y"}
    )
    encode = _encode_from({"arg p1": (1, 0), "arg p2": (0, 1)})

    assert propose_pairs(positions, profiles, encode) == ([], 0)


def test_each_position_is_offered_only_its_nearest_candidate_partner():
    """Four candidates exist (a1b1 a1b2 a2b1 a2b2); the bound keeps each
    position's single nearest, so two pairs are proposed."""
    profiles = position_profiles(
        FOUR,
        {p["chunk_ids"][0]: "m1" for p in FOUR},
        {"ca1": "x", "ca2": "x", "cb1": "y", "cb2": "y"},
    )

    pairs, candidates = propose_pairs(FOUR, profiles, FOUR_ENCODE)

    assert candidates == 4
    assert pairs == [("a1", "b1"), ("a2", "b2")]


# ---------------------------------------------------------------------------
# Packing pairs into relate calls
# ---------------------------------------------------------------------------


def test_pairs_that_touch_are_read_in_one_call_and_others_apart():
    groups = pack_pairs([("a", "b"), ("b", "c"), ("x", "y")])

    assert sorted(g.position_ids for g in groups) == [("a", "b", "c"), ("x", "y")]


def test_no_call_shows_more_positions_than_a_neighbourhood_call_does():
    chain = [(f"p{i:02d}", f"p{i + 1:02d}") for i in range(40)]

    groups = pack_pairs(chain)

    assert all(len(g.position_ids) <= MAX_NEIGHBOURHOOD for g in groups)
    covered = {pid for g in groups for pid in g.position_ids}
    assert covered == {pid for pair in chain for pid in pair}


# ---------------------------------------------------------------------------
# The pass
# ---------------------------------------------------------------------------


def test_a_relation_the_model_asserts_between_a_proposed_pair_is_recorded(tmp_path):
    client = _ScriptedClient([("a1", "b1", "contradicts")])

    outdir, manifest = _run(tmp_path, client)

    rows = [
        json.loads(line)
        for line in (outdir / PROFILE_RELATIONS_FILENAME).read_text(encoding="utf-8").splitlines()
    ]
    assert len(rows) == 1
    assert rows[0]["from_position_id"] == "a1"
    assert rows[0]["to_position_id"] == "b1"
    assert rows[0]["relation"] == "contradicts"
    assert rows[0]["generator"] == GENERATOR
    assert manifest["counts"]["relations_asserted"] == 1


def test_the_model_may_say_there_is_no_relation_and_nothing_is_recorded(tmp_path):
    client = _ScriptedClient([])

    outdir, manifest = _run(tmp_path, client)

    assert (outdir / PROFILE_RELATIONS_FILENAME).read_text(encoding="utf-8") == ""
    assert manifest["counts"]["relations_asserted"] == 0
    assert manifest["counts"]["proposed_pairs"] == 2


def test_a_shared_category_is_never_recorded_as_a_relation(tmp_path):
    """Pairs share a mechanism by construction. Nothing but the model's own
    answer becomes a relation, so with no answer there is no record and no
    label is ever a category name."""
    client = _ScriptedClient([("a1", "b1", "supports")])

    outdir, _ = _run(tmp_path, client)

    text = (outdir / PROFILE_RELATIONS_FILENAME).read_text(encoding="utf-8")
    assert "m1" not in text
    assert '"relation": "supports"' in text


def test_a_relation_between_positions_that_were_not_proposed_is_dropped_and_counted(tmp_path):
    """a1 and a2 hold the same position category, so they are never a
    proposed pair, but both are read with b1 in one call. If the model
    relates them anyway, that relation is not this generator's to record."""
    client = _ScriptedClient([("a1", "b1", "contradicts"), ("a1", "a2", "restates")])
    encode = _encode_from({"arg a1": (1, 0), "arg a2": (0.9, 0.2), "arg b1": (1, 0.1)})

    outdir, manifest = _run(tmp_path, client, positions=FOUR[:3], encode=encode)

    labels = [
        json.loads(line)["relation"]
        for line in (outdir / PROFILE_RELATIONS_FILENAME).read_text(encoding="utf-8").splitlines()
    ]
    assert labels == ["contradicts"]
    assert manifest["counts"]["off_proposal_relations"] == 1


def test_the_default_builds_files_are_not_touched(tmp_path):
    relations = [
        {"from_position_id": "a1", "to_position_id": "b2", "relation": "old", "says": "s"}
    ]
    map_root = tmp_path / "maps"
    outdir = _write_map(map_root, FOUR, relations)
    before = {p.name: p.read_bytes() for p in outdir.iterdir()}
    _four_vocab(tmp_path / "vocab")

    run_profile_relations(
        map_dir=map_root,
        pin="pin",
        vocabulary_dir=tmp_path / "vocab",
        client=_ScriptedClient([("a1", "b1", "contradicts")]),
        encode=FOUR_ENCODE,
        guard=False,
        log=lambda _m: None,
    )

    for name, content in before.items():
        assert (outdir / name).read_bytes() == content, name


def test_the_manifest_reports_overlap_with_the_neighbourhood_relations(tmp_path):
    existing = [
        # same pair as the profile relation, opposite direction: overlap
        {"from_position_id": "b1", "to_position_id": "a1", "relation": "x", "says": "s"},
        {"from_position_id": "a1", "to_position_id": "a2", "relation": "y", "says": "s"},
    ]
    client = _ScriptedClient([("a1", "b1", "contradicts"), ("a2", "b2", "supports")])

    _, manifest = _run(tmp_path, client, relations=existing)

    counts = manifest["counts"]
    assert counts["relations_asserted"] == 2
    assert counts["overlap_with_neighbourhood_relations"] == 1
    assert counts["neighbourhood_relations"] == 2
    assert counts["cross_author_relations"] == 2
    assert counts["candidate_pairs"] == 4
    assert counts["proposed_pairs"] == 2


def test_a_second_run_asks_nothing_again(tmp_path):
    client = _ScriptedClient([("a1", "b1", "contradicts")])
    _run(tmp_path, client)
    first_calls = client.calls

    outdir, manifest = _run(tmp_path, client)

    assert first_calls > 0
    assert client.calls == first_calls
    assert manifest["counts"]["relations_asserted"] == 1
    assert (outdir / PROFILE_MANIFEST_FILENAME).is_file()


def test_no_map_at_the_pin_is_refused_by_name(tmp_path):
    with pytest.raises(MapNotBuiltError):
        run_profile_relations(
            map_dir=tmp_path / "nowhere",
            pin="pin",
            vocabulary_dir=tmp_path / "vocab",
            client=_ScriptedClient([]),
            encode=FOUR_ENCODE,
            guard=False,
            log=lambda _m: None,
        )


def test_no_vocabulary_is_refused_by_name_and_makes_no_call(tmp_path):
    client = _ScriptedClient([])
    _write_map(tmp_path / "maps", FOUR)

    with pytest.raises(NoVocabularyError):
        run_profile_relations(
            map_dir=tmp_path / "maps",
            pin="pin",
            vocabulary_dir=tmp_path / "empty-vocab",
            client=client,
            encode=FOUR_ENCODE,
            guard=False,
            log=lambda _m: None,
        )
    assert client.calls == 0


def test_the_relation_vocabulary_build_reads_profile_relations_too(tmp_path):
    """Kinds are filed through `axial vocabulary build --column relation`,
    which reads the pinned map's relations; profile relations join that
    population so they carry kinds the way neighbourhood relations do."""
    from axial.vocabulary import load_relation_records

    outdir, _ = _run(tmp_path, _ScriptedClient([("a1", "b1", "contradicts")]))

    records = load_relation_records(outdir)

    assert [r["relation"] for r in records] == ["contradicts"]
    assert records[0]["source_id"] == "S1+S3"


def test_without_a_profile_file_the_relation_population_is_what_it_was(tmp_path):
    from axial.vocabulary import load_relation_records

    relations = [{"from_position_id": "a1", "to_position_id": "b2", "relation": "old", "says": "s"}]
    outdir = _write_map(tmp_path / "maps", FOUR, relations)

    assert [r["relation"] for r in load_relation_records(outdir)] == ["old"]


def test_the_map_build_command_gains_no_profile_option():
    """The default build must not change: the profile pass is its own
    subcommand, not a flag on `map build`."""
    from axial.cli import build_parser

    parser = build_parser()
    build_args = parser.parse_args(["map", "build"])
    profile_args = parser.parse_args(["map", "relate-profile"])

    assert not any("profile" in key for key in vars(build_args))
    assert profile_args.map_command == "relate-profile"
