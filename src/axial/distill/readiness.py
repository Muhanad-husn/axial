"""Stage-5b: readiness map -- density clustering + the cluster-`-1` LLM
router (DEC-35, issue #297, plan `plans/phase-a-completion/README.md` stage
5b).

Clusters every persisted chunk embedding (5a, `axial.distill.embed`) with
HDBSCAN, over zero LLM spend, and emits a **readiness map**: per tag axis,
per tag value, whether that tag's chunks sit in a tight, learnable density
region or smear as noise. HDBSCAN's own `-1` label (never cluster `0`) *is*
the low-confidence tail this map marks as LLM-routed -- getting that split
backwards is the real bug the acceptance bar calls out, and this module
never relabels HDBSCAN's own output, so the library's own 0-indexed-clusters/
`-1`-is-noise convention passes straight through unchanged.

Feature engineering (DEC-35, ratified before this slice was written): HDBSCAN
degrades in raw high-dimensional embedding space (distance concentration), so
every vector is L2-normalised (cosine geometry), standardised, then reduced
with **PCA** before clustering -- PCA, never UMAP: UMAP is stochastic even
seeded across library versions (fights this repo's determinism contracts) and
DEC-35 scoped it to notebook-only visualization, which this module does not
build.

Three pinned constants, each a judgment call documented where it is defined
below (`DEFAULT_PCA_COMPONENTS`, `DEFAULT_MIN_CLUSTER_SIZE`,
`DEFAULT_READY_DOMINANT_SHARE`) -- no real embedding store exists in every
environment this module ships to, so these are reasoned starting points, not
numbers fit against the real corpus; 5c/5d re-examine them once
`data/distill/embeddings.lance` exists at corpus scale.

Reuses `axial.distill.embed`'s own LanceDB table (`TABLE_NAME`,
`METADATA_FILTER_KEYS`) as its read path, and
`axial.distill.staleness.resolve_current_pin` for the corpus-pin id/hash this
pass stamps onto its own output manifest -- the same DEC-35 provenance
convention `axial.distill.embed.run_embed` already established, not a second
mechanism.

`numpy`/`scikit-learn`/`hdbscan` (the `distill` dependency group, alongside
5a's `lancedb`/`sentence-transformers`) are imported lazily, inside the
functions that need them, never at module level -- importing this module
(e.g. from `axial.cli`) never requires any of them; only running the pass
does.

DEC-23: the readiness map carries `chunk_id`/cluster ids/tag values only --
never `chunk_text`. Nothing in this module ever reads a chunk's prose (the
persisted vector store itself never carries it either, per 5a).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from axial.distill.embed import DEFAULT_EMBEDDINGS_DIR, METADATA_FILTER_KEYS, TABLE_NAME
from axial.distill.staleness import resolve_current_pin
from axial.eval import corpus_pin as _corpus_pin

# The tag axes the readiness map reports on -- every flattened metadata
# column 5a's store carries except `source_id` (identifies the chunk's
# origin, not a tag axis that could ever "graduate" to a classifier).
TAG_AXES = sorted(METADATA_FILTER_KEYS - {"source_id"})

# HDBSCAN's own noise label -- NOT cluster 0. Never relabelled; kept as a
# named constant only so callers never have to remember the magic number.
NOISE_LABEL = -1

# Derived artifact, alongside 5a's embedding manifest under data/distill/
# (gitignored, DEC-23) -- this pass's own byproduct, not a committed
# contract like the corpus pin.
DEFAULT_MANIFEST_PATH = Path("data/distill/readiness_manifest.json")

# --- Pinned config (DEC-35: "the PCA dimensionality is your own
# measurement/judgment call") ------------------------------------------------
#
# DEFAULT_PCA_COMPONENTS: the default embedding model (5a,
# sentence-transformers/all-MiniLM-L6-v2) produces 384-dim vectors. 50 keeps
# the HDBSCAN input well below the source dimensionality (mitigating
# distance concentration, DEC-35's stated reason for reducing at all) while
# retaining enough structure for density estimation -- a commonly cited
# starting point for PCA-before-HDBSCAN pipelines. No real embedding store
# exists in this environment to tune this further; revisit empirically once
# `data/distill/embeddings.lance` holds the real corpus (5c/5d).
DEFAULT_PCA_COMPONENTS = 50

# DEFAULT_MIN_CLUSTER_SIZE: hdbscan's own library default is 5. The frozen
# corpus is expected at ~17k chunks (plan stage 4) across a handful of tag
# axes, so 5 would fragment into many spurious micro-clusters; 15 is a
# modest, single, unavoidable clustering-shape knob (every HDBSCAN call
# needs one) -- not fit against real data, revisit at 5c/5d.
DEFAULT_MIN_CLUSTER_SIZE = 15

# DEFAULT_READY_DOMINANT_SHARE: a tag value is "tight" when its single most
# common cluster (computed over ALL its chunks, noise included in the
# denominator, so a noisy tag can never look tight just because its few
# non-noise chunks happen to agree) accounts for at least this share. 0.5 --
# majority -- is the simplest threshold that means anything ("more chunks
# agree than disagree"); revisit against gold-parity data once 5c/5d can
# measure whether it actually predicts classifier trainability.
DEFAULT_READY_DOMINANT_SHARE = 0.5

ClusterFn = Callable[[list[list[float]]], list[int]]


class ReadinessError(Exception):
    """Base class for all readiness-map errors."""


class NoEmbeddingsToClusterError(ReadinessError):
    """Raised when `embeddings_dir` holds no persisted vector table -- 5b
    depends on 5a; running the readiness pass before `axial distill embed`
    is a misconfigured invocation, not a valid empty map."""

    def __init__(self, embeddings_dir: Path):
        self.embeddings_dir = embeddings_dir
        super().__init__(
            f"no persisted embeddings found at {embeddings_dir}; run `axial distill embed` first"
        )


class CorpusPinRequiredError(ReadinessError):
    """Raised when no corpus-pin manifest can be resolved (DEC-35: every
    stage-5 artifact records the pin it was built from) -- mirrors
    `axial.distill.embed.CorpusPinRequiredError`."""

    def __init__(self, cause: _corpus_pin.CorpusPinError):
        self.cause = cause
        super().__init__(
            f"readiness pass requires a corpus pin to record provenance against "
            f"({cause}); run `axial pin write <name>` first"
        )


@dataclass(frozen=True)
class ReadinessResult:
    """The outcome of one `run_readiness` call."""

    manifest_path: Path
    embeddings_dir: Path
    chunk_count: int
    cluster_count: int
    noise_count: int
    noise_fraction: float
    corpus_pin_id: str
    vault_snapshot_hash: str


def _default_cluster_fn(
    vectors: list[list[float]],
    *,
    pca_components: int = DEFAULT_PCA_COMPONENTS,
    min_cluster_size: int = DEFAULT_MIN_CLUSTER_SIZE,
) -> list[int]:
    """The real reduction + clustering pipeline (lazy imports -- see module
    docstring): L2-normalise (cosine geometry) -> standardise -> PCA (`svd_solver
    ="full"`, no randomised solver, so the reduction is deterministic given
    the same input, not merely seeded) -> HDBSCAN. Returns one integer label
    per input vector, in input order -- HDBSCAN's own labels, unrelabelled:
    `-1` is noise, real clusters start at `0`."""
    import hdbscan
    import numpy as np
    from sklearn.decomposition import PCA
    from sklearn.preprocessing import StandardScaler, normalize

    array = np.asarray(vectors, dtype=np.float64)
    array = normalize(array)
    array = StandardScaler().fit_transform(array)

    n_components = max(1, min(pca_components, array.shape[0], array.shape[1]))
    reduced = PCA(n_components=n_components, svd_solver="full", random_state=0).fit_transform(array)

    # `allow_single_cluster=True`: HDBSCAN's default cluster-selection method
    # only ever reports a cluster that is a genuine *child* branch of the
    # condensed tree, never the trivial root spanning the whole dataset --
    # so a corpus region that is tight but has no second, equally dense
    # region to split off against would otherwise read as 100% noise
    # (verified directly against this library version: a single isolated,
    # tightly-jittered blob with nothing else present returns all `-1`
    # without this flag). The readiness map's whole job is telling a tight
    # region from noise, so silently mislabeling a real one as noise for
    # want of a sibling cluster would be exactly the wrong failure mode.
    clusterer = hdbscan.HDBSCAN(min_cluster_size=min_cluster_size, allow_single_cluster=True)
    labels = clusterer.fit_predict(reduced)
    return [int(label) for label in labels]


def _load_embedding_rows(embeddings_dir: Path) -> list[dict[str, Any]]:
    """Every persisted row (`chunk_id`, `vector`, the flattened tag-axis
    metadata), sorted by `chunk_id` -- the same filesystem-order-never-leaks
    determinism convention `axial.distill.embed._load_chunk_records` uses."""
    embeddings_dir = Path(embeddings_dir)
    if not embeddings_dir.exists():
        raise NoEmbeddingsToClusterError(embeddings_dir)

    import lancedb

    db = lancedb.connect(embeddings_dir)
    if TABLE_NAME not in db.list_tables().tables:
        raise NoEmbeddingsToClusterError(embeddings_dir)
    rows = db.open_table(TABLE_NAME).to_arrow().to_pylist()
    if not rows:
        raise NoEmbeddingsToClusterError(embeddings_dir)
    rows.sort(key=lambda row: row["chunk_id"])
    return rows


def _build_readiness_map(
    rows: list[dict[str, Any]],
    labels: list[int],
    *,
    ready_dominant_share: float,
) -> dict[str, dict[str, dict[str, Any]]]:
    """Per axis (`TAG_AXES`), per non-empty tag value: total chunk count,
    noise count/fraction, the dominant cluster id/share (share computed over
    the tag's TOTAL chunk count, noise included -- so a tag that is mostly
    noise can never read as "tight" just because its handful of non-noise
    chunks happen to land in one cluster), and the resulting `"tight"` /
    `"noise"` readiness call. A missing/empty tag value (the flattened
    metadata's own `""` convention for "axis not set on this chunk",
    `axial.distill.embed._flatten_metadata`) is excluded -- there is no tag
    to report readiness for."""
    axes: dict[str, dict[str, dict[str, Any]]] = {}
    for axis in TAG_AXES:
        by_value: dict[str, dict[str, Any]] = {}
        for row, label in zip(rows, labels):
            value = row.get(axis) or ""
            if not value:
                continue
            entry = by_value.setdefault(value, {"total": 0, "noise_count": 0, "cluster_counts": {}})
            entry["total"] += 1
            if label == NOISE_LABEL:
                entry["noise_count"] += 1
            else:
                entry["cluster_counts"][label] = entry["cluster_counts"].get(label, 0) + 1

        axis_map: dict[str, Any] = {}
        for value, entry in sorted(by_value.items()):
            total = entry["total"]
            noise_count = entry["noise_count"]
            cluster_counts = entry["cluster_counts"]
            if cluster_counts:
                dominant_cluster_id, dominant_count = max(
                    cluster_counts.items(), key=lambda item: (item[1], -item[0])
                )
            else:
                dominant_cluster_id, dominant_count = None, 0
            dominant_cluster_share = dominant_count / total
            axis_map[value] = {
                "total": total,
                "noise_count": noise_count,
                "noise_fraction": noise_count / total,
                "dominant_cluster_id": dominant_cluster_id,
                "dominant_cluster_share": dominant_cluster_share,
                "readiness": (
                    "tight" if dominant_cluster_share >= ready_dominant_share else "noise"
                ),
            }
        axes[axis] = axis_map
    return axes


def run_readiness(
    embeddings_dir: Path | None = None,
    manifest_path: Path | None = None,
    pca_components: int = DEFAULT_PCA_COMPONENTS,
    min_cluster_size: int = DEFAULT_MIN_CLUSTER_SIZE,
    ready_dominant_share: float = DEFAULT_READY_DOMINANT_SHARE,
    evals_dir: Path | None = None,
    cluster_fn: ClusterFn | None = None,
) -> ReadinessResult:
    """Cluster every persisted chunk embedding under `embeddings_dir`
    (default `axial.distill.embed.DEFAULT_EMBEDDINGS_DIR`) and write the
    readiness map to `manifest_path` (default `DEFAULT_MANIFEST_PATH`): the
    corpus-pin provenance this pass was run against (DEC-35,
    `axial.distill.staleness.resolve_current_pin`), the pinned
    reduction/clustering config, corpus-wide cluster/noise counts, the
    per-axis/per-value readiness map (`_build_readiness_map`), and the full
    `chunk_id -> cluster_id` assignment (5c's own future cluster-stratified
    sampling reads this, per the plan) -- never `chunk_text` (DEC-23).

    `cluster_fn`, when given, replaces the default PCA+HDBSCAN pipeline
    (`_default_cluster_fn`) -- the seam this module's own inner unit tests
    use to exercise the manifest/readiness-map logic without a real
    reduction+clustering run, mirroring `axial.distill.embed`'s own
    `encoder` injection seam.

    Raises `NoEmbeddingsToClusterError` when no persisted embedding table is
    found, and `CorpusPinRequiredError` when no corpus pin can be resolved --
    both loud failures rather than a silently empty or misattributed map.
    """
    if embeddings_dir is None:
        embeddings_dir = DEFAULT_EMBEDDINGS_DIR
    embeddings_dir = Path(embeddings_dir)
    if manifest_path is None:
        manifest_path = DEFAULT_MANIFEST_PATH
    manifest_path = Path(manifest_path)

    try:
        pin = resolve_current_pin(evals_dir)
    except _corpus_pin.CorpusPinError as exc:
        raise CorpusPinRequiredError(exc) from exc

    rows = _load_embedding_rows(embeddings_dir)

    if cluster_fn is None:
        vectors = [row["vector"] for row in rows]
        labels = _default_cluster_fn(
            vectors, pca_components=pca_components, min_cluster_size=min_cluster_size
        )
    else:
        labels = cluster_fn([row["vector"] for row in rows])

    tag_map = _build_readiness_map(rows, labels, ready_dominant_share=ready_dominant_share)

    noise_count = sum(1 for label in labels if label == NOISE_LABEL)
    cluster_count = len({label for label in labels if label != NOISE_LABEL})
    chunk_count = len(rows)

    manifest = {
        "corpus_pin_id": pin["corpus_pin_id"],
        "vault_snapshot_hash": pin["vault_snapshot_hash"],
        "chunk_count": chunk_count,
        "cluster_count": cluster_count,
        "noise_count": noise_count,
        "noise_fraction": noise_count / chunk_count,
        "config": {
            "pca_components": pca_components,
            "min_cluster_size": min_cluster_size,
            "ready_dominant_share": ready_dominant_share,
        },
        "tag_axes": tag_map,
        "cluster_assignments": {row["chunk_id"]: label for row, label in zip(rows, labels)},
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    return ReadinessResult(
        manifest_path=manifest_path,
        embeddings_dir=embeddings_dir,
        chunk_count=chunk_count,
        cluster_count=cluster_count,
        noise_count=noise_count,
        noise_fraction=noise_count / chunk_count,
        corpus_pin_id=pin["corpus_pin_id"],
        vault_snapshot_hash=pin["vault_snapshot_hash"],
    )
