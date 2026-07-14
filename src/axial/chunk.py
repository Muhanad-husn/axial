"""Chunking (charter #148): `run_chunk_embedding` (issue #151, PRD §5 stage 4
/ §7.7 / §8 P0-4) is the sole chunking mechanism. For each prose section, it
finds chunk boundaries by embedding the section's sentences and splitting at
semantic-similarity troughs (gradient thresholding), then a deterministic
two-sided band guard `[CHUNK_MIN, CHUNK_MAX]` wraps those breakpoints. It
reads ONLY the persisted structural tree (`data/trees/<source_id>.json`, via
`axial.extract`) -- no envelope, no text-generating LLM call anywhere in this
path. It writes records to `data/chunks/<source_id>.jsonl` (PRD §7.7) -- the
CLI `chunk` subcommand's mechanism (see `src/axial/cli.py`).

`read_chunks` (issue #154, slice 04 of the chunk-redesign subproject) is the
downstream-facing reader for that same on-disk artifact: `tag.py`, `xref.py`,
and (through them) `vault.py` read chunk records from
`data/chunks/<source_id>.jsonl` via `read_chunks` instead of computing chunks
themselves. It raises `MissingChunkArtifactError` when the artifact does not
exist yet, telling the operator to run `axial chunk` first -- no downstream
pass ever recomputes chunk boundaries (PRD §8 P0-4b).

Source routing (issue #167, PRD §7.8): `run_chunk_embedding` no longer decides
prose/non-prose by node `type` alone. Each block in a kept section's body is
classified by its docling `label` via the shared `axial.router.route_for`
(through `_routed_section_body`'s `iter_routed_blocks` walk) into exactly one
of `prose` / `artifact` / `apparatus`. Only prose-routed text is chunked;
artifact-routed blocks (`table`, `picture`, `caption`) are excluded from
chunking but NOT recorded as a drop (they belong to the not-yet-built
artifact pass, slice 03); apparatus-routed blocks (`document_index`,
`footnote`, `page_header`/`page_footer`, a back-matter `list_item`) are
dropped and recorded to the `<source_id>.skips.jsonl` sidecar with a
route-specific reason, alongside the pre-existing garble backstop
(`_garbage_section_skip_reason`) -- the router-owned skip sidecar is now the
single source of skip truth (§7.8), not garbage-only.

`build_chunk_records` is the shared record-assembly helper: a stable,
deterministic `chunk_id` (`<source_id>_<section order>_<section slug>_<NNN>`,
derived from the source_id, the section node's already-unique `order` field,
the section's own verbatim heading, and the chunk's position within that
section -- no randomness, no timestamps) and `section` (the section's
verbatim heading text). The `order` component is required for uniqueness:
`extract.py`'s tree-builder opens a new top-level section node for every
heading in reading order without nesting, so a real source can have multiple
top-level sections sharing the same heading text (e.g. repeated
"Introduction"/"Notes"/"Conclusion" across chapters) -- the heading slug
alone would collide across them, but each section's `order` is unique by
construction.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import yaml

from axial.checkpoint import load_checkpoint_records
from axial.envelope import (
    MissingSourceError as _EnvelopeMissingSourceError,
    compute_source_id,
)
from axial.extract import load_persisted_tree, tree_path
from axial.llm import DEFAULT_PIPELINE_CONFIG_PATH
from axial.nonprose_guard import MAX_NON_ALPHA_RATIO, garble_only_skip_reason
from axial.router import APPARATUS, PROSE, apparatus_reason, iter_routed_blocks

CHUNKS_DIR = Path("data/chunks")


def _default_chunks_dir(config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH) -> Path:
    """Resolve the chunk-checkpoint directory, mirroring
    `axial.envelope._default_envelopes_dir`'s structure exactly: honor
    `config/pipeline.yaml`'s `paths.chunks_dir` when declared, else fall back
    to the module-level `CHUNKS_DIR` default (`data/chunks`, resolved relative
    to the current working directory -- the same cwd-relative convention the
    envelope/vault dirs already use, so an isolated staging root's checkpoints
    never alias the real `data/` tree). An absent file/key falls back to
    `CHUNKS_DIR`."""
    if not config_path.is_file():
        return CHUNKS_DIR
    with config_path.open("r", encoding="utf-8") as handle:
        document = yaml.safe_load(handle) or {}
    paths_config = document.get("paths", {}) or {}
    configured = paths_config.get("chunks_dir")
    return Path(configured) if configured else CHUNKS_DIR


def chunks_checkpoint_path(source_id: str, chunks_dir: Path = CHUNKS_DIR) -> Path:
    """The reuse-once path for `source_id`'s chunk-pass checkpoint (one JSON
    chunk record per line), keyed by the content-hashed source_id so an edited
    file (a new source_id) never reuses stale chunks (issue #81 point 1)."""
    return chunks_dir / f"{source_id}.jsonl"


def chunks_skips_sidecar_path(source_id: str, chunks_dir: Path = CHUNKS_DIR) -> Path:
    """The companion sidecar path for `source_id`'s router-owned skip log
    (issue #153's garble backstop, generalized by issue #167/PRD §7.8 to also
    carry apparatus drops -- the single source of skip truth), alongside its
    chunk checkpoint (`chunks_checkpoint_path`): one JSON object per line,
    exactly `{"section", "section_order", "reason"}`. `run_chunk_embedding`
    rewrites this cleanly on every call -- created only when there is >= 1
    skip, removed when a rerun has none -- mirroring the main JSONL's own
    overwrite-cleanly contract so a rerun on the same source bytes stays
    idempotent. `axial chunk examine` (a separate, later, read-only
    invocation) reads it to report sections skipped as garbage without
    re-deriving the guard."""
    return chunks_dir / f"{source_id}.skips.jsonl"


def load_chunk_checkpoint(path: Path) -> list[dict[str, Any]]:
    """Load chunk records already persisted to `path` (`run_chunk_embedding`'s
    own on-disk artifact, or -- historically -- the retired chunk-pass
    checkpoint), skipping blank lines. Returns an empty list when the file
    does not exist yet. The underlying read for `read_chunks` (below).

    Hardening (issue #104, mirroring `axial.tag.load_tag_checkpoint`): a torn
    FINAL line (a hard kill mid-write) is healed (dropped) rather than
    poisoning the read. A torn line that is NOT the last one raises
    `ChunkCheckpointCorruptError`, naming the path and the offending
    1-indexed line number. Reuses the same shared
    `axial.checkpoint.load_checkpoint_records` primitive
    `axial.tag.load_tag_checkpoint` builds on."""
    return load_checkpoint_records(path, ChunkCheckpointCorruptError)


class ChunkError(Exception):
    """Base class for all argumentative-chunking errors."""


class MissingSourceError(ChunkError):
    """Raised when the source path does not exist or is not a file."""

    def __init__(self, cause: _EnvelopeMissingSourceError):
        self.cause = cause
        super().__init__(str(cause))


class ChunkCheckpointCorruptError(ChunkError):
    """Raised by `load_chunk_checkpoint` when a NON-final line of a chunk
    checkpoint file is not valid JSON (issue #104, mirroring
    `axial.tag.TagCheckpointCorruptError`). A torn FINAL line is healed
    (dropped) instead -- see `load_chunk_checkpoint`'s docstring; a torn line
    anywhere else is genuine corruption unrelated to a hard-kill mid-append,
    so it still raises loudly."""

    def __init__(self, path: Path, line_no: int, cause: json.JSONDecodeError):
        self.path = path
        self.line_no = line_no
        self.cause = cause
        super().__init__(
            f"corrupt chunk checkpoint {path}: line {line_no} is not valid JSON: {cause}"
        )


class MissingChunkArtifactError(ChunkError):
    """Raised by `read_chunks` when no on-disk chunk artifact exists yet for
    the source (PRD §7.7, §8 P0-4b): downstream passes (`tag`, `xref`, and
    `vault write` through them) never recompute chunk boundaries themselves
    -- the caller must run `axial chunk` first."""

    def __init__(self, path: Path):
        self.path = path
        super().__init__(
            f"no chunk artifact found at {path}; run `axial chunk` on the source first"
        )


class ChunkArtifactCorruptError(ChunkError):
    """Raised by `examine_chunks` (issue #153) when a line of a chunk
    artifact -- the main `<source_id>.jsonl` or its `<source_id>.skips.jsonl`
    sidecar -- is not valid JSON. Modeled on `ChunkCheckpointCorruptError`,
    but unconditional (examine is a diagnostic read, not a resumable
    checkpoint, so there is no "torn final line" healing case to special-case
    here): any malformed line raises loudly, carrying the offending file's
    path and its 1-indexed line number so the operator can go fix it."""

    def __init__(self, path: Path, line_no: int, cause: json.JSONDecodeError):
        self.path = path
        self.line_no = line_no
        self.cause = cause
        super().__init__(
            f"corrupt chunk artifact {path}: line {line_no} is not valid JSON: {cause}"
        )


def read_chunks(
    source_id: str,
    *,
    chunks_dir: Path | None = None,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
) -> list[dict[str, Any]]:
    """Read the on-disk chunk artifact (PRD §7.7) `source_id` already has at
    `data/chunks/<source_id>.jsonl`, written by `axial chunk`
    (`run_chunk_embedding`). Resolves the path with the SAME helpers the
    writer uses (`_default_chunks_dir` / `chunks_checkpoint_path`), so reader
    and writer always agree on where the artifact lives. Returns the chunk
    records in file (section-then-position) order -- the order
    `run_chunk_embedding` wrote them in.

    Raises `MissingChunkArtifactError` if the artifact does not exist yet:
    this is a pure reader, never a recompute path (issue #154, PRD §8
    P0-4b) -- no downstream pass ever (re)derives chunk boundaries itself."""
    if chunks_dir is None:
        chunks_dir = _default_chunks_dir(config_path)
    path = chunks_checkpoint_path(source_id, chunks_dir)
    if not path.exists():
        raise MissingChunkArtifactError(path)
    return load_chunk_checkpoint(path)


_SLUG_MAX_LEN = 80


def _slugify(label: str) -> str:
    """A filesystem/id-safe slug for a section heading, used inside
    chunk_id. Falls back to "section" if the heading has no alphanumerics.

    Capped at `_SLUG_MAX_LEN` chars (issue #94): an unbounded slug -- e.g. a
    section heading that restates a paper's full title -- pushes the note
    filename (`<chunk_id>.md`, `axial.vault._note_path`) past Windows'
    260-char MAX_PATH. The cut trims back to the nearest hyphen boundary
    within the cap where one exists, so the slug never ends mid-word; a
    trailing hyphen left behind by that trim is stripped. Uniqueness is
    unaffected: `build_chunk_records` folds the section's own `order` into
    chunk_id, which already disambiguates sections whose slugs coincide."""
    slug = re.sub(r"[^a-z0-9]+", "-", label.strip().lower()).strip("-")
    if len(slug) > _SLUG_MAX_LEN:
        truncated = slug[:_SLUG_MAX_LEN]
        cut = truncated.rfind("-")
        if cut > 0:
            truncated = truncated[:cut]
        slug = truncated.rstrip("-")
    return slug or "section"


# Clear non-content back-matter / boilerplate section titles that must never
# be chunked or written as vault notes (issue #113). Conservative + exact:
# only unambiguous titles match after normalization; endnotes ("Notes"),
# appendix, preface, and anything ambiguous are KEPT. OCR-mangled titles
# (e.g. tilly's index came through as the garbled section "lad ex") won't
# match here -- that residual is backstopped by the xref input guard (#111).
_BACK_MATTER_TITLES = frozenset(
    {
        "index",
        "general index",
        "subject index",
        "name index",
        "author index",
        "index of names",
        "bibliography",
        "select bibliography",
        "references",
        "reference list",
        "works cited",
        "cited works",
        "table of contents",
        "contents",
        "copyright",
        "list of figures",
        "list of tables",
        "list of illustrations",
        "list of maps",
        "list of abbreviations",
    }
)


def _is_back_matter(title: str) -> bool:
    """True if `title` is a clear non-content back-matter/boilerplate section
    (issue #113): an exact match, after normalization (lowercase, whitespace
    collapsed, surrounding punctuation stripped), against `_BACK_MATTER_TITLES`.
    Conservative by design -- a title that is merely similar (an appendix, an
    endnotes section, a chapter) is KEPT, since a false keep is cheap while a
    false drop loses real content."""
    normalized = re.sub(r"\s+", " ", title.lower()).strip(" .:-–—")
    return normalized in _BACK_MATTER_TITLES


def _section_nodes(tree: dict) -> list[dict]:
    """Top-level nodes that represent a section: opened by a heading, so
    they carry both a verbatim `text` and a `children` list. These are the
    chunking units for this pass (PRD §5 stage 4) -- a top-level node with no
    `children` key (content preceding any heading) carries no section label
    to report provenance for, so it is not a chunking unit here."""
    return [
        child for child in tree.get("children", []) if "children" in child and child.get("text")
    ]


def _routed_section_body(section: dict) -> tuple[list[str], list[dict[str, Any]]]:
    """Route every block in `section`'s body (its `children`, excluding the
    section's own heading) through the shared source router (issue #167, PRD
    §7.8) via `axial.router.iter_routed_blocks`, and split the result into
    `(prose_lines, apparatus_drops)`:

    - `prose_lines` -- ordered text of every prose-routed block (`text`,
      `section_header`, `title`, an in-body `list_item`), chunked as today.
    - `apparatus_drops` -- one router-owned skip record
      (`chunks_skips_sidecar_path`'s `{"section", "section_order", "reason"}`
      shape) per apparatus-routed block (`document_index`, `footnote`,
      `page_header`/`page_footer`, or a back-matter `list_item`): dropped,
      never chunked, each with a route-specific reason
      (`axial.router.apparatus_reason`).

    Artifact-routed blocks (`table`, `picture`, `caption`) contribute to
    NEITHER list -- excluded from chunking, but not a "drop" (§7.8: they are
    routed to the not-yet-built artifact pass, slice 03, not lost).

    `in_back_matter_section` (the router's own `list_item` rule, §7.8) is
    derived here from THIS section's own heading via `_is_back_matter` --
    the same title-based check `run_chunk_embedding` already uses to filter
    whole back-matter sections before this function ever sees them, so it is
    always `False` in the wiring below today; it stays correct in isolation
    (and for any future caller that stops pre-filtering whole sections) since
    it is derived independently, right here, from this section's own text.
    """
    section_label = section.get("text", "")
    section_order = section.get("order", "")
    in_back_matter_section = _is_back_matter(section_label)

    prose_lines: list[str] = []
    apparatus_drops: list[dict[str, Any]] = []
    for child in section.get("children", []):
        for node, route in iter_routed_blocks(child, in_back_matter_section=in_back_matter_section):
            if route == PROSE:
                text = node.get("text")
                if text:
                    prose_lines.append(text)
            elif route == APPARATUS:
                apparatus_drops.append(
                    {
                        "section": section_label,
                        "section_order": node.get("order", section_order),
                        "reason": apparatus_reason(node.get("label")),
                    }
                )
            # route == ARTIFACT: excluded from chunking, not a drop (§7.8).
    return prose_lines, apparatus_drops


def build_chunk_records(
    source_id: str, section_order: str, section_label: str, chunks: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Assemble chunk records carrying a stable, deterministic `chunk_id`
    (`<source_id>_<section order>_<section slug>_<NNN>`), `section` (the
    section's own verbatim heading), and `section_order` (the section node's
    own verbatim `order` field, e.g. "1", "2" -- issue #104: the per-section
    checkpoint's own provenance, letting a resume tell which sections are
    already durably persisted without re-deriving it by parsing chunk_id),
    per PRD §8 P0-4.

    `section_order` is also folded into chunk_id specifically so that two
    distinct top-level sections sharing the same heading text (extract.py
    opens a fresh section node per heading occurrence, unnested) never
    collide on chunk_id -- the heading slug alone is not unique across a
    real multi-chapter source.
    """
    slug = _slugify(section_label)
    order_key = section_order.replace(".", "-") if section_order else "0"
    records = []
    for index, chunk in enumerate(chunks, start=1):
        records.append(
            {
                "chunk_id": f"{source_id}_{order_key}_{slug}_{index:03d}",
                "section": section_label,
                "section_order": section_order,
                "text": chunk["text"],
            }
        )
    return records


# =============================================================================
# Embedding-based chunk stage (issue #151, PRD §5 stage 4 / §7.7 / §8 P0-4)
# =============================================================================
#
# For each prose section: segment its body into sentences, embed the
# sentences with an injectable `Embedder`, build a consecutive-distance
# series, and split at semantic-similarity troughs using gradient
# thresholding (founder preference over percentile thresholding -- try
# gradient first). A deterministic two-sided band guard then wraps those
# breakpoints: MAX side recursively splits any chunk over `CHUNK_MAX` at its
# next-best internal boundary (never emits a section whole, never skips for
# size); MIN side merges adjacent below-`CHUNK_MIN` chunks forward, within a
# section only. No text-generating LLM call anywhere in this path -- the
# stage reads only the persisted structural tree (`axial.extract`), never an
# envelope.

# Band constants (character counts, matching PRD §7.7's "text length"):
# sensible STARTING POINTS anchored on PRD §7.7's "what the vault stores and
# works downstream today (~1-3k characters per chunk)" -- NOT proven-final
# values. Proving/tuning these is the operational `axial chunk examine` loop
# (slice 03), which reads real corpus chunk-size distributions off the
# on-disk artifact; this slice ships a working default, not a tuned one.
CHUNK_MIN = 1000
CHUNK_MAX = 3000

# Per-source sentence-embedding cache (issue #152): cwd-relative, gitignored
# (the blanket `data/` ignore in .gitignore already covers it -- no separate
# entry needed), mirroring `CHUNKS_DIR`/`axial.extract.TREES_DIR`'s own
# convention exactly. Referenced as a module GLOBAL (never captured as a
# function default) by `_default_chunk_cache_dir` below specifically so it
# can be monkeypatched in tests exactly like `CHUNKS_DIR`/`TAGS_DIR` (see
# src/axial/conftest.py's autouse isolation fixture) -- a function default
# value bound at def-time would not pick up a later monkeypatch.
CHUNK_CACHE_DIR = Path("data/chunk_cache")


def _default_chunk_cache_dir() -> Path:
    """The cwd-relative default embedding-cache directory. No
    `config/pipeline.yaml` override exists for this path (unlike
    `_default_chunks_dir`/`_default_envelopes_dir`) -- not part of this
    slice's contract (plan: "data/chunk_cache/", a plain cwd-relative
    default). Reads the module-level `CHUNK_CACHE_DIR` global at CALL time
    (see that constant's own docstring for why)."""
    return CHUNK_CACHE_DIR


# Env-var seam selecting the embedder, mirroring `axial.llm`'s
# `AXIAL_LLM_PROVIDER` convention exactly (see that module's docstring).
# `AXIAL_EMBEDDER=stub` selects the deterministic, offline, no-network stub
# embedder (test/CI seam) explicitly; unset or any other value falls back to
# this module's own default (see `get_embedder` / `HashingEmbedder` below).
EMBEDDER_ENV_VAR = "AXIAL_EMBEDDER"


class MissingTreeError(ChunkError):
    """Raised when no persisted structural tree exists yet for the source
    (PRD §5 stage 4, "the stage reads the persisted structural tree only") --
    the embedding chunk stage never runs docling/Unstructured itself; the
    caller must run `axial extract` first."""

    def __init__(self, path: Path):
        self.path = path
        super().__init__(
            f"no persisted tree found at {path}; run `axial extract` on the source first"
        )


class Embedder(Protocol):
    """A single-method sentence-embedding interface, mirroring
    `axial.llm.LLMClient`'s single-method `complete` shape. Every embedder
    this module can select implements `encode`.

    `model_id` (issue #152) identifies the concrete embedding model an
    instance represents -- the per-source embedding cache's key is a
    function of `(source_id, embedder.model_id)` (see `_CachingEmbedder`
    below), read off the injected embedder itself rather than passed
    separately, since the embedder instance IS the thing whose identity
    determines what "the embedding model" is (mirroring how `axial.llm`
    client selection already works: config/provider picks the object;
    nothing separately re-declares its identity to callers)."""

    model_id: str

    def encode(self, texts: list[str]) -> list[list[float]]:
        """Return one fixed-length numeric vector per input text, in order."""
        ...


_HASHING_EMBEDDER_DIM = 256


def _tokenize(text: str) -> list[str]:
    """A simple, deterministic word tokenizer: lowercase runs of
    alphanumeric characters. No stemming/stopwords -- kept intentionally
    simple (see `HashingEmbedder`'s docstring for the 80/20 rationale)."""
    return re.findall(r"[a-z0-9]+", text.lower())


class HashingEmbedder:
    """Deterministic, offline, dependency-free embedder: a hashing-trick
    bag-of-words vectorizer. Each input text is tokenized into lowercase
    word tokens; each token is hashed (SHA-256, stable across processes and
    Python versions -- unlike Python's own salted `hash()`) into one of
    `dim` buckets and that bucket's count is incremented; the resulting
    count vector is L2-normalized. Cosine similarity between two such
    vectors then approximates lexical/topical overlap: two sentences sharing
    vocabulary land closer together than two sentences that don't, which is
    exactly the "consecutive-distance series" signal the breakpoint detector
    below needs -- without any ML model, model download, or network call.

    In-slice decision (issue #151, 80/20 rationale): this is the SAME
    implementation behind both `AXIAL_EMBEDDER=stub` and the unset/default
    path (see `get_embedder` below). No real sentence-embedding model
    dependency (e.g. `sentence-transformers`) is pulled into this slice --
    the repo has none today (per this module's own docstring history), and
    adding one is disproportionate to a slice whose acceptance criterion is
    "a deterministic, offline split that respects the band", not embedding
    quality (that is the slice-03 examine/tuning loop's job). The `Embedder`
    protocol and `get_embedder` seam are deliberately clean so a real model
    can be swapped in behind a distinct `AXIAL_EMBEDDER` value later,
    lazy-imported exactly like `axial.extract`'s docling/unstructured
    imports, without touching any caller of `get_embedder`.

    `model_id` (issue #152, the embedding-cache seam): defaults to a stable
    value reflecting `dim` (`"hashing-v1-<dim>"`), so two `HashingEmbedder()`
    instances at the same dim (the common case -- `get_embedder` never
    varies it) always agree on a cache key, while an explicit override lets
    a caller simulate "a different embedding model" without changing the
    hashing algorithm itself (e.g. this module's own cache-invalidation
    tests).
    """

    def __init__(self, dim: int = _HASHING_EMBEDDER_DIM, model_id: str | None = None) -> None:
        self._dim = dim
        self.model_id = model_id if model_id is not None else f"hashing-v1-{dim}"

    def encode(self, texts: list[str]) -> list[list[float]]:
        return [self._encode_one(text) for text in texts]

    def _encode_one(self, text: str) -> list[float]:
        vector = [0.0] * self._dim
        for token in _tokenize(text):
            index = int(hashlib.sha256(token.encode("utf-8")).hexdigest(), 16) % self._dim
            vector[index] += 1.0
        norm = math.sqrt(sum(component * component for component in vector))
        if norm > 0:
            vector = [component / norm for component in vector]
        return vector


def get_embedder(config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH) -> Embedder:
    """Select the configured `Embedder`, mirroring `axial.llm.get_client`'s
    `AXIAL_LLM_PROVIDER` seam exactly: `AXIAL_EMBEDDER=stub` explicitly
    selects the deterministic offline stub; unset or any other value falls
    back to this module's own default. Both currently resolve to the same
    `HashingEmbedder` (see its docstring for why) -- the seam exists so a
    future real embedding model can be selected without changing any caller.
    `config_path` is accepted (unused today) to mirror `get_client`'s
    signature for future config-driven provider selection.
    """
    del config_path  # unused today -- kept for signature parity with get_client
    provider = os.environ.get(EMBEDDER_ENV_VAR, "")
    if provider == "stub":
        return HashingEmbedder()
    return HashingEmbedder()


_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def segment_sentences(text: str) -> list[str]:
    """A deterministic, dependency-free sentence segmenter: split on
    whitespace immediately following a sentence-ending punctuation mark
    (`.`, `!`, `?`).

    In-slice decision: no abbreviation/decimal-number handling, and no
    heavier NLP dependency (e.g. nltk's punkt, spaCy) -- disproportionate to
    this slice's 80/20 bar. An occasional over-split (e.g. "Dr. Smith" -> two
    pieces) only ever makes a candidate unit SMALLER, which the MIN-side band
    guard already tolerates and corrects (small pieces merge forward); it
    never produces an oversized, unsplittable unit, which is the failure
    mode that actually matters for the band guarantee.
    """
    stripped = text.strip()
    if not stripped:
        return []
    return [piece.strip() for piece in _SENTENCE_SPLIT_RE.split(stripped) if piece.strip()]


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def consecutive_distances(vectors: list[list[float]]) -> list[float]:
    """The consecutive-distance series (PRD §5 stage 4): one cosine distance
    (`1 - cosine_similarity`) per adjacent pair of embedded sentence
    vectors. `distances[i]` is the distance between `vectors[i]` and
    `vectors[i + 1]` -- a high value means sentence i and i+1 diverge in
    topic; a low value means they're similar."""
    return [1.0 - _cosine_similarity(vectors[i], vectors[i + 1]) for i in range(len(vectors) - 1)]


# Gradient-threshold sensitivity: a breakpoint fires where the distance
# series' own discrete derivative (gradient) spikes more than this many
# standard deviations above its mean -- i.e. a SHARP, LOCAL rise in
# dissimilarity (a genuine topic shift), not a shallow, gradual drift across
# the whole series. Founder preference (per the slice plan): gradient
# thresholding, not percentile thresholding -- tried first here. A sensible
# starting point, not a tuned value (see CHUNK_MIN/CHUNK_MAX's docstring --
# tuning is the slice-03 examine loop's job).
GRADIENT_THRESHOLD_SIGMA = 1.0


def gradient_breakpoints(
    distances: list[float], threshold_sigma: float = GRADIENT_THRESHOLD_SIGMA
) -> list[int]:
    """Gradient-threshold breakpoint detection over a consecutive-distance
    series (see `consecutive_distances`). Computes the discrete derivative
    (gradient) of `distances` -- `gradients[j] = distances[j+1] -
    distances[j]` -- and flags a breakpoint at `distances` index `j + 1`
    wherever `gradients[j]` rises more than `threshold_sigma` standard
    deviations above the gradient series' own mean AND is itself positive
    (a rise, not a fall). Returned indices are 0-based positions into
    `distances` (equivalently, into the gaps between sentences): index `d`
    means "cut between sentence `d` and sentence `d + 1`".

    Needs at least 2 distances (3 sentences) to have a derivative to compare
    against at all; shorter input yields no breakpoints -- nothing to
    contrast a single distance's gradient against.
    """
    if len(distances) < 2:
        return []
    gradients = [distances[i] - distances[i - 1] for i in range(1, len(distances))]
    mean = statistics.mean(gradients)
    stdev = statistics.pstdev(gradients)
    cutoff = mean + threshold_sigma * stdev
    breakpoints = [
        index + 1 for index, gradient in enumerate(gradients) if gradient > cutoff and gradient > 0
    ]
    return breakpoints


def _group_by_breakpoints(sentences: list[str], breakpoints: list[int]) -> list[list[str]]:
    """Partition `sentences` into consecutive groups at the given
    `breakpoints` (0-based `consecutive_distances` indices -- see
    `gradient_breakpoints`'s docstring for exactly what each index means)."""
    groups: list[list[str]] = []
    start = 0
    for cut_after in sorted(set(breakpoints)):
        groups.append(sentences[start : cut_after + 1])
        start = cut_after + 1
    groups.append(sentences[start:])
    return [group for group in groups if group]


def _group_char_len(group: list[str]) -> int:
    return len(" ".join(group))


def _hard_split_by_chars(text: str, chunk_max: int) -> list[str]:
    """Last-resort fallback for a single "sentence" that alone exceeds
    `chunk_max` (e.g. a run-on with no internal sentence-ending punctuation
    for the segmenter to find): split it on raw character boundaries so the
    MAX-side guarantee ("no record exceeds CHUNK_MAX -- no exception") holds
    even in this degenerate case."""
    if not text:
        return []
    return [text[i : i + chunk_max] for i in range(0, len(text), chunk_max)]


def _split_group_to_max(group: list[str], embedder: Embedder, chunk_max: int) -> list[list[str]]:
    """MAX-side band guard (PRD §5 stage 4 / §8 P0-4): if `group`'s joined
    text already fits within `chunk_max`, return it unchanged. Otherwise
    recursively split it at its OWN next-best internal boundary -- the
    highest-distance adjacent-sentence gap within just this group,
    re-embedding only this group's sentences to find it -- and recurse on
    each half. A single-sentence group that alone exceeds `chunk_max` (no
    internal sentence boundary to split at) falls back to a raw character
    split (`_hard_split_by_chars`). This guarantees no returned group's
    joined text ever exceeds `chunk_max`, with NO exception -- unlike the
    MIN side, this invariant is unconditional (PRD §7.7/§8 P0-4: "no record
    exceeds max ... with NO exception").

    Tie-break (bug found via an end-to-end MIN-side test, issue #151): when
    several adjacent-sentence gaps tie for the max distance -- routine with
    repetitive/cyclic prose, or any embedder coarse enough to produce exact
    ties -- always taking the FIRST tied index degenerates into peeling off
    one sentence at a time from the front on every recursive call, producing
    many tiny fragments instead of a balanced split. Among tied maxima, pick
    the one closest to the group's own midpoint instead, so a tie-heavy
    group still bisects roughly in half each recursive step (an unambiguous
    single maximum is unaffected -- this only changes behavior under a tie).
    """
    if _group_char_len(group) <= chunk_max:
        return [group]
    if len(group) == 1:
        return [[piece] for piece in _hard_split_by_chars(group[0], chunk_max)]

    vectors = embedder.encode(group)
    distances = consecutive_distances(vectors)
    best = max(distances)
    midpoint = (len(distances) - 1) / 2
    split_at = min(
        (index for index, distance in enumerate(distances) if distance == best),
        key=lambda index: abs(index - midpoint),
    )
    left, right = group[: split_at + 1], group[split_at + 1 :]
    return _split_group_to_max(left, embedder, chunk_max) + _split_group_to_max(
        right, embedder, chunk_max
    )


def _enforce_max(groups: list[list[str]], embedder: Embedder, chunk_max: int) -> list[list[str]]:
    result: list[list[str]] = []
    for group in groups:
        result.extend(_split_group_to_max(group, embedder, chunk_max))
    return result


def _enforce_min(groups: list[list[str]], chunk_min: int) -> list[list[str]]:
    """MIN-side band guard (PRD §5 stage 4 / §8 P0-4): a below-`chunk_min`
    chunk merges forward into the next one, within this call's own section
    only (callers never pass groups spanning two sections). Merging
    repeats until the accumulated group reaches `chunk_min`, so only the
    LAST group in the returned list can end up below `chunk_min` -- exactly
    the documented exception (a section's last chunk, or a whole section
    shorter than `chunk_min`, may remain below it)."""
    if not groups:
        return []
    merged: list[list[str]] = [list(groups[0])]
    for group in groups[1:]:
        if _group_char_len(merged[-1]) < chunk_min:
            merged[-1].extend(group)
        else:
            merged.append(list(group))
    return merged


def _chunk_section_text(
    text: str,
    embedder: Embedder,
    chunk_min: int = CHUNK_MIN,
    chunk_max: int = CHUNK_MAX,
) -> list[str]:
    """Chunk one prose section's body text: segment into sentences, embed
    and find gradient breakpoints (the primary boundary signal), then wrap
    the two-sided band guard around them -- MAX side first (splits anything
    over-band), MIN side second (merges anything under-band forward), then
    MAX side again as a safety net (a MIN-side merge can itself push a
    group over `chunk_max`; re-splitting after merging keeps the
    unconditional MAX guarantee intact)."""
    sentences = segment_sentences(text)
    if not sentences:
        return []

    if len(sentences) == 1:
        groups: list[list[str]] = [sentences]
    else:
        vectors = embedder.encode(sentences)
        distances = consecutive_distances(vectors)
        breakpoints = gradient_breakpoints(distances)
        groups = _group_by_breakpoints(sentences, breakpoints)

    groups = _enforce_max(groups, embedder, chunk_max)
    groups = _enforce_min(groups, chunk_min)
    groups = _enforce_max(groups, embedder, chunk_max)

    return [" ".join(group) for group in groups]


def _garbage_section_skip_reason(
    text: str, max_non_alpha_ratio: float = MAX_NON_ALPHA_RATIO
) -> str | None:
    """The non-alpha arm ONLY of the shared `axial.nonprose_guard` heuristic
    (PRD §5 stage 4 / §7.7 / §8 P0-4: "size never triggers a skip" for the
    embedding chunk stage -- an oversized but legitimate section is SPLIT,
    never skipped). Delegates to `axial.nonprose_guard.garble_only_skip_reason`
    (issue #169, source-router slice 04, which lifted this stage's own
    "non-alpha arm ONLY" precedent into the shared module so `axial.chunk`,
    `axial.tag`, and `axial.xref` share one definition instead of three
    copies) rather than `non_prose_skip_reason` directly, since that
    function's size arm would skip on size too; this stage's own MAX-side
    band guard (`_split_group_to_max`) is what handles size instead."""
    return garble_only_skip_reason(text, max_non_alpha_ratio=max_non_alpha_ratio)


_CACHE_KEY_SAFE_RE = re.compile(r"[^A-Za-z0-9_.-]+")


def _safe_cache_key_component(value: str) -> str:
    """Make `value` (a source_id or an embedding-model id, either of which
    may contain characters that are awkward in a filename) safe to fold into
    an on-disk cache filename, by replacing every run of
    not-obviously-filesystem-safe characters with a single underscore.

    Two DIFFERENT raw values CAN sanitize to the same safe string (e.g.
    `"model_1"` and `"model!1"` both collapse to `"model_1"`) -- a
    filename collision is therefore possible, most plausibly on `model_id`
    (`compute_source_id` always appends a 12-hex-char suffix to `source_id`,
    which makes a `source_id`-side collision implausible in practice, but
    this function offers no formal guarantee either way). A collision here
    is harmless, not corrupting: `_CachingEmbedder` persists the RAW
    `source_id`/`model_id` inside the cache file itself and checks them
    against the current run's values on load, so a filename shared by two
    distinct `(source_id, model_id)` pairs degrades to a cold cache (an
    extra re-embed) rather than ever serving one pair's vectors to the
    other (see `_CachingEmbedder._load_cache_file`)."""
    return _CACHE_KEY_SAFE_RE.sub("_", value)


class _CachingEmbedder:
    """Wraps another `Embedder`, memoizing sentence -> vector lookups on
    disk so a source's sentence embeddings are computed AT MOST ONCE across
    every run of the chunk stage against it (issue #152, PRD §5 stage 4 /
    §7.7's "cheap band sweeps" acceptance criterion -- memory
    [[chunk-experiment-caching]]).

    Cache key: `(source_id, embedder.model_id)`, both folded into the
    on-disk filename `<chunk_cache_dir>/<source_id>__<model_id>.json` (each
    component sanitized by `_safe_cache_key_component`). Reading the model
    id off the WRAPPED embedder itself (rather than a separately-passed
    argument) is deliberate -- see `Embedder.model_id`'s docstring. Keying
    on `source_id` (a content hash, `axial.envelope.compute_source_id`)
    rather than a filename/path means an edited source (different bytes,
    same filename) never collides with its own prior cache entry, and two
    different sources never collide with each other's, even if they happen
    to share a filename stem (issue #152's "edited source" acceptance
    clause). A different `model_id` for the SAME source_id resolves to a
    DIFFERENT file entirely, so swapping embedding models always misses and
    re-embeds -- no stale cross-model vectors are ever read back.

    Memoization granularity: per SENTENCE TEXT, not per `encode` call or per
    section. `run_chunk_embedding`'s critical path calls `embedder.encode`
    at two distinct sites -- the primary per-section embed in
    `_chunk_section_text`, and the MAX-side re-embed of an over-band
    subgroup's sentences inside `_split_group_to_max` -- but a given
    sentence's embedding is the same VALUE regardless of which call site
    asks for it. Keying by the sentence's own text (rather than, say, a
    (section, position) coordinate) means the MAX-side re-embed of a subset
    of sentences already embedded in the primary pass is a guaranteed cache
    hit, and a later run at a DIFFERENT `[chunk_min, chunk_max]` band --
    which regroups the very same sentences into different-shaped subgroups,
    changing WHICH sentences reach `_split_group_to_max` and in what
    combinations -- still hits, because the cache was never keyed on
    grouping/position in the first place. This is what makes a band-sweep
    re-run's `encode` call count drop to exactly zero (issue #152's central
    assertion), not merely lower.

    Purely a performance layer -- see `encode`'s docstring for why this
    changes nothing about chunk OUTPUT. Loads its on-disk cache file (if
    any) once, at construction; call `flush()` to persist newly-computed
    entries back to disk (idempotent -- a no-op when nothing new was
    computed since the last flush), so a later process/run (not just a
    later call within the same process) reuses it.

    On-disk file shape (issue #152 review finding 1): `{"source_id": ...,
    "model_id": ..., "vectors": {text: vector}}` -- the raw (unsanitized)
    `source_id`/`model_id` are persisted INSIDE the file, not just encoded
    into its filename. `_load_cache_file` checks both against the current
    run's values before trusting the file's vectors at all, so a filename
    collision from `_safe_cache_key_component` (two distinct raw
    `(source_id, model_id)` pairs sanitizing to the same filename -- see
    that function's docstring) can never serve one pair's vectors to the
    other: a mismatch degrades to a cold cache instead. Loading also fails
    SOFT on any read/parse problem (a torn write from a hard kill mid-flush,
    a hand-edited file, wrong JSON shape) -- see `_load_cache_file`'s
    docstring -- mirroring this module's own `load_chunk_checkpoint`
    heal-on-corruption convention (issue #104): the cache is a pure
    performance layer, so it must never be able to abort a run.
    """

    def __init__(self, inner: Embedder, source_id: str, cache_dir: Path) -> None:
        self._inner = inner
        self.model_id = inner.model_id
        self._source_id = source_id
        self._path = cache_dir / (
            f"{_safe_cache_key_component(source_id)}"
            f"__{_safe_cache_key_component(inner.model_id)}.json"
        )
        self._vectors: dict[str, list[float]] = {}
        if self._path.is_file():
            self._vectors = self._load_cache_file()
        self._dirty = False

    def _load_cache_file(self) -> dict[str, list[float]]:
        """Read `self._path` and return its cached vectors, or `{}` (cold)
        if the file cannot be trusted -- either because it is unreadable
        malformed JSON (`json.JSONDecodeError`), the wrong shape (e.g. a
        list instead of an object -- `TypeError`), missing the expected
        keys (`KeyError`), unreadable at the OS level such as a torn write
        still mid-replace (`OSError`), or its own recorded
        `source_id`/`model_id` does not match this instance's (`ValueError`
        -- the finding-1 integrity check: a filename collision must never
        let this run read another `(source_id, model_id)` pair's vectors).
        Any of these prints a one-line warning to stderr (mirroring this
        module's own `print(..., file=sys.stderr)` convention for skips)
        and treats the cache as empty -- construction never raises, and the
        caller simply re-embeds everything, exactly as on a genuinely cold
        cache."""
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise TypeError(f"expected a JSON object, got {type(payload).__name__}")
            if payload["source_id"] != self._source_id or payload["model_id"] != self.model_id:
                raise ValueError(
                    "cache file's recorded source_id/model_id does not match this run "
                    "(filename collision -- see _safe_cache_key_component)"
                )
            vectors = payload["vectors"]
            if not isinstance(vectors, dict):
                raise TypeError(
                    f"expected 'vectors' to be a JSON object, got {type(vectors).__name__}"
                )
            return vectors
        except (json.JSONDecodeError, TypeError, KeyError, ValueError, OSError) as exc:
            print(
                f"chunk: ignoring unreadable embedding cache {self._path}: {exc}",
                file=sys.stderr,
            )
            return {}

    def encode(self, texts: list[str]) -> list[list[float]]:
        """Return one vector per text, in order -- IDENTICAL to what
        `inner.encode` would return for the same text, since a cache hit
        returns exactly the vector `inner.encode` produced (and persisted)
        the first time that same text was seen. A text already in the cache
        never reaches `inner.encode` at all; only genuinely new texts are
        batched into a single call to `inner.encode` (preserving that
        method's own "one call, many texts" batching contract for whatever
        texts remain uncached), and their results are memoized before
        returning."""
        results: list[list[float] | None] = [self._vectors.get(text) for text in texts]
        miss_indices = [index for index, vector in enumerate(results) if vector is None]
        if miss_indices:
            miss_texts = [texts[index] for index in miss_indices]
            miss_vectors = self._inner.encode(miss_texts)
            for index, text, vector in zip(miss_indices, miss_texts, miss_vectors):
                results[index] = vector
                self._vectors[text] = vector
            self._dirty = True
        return results  # type: ignore[return-value]  -- every None slot was just filled above

    def flush(self) -> None:
        """Persist any newly-computed vectors to `self._path`, along with
        this run's raw `source_id`/`model_id` (see the class docstring's
        "On-disk file shape" -- the finding-1 integrity check `_load_cache_file`
        relies on), creating parent directories as needed. A no-op when
        nothing changed since the last flush (a fully warm run, or a flush
        called twice in a row).

        Atomic (issue #152 review finding 2): writes to a sibling temp file
        first, then `os.replace`s it over `self._path` -- `os.replace` is a
        single filesystem rename, so a reader (including a later
        `_CachingEmbedder` construction) always sees either the complete
        prior file or the complete new one, never a torn partial write, even
        if this process is hard-killed mid-flush. `flush()` runs after every
        section in `run_chunk_embedding`, so this matters in practice, not
        just in theory."""
        if not self._dirty:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "source_id": self._source_id,
            "model_id": self.model_id,
            "vectors": self._vectors,
        }
        tmp_path = self._path.with_name(self._path.name + ".tmp")
        tmp_path.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(tmp_path, self._path)
        self._dirty = False


def run_chunk_embedding(
    source_path: str | Path,
    embedder: Embedder | None = None,
    chunks_dir: Path | None = None,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
    chunk_min: int = CHUNK_MIN,
    chunk_max: int = CHUNK_MAX,
    chunk_cache_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """Run the embedding-based chunk stage on `source_path` (issue #151,
    PRD §5 stage 4 / §7.7 / §8 P0-4): read the persisted structural tree
    (`data/trees/<source_id>.json`, never re-running docling/Unstructured --
    `axial.extract.load_persisted_tree`), and for each prose section not
    skipped as garbage, split its ROUTED body (issue #167, PRD §7.8 --
    `_routed_section_body`: prose-labeled blocks only, apparatus dropped and
    logged, artifact excluded) into bounded chunks (see
    `_chunk_section_text`) and write every record to
    `data/chunks/<source_id>.jsonl` in section-then-position order (PRD
    §7.7). No text-generating LLM call anywhere in this path -- `embedder`
    defaults to `get_embedder()` (an `AXIAL_EMBEDDER`-selected, offline
    embedder), never an `LLMClient`.

    `chunk_min`/`chunk_max` (issue #152) override the band guard's default
    `[CHUNK_MIN, CHUNK_MAX]`, threaded straight through to
    `_chunk_section_text`. This is what makes a band SWEEP possible at all:
    re-running with a different band on the same source reshapes the split
    from the SAME underlying sentence embeddings (see below), it does not
    change what "the embeddings" are.

    Embedding cache (issue #152, PRD §5 stage 4 / §7.7's "cheap band
    sweeps"): the injected/resolved `embedder` is wrapped in a
    `_CachingEmbedder` (see its docstring for the full design -- key,
    on-disk location, why per-sentence memoization makes every re-embed
    site free on a warm run) BEFORE it reaches `_chunk_section_text` /
    `_split_group_to_max`, so this method's own callers never see the
    wrapping and every downstream `encode` call is transparently
    cache-backed. `chunk_cache_dir` overrides the cwd-relative default
    (`data/chunk_cache/`, `_default_chunk_cache_dir`), mirroring
    `chunks_dir`'s own override seam. The cache is flushed to disk after
    every section (not just once at the end), so a mid-pass failure still
    leaves already-computed embeddings durably cached for the next attempt
    -- cheap since a flush after an all-cache-hit section is a no-op (see
    `_CachingEmbedder.flush`).

    Overwrites `<source_id>.jsonl` cleanly on every call (idempotent on the
    same source bytes -- deterministic tree read + deterministic embedder +
    deterministic band guard yields byte-identical output on a re-run,
    whether or not the embedding cache was warm: the cache is a pure
    performance layer, never changing chunk output).

    Raises `MissingSourceError` if `source_path` doesn't exist, or
    `MissingTreeError` if no persisted tree exists yet for its source_id --
    this stage never runs extraction itself; the caller must run
    `axial extract` first.
    """
    path = Path(source_path)
    try:
        source_id = compute_source_id(path)
    except _EnvelopeMissingSourceError as exc:
        raise MissingSourceError(exc) from exc

    tp = tree_path(source_id)
    if not tp.exists():
        raise MissingTreeError(tp)
    tree = load_persisted_tree(tp)

    if embedder is None:
        embedder = get_embedder(config_path)

    if chunk_cache_dir is None:
        chunk_cache_dir = _default_chunk_cache_dir()
    embedder = _CachingEmbedder(embedder, source_id, chunk_cache_dir)

    if chunks_dir is None:
        chunks_dir = _default_chunks_dir(config_path)
    out_path = chunks_checkpoint_path(source_id, chunks_dir)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    sections = [node for node in _section_nodes(tree) if not _is_back_matter(node.get("text", ""))]

    skips_path = chunks_skips_sidecar_path(source_id, chunks_dir)
    skip_records: list[dict[str, Any]] = []

    all_records: list[dict[str, Any]] = []
    with out_path.open("w", encoding="utf-8") as handle:
        for section in sections:
            body_lines, apparatus_drops = _routed_section_body(section)
            skip_records.extend(apparatus_drops)
            if not body_lines:
                continue  # no chunkable prose in this section -- zero records

            section_label = section.get("text", "")
            section_order = section.get("order", "")
            body_text = "\n".join(body_lines)

            skip_reason = _garbage_section_skip_reason(body_text)
            if skip_reason is not None:
                print(f"chunk: skipping section {section_label!r}: {skip_reason}", file=sys.stderr)
                skip_records.append(
                    {
                        "section": section_label,
                        "section_order": section_order,
                        "reason": skip_reason,
                    }
                )
                continue

            chunk_texts = _chunk_section_text(body_text, embedder, chunk_min, chunk_max)
            section_records = build_chunk_records(
                source_id,
                section_order,
                section_label,
                [{"text": chunk_text} for chunk_text in chunk_texts],
            )
            for record in section_records:
                handle.write(json.dumps(record) + "\n")
            handle.flush()
            embedder.flush()
            all_records.extend(section_records)

    embedder.flush()
    if skip_records:
        with skips_path.open("w", encoding="utf-8") as handle:
            for record in skip_records:
                handle.write(json.dumps(record) + "\n")
    elif skips_path.exists():
        # A rerun on the same source bytes with zero skips this time must
        # not leave a stale sidecar from an earlier run (idempotency).
        skips_path.unlink()

    return all_records


# --- `axial chunk examine` (issue #153, PRD §7.7 / §8 P0-4b) ---------------
#
# Read-only inspection over the on-disk chunk artifact(s) produced by
# `run_chunk_embedding` above: total/per-source counts, the size
# distribution, boundary sanity, and garbage-skip reporting (from the
# `.skips.jsonl` sidecar). Pure file I/O + arithmetic -- constructs no
# embedder and no LLM client, so it costs zero LLM/embedding spend and can
# run any time after a chunk run exists.

EXAMINE_SAMPLE_SIZE = 5


@dataclass
class ExamineSkip:
    """One garbage-skipped section, read verbatim from a source's
    `.skips.jsonl` sidecar (see `chunks_skips_sidecar_path`)."""

    source_id: str
    section: str
    section_order: str
    reason: str


@dataclass
class ExamineSample:
    """One sampled chunk text, shown with its own identifying fields so an
    eyeball sample can be traced back to its record (PRD §7.7)."""

    source_id: str
    chunk_id: str
    section: str
    text: str


@dataclass
class ExamineStats:
    """Aggregate chunk-quality stats over every chunk artifact under a
    chunks dir (`examine_chunks`'s return value), formatted for display by
    `format_examine_report`."""

    total: int
    per_source: dict[str, int] = field(default_factory=dict)
    min_size: float = 0
    max_size: float = 0
    mean_size: float = 0
    median_size: float = 0
    above_max: int = 0
    below_min: int = 0
    split_sections: int = 0
    skips: list[ExamineSkip] = field(default_factory=list)
    samples: list[ExamineSample] = field(default_factory=list)


def examine_chunks(
    chunks_dir: Path,
    chunk_min: int = CHUNK_MIN,
    chunk_max: int = CHUNK_MAX,
    sample_size: int = EXAMINE_SAMPLE_SIZE,
) -> ExamineStats:
    """Read every `<source_id>.jsonl` chunk artifact under `chunks_dir`
    (excluding `*.skips.jsonl` sidecars -- those are read separately, per
    source, for garbage-skip reporting) and aggregate the stats `axial
    chunk examine` reports: total + per-source counts, the size
    distribution (min/max/mean/median over `text` lengths), boundary
    sanity (chunks above `chunk_max`, chunks below `chunk_min`, sections
    split into multiple chunks -- grouped by (source_id, section_order)),
    sections skipped as garbage with their reasons, and a chunk-text
    sample. Pure read: never opens any chunks-dir file for writing.
    Returns all-zero/empty stats when `chunks_dir` has no chunk artifacts
    (including when it does not exist at all).

    Raises `ChunkArtifactCorruptError` if any line of a main `.jsonl`
    artifact or a `.skips.jsonl` sidecar is not valid JSON -- examine is a
    diagnostic tool, so corruption is surfaced loudly rather than silently
    skipped (mirroring `load_chunk_checkpoint`'s non-final-line behavior)."""
    per_source: dict[str, int] = {}
    sizes: list[int] = []
    above_max = 0
    below_min = 0
    section_counts: dict[tuple[str, str], int] = {}
    skips: list[ExamineSkip] = []
    samples: list[ExamineSample] = []

    if chunks_dir.is_dir():
        jsonl_paths = sorted(
            p for p in chunks_dir.glob("*.jsonl") if not p.name.endswith(".skips.jsonl")
        )
    else:
        jsonl_paths = []

    for path in jsonl_paths:
        source_id = path.stem
        count = 0
        with path.open("r", encoding="utf-8") as handle:
            for line_no, line in enumerate(handle, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ChunkArtifactCorruptError(path, line_no, exc) from exc
                count += 1
                text = record.get("text", "")
                size = len(text)
                sizes.append(size)
                if size > chunk_max:
                    above_max += 1
                if size < chunk_min:
                    below_min += 1
                section_order = str(record.get("section_order", ""))
                key = (source_id, section_order)
                section_counts[key] = section_counts.get(key, 0) + 1
                if len(samples) < sample_size:
                    samples.append(
                        ExamineSample(
                            source_id=source_id,
                            chunk_id=str(record.get("chunk_id", "")),
                            section=str(record.get("section", "")),
                            text=text,
                        )
                    )
        per_source[source_id] = count

        skips_path = chunks_skips_sidecar_path(source_id, chunks_dir)
        if skips_path.is_file():
            with skips_path.open("r", encoding="utf-8") as handle:
                for line_no, line in enumerate(handle, start=1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        skip_record = json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise ChunkArtifactCorruptError(skips_path, line_no, exc) from exc
                    skips.append(
                        ExamineSkip(
                            source_id=source_id,
                            section=str(skip_record.get("section", "")),
                            section_order=str(skip_record.get("section_order", "")),
                            reason=str(skip_record.get("reason", "")),
                        )
                    )

    total = len(sizes)
    split_sections = sum(1 for group_count in section_counts.values() if group_count > 1)

    if sizes:
        min_size: float = min(sizes)
        max_size: float = max(sizes)
        mean_size = statistics.mean(sizes)
        median_size = statistics.median(sizes)
    else:
        min_size = max_size = mean_size = median_size = 0

    return ExamineStats(
        total=total,
        per_source=per_source,
        min_size=min_size,
        max_size=max_size,
        mean_size=mean_size,
        median_size=median_size,
        above_max=above_max,
        below_min=below_min,
        split_sections=split_sections,
        skips=skips,
        samples=samples,
    )


def format_examine_report(
    stats: ExamineStats, chunk_min: int = CHUNK_MIN, chunk_max: int = CHUNK_MAX
) -> str:
    """Render `ExamineStats` into a human-readable report (PRD §7.7).
    Format/wording is left to the implementer (mirroring `run_chunk_
    embedding`'s stderr skip messages) -- only that every listed number is
    present, matches the fixture, and appears near its own label."""
    lines: list[str] = []

    lines.append(
        f"chunk examine: {stats.total} total chunk(s) across {len(stats.per_source)} source(s)"
    )
    for source_id in sorted(stats.per_source):
        lines.append(f"  {source_id}: {stats.per_source[source_id]} chunk(s)")

    lines.append("")
    lines.append(
        "size distribution (chars): "
        f"min={stats.min_size} max={stats.max_size} "
        f"mean={float(stats.mean_size):.1f} median={float(stats.median_size):.1f}"
    )

    lines.append("")
    lines.append(
        f"boundary sanity: {stats.above_max} chunk(s) above max (CHUNK_MAX={chunk_max}), "
        f"{stats.below_min} chunk(s) below min (CHUNK_MIN={chunk_min}), "
        f"{stats.split_sections} section(s) split into multiple chunks"
    )

    lines.append("")
    lines.append(f"sections skipped as garbage: {len(stats.skips)}")
    for skip in stats.skips:
        lines.append(
            f"  [{skip.source_id}] {skip.section!r} (order {skip.section_order}): {skip.reason}"
        )

    lines.append("")
    lines.append("chunk-text sample:")
    if not stats.samples:
        lines.append("  (no chunks to sample)")
    for sample in stats.samples:
        preview = sample.text if len(sample.text) <= 200 else sample.text[:200] + "..."
        lines.append(f"  [{sample.source_id}] {sample.chunk_id} {sample.section!r}: {preview}")

    return "\n".join(lines)
