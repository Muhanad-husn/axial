"""Outer acceptance test for issue #296 (stage-5a: embedding pass + vector
store, DEC-35).

Given the frozen corpus (a fixture vault + corpus pin, built directly --
see the isolation-seam docstring below)
When  `axial distill embed` runs
Then  every prose chunk has a persisted vector keyed by chunk_id, in a real
      vector store (LanceDB) -- not a flat array
And   the store answers a metadata-filtered nearest-neighbour query (by
      source_id and by tag axis)
And   no chunk_text is persisted in the store (DEC-23) -- ids, vectors, and
      filterable metadata only
And   re-running the pass on the same frozen corpus is deterministic
And   `axial distill embed` requires a corpus pin (DEC-35's provenance
      convention) and a non-empty vault -- both loud failures, never a
      silently degraded manifest

See `plans/phase-a-completion/README.md` stage 5a, `docs/DECISIONS.md` DEC-35,
`docs/eval/02-hybrid-tagging-distillation.md`.

Isolation -- the isolated staging root (issue #68), same seam as
tests/analysis/test_corpus_pin.py
-----------------------------------------------------------------------
`axial distill embed` resolves `data/vault/`, `data/distill/`, and
`evals/corpus_pin/` as plain paths relative to the process's current working
directory (no env-var override, no CLI flag -- see `src/axial/distill/embed.py`).
This test runs the CLI as a subprocess with `cwd` set to `isolated_vault_root`,
a private `tmp_path` staging root, never touching the real, shared `data/`
tree.

Seam decision -- fixture notes/pin are built directly, not through the
pipeline
-----------------------------------------------------------------------
Building the fixture via real `axial vault write` would require an LLM
provider. Instead this test writes prose notes directly with
`axial.vault.render_note` (the same stable frontmatter renderer the real
pipeline uses) and writes a real corpus pin via the `axial pin write` CLI
subcommand (already covered by its own outer test) -- so this test's own
subject matter is exactly and only the embedding pass.

Real embedding model, no other LLM call
-----------------------------------------------------------------------
Unlike a Phase-A pipeline pass, `axial distill embed` genuinely calls a
local sentence-transformer -- that IS the behavior under test ("every prose
chunk has a persisted vector"), so this is not run with a stubbed encoder.
It IS run with `AXIAL_LLM_PROVIDER=explode` (the poison-client env seam
already established by tests/eval/test_eval.py and
tests/analysis/test_corpus_pin.py): `axial distill embed` must never reach
a text-generating LLM at all, only the local encoder.

Requires the `distill` dependency group (issue #296): `uv sync --group
distill` before running this file -- `lancedb`/`sentence-transformers` are
optional, not part of `dependencies`/`dev`. `importorskip` below skips this
whole module cleanly on an environment that never synced the group.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

lancedb = pytest.importorskip("lancedb")
pytest.importorskip("sentence_transformers")

from axial.vault import render_note  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

PROVIDER_ENV_VAR = "AXIAL_LLM_PROVIDER"


def _run_axial(root: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env[PROVIDER_ENV_VAR] = "explode"  # poison: any text-gen LLM call crashes the run
    return subprocess.run(
        ["uv", "run", "--project", str(REPO_ROOT), "axial", *args],
        cwd=root,
        capture_output=True,
        text=True,
        env=env,
    )


def _write_chunk_note(
    prose_dir: Path,
    chunk_id: str,
    *,
    field_primary: str = "state",
    role_in_argument: str = "role:claim",
) -> Path:
    prose_dir.mkdir(parents=True, exist_ok=True)
    frontmatter: dict[str, Any] = {
        "chunk_id": chunk_id,
        "section": "Introduction",
        "chunk_text": f"SENTINEL_CHUNK_TEXT_{chunk_id} -- synthetic placeholder prose, not a "
        "real source excerpt, written only for the embedding-pass acceptance fixture.",
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
        "empirical_scope": {"value": "scope:country-case", "polity": "Syria"},
        "polities_touched": ["Syria"],
        "artifact_refs": [],
    }
    path = prose_dir / f"{chunk_id}.md"
    path.write_text(render_note(frontmatter, "# Introduction\n\nbody\n"), encoding="utf-8")
    return path


def _build_fixture_vault(root: Path) -> None:
    """Two chunks from `src1` (one `field:state`, one `field:violence`) and
    one from `src2` -- enough to exercise both a `source_id` filter and a
    tag-axis filter distinctly."""
    prose_dir = root / "data" / "vault" / "prose"
    _write_chunk_note(prose_dir, "src1_000_intro_001", field_primary="state")
    _write_chunk_note(prose_dir, "src1_001_intro_002", field_primary="violence")
    _write_chunk_note(prose_dir, "src2_000_intro_001", field_primary="state")


def _write_corpus_pin(root: Path) -> None:
    (root / "data" / "envelopes").mkdir(parents=True, exist_ok=True)
    result = _run_axial(root, "pin", "write", "baseline")
    assert result.returncode == 0, (
        f"fixture setup: `axial pin write baseline` failed\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )


def _assert_ran_the_real_subcommand(result: subprocess.CompletedProcess) -> None:
    combined_output = result.stdout + result.stderr
    assert (
        "invalid choice" not in combined_output and "unrecognized arguments" not in combined_output
    ), (
        "expected a real 'axial distill embed' run, not an argparse fallback -- "
        "this means the `axial distill embed` CLI subcommand does not exist yet:\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )


def test_embed_persists_a_vector_per_chunk_answers_filtered_nn_queries_no_chunk_text(
    isolated_vault_root,
):
    root = isolated_vault_root
    _build_fixture_vault(root)
    _write_corpus_pin(root)

    result = _run_axial(root, "distill", "embed")
    _assert_ran_the_real_subcommand(result)
    assert result.returncode == 0, (
        f"expected exit 0, got {result.returncode}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    manifest_path = root / "data" / "distill" / "embedding_manifest.json"
    assert manifest_path.is_file(), f"expected a manifest at {manifest_path}"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["chunk_count"] == 3
    assert manifest["corpus_pin_id"] == "baseline"
    assert isinstance(manifest["vault_snapshot_hash"], str) and manifest["vault_snapshot_hash"]
    assert isinstance(manifest["embedding_dim"], int) and manifest["embedding_dim"] > 0

    embeddings_dir = root / "data" / "distill" / "embeddings.lance"
    db = lancedb.connect(embeddings_dir)
    table = db.open_table("chunks")
    rows = table.to_arrow().to_pylist()
    assert len(rows) == 3, "expected one persisted vector per prose chunk"

    for row in rows:
        assert "chunk_text" not in row, (
            f"DEC-23 violation: chunk_text must never be persisted in the vector "
            f"store, found a row carrying it: {row}"
        )
        assert not any(
            f"SENTINEL_CHUNK_TEXT_{cid}" in json.dumps(row)
            for cid in ("src1_000_intro_001", "src1_001_intro_002", "src2_000_intro_001")
        ), f"DEC-23 violation: a fixture chunk_text sentinel leaked into a stored row: {row}"

    query_vector = [0.0] * manifest["embedding_dim"]

    by_source = table.search(query_vector).where("source_id = 'src2'").limit(10).to_list()
    assert [row["chunk_id"] for row in by_source] == ["src2_000_intro_001"], (
        "expected the source_id-filtered nearest-neighbour query to return only "
        f"src2's own chunk, got: {[row['chunk_id'] for row in by_source]}"
    )

    by_tag = table.search(query_vector).where("field_primary = 'violence'").limit(10).to_list()
    assert [row["chunk_id"] for row in by_tag] == ["src1_001_intro_002"], (
        "expected the tag-axis-filtered nearest-neighbour query to return only "
        f"the violence-tagged chunk, got: {[row['chunk_id'] for row in by_tag]}"
    )


def test_embed_is_deterministic_across_reruns_over_the_same_frozen_corpus(isolated_vault_root):
    root = isolated_vault_root
    _build_fixture_vault(root)
    _write_corpus_pin(root)

    first = _run_axial(root, "distill", "embed")
    _assert_ran_the_real_subcommand(first)
    assert first.returncode == 0, f"stdout: {first.stdout!r}\nstderr: {first.stderr!r}"
    embeddings_dir = root / "data" / "distill" / "embeddings.lance"
    manifest_path = root / "data" / "distill" / "embedding_manifest.json"
    first_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    db = lancedb.connect(embeddings_dir)
    first_rows = {
        row["chunk_id"]: row["vector"] for row in db.open_table("chunks").to_arrow().to_pylist()
    }

    second = _run_axial(root, "distill", "embed")
    assert second.returncode == 0, f"stdout: {second.stdout!r}\nstderr: {second.stderr!r}"
    second_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    db2 = lancedb.connect(embeddings_dir)
    second_rows = {
        row["chunk_id"]: row["vector"] for row in db2.open_table("chunks").to_arrow().to_pylist()
    }

    assert first_manifest == second_manifest, (
        "expected an identical manifest across two runs over the same unchanged "
        f"vault, got first={first_manifest!r} vs second={second_manifest!r}"
    )
    assert first_rows == second_rows, (
        "expected byte-identical vectors per chunk_id across two runs over the "
        "same unchanged vault -- the embedding pass must be deterministic"
    )


def test_embed_fails_loudly_without_a_corpus_pin(isolated_vault_root):
    root = isolated_vault_root
    _build_fixture_vault(root)
    # deliberately never write a corpus pin

    result = _run_axial(root, "distill", "embed")
    _assert_ran_the_real_subcommand(result)

    assert result.returncode != 0, (
        f"expected a non-zero exit with no corpus pin present, got 0\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    assert not (root / "data" / "distill" / "embedding_manifest.json").is_file(), (
        "expected no manifest to be written when the pass fails before it can "
        "record real provenance"
    )
    assert "pin" in result.stderr.lower(), (
        f"expected the failure to mention the missing corpus pin, got stderr: {result.stderr!r}"
    )


def test_embed_fails_loudly_on_an_empty_vault(isolated_vault_root):
    root = isolated_vault_root
    (root / "data" / "vault").mkdir(parents=True, exist_ok=True)  # no prose/ subdir at all
    _write_corpus_pin(root)

    result = _run_axial(root, "distill", "embed")
    _assert_ran_the_real_subcommand(result)

    assert result.returncode != 0, (
        f"expected a non-zero exit over an empty vault, got 0\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    assert not (root / "data" / "distill" / "embedding_manifest.json").is_file()
