"""Inner unit tests for `axial.wikidata` (issue #856, DEC-75 step 3): names in
five or more sources reconciled to Wikidata QIDs, cached so a re-run is
offline, and measured against the recorded merge decisions."""

from __future__ import annotations

import json
from pathlib import Path

from axial.wikidata import (
    accepted_qid,
    band_nodes,
    measure,
    reconcile,
    resolve_node,
    run_reconcile,
    type_for_kind,
    write_qids,
)


def _chunks(source: str, n: int) -> list[str]:
    return [f"{source}-2000-aaaaaaaaaaaa_{i:03d}_intro_001" for i in range(n)]


# -- the band ----------------------------------------------------------------


def test_the_band_counts_sources_across_every_surface_of_a_node():
    """A node reaches five sources through its aliases as well as its
    canonical: the merge put those surfaces on one node, so their books
    count together."""
    nodes = [
        {"canonical": "Ba'th Party", "kind": "institution/group", "aliases": ["Baath Party"]},
        {"canonical": "Hama", "kind": "country/state/place", "aliases": []},
    ]
    inventory = {
        "Ba'th Party": {"chunk_ids": _chunks("a", 1) + _chunks("b", 2) + _chunks("c", 1)},
        "Baath Party": {"chunk_ids": _chunks("d", 1) + _chunks("e", 1)},
        "Hama": {
            "chunk_ids": _chunks("a", 1) + _chunks("b", 1) + _chunks("c", 1) + _chunks("d", 1)
        },
    }
    assert [node["canonical"] for node in band_nodes(nodes, inventory)] == ["Ba'th Party"]


# -- the type hint -----------------------------------------------------------


def test_a_kind_maps_to_its_wikidata_type_and_an_unmapped_kind_sends_none():
    assert type_for_kind("person") == "Q5"
    assert type_for_kind("institution/group") == "Q43229"
    assert type_for_kind("concept") is None
    assert type_for_kind(None) is None


def test_a_place_is_typed_geographic_location_not_administrative_entity():
    """Measured 2026-09-29 against the live service: typed Q56061
    (administrative territorial entity), `Europe` comes back `match: true`
    to the European Union (Q458). Typed Q2221906 (geographic location), the
    top candidate for Syria, Europe, Middle East, Damascus, Hama, Lebanon and
    the Ottoman Empire was the right item every time."""
    assert type_for_kind("country/state/place") == "Q2221906"


# -- acceptance --------------------------------------------------------------


def test_only_the_services_own_match_flag_is_accepted():
    tie = [
        {"id": "Q179933", "score": 100.0, "match": False},
        {"id": "Q797513", "score": 100.0, "match": False},
    ]
    assert accepted_qid(tie) is None
    matched = [{"id": "Q179933", "score": 100.0, "match": True}, *tie[1:]]
    assert accepted_qid(matched) == "Q179933"
    assert accepted_qid([]) is None


# -- the cache ---------------------------------------------------------------


def test_every_response_is_cached_and_a_rerun_is_offline(tmp_path: Path):
    cache = tmp_path / "wikidata" / "responses.jsonl"
    calls: list[dict] = []

    def post(batch: dict) -> dict:
        calls.append(batch)
        return {
            key: {"result": [{"id": f"Q{q['query']}", "score": 100.0, "match": True}]}
            for key, q in batch.items()
        }

    queries = [("1", "Q5"), ("2", None), ("3", "Q5")]
    first = reconcile(queries, cache_path=cache, post=post, batch_size=2)
    assert len(calls) == 2
    assert first[("2", None)][0]["id"] == "Q2"
    assert calls[0]["q0"] == {"query": "1", "type": "Q5"}
    assert "type" not in calls[0]["q1"], "an unmapped kind sends no type constraint"

    def offline(batch: dict) -> dict:
        raise AssertionError("a cached query must never reach the service")

    assert reconcile(queries, cache_path=cache, post=offline) == first


def test_a_new_query_asks_only_for_itself(tmp_path: Path):
    cache = tmp_path / "responses.jsonl"
    asked: list[str] = []

    def post(batch: dict) -> dict:
        asked.extend(q["query"] for q in batch.values())
        return {key: {"result": []} for key in batch}

    reconcile([("a", None)], cache_path=cache, post=post)
    reconcile([("a", None), ("b", None)], cache_path=cache, post=post)
    assert asked == ["a", "b"]


# -- a node's QID and its verdict on the merge -------------------------------


def test_the_canary_baath_and_bath_land_on_one_qid_and_agree_with_the_merge():
    node = {"canonical": "Ba'th Party", "kind": "institution/group", "aliases": ["Baath Party"]}
    resolution = resolve_node(node, {"Ba'th Party": "Q179933", "Baath Party": "Q179933"})
    assert resolution["qid"] == "Q179933"
    assert resolution["verdict"] == "agrees"


def test_two_qids_on_one_node_is_a_disagreement_and_the_canonical_wins():
    node = {"canonical": "Asad", "kind": "person", "aliases": ["Hafiz al-Asad", "Bashar al-Asad"]}
    resolution = resolve_node(
        node, {"Asad": "Q118725", "Hafiz al-Asad": "Q118725", "Bashar al-Asad": "Q44329"}
    )
    assert resolution["qid"] == "Q118725"
    assert resolution["verdict"] == "disagrees"
    assert resolution["surface_qids"] == {
        "Asad": "Q118725",
        "Hafiz al-Asad": "Q118725",
        "Bashar al-Asad": "Q44329",
    }


def test_an_unmatched_canonical_takes_its_aliases_qid_only_when_they_agree():
    node = {"canonical": "Tilly", "kind": "person", "aliases": ["Charles Tilly", "C. Tilly"]}
    assert (
        resolve_node(node, {"Charles Tilly": "Q717635", "C. Tilly": "Q717635"})["qid"] == "Q717635"
    )
    split = resolve_node(node, {"Charles Tilly": "Q717635", "C. Tilly": "Q1"})
    assert split["qid"] is None, "never guess between two QIDs"


def test_one_matched_surface_resolves_but_does_not_test_the_merge():
    node = {"canonical": "Hama", "kind": "country/state/place", "aliases": ["Hamah"]}
    resolution = resolve_node(node, {"Hama": "Q173545", "Hamah": None})
    assert resolution["qid"] == "Q173545"
    assert resolution["verdict"] == "untested"
    assert resolve_node(node, {})["qid"] is None


# -- the measurement ---------------------------------------------------------


def test_measure_reports_resolution_agreement_and_both_kinds_of_disagreement():
    resolutions = [
        {"canonical": "Ba'th Party", "qid": "Q179933", "verdict": "agrees", "surface_qids": {}},
        {"canonical": "Baath", "qid": "Q179933", "verdict": "untested", "surface_qids": {}},
        {
            "canonical": "Asad",
            "qid": "Q118725",
            "verdict": "disagrees",
            "surface_qids": {"x": "Q1"},
        },
        {"canonical": "Syria", "qid": None, "verdict": "untested", "surface_qids": {}},
    ]
    report = measure(resolutions)
    assert report["band"] == 4
    assert report["resolved"] == 3
    assert report["resolution_rate"] == 0.75
    assert report["tested"] == 2
    assert report["agrees"] == 1
    assert report["agreement_rate"] == 0.5
    assert [entry["canonical"] for entry in report["merged_apart"]] == ["Asad"]
    assert report["kept_apart"] == [{"qid": "Q179933", "canonicals": ["Ba'th Party", "Baath"]}]


# -- the whole pass ----------------------------------------------------------


def test_the_pass_writes_band_qids_to_the_index_and_measures_the_merge(tmp_path: Path):
    names = tmp_path / "names"
    names.mkdir()
    (names / "alias_map.json").write_text(
        json.dumps(
            {
                "nodes": [
                    {
                        "canonical": "Ba'th Party",
                        "kind": "institution/group",
                        "aliases": ["Baath Party"],
                    },
                    {"canonical": "Hama", "kind": "country/state/place", "aliases": []},
                ]
            }
        ),
        encoding="utf-8",
    )
    wide = [c for s in "abcde" for c in _chunks(s, 1)]
    (names / "inventory.jsonl").write_text(
        "\n".join(
            json.dumps(r)
            for r in [
                {"surface": "Ba'th Party", "chunk_ids": wide[:3]},
                {"surface": "Baath Party", "chunk_ids": wide[3:]},
                {"surface": "Hama", "chunk_ids": wide[:1]},
            ]
        ),
        encoding="utf-8",
    )
    (names / "index.json").write_text(
        json.dumps({"names": ["Ba'th Party", "Hama"]}), encoding="utf-8"
    )
    sent: list[dict] = []

    def post(batch: dict) -> dict:
        sent.extend(batch.values())
        return {k: {"result": [{"id": "Q179933", "score": 100.0, "match": True}]} for k in batch}

    report = run_reconcile(names_dir=names, post=post, log=lambda _: None)

    assert sent == [
        {"query": "Ba'th Party", "type": "Q43229"},
        {"query": "Baath Party", "type": "Q43229"},
    ], "Hama sits in one source, outside the band"
    assert json.loads((names / "index.json").read_text(encoding="utf-8"))["qids"] == {
        "Ba'th Party": "Q179933"
    }
    assert report["resolved"] == 1 and report["agrees"] == 1
    assert json.loads((names / "wikidata" / "report.json").read_text(encoding="utf-8")) == report
    assert (names / "wikidata" / "resolutions.jsonl").read_text(encoding="utf-8").count("\n") == 1


# -- the index ---------------------------------------------------------------


def test_qids_are_written_beside_the_names_and_the_names_list_is_untouched(tmp_path: Path):
    index = tmp_path / "index.json"
    index.write_text(json.dumps({"version": 1, "names": ["Hama", "Syria"]}), encoding="utf-8")
    write_qids(index, {"Hama": "Q173545", "Syria": None})
    written = json.loads(index.read_text(encoding="utf-8"))
    assert written["names"] == ["Hama", "Syria"]
    assert written["qids"] == {"Hama": "Q173545", "Syria": None}
