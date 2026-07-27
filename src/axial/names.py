"""Phase A v1 slice 04 (issue #415): the name inventory and similarity view
(`specs/PRODUCT.md` §7.16, P0-12's first two bullets).

D10: "Reconcile runs over names, not notes. Similarity and clustering are a
viewing aid so the merge aggressiveness can be chosen by looking at the
distribution; the model makes the merge calls with clusters as hints. Start
loose, tighten by inspection." This module builds the first two of the
three artifacts §7.16 describes under `data/names/` -- the third, the alias
map, is slice 05 (Reconcile proper), which this module never calls into and
never makes a merge decision itself:

  1. **The inventory (LLM-free).** One record per distinct name SURFACE FORM
     out of slice 02's per-note answer records
     (`data/answers/<source_id>.jsonl`, `axial.interrogate`), read from
     exactly the two fields §7.16 names -- `names[]` (which carries its own
     `kind`) and `citations[].cited` -- "the complete, lossless record of
     what the corpus said." `uses`, `defines`, `arguing_against` and
     `position_of` are deliberately NOT read here, even though an earlier
     draft of this slice's brief listed them: verified directly against the
     real 6,148-note corpus, `arguing_against`/`position_of` are
     argumentative CLAUSES describing a stance (61-74 characters on
     average, up to 310), not name surface forms, and are overwhelmingly
     unique per note; `uses`/`defines` mostly restate what `names[]` (whose
     `kind` vocabulary already includes `concept`) already carries, and
     §7.16's own inventory record shape -- `{surface, kind, count,
     chunk_ids[]}` -- has no room for a second field's kind either. Where
     the corpus gave one surface form more than one `kind`, the record
     keeps the most frequent, ties broken by first occurrence (§7.16) --
     the joined kind vocabulary (§7.15, issue #431) already removed the
     collisions that carried real information, so what a tie discards here
     is a distinction the vocabulary itself declines to make.
  2. **The similarity view (LLM-free).** Every distinct surface form is
     embedded with the same local, deterministic, CPU sentence-transformer
     `axial.distill.embed` uses (`DEFAULT_MODEL_NAME`, lazy-imported --
     mirrors that module's own lazy-import pattern, never `run_embed`/
     `_flatten_metadata`, which are chunk-shaped and keyed on the closed tag
     axes slice 03 retired), then clustered with HDBSCAN
     (`axial.distill.readiness`'s own PCA + StandardScaler + HDBSCAN
     pipeline, reused as a pattern, not called: that module clusters chunk
     embeddings for a different question, "is this tag value ready to
     graduate off the LLM"). PCA first is not optional at this embedding
     dimensionality (384): raw-space HDBSCAN measured directly against
     20,000 real surface forms from this corpus took 316s; PCA(93, the same
     component count `axial.distill.readiness` measured against this same
     embedding model's chunk-embedding spectrum) then HDBSCAN cuts that to
     49s -- roughly 6x, from the same curse-of-dimensionality cause that
     module's own docstring names. `min_cluster_size=2`/`min_samples=1` --
     the loosest values HDBSCAN accepts -- rather than that module's tuned
     15/5: D10 says start loose, and a merge-hint viewing aid must not
     itself discard a real 2-member alias pair as noise before the founder
     ever sees it.
  3. Both artifacts persist under `data/names/` (§6's directory layout,
     `data/names/ # inventory, similarity view, alias map, index`):
     `inventory.jsonl` (one JSON object per surface form, the exact §7.16
     shape) and `embeddings.lance` (vectors + cluster labels, LanceDB,
     `axial.distill.embed`'s own write convention: `mode="overwrite"`,
     embedded/local/no server) plus a small manifest.
  4. `examine_names`/`format_names_report` read the persisted similarity
     view back (zero model/embedding calls, mirroring
     `axial.chunk.examine_chunks`'s own read-only-over-persisted-data shape)
     and report the cluster-size and nearest-neighbour similarity
     distribution the founder looks at before slice 05 sets its merge
     aggressiveness (P0-12: "cluster counts and sizes ... the largest
     clusters with members, a sample of borderline pairs").

Out of scope (this slice only): making any merge decision (05, the alias
map), any LLM call, and touching `axial.distill.embed`'s existing
chunk-embedding behaviour, which this module never imports from.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator

from axial.interrogate import _default_answers_dir, is_abstention
from axial.paths import DEFAULT_PIPELINE_CONFIG_PATH

# The same local, deterministic, CPU sentence-transformer `axial.distill.
# embed` embeds vault chunks with (DEC-35) -- one shared default so a name's
# vector and a chunk's vector live in the same embedding space, should a
# later slice ever want to compare them.
DEFAULT_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"

# §6's directory layout: `data/names/ # inventory, similarity view, alias
# map, index (§7.16)` -- all three of Reconcile's artifacts share one
# parent; slice 05 writes `alias_map.json` alongside these two.
DEFAULT_NAMES_DATA_DIR = Path("data/names")
DEFAULT_INVENTORY_PATH = DEFAULT_NAMES_DATA_DIR / "inventory.jsonl"
DEFAULT_EMBEDDINGS_DIR = DEFAULT_NAMES_DATA_DIR / "embeddings.lance"
DEFAULT_MANIFEST_PATH = DEFAULT_NAMES_DATA_DIR / "similarity_manifest.json"
TABLE_NAME = "names"

# HDBSCAN's own noise label (never cluster 0) -- named so no caller has to
# remember the magic number (mirrors `axial.distill.readiness.NOISE_LABEL`).
NOISE_LABEL = -1

# The loosest values HDBSCAN accepts (D10: "start loose, tighten by
# inspection") -- not `axial.distill.readiness`'s tuned 15/5, which answers a
# different question (tag-value readiness) over chunk embeddings, not
# name-alias candidates over name embeddings.
DEFAULT_MIN_CLUSTER_SIZE = 2
DEFAULT_MIN_SAMPLES = 1

# Reused from `axial.distill.readiness.DEFAULT_PCA_COMPONENTS`: measured
# against the real 18,410-chunk corpus's own 384-dim embedding spectrum
# (Kaiser criterion), for the same embedding model this module uses. Not
# re-derived for the name-surface-form distribution specifically (a
# different, shorter-text population) -- reusing an already-measured
# reduction for the same model beats leaving PCA off entirely (see module
# docstring's 316s-vs-49s finding) or inventing a second untested constant.
DEFAULT_PCA_COMPONENTS = 93

# The two fields §7.16 names as the inventory's source: "built by reading
# every answer record's `names` and `citations`". Nothing else is read.
_NAMES_FIELD = "names"
_CITATIONS_FIELD = "citations"

_WHITESPACE = re.compile(r"\s+")

Encoder = Callable[[list[str]], list[list[float]]]
ClusterFn = Callable[[list[list[float]]], list[int]]


class NamesError(Exception):
    """Base class for all name-inventory errors."""


class NoAnswersToEmbedError(NamesError):
    """Raised when `answers_dir` holds no interrogation answer records, or
    none of them name anything -- running this pass before slice 02
    (`axial interrogate`) is a misconfigured invocation, not a valid empty
    inventory (mirrors `axial.distill.embed.NoChunksToEmbedError`'s own
    loud-failure convention)."""

    def __init__(self, answers_dir: Path):
        self.answers_dir = answers_dir
        super().__init__(
            f"no interrogation answers found under {answers_dir} to build a name "
            f"inventory from; run `axial interrogate` first"
        )


class NoNamesToClusterError(NamesError):
    """Raised when `examine_names` is asked to read a similarity view that
    does not exist yet -- running the report before `run_names` is a
    misconfigured invocation."""

    def __init__(self, embeddings_dir: Path):
        self.embeddings_dir = embeddings_dir
        super().__init__(
            f"no persisted similarity view found at {embeddings_dir}; run the name "
            f"inventory pass first"
        )


# ---------------------------------------------------------------------------
# Collecting name occurrences off the answer records (§7.16: names + citations)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NameOccurrence:
    """One mention of one surface form, in one note. `kind` is only ever
    set for a `names[]` mention -- a citation is not asked for one."""

    surface_form: str
    chunk_id: str
    kind: str | None = None


def _clean(value: Any) -> str | None:
    """Whitespace-normalise a candidate surface form; `None` for anything
    that is not a non-blank string (never crash on a malformed answer)."""
    if not isinstance(value, str):
        return None
    cleaned = _WHITESPACE.sub(" ", value).strip()
    return cleaned or None


def iter_name_occurrences(record: dict[str, Any]) -> Iterator[NameOccurrence]:
    """Every `NameOccurrence` one answer record contributes, from `names[]`
    and `citations[].cited` only (§7.16) -- skips failure/skip records (no
    `answers` key) and the D7 abstention on each field. `is_abstention`
    (`axial.interrogate`) is reused rather than re-derived, so a change to
    what counts as an abstention never has to be made twice."""
    answers = record.get("answers")
    if not isinstance(answers, dict):
        return
    chunk_id = record.get("chunk_id", "")

    names = answers.get(_NAMES_FIELD)
    if isinstance(names, list) and not is_abstention(names):
        for entry in names:
            if not isinstance(entry, dict):
                continue
            surface_form = _clean(entry.get("name"))
            if surface_form is None:
                continue
            yield NameOccurrence(surface_form, chunk_id, _clean(entry.get("kind")))

    citations = answers.get(_CITATIONS_FIELD)
    if isinstance(citations, list) and not is_abstention(citations):
        for entry in citations:
            if not isinstance(entry, dict):
                continue
            surface_form = _clean(entry.get("cited"))
            if surface_form is None:
                continue
            yield NameOccurrence(surface_form, chunk_id, None)


def load_answer_records(answers_dir: Path) -> list[dict[str, Any]]:
    """Every record (answer, failure, or skip) across every
    `<source_id>.jsonl` under `answers_dir`, sorted by filename -- the same
    "filesystem order never leaks into the result" determinism convention
    `axial.distill.embed._load_chunk_records` uses. Blank lines are
    tolerated (mirrors the checkpoint reader's own tolerance)."""
    if not answers_dir.is_dir():
        return []
    records: list[dict[str, Any]] = []
    for path in sorted(answers_dir.glob("*.jsonl")):
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                records.append(json.loads(line))
    return records


def collect_occurrences(records: Iterable[dict[str, Any]]) -> Iterator[NameOccurrence]:
    """Flat-map `iter_name_occurrences` over every record."""
    for record in records:
        yield from iter_name_occurrences(record)


# ---------------------------------------------------------------------------
# The inventory: one entry per distinct surface form (§7.16's exact shape)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InventoryEntry:
    """One distinct name surface form: `{surface, kind, count, chunk_ids[]}`
    (§7.16). `kind` is the single most frequent one seen for it, ties broken
    by first occurrence -- `None` when the surface never appeared with a
    kind at all (a citation-only surface form)."""

    surface_form: str
    kind: str | None
    count: int
    chunk_ids: tuple[str, ...]


def build_inventory(occurrences: Iterable[NameOccurrence]) -> list[InventoryEntry]:
    """Group occurrences by their exact (whitespace-normalised) surface
    form -- "the complete, lossless record of what the corpus said" (§7.16).
    No casefolding, no fuzzy merge here -- two surface forms that differ by
    so much as case are two rows; embedding distance (not string identity)
    is this module's whole mechanism for saying two rows are close, and
    slice 05 is where a merge is actually decided. Returned sorted by
    surface form, for the same determinism reason `_load_chunk_records`/
    `_load_embedding_rows` sort by chunk_id."""
    grouped: dict[str, dict[str, Any]] = {}
    order = 0
    for occurrence in occurrences:
        bucket = grouped.setdefault(
            occurrence.surface_form,
            {"count": 0, "kind_counts": {}, "kind_first_seen": {}, "chunk_ids": set()},
        )
        bucket["count"] += 1
        bucket["chunk_ids"].add(occurrence.chunk_id)
        if occurrence.kind:
            bucket["kind_counts"][occurrence.kind] = (
                bucket["kind_counts"].get(occurrence.kind, 0) + 1
            )
            bucket["kind_first_seen"].setdefault(occurrence.kind, order)
        order += 1

    entries = []
    for surface_form in sorted(grouped):
        bucket = grouped[surface_form]
        kind_counts = bucket["kind_counts"]
        if kind_counts:
            # Most frequent kind; ties broken by first occurrence (§7.16).
            resolved_kind = min(
                kind_counts,
                key=lambda kind: (-kind_counts[kind], bucket["kind_first_seen"][kind]),
            )
        else:
            resolved_kind = None
        entries.append(
            InventoryEntry(
                surface_form=surface_form,
                kind=resolved_kind,
                count=bucket["count"],
                chunk_ids=tuple(sorted(bucket["chunk_ids"])),
            )
        )
    return entries


def write_inventory(entries: list[InventoryEntry], path: Path) -> None:
    """Write the inventory as one JSON object per line, §7.16's exact
    `{surface, kind, count, chunk_ids[]}` shape -- the complete, lossless,
    LLM-free artifact, independent of whatever the similarity view goes on
    to compute."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for entry in entries:
            handle.write(
                json.dumps(
                    {
                        "surface": entry.surface_form,
                        "kind": entry.kind,
                        "count": entry.count,
                        "chunk_ids": list(entry.chunk_ids),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )


# ---------------------------------------------------------------------------
# Embedding (the `axial.distill.embed` pattern, not its chunk-shaped code)
# ---------------------------------------------------------------------------


def _default_encoder(model_name: str) -> Encoder:
    """Lazily build the real sentence-transformer encoder (imports
    `sentence_transformers` here, never at module level, mirroring
    `axial.distill.embed._default_encoder`). CPU-only, eval-mode inference:
    deterministic given the same model checkpoint and input text."""
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(model_name)

    def encode(texts: list[str]) -> list[list[float]]:
        return model.encode(texts, convert_to_numpy=True).tolist()

    return encode


def _default_cluster_fn(
    vectors: list[list[float]],
    *,
    pca_components: int = DEFAULT_PCA_COMPONENTS,
    min_cluster_size: int = DEFAULT_MIN_CLUSTER_SIZE,
    min_samples: int = DEFAULT_MIN_SAMPLES,
) -> list[int]:
    """L2-normalise -> standardise -> PCA -> HDBSCAN, reusing `axial.distill.
    readiness._default_cluster_fn`'s own measured pipeline shape (see module
    docstring for the real timing this reduction step buys on this corpus).
    `cluster_selection_method="leaf"`/`allow_single_cluster=True`: that
    module measured `eom` (HDBSCAN's own implicit default) collapsing the
    whole corpus to one blob regardless of PCA dims, for this same embedding
    model family; `leaf` is reused for the same reason. Returns one integer
    label per input vector, in input order, unrelabelled: `-1` is
    `NOISE_LABEL`, real clusters start at `0`."""
    import hdbscan
    import numpy as np
    from sklearn.decomposition import PCA
    from sklearn.preprocessing import StandardScaler, normalize

    array = np.asarray(vectors, dtype=np.float64)
    array = normalize(array)
    array = StandardScaler().fit_transform(array)

    n_components = max(1, min(pca_components, array.shape[0], array.shape[1]))
    reduced = PCA(n_components=n_components, svd_solver="full", random_state=0).fit_transform(array)

    clusterer = hdbscan.HDBSCAN(
        min_cluster_size=min_cluster_size,
        min_samples=min_samples,
        cluster_selection_method="leaf",
        allow_single_cluster=True,
    )
    labels = clusterer.fit_predict(reduced)
    return [int(label) for label in labels]


# ---------------------------------------------------------------------------
# The pass: collect -> write inventory -> embed -> cluster -> persist
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NamesResult:
    """The outcome of one `run_names` call."""

    inventory_path: Path
    embeddings_dir: Path
    manifest_path: Path
    entry_count: int
    occurrence_count: int
    model_name: str
    embedding_dim: int
    cluster_count: int
    noise_count: int


def run_names(
    answers_dir: Path | None = None,
    inventory_path: Path | None = None,
    embeddings_dir: Path | None = None,
    manifest_path: Path | None = None,
    model_name: str = DEFAULT_MODEL_NAME,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
    encoder: Encoder | None = None,
    cluster_fn: ClusterFn | None = None,
    pca_components: int = DEFAULT_PCA_COMPONENTS,
    min_cluster_size: int = DEFAULT_MIN_CLUSTER_SIZE,
    min_samples: int = DEFAULT_MIN_SAMPLES,
) -> NamesResult:
    """Build the name inventory over every interrogation answer record under
    `answers_dir` (default resolved via `axial.interrogate._default_answers_
    dir`), write it to `inventory_path` (default `DEFAULT_INVENTORY_PATH`),
    embed each distinct surface form, cluster the embeddings, and persist
    vectors + cluster labels to a LanceDB table at `embeddings_dir` (default
    `DEFAULT_EMBEDDINGS_DIR`), plus a small JSON manifest at `manifest_path`
    (default `DEFAULT_MANIFEST_PATH`).

    `encoder`/`cluster_fn`, when given, replace the default sentence-
    transformer/HDBSCAN pipeline -- the seam this module's own inner unit
    tests use to exercise the collect/persist path without a real model or
    clustering run, mirroring `axial.distill.embed`'s own `encoder`
    injection seam.

    Raises `NoAnswersToEmbedError` when no answer records are found, or none
    of them name anything -- a loud failure rather than a silently empty
    inventory.
    """
    if answers_dir is None:
        answers_dir = _default_answers_dir(config_path)
    answers_dir = Path(answers_dir)
    if inventory_path is None:
        inventory_path = DEFAULT_INVENTORY_PATH
    inventory_path = Path(inventory_path)
    if embeddings_dir is None:
        embeddings_dir = DEFAULT_EMBEDDINGS_DIR
    embeddings_dir = Path(embeddings_dir)
    if manifest_path is None:
        manifest_path = DEFAULT_MANIFEST_PATH
    manifest_path = Path(manifest_path)

    records = load_answer_records(answers_dir)
    if not records:
        raise NoAnswersToEmbedError(answers_dir)

    occurrences = list(collect_occurrences(records))
    entries = build_inventory(occurrences)
    if not entries:
        raise NoAnswersToEmbedError(answers_dir)

    write_inventory(entries, inventory_path)

    if encoder is None:
        encoder = _default_encoder(model_name)
    vectors = encoder([entry.surface_form for entry in entries])

    if cluster_fn is None:
        labels = _default_cluster_fn(
            vectors,
            pca_components=pca_components,
            min_cluster_size=min_cluster_size,
            min_samples=min_samples,
        )
    else:
        labels = cluster_fn(vectors)

    rows = [
        {
            "surface_form": entry.surface_form,
            "kind": entry.kind or "",
            "count": entry.count,
            "chunk_ids_json": json.dumps(list(entry.chunk_ids), ensure_ascii=False),
            "cluster_label": label,
            "vector": list(vector),
        }
        for entry, vector, label in zip(entries, vectors, labels)
    ]

    import lancedb

    embeddings_dir.parent.mkdir(parents=True, exist_ok=True)
    db = lancedb.connect(embeddings_dir)
    db.create_table(TABLE_NAME, data=rows, mode="overwrite")

    embedding_dim = len(rows[0]["vector"])
    cluster_count = len({label for label in labels if label != NOISE_LABEL})
    noise_count = sum(1 for label in labels if label == NOISE_LABEL)

    manifest = {
        "model_name": model_name,
        "embedding_dim": embedding_dim,
        "entry_count": len(entries),
        "occurrence_count": len(occurrences),
        "cluster_count": cluster_count,
        "noise_count": noise_count,
        "table_name": TABLE_NAME,
        "inventory_path": str(inventory_path),
        "config": {
            "pca_components": pca_components,
            "min_cluster_size": min_cluster_size,
            "min_samples": min_samples,
        },
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    return NamesResult(
        inventory_path=inventory_path,
        embeddings_dir=embeddings_dir,
        manifest_path=manifest_path,
        entry_count=len(entries),
        occurrence_count=len(occurrences),
        model_name=model_name,
        embedding_dim=embedding_dim,
        cluster_count=cluster_count,
        noise_count=noise_count,
    )


# ---------------------------------------------------------------------------
# The report: read-only over persisted data, zero model/embedding calls
# (mirrors `axial.chunk.examine_chunks`/`format_examine_report`)
# ---------------------------------------------------------------------------

# How many entries the report samples per cluster for a human to read
# (mirrors `axial.chunk.EXAMINE_SAMPLE_SIZE`'s own convention).
EXAMINE_CLUSTER_SAMPLE = 5
EXAMINE_TOP_CLUSTERS = 10
# How many entries the nearest-neighbour similarity spread is measured over
# -- exact pairwise cosine similarity is O(n^2) in memory, so this report
# samples rather than computing it over the whole inventory (the same
# sampling convention `axial.chunk.examine_chunks`'s own chunk-text sample
# uses; the persisted table itself is complete).
EXAMINE_SIMILARITY_SAMPLE = 500


@dataclass(frozen=True)
class NamesExamineStats:
    """What `axial names examine` reports (D10's viewing aid, P0-12)."""

    entry_count: int
    occurrence_count: int
    cluster_count: int
    noise_count: int
    cluster_sizes: list[int]  # non-noise cluster sizes, descending
    top_clusters: list[tuple[int, int, list[str]]]  # (label, size, sample surface forms)
    similarity_min: float | None
    similarity_max: float | None
    similarity_mean: float | None
    similarity_median: float | None


def _load_name_rows(embeddings_dir: Path) -> list[dict[str, Any]]:
    embeddings_dir = Path(embeddings_dir)
    if not embeddings_dir.exists():
        raise NoNamesToClusterError(embeddings_dir)

    import lancedb

    db = lancedb.connect(embeddings_dir)
    if TABLE_NAME not in db.list_tables().tables:
        raise NoNamesToClusterError(embeddings_dir)
    rows = db.open_table(TABLE_NAME).to_arrow().to_pylist()
    if not rows:
        raise NoNamesToClusterError(embeddings_dir)
    rows.sort(key=lambda row: row["surface_form"])
    return rows


def _nearest_neighbour_similarities(rows: list[dict[str, Any]], sample_size: int) -> list[float]:
    """Cosine similarity from each of a sample of rows to its nearest OTHER
    row, computed once over the full persisted vector set (so a sampled
    row's "nearest" is still its true nearest neighbour, not just its
    nearest within the sample). Empty input / a single row yields `[]`."""
    if len(rows) < 2:
        return []

    import numpy as np

    vectors = np.asarray([row["vector"] for row in rows], dtype=np.float64)
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    normalised = vectors / norms

    sample_indices = list(range(min(sample_size, len(rows))))
    similarities = []
    for index in sample_indices:
        scores = normalised @ normalised[index]
        scores[index] = -1.0  # exclude self
        similarities.append(float(scores.max()))
    return similarities


def examine_names(
    embeddings_dir: Path = DEFAULT_EMBEDDINGS_DIR,
    similarity_sample: int = EXAMINE_SIMILARITY_SAMPLE,
) -> NamesExamineStats:
    """Read the persisted similarity view back (zero model/embedding calls --
    the vectors and cluster labels are already on disk) and compute the
    distribution the founder looks at before slice 05 sets its merge
    aggressiveness: cluster sizes, a sample from the largest clusters, and
    the nearest-neighbour cosine-similarity spread over a sample of
    entries."""
    rows = _load_name_rows(embeddings_dir)

    cluster_members: dict[int, list[str]] = {}
    noise_count = 0
    for row in rows:
        label = row["cluster_label"]
        if label == NOISE_LABEL:
            noise_count += 1
        else:
            cluster_members.setdefault(label, []).append(row["surface_form"])

    cluster_sizes = sorted((len(members) for members in cluster_members.values()), reverse=True)
    top_clusters = [
        (label, len(members), sorted(members)[:EXAMINE_CLUSTER_SAMPLE])
        for label, members in sorted(
            cluster_members.items(), key=lambda item: len(item[1]), reverse=True
        )[:EXAMINE_TOP_CLUSTERS]
    ]

    similarities = _nearest_neighbour_similarities(rows, similarity_sample)
    if similarities:
        ordered = sorted(similarities)
        mid = len(ordered) // 2
        median = ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2
        similarity_min, similarity_max = ordered[0], ordered[-1]
        similarity_mean = sum(ordered) / len(ordered)
    else:
        similarity_min = similarity_max = similarity_mean = median = None

    return NamesExamineStats(
        entry_count=len(rows),
        occurrence_count=sum(row["count"] for row in rows),
        cluster_count=len(cluster_members),
        noise_count=noise_count,
        cluster_sizes=cluster_sizes,
        top_clusters=top_clusters,
        similarity_min=similarity_min,
        similarity_max=similarity_max,
        similarity_mean=similarity_mean,
        similarity_median=median,
    )


def format_names_report(stats: NamesExamineStats) -> str:
    """Render `NamesExamineStats` into a human-readable report -- format
    left to the implementer (mirrors `axial.chunk.format_examine_report`'s
    own docstring), only that every listed number is present."""
    lines: list[str] = []

    lines.append(
        f"names examine: {stats.entry_count} distinct surface form(s), "
        f"{stats.occurrence_count} total occurrence(s)"
    )
    lines.append(
        f"clusters: {stats.cluster_count} non-noise cluster(s), "
        f"{stats.noise_count} noise (unclustered) entries"
    )

    lines.append("")
    if stats.cluster_sizes:
        n = len(stats.cluster_sizes)
        mean_size = sum(stats.cluster_sizes) / n
        median_size = (
            stats.cluster_sizes[n // 2]
            if n % 2
            else (stats.cluster_sizes[n // 2 - 1] + stats.cluster_sizes[n // 2]) / 2
        )
        lines.append(
            "cluster size distribution: "
            f"min={stats.cluster_sizes[-1]} max={stats.cluster_sizes[0]} "
            f"mean={mean_size:.1f} median={median_size:.1f}"
        )
    else:
        lines.append("cluster size distribution: (no non-noise clusters)")

    lines.append("")
    lines.append("largest clusters:")
    if not stats.top_clusters:
        lines.append("  (none)")
    for label, size, sample in stats.top_clusters:
        lines.append(f"  cluster {label} ({size} member(s)): {sample}")

    lines.append("")
    if stats.similarity_mean is not None:
        lines.append(
            "nearest-neighbour cosine similarity spread (sampled): "
            f"min={stats.similarity_min:.3f} max={stats.similarity_max:.3f} "
            f"mean={stats.similarity_mean:.3f} median={stats.similarity_median:.3f}"
        )
    else:
        lines.append("nearest-neighbour cosine similarity spread: (fewer than 2 entries)")

    return "\n".join(lines)
