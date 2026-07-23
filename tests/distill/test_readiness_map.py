"""Outer acceptance test for issue #297 (stage-5b: HDBSCAN readiness map +
cluster-`-1` LLM router, DEC-35).

Given persisted chunk embeddings for the frozen corpus (5a)
When  the readiness map is built
Then  it runs with zero LLM calls
And   it reports, per tag, whether the tag sits in a tight cluster or smears
      as noise
And   the cluster-`-1` noise set is identified and marked as the LLM-routed
      tail (NOT cluster 0)
And   the reduction + clustering step is deterministic given a pinned config
And   no source text appears in the emitted map (DEC-23)

See `plans/phase-a-completion/README.md` stage 5b, `docs/DECISIONS.md`
DEC-35, `docs/eval/02-hybrid-tagging-distillation.md`.

Isolation -- the isolated staging root (issue #68), same seam as
`tests/distill/test_embedding_pass.py`
-----------------------------------------------------------------------
`axial distill readiness-map` resolves `data/distill/embeddings.lance`,
`data/distill/readiness_manifest.json`, and `evals/corpus_pin/` as plain
paths relative to the process's cwd. This test runs the CLI as a subprocess
with `cwd` set to `isolated_vault_root`, never touching the real, shared
`data/` tree.

Seam decision -- the 5a embedding store fixture is built directly, not
through the real embedding model
-----------------------------------------------------------------------
5b's own subject matter is the reduction+clustering pass, not the embedding
pass itself (5a already has its own acceptance coverage for that). Building
the fixture vector store via `run_embed(..., encoder=<deterministic fake>)`
-- the exact injection seam `axial.distill.embed`'s own inner unit tests use
-- lets this test place chunks at known, well-separated coordinates so the
tight-cluster/noise split is exactly controlled and does not depend on a
downloaded sentence-transformer model. The CLI subcommand actually under
test (`axial distill readiness-map`) still runs for real, as a subprocess,
against that fixture store.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

lancedb = pytest.importorskip("lancedb")
pytest.importorskip("sentence_transformers")
pytest.importorskip("hdbscan")
pytest.importorskip("sklearn")

from axial.distill.embed import run_embed  # noqa: E402
from axial.vault import render_note  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

PROVIDER_ENV_VAR = "AXIAL_LLM_PROVIDER"

VECTOR_DIM = 5


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


def _fake_encoder(texts: list[str]) -> list[list[float]]:
    """Parses each chunk's `chunk_text` (written as a comma-separated vector
    by `_write_chunk_note`) straight back into floats -- the exact fake
    encoder `axial.distill.test_embed_unit` uses, letting this test place
    each fixture chunk at an exact, known coordinate."""
    return [[float(value) for value in text.split(",")] for text in texts]


def _vector_text(vector: list[float]) -> str:
    return ",".join(str(value) for value in vector)


def _write_chunk_note(
    prose_dir: Path,
    chunk_id: str,
    vector: list[float],
    *,
    field_primary: str,
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


def _tight_cluster_vectors(n: int, center: float) -> list[list[float]]:
    """`n` points tightly jittered around `(center, center, center, center,
    center)` -- a genuine, tight density region."""
    return [[center + i * 0.001, center, center, center, center] for i in range(n)]


def _scattered_noise_vectors(n: int) -> list[list[float]]:
    """`n` points, each a large, distinct one-hot-ish vector -- pairwise far
    enough apart (and, once L2-normalised, collapsed into at most
    `VECTOR_DIM` repeated directions with far fewer than `n` copies each)
    that none can meet a real cluster's minimum size: pure noise by
    construction."""
    vectors = []
    for i in range(n):
        vector = [0.0] * VECTOR_DIM
        vector[i % VECTOR_DIM] = 1000.0 + i * 733.0
        vectors.append(vector)
    return vectors


def _build_fixture_embeddings(root: Path) -> None:
    """20 `field:state` chunks in one tight, learnable density region, and
    15 `field:violence` chunks scattered as noise -- enough to exercise both
    a "tight" and a "noise" readiness call in the same corpus."""
    prose_dir = root / "data" / "vault" / "prose"
    tight_vectors = _tight_cluster_vectors(20, center=5.0)
    noise_vectors = _scattered_noise_vectors(15)
    for index, vector in enumerate(tight_vectors):
        _write_chunk_note(prose_dir, f"src1_{index:03d}_intro_001", vector, field_primary="state")
    for index, vector in enumerate(noise_vectors):
        _write_chunk_note(
            prose_dir, f"src2_{index:03d}_intro_001", vector, field_primary="violence"
        )

    envelopes_dir = root / "data" / "envelopes"
    envelopes_dir.mkdir(parents=True, exist_ok=True)
    result = _run_axial(root, "pin", "write", "baseline")
    assert result.returncode == 0, (
        f"fixture setup: `axial pin write baseline` failed\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    run_embed(
        vault_dir=root / "data" / "vault",
        embeddings_dir=root / "data" / "distill" / "embeddings.lance",
        manifest_path=root / "data" / "distill" / "embedding_manifest.json",
        evals_dir=root / "evals" / "corpus_pin",
        encoder=_fake_encoder,
    )


def _assert_ran_the_real_subcommand(result: subprocess.CompletedProcess) -> None:
    combined_output = result.stdout + result.stderr
    assert (
        "invalid choice" not in combined_output and "unrecognized arguments" not in combined_output
    ), (
        "expected a real 'axial distill readiness-map' run, not an argparse fallback -- "
        "this means the CLI subcommand does not exist yet:\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )


def test_readiness_map_splits_tight_tag_from_noise_tag_zero_llm_no_chunk_text(
    isolated_vault_root,
):
    root = isolated_vault_root
    _build_fixture_embeddings(root)

    result = _run_axial(root, "distill", "readiness-map")
    _assert_ran_the_real_subcommand(result)
    assert result.returncode == 0, (
        f"expected exit 0, got {result.returncode}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    manifest_path = root / "data" / "distill" / "readiness_manifest.json"
    assert manifest_path.is_file(), f"expected a readiness manifest at {manifest_path}"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["chunk_count"] == 35
    assert manifest["corpus_pin_id"] == "baseline"
    assert isinstance(manifest["vault_snapshot_hash"], str) and manifest["vault_snapshot_hash"]

    # -- zero LLM calls: AXIAL_LLM_PROVIDER=explode above would have crashed
    # the run had any text-generating call been attempted; exit 0 already
    # proves it, this just documents the intent.

    # -- the -1/noise route split, not cluster 0
    field_map = manifest["tag_axes"]["field_primary"]
    assert field_map["state"]["readiness"] == "tight", (
        f"expected the tightly-clustered 'state' tag to read as tight, got: {field_map['state']!r}"
    )
    assert field_map["state"]["dominant_cluster_id"] == 0, (
        "expected the first real cluster to be id 0 (HDBSCAN's own convention, "
        f"never relabelled), got: {field_map['state']!r}"
    )
    assert field_map["violence"]["readiness"] == "noise", (
        f"expected the scattered 'violence' tag to read as noise, got: {field_map['violence']!r}"
    )
    assert field_map["violence"]["noise_fraction"] == 1.0
    assert field_map["violence"]["dominant_cluster_id"] is None

    # -- cluster_assignments: every noise-labelled chunk is -1, never 0
    assignments = manifest["cluster_assignments"]
    noise_chunk_ids = [f"src2_{i:03d}_intro_001" for i in range(15)]
    for chunk_id in noise_chunk_ids:
        assert assignments[chunk_id] == -1, (
            f"expected {chunk_id} (scattered noise fixture point) to be labelled -1, "
            f"got {assignments[chunk_id]!r}"
        )
    assert set(assignments.values()) >= {-1, 0}, (
        f"expected both the noise label -1 and a real cluster starting at 0, "
        f"got labels: {sorted(set(assignments.values()))!r}"
    )

    # -- DEC-23: no source chunk_text anywhere in the emitted map
    manifest_text = json.dumps(manifest)
    for vector in _tight_cluster_vectors(20, center=5.0) + _scattered_noise_vectors(15):
        assert _vector_text(vector) not in manifest_text, (
            "DEC-23 violation: a fixture chunk_text sentinel leaked into the readiness manifest"
        )


def test_readiness_map_is_deterministic_across_reruns_over_the_same_embeddings(
    isolated_vault_root,
):
    root = isolated_vault_root
    _build_fixture_embeddings(root)

    first = _run_axial(root, "distill", "readiness-map")
    _assert_ran_the_real_subcommand(first)
    assert first.returncode == 0, f"stdout: {first.stdout!r}\nstderr: {first.stderr!r}"
    manifest_path = root / "data" / "distill" / "readiness_manifest.json"
    first_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    second = _run_axial(root, "distill", "readiness-map")
    assert second.returncode == 0, f"stdout: {second.stdout!r}\nstderr: {second.stderr!r}"
    second_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert first_manifest == second_manifest, (
        "expected an identical readiness manifest across two runs over the same "
        "unchanged embedding store -- the reduction+clustering step must be "
        f"deterministic given a pinned config, got first={first_manifest!r} vs "
        f"second={second_manifest!r}"
    )


def test_readiness_map_fails_loudly_without_persisted_embeddings(isolated_vault_root):
    root = isolated_vault_root
    (root / "data" / "envelopes").mkdir(parents=True, exist_ok=True)
    (root / "data" / "vault").mkdir(parents=True, exist_ok=True)
    result = _run_axial(root, "pin", "write", "baseline")
    assert result.returncode == 0, f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    # deliberately never run `axial distill embed`

    result = _run_axial(root, "distill", "readiness-map")
    _assert_ran_the_real_subcommand(result)

    assert result.returncode != 0, (
        f"expected a non-zero exit with no persisted embeddings, got 0\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    assert not (root / "data" / "distill" / "readiness_manifest.json").is_file()
    assert "embed" in result.stderr.lower(), (
        f"expected the failure to mention the missing embeddings, got stderr: {result.stderr!r}"
    )
