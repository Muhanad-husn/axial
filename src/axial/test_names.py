"""Inner unit tests for Phase A v1 slice 04 (issue #415: the name inventory
and similarity view, spec §7.16).

`lancedb`/`hdbscan`/`scikit-learn` are optional `distill`-group dependencies
(`uv sync --group distill`) -- `importorskip` here means this whole module
skips cleanly (not errors) on an environment that never synced the group,
mirroring `axial.distill.embed`'s own inner unit tests (`src/axial/distill/
test_embed_unit.py`).

Most tests here use an injected fake `encoder`/`cluster_fn` (plain
callables, mirroring `axial.distill.embed`'s `encoder` seam and
`axial.distill.readiness`'s `cluster_fn` seam) so the collect/persist/report
path runs fast and network-free, independent of the real model or the real
PCA+HDBSCAN pipeline's own behaviour on any given input.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

lancedb = pytest.importorskip("lancedb")

from axial.names import (  # noqa: E402
    NameOccurrence,
    NoAnswersToEmbedError,
    NoNamesToClusterError,
    TABLE_NAME,
    _borderline_pairs,
    _nearest_neighbour_pairs,
    _relabel_from_tree,
    build_inventory,
    collect_occurrences,
    examine_names,
    format_names_report,
    iter_name_occurrences,
    load_answer_records,
    run_names,
    write_inventory,
)


def _fake_encoder(surface_forms: list[str]) -> list[list[float]]:
    """A deterministic stand-in for the real sentence-transformer: maps each
    distinct surface form to a 2D vector by its position in a fixed
    alphabet, so near-identical strings land near each other and unrelated
    ones land far apart -- exactly the property the real encoder is trusted
    to have, without downloading it."""
    return [[float(len(form)), float(sum(ord(ch) for ch in form) % 97)] for form in surface_forms]


def _fake_cluster_fn(vectors: list[list[float]]) -> list[int]:
    """Groups vectors by exact value into small integer labels, deterministic
    and independent of HDBSCAN's own real clustering decisions."""
    labels: dict[tuple[float, ...], int] = {}
    result = []
    for vector in vectors:
        key = tuple(vector)
        if key not in labels:
            labels[key] = len(labels)
        result.append(labels[key])
    return result


def _write_answers(answers_dir: Path, source_id: str, records: list[dict]) -> Path:
    answers_dir.mkdir(parents=True, exist_ok=True)
    path = answers_dir / f"{source_id}.jsonl"
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")
    return path


def _answer_record(chunk_id: str, source_id: str, answers: dict) -> dict:
    return {
        "chunk_id": chunk_id,
        "source_id": source_id,
        "pass": "note_interrogate",
        "answers": answers,
    }


def _base_answers(**overrides) -> dict:
    base = {
        "about": ["x"],
        "claim": "x",
        "move": "x",
        "ranges_over": "not-in-passage",
        "stops_holding": "not-in-passage",
        "position_of": "not-in-passage",
        "arguing_against": [],
        "names": [],
        "citations": [],
        "mechanism": "not-in-passage",
        "evidence": "not-in-passage",
        "comparison": "not-in-passage",
        "defines": [],
        "uses": [],
        "concedes": "not-in-passage",
        "assumes": "not-in-passage",
    }
    base.update(overrides)
    return base


# --- iter_name_occurrences ---------------------------------------------------


def test_iter_name_occurrences_collects_names_and_citations_only():
    record = _answer_record(
        "c1",
        "s1",
        _base_answers(
            names=[{"name": "Kevin Attell", "kind": "person"}],
            citations=[{"cited": "Gellner 1992", "stance": "authority", "about": "x"}],
            uses=["SENTINEL_never_collected"],
            defines=["SENTINEL_never_collected"],
            arguing_against=["SENTINEL_never_collected"],
            position_of="SENTINEL_never_collected",
        ),
    )

    occurrences = list(iter_name_occurrences(record))
    surface_forms = {occ.surface_form for occ in occurrences}

    assert surface_forms == {"Kevin Attell", "Gellner 1992"}
    assert not any("SENTINEL" in form for form in surface_forms)
    by_form = {occ.surface_form: occ for occ in occurrences}
    assert by_form["Kevin Attell"].kind == "person"
    assert by_form["Gellner 1992"].kind is None
    assert all(occ.chunk_id == "c1" for occ in occurrences)


def test_iter_name_occurrences_skips_abstentions_and_blank_records():
    record = _answer_record(
        "c1", "s1", _base_answers(names=["not-in-passage"], citations=["not-in-passage"])
    )
    failure_record = {"chunk_id": "c2", "source_id": "s1", "failure_reason": "boom"}

    assert list(iter_name_occurrences(record)) == []
    assert list(iter_name_occurrences(failure_record)) == []


def test_iter_name_occurrences_skips_malformed_entries_without_crashing():
    record = _answer_record(
        "c1",
        "s1",
        _base_answers(
            names=[{"name": "Real Name", "kind": "person"}, {"kind": "person"}, "not-a-dict"],
            citations=[{"cited": ""}, {"about": "no cited key"}, {"cited": "Real Cite"}],
        ),
    )

    occurrences = list(iter_name_occurrences(record))
    surface_forms = {occ.surface_form for occ in occurrences}

    assert surface_forms == {"Real Name", "Real Cite"}


# --- load_answer_records / collect_occurrences -------------------------------


def test_load_answer_records_reads_every_source_sorted(tmp_path: Path):
    answers_dir = tmp_path / "answers"
    _write_answers(answers_dir, "src2", [_answer_record("c1", "src2", _base_answers())])
    _write_answers(answers_dir, "src1", [_answer_record("c1", "src1", _base_answers())])

    records = load_answer_records(answers_dir)

    assert [record["source_id"] for record in records] == ["src1", "src2"]


def test_load_answer_records_missing_dir_returns_empty(tmp_path: Path):
    assert load_answer_records(tmp_path / "nope") == []


def test_collect_occurrences_flat_maps_over_records():
    records = [
        _answer_record("c1", "s1", _base_answers(names=[{"name": "a", "kind": "concept"}])),
        _answer_record("c2", "s1", _base_answers(names=[{"name": "b", "kind": "concept"}])),
    ]

    forms = sorted(occ.surface_form for occ in collect_occurrences(records))

    assert forms == ["a", "b"]


# --- build_inventory (§7.16's exact shape) -----------------------------------


def test_build_inventory_groups_exact_surface_form_across_notes():
    occurrences = [
        NameOccurrence("Kevin Attell", "c1", "person"),
        NameOccurrence("Kevin Attell", "c1", "person"),
        NameOccurrence("Kevin Attell", "c2", "person"),
    ]

    entries = build_inventory(occurrences)

    assert len(entries) == 1
    entry = entries[0]
    assert entry.surface_form == "Kevin Attell"
    assert entry.count == 3
    assert entry.kind == "person"
    assert entry.chunk_ids == ("c1", "c2")


def test_build_inventory_resolves_kind_by_frequency_then_first_occurrence():
    # "state" tagged concept twice, person once -- concept wins on frequency.
    occurrences = [
        NameOccurrence("state", "c1", "concept"),
        NameOccurrence("state", "c2", "person"),
        NameOccurrence("state", "c3", "concept"),
    ]

    entries = build_inventory(occurrences)

    assert entries[0].kind == "concept"


def test_build_inventory_kind_tie_broken_by_first_occurrence():
    occurrences = [
        NameOccurrence("state", "c1", "concept"),
        NameOccurrence("state", "c2", "person"),
    ]

    entries = build_inventory(occurrences)

    assert entries[0].kind == "concept"  # first-seen kind wins a 1-1 tie


def test_build_inventory_citation_only_surface_has_no_kind():
    entries = build_inventory([NameOccurrence("Gellner 1992", "c1", None)])

    assert entries[0].kind is None


def test_build_inventory_keeps_distinct_case_as_distinct_entries():
    occurrences = [
        NameOccurrence("gellner", "c1"),
        NameOccurrence("Gellner", "c2"),
    ]

    entries = build_inventory(occurrences)

    assert sorted(entry.surface_form for entry in entries) == ["Gellner", "gellner"]


def test_build_inventory_sorted_by_surface_form():
    occurrences = [NameOccurrence("Zeta", "c1"), NameOccurrence("Alpha", "c2")]

    entries = build_inventory(occurrences)

    assert [entry.surface_form for entry in entries] == ["Alpha", "Zeta"]


def test_write_inventory_matches_spec_shape(tmp_path: Path):
    entries = build_inventory(
        [
            NameOccurrence("Kevin Attell", "c1", "person"),
            NameOccurrence("Kevin Attell", "c2", "person"),
        ]
    )
    path = tmp_path / "inventory.jsonl"

    write_inventory(entries, path)

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record == {
        "surface": "Kevin Attell",
        "kind": "person",
        "count": 2,
        "chunk_ids": ["c1", "c2"],
    }


# --- run_names: loud failures ------------------------------------------------


def test_run_names_missing_answers_dir_raises(tmp_path: Path):
    with pytest.raises(NoAnswersToEmbedError):
        run_names(
            answers_dir=tmp_path / "answers",
            inventory_path=tmp_path / "inventory.jsonl",
            embeddings_dir=tmp_path / "embeddings.lance",
            manifest_path=tmp_path / "manifest.json",
            encoder=_fake_encoder,
            cluster_fn=_fake_cluster_fn,
        )


def test_run_names_no_names_in_any_note_raises(tmp_path: Path):
    answers_dir = tmp_path / "answers"
    _write_answers(answers_dir, "s1", [_answer_record("c1", "s1", _base_answers())])

    with pytest.raises(NoAnswersToEmbedError):
        run_names(
            answers_dir=answers_dir,
            inventory_path=tmp_path / "inventory.jsonl",
            embeddings_dir=tmp_path / "embeddings.lance",
            manifest_path=tmp_path / "manifest.json",
            encoder=_fake_encoder,
            cluster_fn=_fake_cluster_fn,
        )


# --- run_names: the persisted artifacts --------------------------------------


def test_run_names_persists_inventory_vectors_and_cluster_labels(tmp_path: Path):
    answers_dir = tmp_path / "answers"
    _write_answers(
        answers_dir,
        "s1",
        [
            _answer_record(
                "c1", "s1", _base_answers(names=[{"name": "Kevin Attell", "kind": "person"}])
            ),
            _answer_record(
                "c2",
                "s1",
                _base_answers(citations=[{"cited": "Gellner 1992", "stance": "authority"}]),
            ),
        ],
    )
    inventory_path = tmp_path / "inventory.jsonl"
    embeddings_dir = tmp_path / "embeddings.lance"
    manifest_path = tmp_path / "manifest.json"

    result = run_names(
        answers_dir=answers_dir,
        inventory_path=inventory_path,
        embeddings_dir=embeddings_dir,
        manifest_path=manifest_path,
        encoder=_fake_encoder,
        cluster_fn=_fake_cluster_fn,
    )

    assert result.entry_count == 2
    assert result.occurrence_count == 2

    inventory_lines = inventory_path.read_text(encoding="utf-8").splitlines()
    inventory = {json.loads(line)["surface"]: json.loads(line) for line in inventory_lines}
    assert inventory["Kevin Attell"] == {
        "surface": "Kevin Attell",
        "kind": "person",
        "count": 1,
        "chunk_ids": ["c1"],
    }
    assert inventory["Gellner 1992"]["kind"] is None

    db = lancedb.connect(embeddings_dir)
    rows = db.open_table("names").to_arrow().to_pylist()
    by_form = {row["surface_form"]: row for row in rows}
    assert by_form["Kevin Attell"]["kind"] == "person"
    assert by_form["Gellner 1992"]["kind"] == ""
    assert json.loads(by_form["Kevin Attell"]["chunk_ids_json"]) == ["c1"]
    for row in rows:
        assert isinstance(row["vector"], list) and row["vector"]
        assert "cluster_label" in row

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["entry_count"] == 2
    assert manifest["occurrence_count"] == 2
    assert manifest["model_name"]
    assert manifest["config"]["min_cluster_size"] == 2
    assert manifest["config"]["min_samples"] == 1
    assert manifest["inventory_path"] == str(inventory_path)


def test_run_names_is_deterministic_across_reruns(tmp_path: Path):
    answers_dir = tmp_path / "answers"
    _write_answers(
        answers_dir,
        "s1",
        [
            _answer_record(
                "c1",
                "s1",
                _base_answers(
                    names=[
                        {"name": "Alpha", "kind": "concept"},
                        {"name": "Beta", "kind": "concept"},
                    ]
                ),
            )
        ],
    )
    kwargs = dict(
        answers_dir=answers_dir,
        inventory_path=tmp_path / "inventory.jsonl",
        embeddings_dir=tmp_path / "embeddings.lance",
        manifest_path=tmp_path / "manifest.json",
        encoder=_fake_encoder,
        cluster_fn=_fake_cluster_fn,
    )

    first = run_names(**kwargs)
    second = run_names(**kwargs)

    assert first.entry_count == second.entry_count == 2
    assert first.cluster_count == second.cluster_count
    assert first.noise_count == second.noise_count


# --- examine_names / format_names_report -------------------------------------


def _write_names_table(embeddings_dir: Path, entries: list[tuple[str, list[float], int]]) -> None:
    """Write a `names` LanceDB table directly, with CONTROLLED vectors --
    `examine_names` always re-clusters with the real PCA+HDBSCAN pipeline
    (no `cluster_fn` injection seam; that IS the behaviour under test), so
    its tests need vectors whose real geometry is known, not `_fake_encoder`'s
    arbitrary string-derived ones."""
    rows = [
        {
            "surface_form": surface_form,
            "kind": "",
            "count": count,
            "chunk_ids_json": "[]",
            "cluster_label": -1,  # unused by examine_names; it re-clusters
            "vector": vector,
        }
        for surface_form, vector, count in entries
    ]
    db = lancedb.connect(embeddings_dir)
    db.create_table(TABLE_NAME, data=rows, mode="overwrite")


def test_examine_names_missing_table_raises(tmp_path: Path):
    with pytest.raises(NoNamesToClusterError):
        examine_names(embeddings_dir=tmp_path / "nope.lance")


def _tightness_fixture_vectors() -> list[tuple[str, list[float], int]]:
    """Two dense, well-separated (antipodal-direction) groups -- mirrors
    `axial.distill.readiness`'s own real-pipeline unit-test fixture shape
    (`test_default_cluster_fn_separates_two_dense_regions...`), which is
    proven stable through this exact normalise/standardise/PCA pipeline at
    small N, unlike a hand-picked "obviously distinct" fixture (verified
    directly: a magnitude-only or too-small fixture collapses unpredictably
    once StandardScaler sees near-zero per-feature variance -- small-N
    synthetic data does not behave like the real, thousands-of-points
    corpus this pipeline is tuned for). `min_cluster_size=2` vs `5` is an
    empirically found (not guessed) real transition on this exact fixture:
    both dense groups survive at 2, and BOTH collapse to noise at 5 (`leaf`
    selection requires every surviving leaf to meet the size, so the
    smaller 3-member group failing drags the whole tree's leaf selection
    down) -- exactly the real, if blunt, "where this setting decides
    something" case a founder would see in the real report."""
    group_a = [(f"Alpha{i}", [5.0 + i * 0.01, 5.0, 5.0], 1) for i in range(6)]
    group_b = [(f"Beta{i}", [-5.0 + i * 0.01, -5.0, -5.0], 1) for i in range(3)]
    noise = [("Gamma", [5.0, -5.0, 5.0], 1), ("Delta", [-5.0, 5.0, -5.0], 1)]
    return group_a + group_b + noise


def test_examine_names_sweeps_tightness_from_one_fit(tmp_path: Path):
    embeddings_dir = tmp_path / "embeddings.lance"
    entries = _tightness_fixture_vectors()
    _write_names_table(embeddings_dir, entries)

    stats = examine_names(embeddings_dir=embeddings_dir, min_cluster_sizes=[2, 5], min_samples=1)

    assert stats.entry_count == len(entries)
    assert stats.occurrence_count == len(entries)
    assert stats.similarity_min is not None
    assert [t.min_cluster_size for t in stats.tightness] == [2, 5]

    loose, tight = stats.tightness
    assert loose.min_samples == tight.min_samples == 1
    # mcs=2: both dense groups form their own real cluster.
    assert loose.cluster_count == 2
    assert loose.noise_count == 0
    # mcs=5: the 3-member group can no longer meet the threshold, and
    # `leaf` selection carries that down to noise for everyone.
    assert tight.cluster_count == 0
    assert tight.noise_count == len(entries)
    assert tight.noise_fraction == 1.0
    # noise never DEcreases as min_cluster_size tightens -- a structural
    # HDBSCAN invariant (a stricter threshold only ever demotes points to
    # noise, never promotes noise back into a cluster).
    assert tight.noise_count >= loose.noise_count

    # At mcs=5 every entry is noise, so the highest-similarity sampled pair
    # (within either original dense group) is a real borderline pair: a
    # near-identical pair this tightness declined to cluster at all.
    assert tight.borderline_pairs
    assert tight.borderline_pairs == sorted(
        tight.borderline_pairs, key=lambda item: item[2], reverse=True
    )

    report = format_names_report(stats)
    assert f"{len(entries)} distinct surface form(s)" in report
    assert f"{len(entries)} total occurrence(s)" in report
    assert "tightness sweep (2 candidate(s))" in report
    assert "min_cluster_size=2 min_samples=1" in report
    assert "min_cluster_size=5 min_samples=1" in report
    assert "nearest-neighbour cosine similarity spread" in report
    assert "borderline pairs" in report


def test_examine_names_default_sweep_uses_module_defaults(tmp_path: Path):
    embeddings_dir = tmp_path / "embeddings.lance"
    _write_names_table(
        embeddings_dir,
        [("Alpha", [0.0, 0.0], 1), ("Alpha2", [0.01, 0.01], 1), ("Zeta", [50.0, 50.0], 1)],
    )

    from axial.names import DEFAULT_TIGHTNESS_MIN_CLUSTER_SIZES

    stats = examine_names(embeddings_dir=embeddings_dir)

    assert [t.min_cluster_size for t in stats.tightness] == sorted(
        DEFAULT_TIGHTNESS_MIN_CLUSTER_SIZES
    )


def test_format_names_report_handles_no_tightness_candidates():
    class _Stats:
        entry_count = 0
        occurrence_count = 0
        similarity_min = None
        similarity_max = None
        similarity_mean = None
        similarity_median = None
        tightness: list = []

    report = format_names_report(_Stats())

    assert "tightness sweep (0 candidate(s))" in report
    assert "(fewer than 2 entries)" in report


# --- _relabel_from_tree: cheap relabel matches a fresh fit -------------------


def test_relabel_from_tree_matches_a_fresh_fit_at_the_same_settings():
    import hdbscan
    import numpy as np

    rng = np.random.default_rng(0)
    reduced = np.vstack(
        [
            rng.normal(loc=[0, 0], scale=0.05, size=(6, 2)),
            rng.normal(loc=[5, 5], scale=0.05, size=(4, 2)),
            rng.uniform(-10, 15, size=(10, 2)),
        ]
    )

    clusterer = hdbscan.HDBSCAN(
        min_cluster_size=2,
        min_samples=1,
        cluster_selection_method="leaf",
        allow_single_cluster=True,
    )
    clusterer.fit(reduced)
    slt = clusterer.single_linkage_tree_.to_numpy()

    cheap_labels = _relabel_from_tree(reduced, slt, min_cluster_size=4)

    fresh = hdbscan.HDBSCAN(
        min_cluster_size=4,
        min_samples=1,
        cluster_selection_method="leaf",
        allow_single_cluster=True,
    )
    fresh_labels = fresh.fit_predict(reduced)

    def partition(labels):
        groups: dict[int, set[int]] = {}
        for index, label in enumerate(labels):
            if label == -1:
                continue
            groups.setdefault(label, set()).add(index)
        return sorted(frozenset(group) for group in groups.values())

    assert partition(cheap_labels) == partition(list(fresh_labels))
    assert {i for i, label in enumerate(cheap_labels) if label == -1} == {
        i for i, label in enumerate(fresh_labels) if label == -1
    }


# --- _nearest_neighbour_pairs / _borderline_pairs ----------------------------


def test_nearest_neighbour_pairs_finds_the_closest_other_row():
    rows = [
        {"surface_form": "a", "vector": [1.0, 0.0]},
        {"surface_form": "b", "vector": [0.99, 0.01]},  # nearly identical to "a"
        {"surface_form": "c", "vector": [-1.0, 0.0]},  # opposite direction
    ]

    pairs = _nearest_neighbour_pairs(rows, sample_size=3)

    by_index = {i: (j, sim) for i, j, sim in pairs}
    assert by_index[0][0] == 1  # "a"'s nearest is "b"
    assert by_index[0][1] > 0.9
    assert by_index[2][1] < 0  # "c" is anti-correlated with everything else


def test_nearest_neighbour_pairs_empty_for_fewer_than_two_rows():
    assert _nearest_neighbour_pairs([{"surface_form": "a", "vector": [1.0]}], sample_size=5) == []
    assert _nearest_neighbour_pairs([], sample_size=5) == []


def test_borderline_pairs_excludes_same_cluster_dedupes_and_sorts():
    rows = [
        {"surface_form": "a"},
        {"surface_form": "b"},
        {"surface_form": "c"},
        {"surface_form": "d"},
    ]
    # (i, j, similarity): a-b same cluster (excluded); a-c and b-d cross
    # clusters at different similarities; c-d both noise.
    pairs = [(0, 1, 0.99), (0, 2, 0.5), (1, 3, 0.8), (2, 3, 0.6)]
    labels = [0, 0, 1, -1]  # a,b in cluster 0; c in cluster 1; d is noise

    result = _borderline_pairs(rows, pairs, labels, top_n=5)

    assert ("b", "d", 0.8) in result
    assert ("c", "d", 0.6) in result
    assert not any({a, b} == {"a", "b"} for a, b, _sim in result)  # same-cluster excluded
    assert result == sorted(result, key=lambda item: item[2], reverse=True)


def test_borderline_pairs_respects_top_n():
    rows = [{"surface_form": str(i)} for i in range(5)]
    pairs = [(0, 1, 0.9), (1, 2, 0.8), (2, 3, 0.7), (3, 4, 0.6)]
    labels = [-1, -1, -1, -1, -1]  # everything noise -> every pair qualifies

    result = _borderline_pairs(rows, pairs, labels, top_n=2)

    assert len(result) == 2
    assert result[0][2] == 0.9 and result[1][2] == 0.8
