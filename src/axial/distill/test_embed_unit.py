"""Inner unit tests for the stage-5a embedding pass (issue #296, DEC-35).

`lancedb` is an optional `distill`-group dependency (`uv sync --group
distill`), not part of the base `dependencies`/`dev` groups the fast
per-commit gate assumes -- `importorskip` here means this whole module
skips cleanly (not errors) on an environment that never synced the group,
while still running for real wherever it is installed (this repo's own dev
environment, and CI once its workflow syncs the group -- see the PR body).

These tests use an injected fake encoder (`_fake_encoder`, parsing a
comma-separated vector straight out of `chunk_text`) rather than the real
`sentence-transformers` model, so they stay fast and network-free -- the
LanceDB write/query/manifest path is exactly the same regardless of which
encoder produced the vectors. The one test that exercises the REAL default
model (`test_default_encoder_is_deterministic`) is marked `slow`: a fresh
environment's first run downloads ~90MB from the Hugging Face Hub, which
would blow the fast gate's budget on every future commit across this repo,
not just this one -- mirrors `axial.extract`'s own real-docling test being
marked `slow` for the identical reason.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

lancedb = pytest.importorskip("lancedb")

from axial.distill.embed import (  # noqa: E402
    CorpusPinRequiredError,
    DEFAULT_MODEL_NAME,
    NoChunksToEmbedError,
    UnknownSearchFilterError,
    _default_encoder,
    _load_chunk_records,
    run_embed,
    search,
)
from axial.eval.corpus_pin import write_pin  # noqa: E402
from axial.vault import render_note  # noqa: E402


def _vector_text(vector: list[float]) -> str:
    return ",".join(str(value) for value in vector)


def _fake_encoder(texts: list[str]) -> list[list[float]]:
    """A deterministic stand-in for the real sentence-transformer: parses
    each chunk's `chunk_text` (written as a comma-separated vector by
    `_write_chunk_note` below) straight back into floats, so a test controls
    exactly what vector each fixture chunk embeds to."""
    return [[float(value) for value in text.split(",")] for text in texts]


def _write_chunk_note(
    prose_dir: Path,
    chunk_id: str,
    vector: list[float],
    *,
    field_primary: str = "state",
    role_in_argument: str = "role:claim",
    empirical_scope_value: str = "scope:country-case",
    polity: str | None = "Syria",
) -> Path:
    prose_dir.mkdir(parents=True, exist_ok=True)
    empirical_scope = {"value": empirical_scope_value}
    if polity is not None:
        empirical_scope["polity"] = polity
    frontmatter = {
        "chunk_id": chunk_id,
        "section": "Introduction",
        "chunk_text": _vector_text(vector),
        "source_meta": {"author": "A", "title": "T"},
        "schema_version": "0.1",
        "role_in_argument": role_in_argument,
        "field": {"primary": field_primary, "secondary": []},
        "claim_type": {"primary": "state-formation", "secondary": None, "subtags": []},
        "theory_school": {
            "primary": "institutionalist-state-centered",
            "secondary": None,
            "status": "candidate",
        },
        "empirical_scope": empirical_scope,
        "polities_touched": [polity] if polity else [],
        "artifact_refs": [],
    }
    path = prose_dir / f"{chunk_id}.md"
    path.write_text(render_note(frontmatter, "# Introduction\n\nbody\n"), encoding="utf-8")
    return path


def _stage_pin(tmp_path: Path, name: str = "baseline") -> Path:
    """Write a corpus pin over whatever is currently under
    `tmp_path/data/vault` -- run_embed requires one to exist (DEC-35's
    provenance requirement). Returns `evals_dir`."""
    vault_dir = tmp_path / "data" / "vault"
    envelopes_dir = tmp_path / "data" / "envelopes"
    envelopes_dir.mkdir(parents=True, exist_ok=True)
    evals_dir = tmp_path / "evals" / "corpus_pin"
    write_pin(name, vault_dir=vault_dir, envelopes_dir=envelopes_dir, evals_dir=evals_dir)
    return evals_dir


# --- _load_chunk_records -----------------------------------------------------


def test_load_chunk_records_sorted_by_chunk_id_with_flattened_metadata(tmp_path: Path):
    vault_dir = tmp_path / "data" / "vault"
    prose_dir = vault_dir / "prose"
    _write_chunk_note(prose_dir, "src1_001_intro_002", [0.2], field_primary="violence")
    _write_chunk_note(prose_dir, "src1_000_intro_001", [0.1], field_primary="state")

    records = _load_chunk_records(vault_dir)

    chunk_ids = [record[0] for record in records]
    assert chunk_ids == sorted(chunk_ids)
    _chunk_id, chunk_text, metadata = records[0]
    assert chunk_text == "0.1"
    assert metadata == {
        "chunk_id": "src1_000_intro_001",
        "source_id": "src1",
        "role_in_argument": "role:claim",
        "field_primary": "state",
        "claim_type_primary": "state-formation",
        "theory_school_primary": "institutionalist-state-centered",
        "empirical_scope_value": "scope:country-case",
        "polity": "Syria",
    }


def test_load_chunk_records_missing_axis_projects_to_empty_string_not_none(tmp_path: Path):
    vault_dir = tmp_path / "data" / "vault"
    prose_dir = vault_dir / "prose"
    prose_dir.mkdir(parents=True)
    frontmatter = {
        "chunk_id": "src1_000_intro_001",
        "section": "Introduction",
        "chunk_text": "0.1",
        "source_meta": {"author": "A"},
        "schema_version": "0.1",
        "role_in_argument": "role:claim",
    }
    (prose_dir / "src1_000_intro_001.md").write_text(
        render_note(frontmatter, "# Introduction\n\nbody\n"), encoding="utf-8"
    )

    (_chunk_id, _chunk_text, metadata) = _load_chunk_records(vault_dir)[0]

    assert metadata["field_primary"] == ""
    assert metadata["polity"] == ""


# --- run_embed: loud failures ------------------------------------------------


def test_run_embed_missing_prose_dir_raises_no_chunks_to_embed(tmp_path: Path):
    vault_dir = tmp_path / "data" / "vault"
    vault_dir.mkdir(parents=True)
    evals_dir = _stage_pin(tmp_path)

    with pytest.raises(NoChunksToEmbedError):
        run_embed(
            vault_dir=vault_dir,
            embeddings_dir=tmp_path / "embeddings.lance",
            manifest_path=tmp_path / "manifest.json",
            evals_dir=evals_dir,
            encoder=_fake_encoder,
        )


def test_run_embed_requires_a_corpus_pin(tmp_path: Path):
    vault_dir = tmp_path / "data" / "vault"
    _write_chunk_note(vault_dir / "prose", "src1_000_intro_001", [0.1])
    evals_dir = tmp_path / "evals" / "corpus_pin"  # never written

    with pytest.raises(CorpusPinRequiredError):
        run_embed(
            vault_dir=vault_dir,
            embeddings_dir=tmp_path / "embeddings.lance",
            manifest_path=tmp_path / "manifest.json",
            evals_dir=evals_dir,
            encoder=_fake_encoder,
        )


# --- run_embed: the persisted store ------------------------------------------


def test_run_embed_writes_vectors_and_metadata_never_chunk_text(tmp_path: Path):
    vault_dir = tmp_path / "data" / "vault"
    _write_chunk_note(vault_dir / "prose", "src1_000_intro_001", [0.1, 0.2], field_primary="state")
    _write_chunk_note(
        vault_dir / "prose", "src1_001_intro_002", [0.4, 0.5], field_primary="violence"
    )
    evals_dir = _stage_pin(tmp_path)
    embeddings_dir = tmp_path / "embeddings.lance"
    manifest_path = tmp_path / "manifest.json"

    result = run_embed(
        vault_dir=vault_dir,
        embeddings_dir=embeddings_dir,
        manifest_path=manifest_path,
        evals_dir=evals_dir,
        encoder=_fake_encoder,
    )

    assert result.chunk_count == 2
    assert result.embedding_dim == 2

    db = lancedb.connect(embeddings_dir)
    table = db.open_table("chunks")
    rows = table.to_arrow().to_pylist()
    assert len(rows) == 2
    for row in rows:
        assert "chunk_text" not in row, f"DEC-23 violation: chunk_text leaked into the store: {row}"
        assert isinstance(row["vector"], list) and row["vector"]
        assert row["source_id"] == "src1"

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["chunk_count"] == 2
    assert manifest["model_name"] == DEFAULT_MODEL_NAME
    assert manifest["embedding_dim"] == 2
    assert manifest["corpus_pin_id"] == "baseline"
    assert "chunk_text" not in json.dumps(manifest)


def test_run_embed_is_deterministic_across_reruns_over_an_unchanged_vault(tmp_path: Path):
    vault_dir = tmp_path / "data" / "vault"
    _write_chunk_note(vault_dir / "prose", "src1_000_intro_001", [0.1, 0.2, 0.3])
    _write_chunk_note(vault_dir / "prose", "src2_000_intro_001", [0.9, 0.8, 0.7])
    evals_dir = _stage_pin(tmp_path)
    embeddings_dir = tmp_path / "embeddings.lance"
    manifest_path = tmp_path / "manifest.json"
    kwargs = dict(
        vault_dir=vault_dir,
        embeddings_dir=embeddings_dir,
        manifest_path=manifest_path,
        evals_dir=evals_dir,
        encoder=_fake_encoder,
    )

    first = run_embed(**kwargs)
    first_query = search(embeddings_dir, [0.1, 0.2, 0.29], limit=5)

    second = run_embed(**kwargs)
    second_query = search(embeddings_dir, [0.1, 0.2, 0.29], limit=5)

    assert first.chunk_count == second.chunk_count
    assert [row["chunk_id"] for row in first_query] == [row["chunk_id"] for row in second_query]
    assert [row["vector"] for row in first_query] == [row["vector"] for row in second_query]


# --- search: metadata-filtered nearest-neighbour -----------------------------


def test_search_filters_by_source_id(tmp_path: Path):
    vault_dir = tmp_path / "data" / "vault"
    _write_chunk_note(vault_dir / "prose", "src1_000_intro_001", [0.1, 0.1])
    _write_chunk_note(vault_dir / "prose", "src2_000_intro_001", [0.1, 0.1])
    evals_dir = _stage_pin(tmp_path)
    embeddings_dir = tmp_path / "embeddings.lance"
    run_embed(
        vault_dir=vault_dir,
        embeddings_dir=embeddings_dir,
        manifest_path=tmp_path / "manifest.json",
        evals_dir=evals_dir,
        encoder=_fake_encoder,
    )

    results = search(embeddings_dir, [0.1, 0.1], source_id="src2", limit=5)

    assert [row["chunk_id"] for row in results] == ["src2_000_intro_001"]


def test_search_filters_by_tag_axis(tmp_path: Path):
    vault_dir = tmp_path / "data" / "vault"
    _write_chunk_note(vault_dir / "prose", "src1_000_intro_001", [0.1, 0.1], field_primary="state")
    _write_chunk_note(
        vault_dir / "prose", "src1_001_intro_002", [0.1, 0.1], field_primary="violence"
    )
    evals_dir = _stage_pin(tmp_path)
    embeddings_dir = tmp_path / "embeddings.lance"
    run_embed(
        vault_dir=vault_dir,
        embeddings_dir=embeddings_dir,
        manifest_path=tmp_path / "manifest.json",
        evals_dir=evals_dir,
        encoder=_fake_encoder,
    )

    results = search(embeddings_dir, [0.1, 0.1], field_primary="violence", limit=5)

    assert [row["chunk_id"] for row in results] == ["src1_001_intro_002"]


def test_search_unknown_filter_key_raises(tmp_path: Path):
    vault_dir = tmp_path / "data" / "vault"
    _write_chunk_note(vault_dir / "prose", "src1_000_intro_001", [0.1])
    evals_dir = _stage_pin(tmp_path)
    embeddings_dir = tmp_path / "embeddings.lance"
    run_embed(
        vault_dir=vault_dir,
        embeddings_dir=embeddings_dir,
        manifest_path=tmp_path / "manifest.json",
        evals_dir=evals_dir,
        encoder=_fake_encoder,
    )

    with pytest.raises(UnknownSearchFilterError):
        search(embeddings_dir, [0.1], not_a_real_column="x")


# --- the real default encoder (slow: first run downloads the model) ---------


@pytest.mark.slow
def test_default_encoder_is_deterministic():
    encode = _default_encoder(DEFAULT_MODEL_NAME)
    texts = ["state formation through contested violence", "institutions and political order"]

    first = encode(texts)
    second = encode(texts)

    assert first == second
    assert len(first[0]) == 384
