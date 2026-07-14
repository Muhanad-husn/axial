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

The retired LLM-echo chunker (`run_chunk`, issue #17 slice 05: one LLM call
per section against the stored envelope) is REMOVED as of slice 04 -- it is
no longer reachable from this module at all.

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
from axial.nonprose_guard import MAX_NON_ALPHA_RATIO

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


def _prose_text_lines(node: dict) -> list[str]:
    """Collect a node's own text plus all descendants' text, in order --
    prose nodes only (never artifact nodes like tables/pictures), since this
    pass produces prose chunks (PRD §5 stage 4, "Output: prose chunks")."""
    lines = []
    if node.get("type") == "prose":
        text = node.get("text")
        if text:
            lines.append(text)
    for child in node.get("children", []):
        lines.extend(_prose_text_lines(child))
    return lines


def _section_body_lines(node: dict) -> list[str]:
    """A section node's body text lines (excluding its own heading)."""
    return [line for child in node.get("children", []) for line in _prose_text_lines(child)]


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
    this module can select implements `encode`."""

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
    """

    def __init__(self, dim: int = _HASHING_EMBEDDER_DIM) -> None:
        self._dim = dim

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
    never skipped). Deliberately does not reuse
    `axial.nonprose_guard.non_prose_skip_reason` directly, since that
    function's size arm would skip on size too; this stage's own MAX-side
    band guard (`_split_group_to_max`) is what handles size instead."""
    char_count = len(text)
    if not char_count:
        return None
    non_alpha_ratio = sum(1 for c in text if not c.isalpha()) / char_count
    if non_alpha_ratio > max_non_alpha_ratio:
        return f"high non-alpha ratio ({non_alpha_ratio:.1%})"
    return None


def run_chunk_embedding(
    source_path: str | Path,
    embedder: Embedder | None = None,
    chunks_dir: Path | None = None,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
) -> list[dict[str, Any]]:
    """Run the embedding-based chunk stage on `source_path` (issue #151,
    PRD §5 stage 4 / §7.7 / §8 P0-4): read the persisted structural tree
    (`data/trees/<source_id>.json`, never re-running docling/Unstructured --
    `axial.extract.load_persisted_tree`), and for each prose section not
    skipped as garbage, split its body into bounded chunks (see
    `_chunk_section_text`) and write every record to
    `data/chunks/<source_id>.jsonl` in section-then-position order (PRD
    §7.7). No text-generating LLM call anywhere in this path -- `embedder`
    defaults to `get_embedder()` (an `AXIAL_EMBEDDER`-selected, offline
    embedder), never an `LLMClient`.

    Overwrites `<source_id>.jsonl` cleanly on every call (idempotent on the
    same source bytes -- deterministic tree read + deterministic embedder +
    deterministic band guard yields byte-identical output on a re-run).

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

    if chunks_dir is None:
        chunks_dir = _default_chunks_dir(config_path)
    out_path = chunks_checkpoint_path(source_id, chunks_dir)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    sections = [node for node in _section_nodes(tree) if not _is_back_matter(node.get("text", ""))]

    all_records: list[dict[str, Any]] = []
    with out_path.open("w", encoding="utf-8") as handle:
        for section in sections:
            body_lines = _section_body_lines(section)
            if not body_lines:
                continue  # no chunkable prose in this section -- zero records

            section_label = section.get("text", "")
            section_order = section.get("order", "")
            body_text = "\n".join(body_lines)

            skip_reason = _garbage_section_skip_reason(body_text)
            if skip_reason is not None:
                print(f"chunk: skipping section {section_label!r}: {skip_reason}", file=sys.stderr)
                continue

            chunk_texts = _chunk_section_text(body_text, embedder)
            section_records = build_chunk_records(
                source_id,
                section_order,
                section_label,
                [{"text": chunk_text} for chunk_text in chunk_texts],
            )
            for record in section_records:
                handle.write(json.dumps(record) + "\n")
            handle.flush()
            all_records.extend(section_records)

    return all_records
