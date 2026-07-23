"""Stage-5a: embedding pass + vector store (DEC-35, issue #296, plan
`plans/phase-a-completion/README.md` stage 5a).

Embeds every prose chunk in the frozen vault ONCE, via a local
sentence-transformer (deterministic, CPU, no per-call cost -- DEC-35), and
persists the vectors in LanceDB (embedded, local, no server process --
DEC-35) keyed by `chunk_id`, alongside a flat metadata projection every
downstream stage-5 mechanism (5b's clustering, 5c's stratified sampling,
5c/5e's oversampler/drift-monitor nearest-neighbour lookups) filters on:
`source_id` and each single-valued tag axis's own scalar. `chunk_text` is
read from the vault only long enough to embed it, then discarded -- never
persisted in the store (DEC-23): the store carries ids, vectors, and
filterable metadata only.

This is a *different job* from the v0 chunker (`axial.chunk`, PRD §5 stage
4), which is embedding-free by design and stays that way; this module does
not touch it (PRD §12's "Embeddings: the chunk stage is model-free" claim is
unchanged -- this is a separate, later-stage representation, not a chunking
mechanism). It reuses `axial.query.reader`, Phase B's read-only vault
surface, rather than `axial.vault` (whose write-side stack pulls in the
whole LLM-backed pipeline -- `axial.tag`, `axial.artifacts`, `axial.xref`,
`axial.llm` -- to define one frontmatter parse, issue #249 F1).

Determinism (the acceptance bar's fourth clause): a fixed sentence-transformer
checkpoint run on CPU in eval/no-dropout mode reproduces the same vectors,
bit-for-bit, given the same input text (verified directly against the real
default model in this module's inner unit tests). The store write itself
does not need to be byte-identical on disk the way `corpus_pin`'s JSON
manifest is (module docstring there) -- each run overwrites the LanceDB
table fresh (`mode="overwrite"`), the same "write fresh every run, never
patch in place" idempotency convention `axial.vault` already established --
so a rerun reproduces the same query *results*, which is what the
acceptance bar actually asks for.

`sentence-transformers`/`lancedb` (the new `distill` dependency group) are
imported lazily, inside the functions that need them, never at module
level -- mirroring `axial.extract`'s own lazy `docling` import -- so
importing this module (e.g. from `axial.cli`, to register the CLI
subcommand) never requires either package; only running the pass itself
does.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from axial.distill.staleness import resolve_current_pin
from axial.eval import corpus_pin as _corpus_pin
from axial.paths import DEFAULT_PIPELINE_CONFIG_PATH, default_vault_dir
from axial.query.reader import MissingVaultDirError as _ReaderMissingVaultDirError
from axial.query.reader import QueryError as _ReaderQueryError
from axial.query.reader import _iter_chunk_frontmatter, _require, source_id_from_chunk_id

# The default local sentence-transformer (DEC-35): small (~90MB),
# CPU-friendly, deterministic, no per-call cost at 17k-80k chunks, and no
# dependency on the configured OpenRouter tagging models exposing an
# embedding endpoint.
DEFAULT_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"

# Derived stage-5 artifacts live under data/ (gitignored, DEC-23) alongside
# every other pipeline directory (data/vault, data/envelopes, data/chunks) --
# not evals/corpus_pin/ (which IS committed): the LanceDB store is real
# binary vector data, and the manifest beside it is this pass's own
# byproduct, not a small, reviewable, git-tracked contract like the corpus
# pin.
DEFAULT_EMBEDDINGS_DIR = Path("data/distill/embeddings.lance")
DEFAULT_MANIFEST_PATH = Path("data/distill/embedding_manifest.json")

TABLE_NAME = "chunks"

# The flattened, single-valued metadata columns every row carries (never
# `chunk_text`, DEC-23) -- the acceptance bar's "filterable metadata" for
# `search`'s own metadata-filtered ANN query.
METADATA_FILTER_KEYS = frozenset(
    {
        "source_id",
        "role_in_argument",
        "field_primary",
        "claim_type_primary",
        "theory_school_primary",
        "empirical_scope_value",
        "polity",
    }
)

Encoder = Callable[[list[str]], list[list[float]]]


class EmbedError(Exception):
    """Base class for all embedding-pass errors."""


class NoChunksToEmbedError(EmbedError):
    """Raised when the vault's `prose/` directory is absent or holds no
    chunk notes -- running the pass against an empty or not-yet-tagged vault
    is a misconfigured invocation, not a valid zero-chunk manifest (mirrors
    `axial.vault.MissingEnvelopeError`'s own loud-failure convention for a
    missing prerequisite)."""

    def __init__(self, prose_dir: Path):
        self.prose_dir = prose_dir
        super().__init__(
            f"no prose chunks found under {prose_dir} to embed; run the tagging "
            f"pipeline (`axial vault write`) first"
        )


class CorpusPinRequiredError(EmbedError):
    """Raised when no corpus-pin manifest can be resolved (DEC-35: every
    stage-5 artifact records the pin it was built from) -- wraps
    `axial.eval.corpus_pin`'s own `MissingCorpusPinError`/
    `AmbiguousCorpusPinError` so the CLI renders a clean `error: ...` line
    instead of a bare traceback."""

    def __init__(self, cause: _corpus_pin.CorpusPinError):
        self.cause = cause
        super().__init__(
            f"embedding pass requires a corpus pin to record provenance against "
            f"({cause}); run `axial pin write <name>` first"
        )


class MalformedVaultNoteError(EmbedError):
    """Wraps `axial.query.reader.QueryError` (a malformed/corrupted note's
    frontmatter, or a `chunk_id` that does not match the
    `<source_id>_<order>_<slug>_<NNN>` shape `source_id_from_chunk_id`
    parses) -- a real pipeline never produces either, but a hand-edited or
    corrupted vault note must still fail with a clean `error: ...` line, not
    a bare traceback from a module this pass merely reuses as its read
    layer."""

    def __init__(self, cause: _ReaderQueryError):
        self.cause = cause
        super().__init__(f"malformed vault note encountered while embedding: {cause}")


class UnknownSearchFilterError(EmbedError):
    """`search` was called with a filter key outside `METADATA_FILTER_KEYS`
    -- a typo'd column must not quietly resolve to a LanceDB error deep
    inside the query engine, and must not quietly match everything either."""

    def __init__(self, unknown_keys: set[str]):
        self.unknown_keys = unknown_keys
        super().__init__(
            f"unknown search filter key(s) {sorted(unknown_keys)!r}; expected "
            f"only {sorted(METADATA_FILTER_KEYS)!r}"
        )


@dataclass(frozen=True)
class EmbedResult:
    """The outcome of one `run_embed` call."""

    embeddings_dir: Path
    manifest_path: Path
    chunk_count: int
    model_name: str
    embedding_dim: int
    corpus_pin_id: str
    vault_snapshot_hash: str


def _default_encoder(model_name: str) -> Encoder:
    """Lazily build the real sentence-transformer encoder (imports
    `sentence_transformers` here, never at module level -- see module
    docstring). CPU-only, eval-mode inference: deterministic given the same
    model checkpoint and input text."""
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(model_name)

    def encode(texts: list[str]) -> list[list[float]]:
        return model.encode(texts, convert_to_numpy=True).tolist()

    return encode


def _flatten_metadata(chunk_id: str, frontmatter: dict[str, Any]) -> dict[str, Any]:
    """The filterable metadata projection for one chunk (never `chunk_text`,
    DEC-23): `source_id` (parsed from the chunk_id itself, the same seam
    `axial.query.reader.query_by_source` uses) plus each single-valued tag
    axis's own scalar -- `role_in_argument` (already flat), `field`/
    `claim_type`/`theory_school`'s nested `primary`, and `empirical_scope`'s
    `value`/`polity`. A missing axis value projects to `""`, never `None` --
    an all-`str` column with some empty values is simpler for LanceDB's
    schema inference than one mixing `str` and `NoneType` across rows."""
    field = frontmatter.get("field") or {}
    claim_type = frontmatter.get("claim_type") or {}
    theory_school = frontmatter.get("theory_school") or {}
    empirical_scope = frontmatter.get("empirical_scope") or {}
    return {
        "chunk_id": chunk_id,
        "source_id": source_id_from_chunk_id(chunk_id),
        "role_in_argument": frontmatter.get("role_in_argument") or "",
        "field_primary": field.get("primary") or "",
        "claim_type_primary": claim_type.get("primary") or "",
        "theory_school_primary": theory_school.get("primary") or "",
        "empirical_scope_value": empirical_scope.get("value") or "",
        "polity": empirical_scope.get("polity") or "",
    }


def _load_chunk_records(vault_dir: Path) -> list[tuple[str, str, dict[str, Any]]]:
    """Every vault chunk's `(chunk_id, chunk_text, metadata)`, sorted by
    `chunk_id` -- the same determinism convention `axial.eval.corpus_pin`'s
    own vault-snapshot hash uses (filesystem enumeration order must never
    leak into the result)."""
    records = []
    for path, frontmatter in _iter_chunk_frontmatter(vault_dir):
        chunk_id = _require(frontmatter, path, "chunk_id")
        chunk_text = _require(frontmatter, path, "chunk_text")
        records.append((chunk_id, chunk_text, _flatten_metadata(chunk_id, frontmatter)))
    records.sort(key=lambda record: record[0])
    return records


def run_embed(
    vault_dir: Path | None = None,
    embeddings_dir: Path | None = None,
    manifest_path: Path | None = None,
    model_name: str = DEFAULT_MODEL_NAME,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
    evals_dir: Path | None = None,
    encoder: Encoder | None = None,
) -> EmbedResult:
    """Embed every prose chunk in `vault_dir` (default resolved via
    `axial.paths.default_vault_dir`) once, and persist the vectors in a
    LanceDB table at `embeddings_dir` (default `DEFAULT_EMBEDDINGS_DIR`),
    keyed by `chunk_id`, alongside the filterable metadata projection
    (`_flatten_metadata`). Writes a small JSON manifest to `manifest_path`
    (default `DEFAULT_MANIFEST_PATH`) recording the model name, embedding
    dimension, chunk count, and the corpus-pin id/`vault_snapshot_hash` this
    pass was built against (DEC-35's staleness convention,
    `axial.distill.staleness`) -- every later stage-5 artifact reuses this
    same seam.

    `encoder`, when given, replaces the default sentence-transformer
    (`_default_encoder`) -- the seam this module's own inner unit tests use
    to exercise the LanceDB write/query/manifest path without downloading a
    real model, mirroring the `client: LLMClient | None` injection seam
    already used throughout this codebase (`axial.tag.run_tag`,
    `axial.vault.run_vault_write`, etc.).

    Raises `NoChunksToEmbedError` when the vault holds no prose chunks, and
    `CorpusPinRequiredError` when no corpus pin can be resolved -- both loud
    failures rather than a silently degraded or empty manifest.
    """
    if vault_dir is None:
        vault_dir = default_vault_dir(config_path)
    vault_dir = Path(vault_dir)
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

    try:
        records = _load_chunk_records(vault_dir)
    except _ReaderMissingVaultDirError as exc:
        raise NoChunksToEmbedError(vault_dir / "prose") from exc
    except _ReaderQueryError as exc:
        raise MalformedVaultNoteError(exc) from exc
    if not records:
        raise NoChunksToEmbedError(vault_dir / "prose")

    if encoder is None:
        encoder = _default_encoder(model_name)

    chunk_texts = [chunk_text for _chunk_id, chunk_text, _metadata in records]
    vectors = encoder(chunk_texts)

    rows = []
    for (_chunk_id, _chunk_text, metadata), vector in zip(records, vectors):
        row = dict(metadata)
        row["vector"] = list(vector)
        rows.append(row)

    import lancedb

    embeddings_dir.parent.mkdir(parents=True, exist_ok=True)
    db = lancedb.connect(embeddings_dir)
    db.create_table(TABLE_NAME, data=rows, mode="overwrite")

    embedding_dim = len(rows[0]["vector"])
    manifest = {
        "model_name": model_name,
        "embedding_dim": embedding_dim,
        "chunk_count": len(rows),
        "corpus_pin_id": pin["corpus_pin_id"],
        "vault_snapshot_hash": pin["vault_snapshot_hash"],
        "table_name": TABLE_NAME,
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    return EmbedResult(
        embeddings_dir=embeddings_dir,
        manifest_path=manifest_path,
        chunk_count=len(rows),
        model_name=model_name,
        embedding_dim=embedding_dim,
        corpus_pin_id=pin["corpus_pin_id"],
        vault_snapshot_hash=pin["vault_snapshot_hash"],
    )


def _escape_sql_literal(value: str) -> str:
    return value.replace("'", "''")


def search(
    embeddings_dir: Path,
    query_vector: list[float],
    *,
    limit: int = 10,
    **filters: str,
) -> list[dict[str, Any]]:
    """Nearest-neighbour query over the persisted store (the acceptance
    bar's own "metadata-filtered ANN" requirement): any of
    `METADATA_FILTER_KEYS` (`source_id`, plus each flattened tag-axis
    column) may be given as an exact-match filter, conjoined with AND.
    Returns each matching row (chunk_id + metadata + a lancedb `_distance`
    column), nearest first -- never `chunk_text` (DEC-23; the store never
    persisted it in the first place, so there is nothing to leak).

    The one seam later stage-5 slices (5c's oversampler, 5e's drift monitor,
    5b's `-1`-triage) reuse rather than hand-rolling their own `.where()`
    SQL-literal construction against this table."""
    unknown_keys = set(filters) - METADATA_FILTER_KEYS
    if unknown_keys:
        raise UnknownSearchFilterError(unknown_keys)

    import lancedb

    db = lancedb.connect(Path(embeddings_dir))
    table = db.open_table(TABLE_NAME)
    query = table.search(list(query_vector)).limit(limit)
    if filters:
        clause = " AND ".join(
            f"{key} = '{_escape_sql_literal(value)}'" for key, value in filters.items()
        )
        query = query.where(clause)
    return query.to_list()
