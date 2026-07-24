"""Inner unit tests for the stage-5b readiness map (issue #297, DEC-35).

Most tests use an injected fake `cluster_fn` -- a plain
`list[list[float]] -> list[int]` label assignment, mirroring
`axial.distill.embed`'s own `encoder` seam -- so the manifest/readiness-map
logic runs fast and network-free, independent of what the real PCA+HDBSCAN
pipeline happens to decide on any given input. A handful of tests exercise
the REAL `_default_cluster_fn` (real numpy/scikit-learn/hdbscan, small
synthetic data) -- these libraries are fast and cheap at unit-test scale, so
they are not marked `slow` (mirrors this repo's own guidance: mark `slow`
only what is genuinely expensive, e.g. a first-run model download).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

lancedb = pytest.importorskip("lancedb")
pytest.importorskip("hdbscan")
pytest.importorskip("sklearn")

from axial.distill.embed import run_embed  # noqa: E402
from axial.distill.readiness import (  # noqa: E402
    CorpusPinRequiredError,
    NoEmbeddingsToClusterError,
    ReadinessResult,
    _build_readiness_map,
    _default_cluster_fn,
    _load_embedding_rows,
    run_readiness,
)
from axial.eval.corpus_pin import write_pin  # noqa: E402
from axial.vault import render_note  # noqa: E402


def _vector_text(vector: list[float]) -> str:
    return ",".join(str(value) for value in vector)


def _fake_embed_encoder(texts: list[str]) -> list[list[float]]:
    return [[float(value) for value in text.split(",")] for text in texts]


def _write_chunk_note(
    prose_dir: Path,
    chunk_id: str,
    vector: list[float],
    *,
    field_primary: str = "state",
    theory_school_primary: str = "institutionalist-state-centered",
) -> Path:
    prose_dir.mkdir(parents=True, exist_ok=True)
    frontmatter = {
        "chunk_id": chunk_id,
        "section": "Introduction",
        "chunk_text": _vector_text(vector),
        "source_meta": {"author": "A", "title": "T"},
        "schema_version": "0.1",
        "role_in_argument": "role:claim",
        "field": {"primary": field_primary, "secondary": []},
        "claim_type": {"primary": "state-formation", "secondary": None, "subtags": []},
        "theory_school": {
            "primary": theory_school_primary,
            "secondary": None,
            "status": "candidate",
        },
        "empirical_scope": {"value": "scope:country-case", "polity": "Syria"},
        "polities_touched": ["Syria"],
        "artifact_refs": [],
    }
    path = prose_dir / f"{chunk_id}.md"
    path.write_text(render_note(frontmatter, "# Introduction\n\nbody\n"), encoding="utf-8")
    return path


def _stage_pin(tmp_path: Path, name: str = "baseline") -> Path:
    vault_dir = tmp_path / "data" / "vault"
    vault_dir.mkdir(parents=True, exist_ok=True)
    envelopes_dir = tmp_path / "data" / "envelopes"
    envelopes_dir.mkdir(parents=True, exist_ok=True)
    evals_dir = tmp_path / "evals" / "corpus_pin"
    write_pin(name, vault_dir=vault_dir, envelopes_dir=envelopes_dir, evals_dir=evals_dir)
    return evals_dir


def _stage_embeddings(tmp_path: Path, chunks: list[tuple[str, list[float], str]]) -> Path:
    """Writes vault notes for each `(chunk_id, vector, field_primary)` and
    embeds them via the fake encoder (parses `chunk_text` straight back into
    floats), returning `embeddings_dir`."""
    vault_dir = tmp_path / "data" / "vault"
    for chunk_id, vector, field_primary in chunks:
        _write_chunk_note(vault_dir / "prose", chunk_id, vector, field_primary=field_primary)
    evals_dir = _stage_pin(tmp_path)
    embeddings_dir = tmp_path / "embeddings.lance"
    run_embed(
        vault_dir=vault_dir,
        embeddings_dir=embeddings_dir,
        manifest_path=tmp_path / "embedding_manifest.json",
        evals_dir=evals_dir,
        encoder=_fake_embed_encoder,
    )
    return embeddings_dir


# --- _load_embedding_rows -----------------------------------------------------


def test_load_embedding_rows_missing_dir_raises(tmp_path: Path):
    with pytest.raises(NoEmbeddingsToClusterError):
        _load_embedding_rows(tmp_path / "nope.lance")


def test_load_embedding_rows_sorted_by_chunk_id(tmp_path: Path):
    embeddings_dir = _stage_embeddings(
        tmp_path,
        [
            ("src1_001_intro_002", [0.2, 0.2], "state"),
            ("src1_000_intro_001", [0.1, 0.1], "state"),
        ],
    )

    rows = _load_embedding_rows(embeddings_dir)

    assert [row["chunk_id"] for row in rows] == ["src1_000_intro_001", "src1_001_intro_002"]


# --- _build_readiness_map: pure logic, no I/O ---------------------------------


def test_build_readiness_map_tight_tag_vs_noise_tag():
    rows = [
        {"chunk_id": "a", "field_primary": "state"},
        {"chunk_id": "b", "field_primary": "state"},
        {"chunk_id": "c", "field_primary": "state"},
        {"chunk_id": "d", "field_primary": "violence"},
        {"chunk_id": "e", "field_primary": "violence"},
    ]
    labels = [0, 0, 0, -1, -1]

    readiness_map = _build_readiness_map(rows, labels, ready_dominant_share=0.5)

    state_entry = readiness_map["field_primary"]["state"]
    assert state_entry["total"] == 3
    assert state_entry["noise_count"] == 0
    assert state_entry["noise_fraction"] == 0.0
    assert state_entry["dominant_cluster_id"] == 0
    assert state_entry["dominant_cluster_share"] == 1.0
    assert state_entry["readiness"] == "tight"

    violence_entry = readiness_map["field_primary"]["violence"]
    assert violence_entry["total"] == 2
    assert violence_entry["noise_count"] == 2
    assert violence_entry["noise_fraction"] == 1.0
    assert violence_entry["dominant_cluster_id"] is None
    assert violence_entry["dominant_cluster_share"] == 0.0
    assert violence_entry["readiness"] == "noise"


def test_build_readiness_map_share_is_computed_over_non_noise_chunks_only():
    """`dominant_cluster_share` and `noise_fraction` are deliberately
    orthogonal (founder-approved semantics, post-#358 real-corpus
    validation): a tag can be almost entirely noise by volume
    (`noise_fraction` high -- most of its chunks are LLM-routed) while its
    small non-noise remainder is still fully concentrated in one real
    cluster (`dominant_cluster_share` == 1.0 -- "tight" once it does land
    somewhere), because the share denominator is non-noise count, not total
    count."""
    rows = [{"chunk_id": str(i), "field_primary": "state"} for i in range(10)]
    # 8 of 10 are noise; the remaining 2 agree on cluster 0.
    labels = [-1] * 8 + [0, 0]

    readiness_map = _build_readiness_map(rows, labels, ready_dominant_share=0.5)

    entry = readiness_map["field_primary"]["state"]
    assert entry["noise_fraction"] == pytest.approx(0.8)
    assert entry["dominant_cluster_share"] == pytest.approx(1.0)
    assert entry["readiness"] == "tight"


def test_build_readiness_map_fragmented_non_noise_portion_reads_noise():
    """A tag whose non-noise chunks are themselves split across several
    clusters (no majority) must still read "noise", regardless of how much
    of the tag is noise overall."""
    rows = [{"chunk_id": str(i), "field_primary": "state"} for i in range(10)]
    # 4 noise; the remaining 6 split evenly across three different clusters
    # -- no cluster holds a majority of the non-noise portion.
    labels = [-1] * 4 + [0, 0, 1, 1, 2, 2]

    readiness_map = _build_readiness_map(rows, labels, ready_dominant_share=0.5)

    entry = readiness_map["field_primary"]["state"]
    assert entry["dominant_cluster_share"] == pytest.approx(1 / 3)
    assert entry["readiness"] == "noise"


def test_build_readiness_map_all_noise_tag_reads_noise_no_divide_by_zero():
    """A tag with zero non-noise chunks (`non_noise == 0`) must read
    `dominant_cluster_share == 0.0` and `readiness == "noise"` outright --
    never a `ZeroDivisionError`."""
    rows = [{"chunk_id": str(i), "field_primary": "state"} for i in range(5)]
    labels = [-1] * 5

    readiness_map = _build_readiness_map(rows, labels, ready_dominant_share=0.5)

    entry = readiness_map["field_primary"]["state"]
    assert entry["noise_fraction"] == 1.0
    assert entry["dominant_cluster_id"] is None
    assert entry["dominant_cluster_share"] == 0.0
    assert entry["readiness"] == "noise"


def test_build_readiness_map_excludes_empty_tag_values():
    rows = [{"chunk_id": "a", "field_primary": ""}, {"chunk_id": "b", "field_primary": "state"}]
    labels = [0, 0]

    readiness_map = _build_readiness_map(rows, labels, ready_dominant_share=0.5)

    assert "" not in readiness_map["field_primary"]
    assert "state" in readiness_map["field_primary"]


def test_build_readiness_map_covers_every_tag_axis():
    rows = [{"chunk_id": "a", "field_primary": "state", "theory_school_primary": "x"}]
    labels = [0]

    readiness_map = _build_readiness_map(rows, labels, ready_dominant_share=0.5)

    from axial.distill.readiness import TAG_AXES

    assert set(readiness_map.keys()) == set(TAG_AXES)


# --- run_readiness: loud failures --------------------------------------------


def test_run_readiness_missing_embeddings_raises(tmp_path: Path):
    evals_dir = _stage_pin(tmp_path)

    with pytest.raises(NoEmbeddingsToClusterError):
        run_readiness(
            embeddings_dir=tmp_path / "nope.lance",
            manifest_path=tmp_path / "readiness.json",
            evals_dir=evals_dir,
            cluster_fn=lambda vectors: [0] * len(vectors),
        )


def test_run_readiness_requires_a_corpus_pin(tmp_path: Path):
    embeddings_dir = _stage_embeddings(tmp_path, [("a_000_x_001", [0.1, 0.1], "state")])
    never_written_evals_dir = tmp_path / "evals_missing"

    with pytest.raises(CorpusPinRequiredError):
        run_readiness(
            embeddings_dir=embeddings_dir,
            manifest_path=tmp_path / "readiness.json",
            evals_dir=never_written_evals_dir,
            cluster_fn=lambda vectors: [0] * len(vectors),
        )


# --- run_readiness: the persisted manifest, fake cluster_fn -----------------


def test_run_readiness_writes_manifest_and_result(tmp_path: Path):
    chunks = [
        ("a_000_x_001", [0.1, 0.1], "state"),
        ("a_001_x_002", [0.2, 0.2], "state"),
        ("a_002_x_003", [9.0, 9.0], "violence"),
    ]
    embeddings_dir = _stage_embeddings(tmp_path, chunks)
    evals_dir = tmp_path / "evals" / "corpus_pin"
    manifest_path = tmp_path / "readiness.json"

    result = run_readiness(
        embeddings_dir=embeddings_dir,
        manifest_path=manifest_path,
        evals_dir=evals_dir,
        cluster_fn=lambda vectors: [0, 0, -1],
    )

    assert isinstance(result, ReadinessResult)
    assert result.chunk_count == 3
    assert result.cluster_count == 1
    assert result.noise_count == 1
    assert result.noise_fraction == pytest.approx(1 / 3)
    assert result.corpus_pin_id == "baseline"

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["chunk_count"] == 3
    assert manifest["cluster_count"] == 1
    assert manifest["noise_count"] == 1
    assert manifest["corpus_pin_id"] == "baseline"
    assert manifest["cluster_assignments"] == {
        "a_000_x_001": 0,
        "a_001_x_002": 0,
        "a_002_x_003": -1,
    }
    assert manifest["tag_axes"]["field_primary"]["state"]["readiness"] == "tight"
    assert manifest["tag_axes"]["field_primary"]["violence"]["readiness"] == "noise"
    # DEC-23: no chunk_text (the fake encoder's own comma-separated vector
    # strings) anywhere in the emitted manifest.
    manifest_text = json.dumps(manifest)
    for _chunk_id, vector, _field in chunks:
        assert _vector_text(vector) not in manifest_text


def test_run_readiness_config_is_recorded_on_the_manifest(tmp_path: Path):
    embeddings_dir = _stage_embeddings(tmp_path, [("a_000_x_001", [0.1, 0.1], "state")])
    evals_dir = tmp_path / "evals" / "corpus_pin"
    manifest_path = tmp_path / "readiness.json"

    run_readiness(
        embeddings_dir=embeddings_dir,
        manifest_path=manifest_path,
        pca_components=7,
        min_cluster_size=3,
        min_samples=2,
        ready_dominant_share=0.6,
        evals_dir=evals_dir,
        cluster_fn=lambda vectors: [0] * len(vectors),
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["config"] == {
        "pca_components": 7,
        "min_cluster_size": 3,
        "min_samples": 2,
        "ready_dominant_share": 0.6,
    }


# --- _default_cluster_fn: the real PCA + HDBSCAN pipeline --------------------


def test_default_cluster_fn_separates_two_dense_regions_ids_start_at_zero_noise_is_negative_one():
    cluster_a = [[5.0 + i * 0.01, 5.0, 5.0] for i in range(20)]
    cluster_b = [[-5.0 + i * 0.01, -5.0, -5.0] for i in range(20)]
    vectors = cluster_a + cluster_b

    labels = _default_cluster_fn(vectors, pca_components=3, min_cluster_size=10)

    assert set(labels) <= {-1, 0, 1}
    # both regions are dense enough to be found as real clusters (not
    # entirely swallowed as noise), and the two clusters carry different ids
    non_noise = {label for label in labels if label != -1}
    assert non_noise == {0, 1}
    assert min(non_noise) == 0, "expected the first real cluster to be labelled 0, not off-by-one"


def test_default_cluster_fn_is_deterministic_across_calls():
    cluster_a = [[5.0 + i * 0.01, 5.0, 5.0] for i in range(20)]
    cluster_b = [[-5.0 + i * 0.01, -5.0, -5.0] for i in range(20)]
    vectors = cluster_a + cluster_b

    first = _default_cluster_fn(vectors, pca_components=3, min_cluster_size=10)
    second = _default_cluster_fn(vectors, pca_components=3, min_cluster_size=10)

    assert first == second


def test_default_cluster_fn_caps_pca_components_to_available_dimensions():
    """`pca_components` larger than the sample/feature count must not crash
    -- PCA cannot extract more components than `min(n_samples, n_features)`."""
    vectors = [[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]]

    labels = _default_cluster_fn(vectors, pca_components=50, min_cluster_size=2)

    assert len(labels) == 3
