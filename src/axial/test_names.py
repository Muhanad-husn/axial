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


def test_examine_names_missing_table_raises(tmp_path: Path):
    with pytest.raises(NoNamesToClusterError):
        examine_names(embeddings_dir=tmp_path / "nope.lance")


def test_examine_names_reports_cluster_sizes_and_similarity(tmp_path: Path):
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
                        {"name": "Alpha2", "kind": "concept"},
                    ]
                ),
            ),
            _answer_record("c2", "s1", _base_answers(names=[{"name": "Zeta", "kind": "concept"}])),
        ],
    )
    embeddings_dir = tmp_path / "embeddings.lance"

    def cluster_fn(vectors: list[list[float]]) -> list[int]:
        # First two entries ("Alpha", "Alpha2") cluster together; the third
        # ("Zeta") is noise -- exercises both branches of the report.
        return [0, 0, -1][: len(vectors)]

    run_names(
        answers_dir=answers_dir,
        inventory_path=tmp_path / "inventory.jsonl",
        embeddings_dir=embeddings_dir,
        manifest_path=tmp_path / "manifest.json",
        encoder=_fake_encoder,
        cluster_fn=cluster_fn,
    )

    stats = examine_names(embeddings_dir=embeddings_dir)

    assert stats.entry_count == 3
    assert stats.cluster_count == 1
    assert stats.noise_count == 1
    assert stats.cluster_sizes == [2]
    assert stats.top_clusters == [(0, 2, ["Alpha", "Alpha2"])]
    assert stats.similarity_min is not None

    report = format_names_report(stats)
    assert "3 distinct surface form(s)" in report
    assert "1 non-noise cluster(s)" in report
    assert "1 noise" in report
    assert "cluster 0 (2 member(s))" in report
    assert "nearest-neighbour cosine similarity spread" in report


def test_format_names_report_handles_empty_clusters():
    class _Stats:
        entry_count = 0
        occurrence_count = 0
        cluster_count = 0
        noise_count = 0
        cluster_sizes: list[int] = []
        top_clusters: list = []
        similarity_min = None
        similarity_max = None
        similarity_mean = None
        similarity_median = None

    report = format_names_report(_Stats())

    assert "(no non-noise clusters)" in report
    assert "(none)" in report
    assert "(fewer than 2 entries)" in report
