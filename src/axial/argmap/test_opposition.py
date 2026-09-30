"""Issue #860: `--grouping opposition` bags passages by what they argue
against, in its own directory, and leaves the baseline alone."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from axial.argmap.build import Passage, _prior_pin_dir, build_jobs, run_map_build
from axial.argmap.compare import load_build
from axial.argmap.opposition import load_opposition_keys, opposition_bags
from axial.llm import StubLLMClient
from axial.query import store as note_store


def _p(source: str, n: int) -> Passage:
    return Passage(f"{source}_{n}", source, source.split("-")[0], f"claim {source} {n}")


def _ids(bags: dict) -> dict:
    return {k: [m.chunk_id for m in v] for k, v in bags.items()}


def test_a_passage_with_several_keys_joins_the_key_argued_against_from_most_books() -> None:
    a1, b1, c1 = _p("a-1", 1), _p("b-1", 1), _p("c-1", 1)
    keys = {
        a1.chunk_id: ["arg:X", "arg:Y"],
        b1.chunk_id: ["arg:X"],
        c1.chunk_id: ["arg:Y", "arg:X"],
    }
    bags, rest = opposition_bags([a1, b1, c1], keys)
    assert _ids(bags) == {"arg:X": [a1.chunk_id, b1.chunk_id, c1.chunk_id]}
    assert rest == []


def test_ties_go_to_most_passages_then_lexical_key() -> None:
    a1, a2, b1 = _p("a-1", 1), _p("a-1", 2), _p("b-1", 1)
    # X and Y are each argued from 2 books; Y has 3 passages, X has 2.
    keys = {
        a1.chunk_id: ["arg:X", "arg:Y"],
        a2.chunk_id: ["arg:Y"],
        b1.chunk_id: ["arg:X", "arg:Y"],
    }
    bags, _ = opposition_bags([a1, a2, b1], keys)
    assert set(bags) == {"arg:Y"}
    m, n = _p("m-1", 1), _p("n-1", 1)
    keys = {m.chunk_id: ["arg:B", "arg:A"], n.chunk_id: ["arg:A", "arg:B"]}
    bags, _ = opposition_bags([m, n], keys)
    assert set(bags) == {"arg:A"}


def test_a_key_held_by_one_passage_forms_no_bag_and_the_passage_falls_back() -> None:
    a1, b1, c1 = _p("a-1", 1), _p("b-1", 1), _p("c-1", 1)
    keys = {a1.chunk_id: ["arg:X"], b1.chunk_id: ["arg:X"], c1.chunk_id: ["arg:lonely"]}
    bags, rest = opposition_bags([a1, b1, c1], keys)
    assert set(bags) == {"arg:X"}
    assert rest == [c1]


def test_a_passage_with_no_key_falls_back() -> None:
    a1 = _p("a-1", 1)
    assert opposition_bags([a1], {}) == ({}, [a1])


def test_opposition_bags_slice_through_the_existing_author_spread_jobs() -> None:
    members = [_p(f"a{i}-1", 0) for i in range(3)]
    bags, _ = opposition_bags(members, {m.chunk_id: ["arg:X"] for m in members})
    assert [job.bag for job in build_jobs(bags)] == ["arg:X"]


def _vault(tmp_path: Path, against: list, citations: list) -> Path:
    vault = tmp_path / "vault"
    vault.mkdir()
    connection = sqlite3.connect(note_store.store_path(vault))
    connection.executescript(note_store.SCHEMA)
    connection.executemany("INSERT INTO note_arguing_against VALUES (?,?,?,?)", against)
    connection.executemany("INSERT INTO note_citations VALUES (?,?,?,?,?)", citations)
    connection.commit()
    connection.close()
    return vault


def test_keys_are_resolved_targets_plus_foil_citations_only(tmp_path: Path) -> None:
    vault = _vault(
        tmp_path,
        [("c1", "s1", "the state", "State"), ("c2", "s2", "nothing found", None)],
        [
            ("c1", "s1", "Tilly  1990", "foil", None),
            ("c2", "s2", "tilly 1990", "foil", None),
            ("c2", "s2", "Mann 1986", "support", None),
        ],
    )
    keys = load_opposition_keys(vault)
    assert keys["c1"] == ["arg:State", "foil:tilly 1990"]
    assert keys["c2"] == ["foil:tilly 1990"]


# -- build ---------------------------------------------------------------


class _Client(StubLLMClient):
    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        self.call_count += 1
        return json.dumps({"arguments": [], "unassigned": []})


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr("axial.argmap.build.load_back_matter_sections", lambda trees_dir: {})
    answers = tmp_path / "answers"
    answers.mkdir()
    for source in ("alpha-2020-x", "beta-2021-y"):
        lines = [
            {
                "source_id": source,
                "chunk_id": f"{source}_{i}",
                "answers": {
                    "claim": f"Claim {source} {i}.",
                    "mechanism": "m",
                    "comparison": "not-in-passage",
                    "concedes": "not-in-passage",
                    "assumes": "not-in-passage",
                    "position_of": "not-in-passage",
                    "ranges_over": "not-in-passage",
                },
            }
            for i in range(2)
        ]
        (answers / f"{source}.jsonl").write_text(
            "".join(json.dumps(x) + "\n" for x in lines), encoding="utf-8"
        )
    # Chunk 0 of both books argues against State; chunk 1 of each against nothing.
    return _vault(
        tmp_path,
        [
            ("alpha-2020-x_0", "alpha-2020-x", "s", "State"),
            ("beta-2021-y_0", "beta-2021-y", "s", "State"),
        ],
        [],
    )


def _build(tmp_path: Path, vault: Path, **kwargs):
    return run_map_build(
        answers_dir=tmp_path / "answers",
        trees_dir=tmp_path / "trees",
        map_dir=tmp_path / "map",
        vault_dir=vault,
        client=_Client(),
        encode=lambda claims: [[1.0, 0.0] for _ in claims],
        pin="pin1",
        guard=False,
        log=lambda _msg: None,
        **kwargs,
    )


def test_opposition_build_writes_its_own_directory_with_opposition_and_wording_bags(
    tmp_path: Path, corpus: Path
) -> None:
    manifest = _build(tmp_path, corpus, grouping="opposition")
    out = tmp_path / "map" / "pin1-opposition"
    assert not (tmp_path / "map" / "pin1" / "map.json").exists()
    written = json.loads((out / "map.json").read_text(encoding="utf-8"))
    assert written["grouping"]["mode"] == "opposition"
    assert manifest["counts"]["passages_selected"] == 4
    # One opposition bag (the two State passages) + one wording bag (the other two).
    assert manifest["counts"]["bags"] == 2
    assert manifest["grouping"]["opposition_bags"] == 1
    assert manifest["grouping"]["passages_wording_fallback"] == 2
    state = json.loads((out / "bag_state.json").read_text(encoding="utf-8"))
    assert len(state["assignments"]) == 4
    assert all(isinstance(v, int) for v in state["assignments"].values())
    assert load_build(out, "B").grouping_mode == "opposition"


def test_opposition_build_never_touches_the_baseline_directory(
    tmp_path: Path, corpus: Path
) -> None:
    _build(tmp_path, corpus)
    base = tmp_path / "map" / "pin1"
    before = {p.name: p.read_bytes() for p in base.iterdir()}
    _build(tmp_path, corpus, grouping="opposition")
    assert {p.name: p.read_bytes() for p in base.iterdir()} == before


def test_an_opposition_directory_is_never_the_prior_pin_of_a_later_build(tmp_path: Path) -> None:
    for name in ("aaaa", "aaaa-opposition"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "map.json").write_text("{}", encoding="utf-8")
    assert _prior_pin_dir(tmp_path, "bbbb") == tmp_path / "aaaa"


def test_map_json_records_the_configured_reasoning_not_a_mirror(
    tmp_path: Path, corpus: Path
) -> None:
    # #875 moved both passes to medium in config; map.json kept saying high.
    config = tmp_path / "pipeline.yaml"
    config.write_text(
        "llm:\n  reasoning_by_pass:\n    position_extract: low\n    position_relate: low\n",
        encoding="utf-8",
    )
    _build(tmp_path, corpus, config_path=config)
    written = json.loads((tmp_path / "map" / "pin1" / "map.json").read_text(encoding="utf-8"))
    assert written["reasoning"] == "low"
    assert written["relations"]["reasoning"] == "low"
