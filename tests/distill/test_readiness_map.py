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
-- lets this test place chunks at known, deterministic coordinates and still
run the REAL default PCA+HDBSCAN pipeline (`_default_cluster_fn`, the
`leaf`/`min_samples`/PCA-93 config #358's real-corpus validation pinned) as
a subprocess against a real LanceDB store, without downloading a sentence-
transformer model.

Fixture shape -- why two dense blobs, not "one tight + scattered noise"
-----------------------------------------------------------------------
`cluster_selection_method="leaf"` (see `_default_cluster_fn`'s own docstring)
never reports even a single, perfectly tight density region as a cluster
unless the dataset has at least one OTHER, similarly dense region for the
condensed tree to branch against -- confirmed directly while building this
fixture (an isolated tight blob with nothing else present reads 100% noise
under `leaf`, regardless of `allow_single_cluster`). Two deterministic
Gaussian blobs (`numpy.random.RandomState`, fixed seeds -- reproducible,
not flaky) give the tree real structure to branch on; a third, small,
diffuse group demonstrates the noise route directly. Exact expected labels
were verified directly against this real pipeline before being hardcoded
below (see the PR body for the derivation).
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import numpy as np
import pytest

lancedb = pytest.importorskip("lancedb")
pytest.importorskip("sentence_transformers")
pytest.importorskip("hdbscan")
pytest.importorskip("sklearn")

from axial.distill.embed import run_embed  # noqa: E402
from axial.vault import render_note  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

PROVIDER_ENV_VAR = "AXIAL_LLM_PROVIDER"

VECTOR_DIM = 100


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


def _blob_vectors(n: int, center: float, std: float, seed: int) -> list[list[float]]:
    """`n` points drawn from a fixed-seed Gaussian (`numpy.random.RandomState`
    -- deterministic and reproducible across runs/machines, not a live
    random draw) around `(center, ..., center)` in `VECTOR_DIM` dimensions."""
    return np.random.RandomState(seed).normal(loc=center, scale=std, size=(n, VECTOR_DIM)).tolist()


# Two well-separated, tight Gaussian blobs (35 + 25 points) give the real
# PCA+HDBSCAN pipeline a genuine multi-region tree to branch on (see the
# module docstring's "Fixture shape" note); a third, small, diffuse group
# (14 points) demonstrates the noise route. Every count/seed/std below was
# chosen and then verified directly against `_default_cluster_fn` at the
# real, pinned production config (PCA=93, mcs=15, ms=5, leaf) before the
# expected labels were hardcoded into the tests below.
CLUSTER_A_VECTORS = _blob_vectors(35, center=5.0, std=0.1, seed=1)  # -> field:state
CLUSTER_B_VECTORS = _blob_vectors(25, center=-5.0, std=0.1, seed=2)  # -> field:violence
SCATTERED_VECTORS = _blob_vectors(14, center=0.0, std=1.0, seed=0)  # -> field:conflict


def _build_fixture_embeddings(root: Path) -> None:
    """35 `field:state` chunks and 25 `field:violence` chunks, each its own
    tight, learnable density region, plus 14 `field:conflict` chunks
    scattered near the origin -- mostly (but, realistically, not perfectly)
    routed to noise. Exercises a real "tight" readiness call on real
    PCA+HDBSCAN output, and real `-1` noise labels in the same corpus."""
    prose_dir = root / "data" / "vault" / "prose"
    for index, vector in enumerate(CLUSTER_A_VECTORS):
        _write_chunk_note(prose_dir, f"src1_{index:03d}_intro_001", vector, field_primary="state")
    for index, vector in enumerate(CLUSTER_B_VECTORS):
        _write_chunk_note(
            prose_dir, f"src2_{index:03d}_intro_001", vector, field_primary="violence"
        )
    for index, vector in enumerate(SCATTERED_VECTORS):
        _write_chunk_note(
            prose_dir, f"src3_{index:03d}_intro_001", vector, field_primary="conflict"
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

    assert manifest["chunk_count"] == 74
    assert manifest["corpus_pin_id"] == "baseline"
    assert isinstance(manifest["vault_snapshot_hash"], str) and manifest["vault_snapshot_hash"]

    # -- zero LLM calls: AXIAL_LLM_PROVIDER=explode above would have crashed
    # the run had any text-generating call been attempted; exit 0 already
    # proves it, this just documents the intent.

    # -- both real, well-separated blobs are found whole, as their own
    # cluster, starting at id 0 -- not cluster 0 vs 1 confused with noise.
    field_map = manifest["tag_axes"]["field_primary"]
    assert field_map["state"] == {
        "total": 35,
        "noise_count": 0,
        "noise_fraction": 0.0,
        "dominant_cluster_id": 0,
        "dominant_cluster_share": 1.0,
        "readiness": "tight",
    }, (
        f"expected the 'state' blob to read as a single, whole, tight cluster, got: {field_map['state']!r}"
    )
    assert field_map["violence"] == {
        "total": 25,
        "noise_count": 0,
        "noise_fraction": 0.0,
        "dominant_cluster_id": 1,
        "dominant_cluster_share": 1.0,
        "readiness": "tight",
    }, (
        f"expected the 'violence' blob to read as a single, whole, tight cluster, got: "
        f"{field_map['violence']!r}"
    )

    # -- the scattered 'conflict' tag: mostly noise-routed (9/14 chunks are
    # -1) yet the handful that DID land in a real cluster all agree, so it
    # still reads "tight" -- a real demonstration, on real pipeline output,
    # of the founder-approved orthogonal semantics (#358): noise_fraction
    # ("how much is LLM-routed") and dominant_cluster_share ("how
    # concentrated is the part that isn't") are independent numbers.
    assert field_map["conflict"] == {
        "total": 14,
        "noise_count": 9,
        "noise_fraction": 9 / 14,
        "dominant_cluster_id": 1,
        "dominant_cluster_share": 0.6,
        "readiness": "tight",
    }, (
        f"expected the 'conflict' tag's exact, previously-verified split, got: {field_map['conflict']!r}"
    )

    # -- the -1/noise route split, not cluster 0: real noise labels exist,
    # and every real cluster id present starts at 0 (never offset by one).
    assignments = manifest["cluster_assignments"]
    assert manifest["noise_count"] == 9
    assert manifest["cluster_count"] == 2
    assert set(assignments.values()) == {-1, 0, 1}, (
        f"expected exactly the noise label -1 and two real clusters starting at 0, "
        f"got labels: {sorted(set(assignments.values()))!r}"
    )
    assert assignments["src1_000_intro_001"] == 0
    assert assignments["src2_000_intro_001"] == 1

    # -- DEC-23: no source chunk_text anywhere in the emitted map
    manifest_text = json.dumps(manifest)
    for vector in CLUSTER_A_VECTORS + CLUSTER_B_VECTORS + SCATTERED_VECTORS:
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
