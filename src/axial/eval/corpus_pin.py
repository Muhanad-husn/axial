"""Corpus-pin manifest: a committed, reproducible corpus reference (issue
#248, specs/PHASE-B.md §7.12, §8 P0-10).

Scores are only comparable across two runs if both ran against the same
corpus. Because all of `data/` is gitignored (DEC-23), the pin is a
**manifest + hashes, not a commit**: `write_pin` computes and writes
`evals/corpus_pin/<name>.json` (a path that IS committed -- ids and hashes
only, never source prose) carrying three fields:

- `sources` -- one entry per `data/envelopes/*.json` envelope, each with the
  envelope's own `source_id` and a `content_hash` of the **raw ingested
  source file itself** (§7.12, docs/eval/01-answer-quality.md: "content hash
  of the ingested input") -- read from `data/sources/` (the durable operator
  convention, see docs/postmortem/gold-run-2026-07/canary-run-runbook.md),
  resolved from the envelope's own `source_id` stem. The hash reuses
  `axial.envelope.content_digest`, the exact primitive `compute_source_id`
  already hashes a source's bytes with, so this module never invents a
  second hashing convention. This is deliberately NOT a hash of the
  envelope JSON: the envelope is an LLM-produced, nondeterministic output
  (regenerated routinely -- #235, #241, the GLM trial) -- hashing it would
  make `content_hash` move on every regen even when the underlying source
  never changed, collapsing the provenance triple's what-went-in slot into
  a copy of an already-nondeterministic what-came-out. A source file that
  cannot be found (or resolves ambiguously) under `data/sources/` is a
  loud failure (`MissingSourceFileError`/`AmbiguousSourceFileError`), never
  a silent fallback to the envelope hash or to the `source_id` digest.
- `ingest_code_sha` -- the axial checkout's own current git HEAD (code
  provenance: "the commit the Phase-A pipeline ran at", §7.12). Resolved
  from this module's own file location (`_repo_root`), never from the
  calling process's working directory -- `axial pin write` is routinely run
  from a vault/envelopes directory that is not itself a git checkout at
  all (e.g. an operator's data root), and the SHA must still name the code.
  A repository state where the SHA cannot be read (no `git`, not a
  checkout, no commits yet) fails loudly (`GitShaUnavailableError`) rather
  than ever writing a pin with a null or placeholder SHA.
- `vault_snapshot_hash` -- a single sha256 hex digest over every
  `data/vault/prose/*.md` note's `(chunk_id, tags)` pair, sorted by
  `chunk_id` so filesystem enumeration order never affects it. The tag
  projection (`TAG_AXES`) covers exactly the schema's tag axes and
  deliberately excludes `chunk_text` and `source_meta` (DEC-23) -- the
  manifest is committed to the repo, so it must never be able to carry
  source prose. Artifact notes (`data/vault/artifacts/`) are out of this
  slice's projection (plan: "the §7.12 minimum is chunk_ids + tags; widening
  the projection is a later, measured decision").

Byte-identical reruns. `write_pin` serializes with `json.dumps(...,
indent=2, sort_keys=True)` plus a trailing newline (the same convention
`axial.envelope.write_envelope` and `axial.eval.run_eval` already use) and
writes no timestamp, no random id, and nothing whose order is left to
filesystem/dict iteration -- every collection is explicitly sorted before
hashing or serializing. An unchanged vault + unchanged raw sources
(envelopes may be freely regenerated, per above) + an unchanged HEAD
therefore write a byte-identical file on every rerun.

LLM-free by construction: this module calls no model and no embedding
client on any path -- it only reads JSON/YAML/Markdown already on disk and
shells `git rev-parse HEAD`.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

import yaml

from axial.envelope import content_digest, _default_envelopes_dir
from axial.intake import SUPPORTED_EXTENSIONS
from axial.llm import DEFAULT_PIPELINE_CONFIG_PATH
from axial.paths import default_sources_dir as _default_sources_dir
from axial.vault import _default_vault_dir

# The default write location (§7.12: "committed under evals/corpus_pin/").
# Deliberately a plain cwd-relative path -- like every other data/config
# directory in this codebase, `axial pin write` exposes no
# `--evals-dir` flag and reads no env-var override (see the outer
# acceptance test's isolation-seam docstring).
EVALS_DIR = Path("evals") / "corpus_pin"

# `SOURCES_DIR`/`default_sources_dir` now live in `axial.paths` (issue
# #281); the latter is imported above as `_default_sources_dir`, so this
# module -- like `axial.vault` for `VAULT_DIR`/`_default_vault_dir` -- has
# exactly one owner of the config-path resolution rather than a second,
# independently-agreeing copy of it.

# The envelope's own `source_id` shape is `f"{path.stem}-{digest[:12]}"`
# (axial.envelope.compute_source_id) -- a stem, a literal hyphen, then
# exactly 12 lowercase hex digits. Anchored at the END of the string (not
# split on the first/last hyphen) so a stem that itself contains hyphens
# (routine -- e.g. "tilly-from-mobilization-to-revolution") is recovered
# whole.
_SOURCE_ID_PATTERN = re.compile(r"^(?P<stem>.+)-(?P<digest12>[0-9a-f]{12})$")

# The tag-axis frontmatter keys the vault snapshot hash projects each note
# onto (§7.12: "chunk_ids + tags, never chunk_text", DEC-23). Deliberately
# excludes `chunk_id` itself (carried as the pair's own key, not part of the
# tag payload), `chunk_text`, and `source_meta` -- a note frontmatter key
# not in this tuple is silently excluded from the hash, so an unrelated
# future frontmatter addition can't unintentionally widen what the pin
# tracks.
TAG_AXES = (
    "role_in_argument",
    "field",
    "claim_type",
    "theory_school",
    "empirical_scope",
    "polities_touched",
)


class CorpusPinError(Exception):
    """Base class for all corpus-pin errors."""


class MissingVaultDirError(CorpusPinError):
    """Raised when the vault directory the snapshot hash reads from does
    not exist."""

    def __init__(self, path: Path):
        self.path = path
        super().__init__(f"no vault directory found at {path}; run the ingestion pipeline first")


class MissingEnvelopesDirError(CorpusPinError):
    """Raised when the envelopes directory the source list reads from does
    not exist."""

    def __init__(self, path: Path):
        self.path = path
        super().__init__(f"no envelopes directory found at {path}; run `axial envelope` first")


class MalformedEnvelopeError(CorpusPinError):
    """Raised when an envelope file under `<envelopes_dir>/*.json` is not
    parseable JSON -- a corrupted or hand-edited envelope, never silently
    skipped or left to surface as a bare `json.JSONDecodeError` traceback."""

    def __init__(self, path: Path, cause: Exception):
        self.path = path
        self.cause = cause
        super().__init__(f"malformed envelope JSON at {path}: {cause}")


class UnresolvableSourceIdError(CorpusPinError):
    """Raised when an envelope's own `source_id` does not match the shape
    `compute_source_id` always produces (`{stem}-{12 hex digits}`), so no
    filename stem can be recovered to resolve the raw source file by."""

    def __init__(self, source_id: str, envelope_path: Path):
        self.source_id = source_id
        self.envelope_path = envelope_path
        super().__init__(
            f"envelope {envelope_path} carries a source_id {source_id!r} that does not match "
            f"the expected '<stem>-<12 hex digits>' shape (compute_source_id); cannot resolve "
            f"its raw source file"
        )


class MissingSourceFileError(CorpusPinError):
    """Raised when no raw source file matching an envelope's source_id stem
    (any of `axial.intake.SUPPORTED_EXTENSIONS`) exists under the sources
    directory. `content_hash` is never silently backfilled from the
    envelope hash or the source_id digest instead (§7.12, founder
    adjudication on issue #248: "a provenance tool that silently degrades
    its provenance is worse than one that stops")."""

    def __init__(self, source_id: str, sources_dir: Path):
        self.source_id = source_id
        self.sources_dir = sources_dir
        super().__init__(
            f"no raw source file found for source_id {source_id!r} under {sources_dir} "
            f"(looked for {', '.join(sorted(SUPPORTED_EXTENSIONS))}); place the original "
            f"source file there before running `axial pin write`"
        )


class AmbiguousSourceFileError(CorpusPinError):
    """Raised when more than one raw source file matches an envelope's
    source_id stem under the sources directory (e.g. both a `.pdf` and a
    `.docx` with the same stem) -- an unresolvable ambiguity, never
    silently resolved by picking one."""

    def __init__(self, source_id: str, sources_dir: Path, candidates: list[Path]):
        self.source_id = source_id
        self.sources_dir = sources_dir
        self.candidates = candidates
        named = ", ".join(str(candidate) for candidate in candidates)
        super().__init__(
            f"ambiguous raw source file for source_id {source_id!r} under {sources_dir}: "
            f"found {len(candidates)} candidates ({named})"
        )


class MalformedNoteError(CorpusPinError):
    """Raised when a vault prose note under `<vault_dir>/prose/` is not a
    well-formed `---`-delimited YAML-frontmatter note (`axial.vault.render_note`'s
    own shape) -- a corrupted or hand-edited note (no closing '---'
    delimiter, unparseable frontmatter YAML, or frontmatter that doesn't
    parse to a mapping), never silently skipped."""

    def __init__(self, path: Path, reason: str | None = None):
        self.path = path
        detail = reason or "no closing '---' frontmatter delimiter"
        super().__init__(f"malformed vault note ({detail}): {path}")


class GitShaUnavailableError(CorpusPinError):
    """Raised when the axial checkout's own git HEAD commit cannot be
    read -- e.g. `git` is not installed, the checkout is not (or is no
    longer) a git repository, or it has no commits yet. Never silently
    substituted with a null or placeholder SHA (plan, inner unit test 2)."""

    def __init__(self, cause: Exception):
        self.cause = cause
        super().__init__(f"could not resolve the axial checkout's own git HEAD commit: {cause}")


def _repo_root() -> Path:
    """The axial checkout's own root directory, derived from this module's
    own file location -- NOT from `Path.cwd()`. `axial pin write` is
    designed to run with its cwd set to an arbitrary vault/envelopes/evals
    data root (see the outer acceptance test's isolation-seam docstring),
    so `ingest_code_sha` must resolve the CODE's commit independently of
    wherever that data root happens to be (§7.12: "the commit the Phase-A
    pipeline ran at" is code provenance, not data location)."""
    # src/axial/eval/corpus_pin.py -> axial/eval -> axial -> src -> repo root
    return Path(__file__).resolve().parent.parent.parent.parent


def ingest_code_sha(repo_root: Path | None = None) -> str:
    """The axial checkout's own current git HEAD commit SHA (§7.12,
    "ingest-code SHA"). Fails loudly (`GitShaUnavailableError`) rather than
    ever returning a null/placeholder value."""
    root = repo_root if repo_root is not None else _repo_root()
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise GitShaUnavailableError(exc) from exc

    sha = result.stdout.strip()
    if not sha:
        raise GitShaUnavailableError(RuntimeError("`git rev-parse HEAD` returned empty output"))
    return sha


def _stem_from_source_id(source_id: str, envelope_path: Path) -> str:
    """Recover the raw source file's filename stem from an envelope's own
    `source_id` (`compute_source_id`'s `{stem}-{12 hex digits}` shape),
    anchored so a stem that itself contains hyphens survives intact."""
    match = _SOURCE_ID_PATTERN.match(source_id)
    if match is None:
        raise UnresolvableSourceIdError(source_id, envelope_path)
    return match.group("stem")


def _resolve_source_file(source_id: str, stem: str, sources_dir: Path) -> Path:
    """The one raw source file under `sources_dir` whose filename stem is
    `stem` and whose extension is one of `axial.intake.SUPPORTED_EXTENSIONS`.
    Fails loudly -- `MissingSourceFileError` on zero matches,
    `AmbiguousSourceFileError` on more than one -- rather than ever falling
    back to a different hash source (founder adjudication, issue #248)."""
    candidates = sorted(
        sources_dir / f"{stem}{extension}"
        for extension in SUPPORTED_EXTENSIONS
        if (sources_dir / f"{stem}{extension}").is_file()
    )
    if not candidates:
        raise MissingSourceFileError(source_id, sources_dir)
    if len(candidates) > 1:
        raise AmbiguousSourceFileError(source_id, sources_dir, candidates)
    return candidates[0]


def _build_sources(envelopes_dir: Path, sources_dir: Path) -> list[dict[str, str]]:
    """One entry per `<envelopes_dir>/*.json` envelope: its own `source_id`
    plus a `content_hash` of the **raw ingested source file** under
    `sources_dir`, reusing `axial.envelope.content_digest` -- the same
    hashing primitive `compute_source_id` already hashes source bytes with
    (§7.12: "reusing envelope.compute_source_id()'s existing hashing
    path"), applied here to the actual input rather than the (nondeterministic,
    LLM-produced) envelope output -- see the module docstring. Sorted by
    `source_id` so filesystem enumeration order never affects the result.
    Raises `MalformedEnvelopeError` -- naming the envelope's own path --
    both when a `*.json` file isn't parseable JSON and when it parses to
    something other than a mapping (e.g. a bare JSON list/scalar), mirroring
    `_split_frontmatter`'s identical non-mapping guard on the note path."""
    if not envelopes_dir.is_dir():
        raise MissingEnvelopesDirError(envelopes_dir)

    entries = []
    for envelope_path in envelopes_dir.glob("*.json"):
        try:
            envelope = json.loads(envelope_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise MalformedEnvelopeError(envelope_path, exc) from exc

        if not isinstance(envelope, dict):
            raise MalformedEnvelopeError(
                envelope_path,
                TypeError(f"envelope did not parse to a mapping, got {type(envelope).__name__}"),
            )

        source_id = envelope.get("source_id") or envelope_path.stem
        stem = _stem_from_source_id(source_id, envelope_path)
        source_path = _resolve_source_file(source_id, stem, sources_dir)
        entries.append({"source_id": source_id, "content_hash": content_digest(source_path)})

    entries.sort(key=lambda entry: entry["source_id"])
    return entries


def _split_frontmatter(text: str, note_path: Path) -> dict[str, Any]:
    """Parse a vault note's leading `---`-delimited YAML frontmatter block
    (`axial.vault.render_note`'s own shape) into a mapping. Raises
    `MalformedNoteError` -- naming the note's own path -- when the note
    doesn't open with, or never closes, a frontmatter block; when the
    frontmatter YAML itself doesn't parse; or when it parses to something
    other than a mapping (e.g. a bare YAML list) -- never silently skipped,
    and never left to escape as a bare `yaml.YAMLError`/`AttributeError`
    traceback naming no file."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise MalformedNoteError(note_path)

    closing_index = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            closing_index = index
            break
    if closing_index is None:
        raise MalformedNoteError(note_path)

    frontmatter_text = "\n".join(lines[1:closing_index])
    try:
        data = yaml.safe_load(frontmatter_text)
    except yaml.YAMLError as exc:
        raise MalformedNoteError(note_path, f"invalid frontmatter YAML: {exc}") from exc

    if data is None:
        return {}
    if not isinstance(data, dict):
        raise MalformedNoteError(
            note_path, f"frontmatter did not parse to a mapping, got {type(data).__name__}"
        )
    return data


def _tag_projection(frontmatter: dict[str, Any]) -> dict[str, Any]:
    """The snapshot-hash tag payload for one note: exactly the schema tag
    axes present in `frontmatter` (`TAG_AXES`) -- never `chunk_text`, never
    `source_meta` (DEC-23)."""
    return {axis: frontmatter[axis] for axis in TAG_AXES if axis in frontmatter}


def _collect_snapshot_pairs(vault_dir: Path) -> list[list[Any]]:
    """Every `<vault_dir>/prose/*.md` note's `(chunk_id, tags)` pair, sorted
    by `chunk_id` (§7.12, plan inner unit test 3) -- so filesystem
    enumeration order never affects the result. Split out from
    `_build_vault_snapshot_hash` as its own, directly testable seam: a unit
    test can assert this list's own sort order without depending on
    whichever order the filesystem happens to hand back `Path.glob` (that
    order already happens to be alphabetical on common filesystems, which
    would make a test that merely varies WRITE order pass regardless of
    whether the `sort` below is even present). `<vault_dir>/prose/` absent
    (a vault dir that exists but holds no prose notes yet, e.g. only
    artifacts) yields the empty list; `vault_dir` itself absent is the loud
    failure (`MissingVaultDirError`)."""
    if not vault_dir.is_dir():
        raise MissingVaultDirError(vault_dir)

    prose_dir = vault_dir / "prose"
    pairs: list[list[Any]] = []
    if prose_dir.is_dir():
        for note_path in prose_dir.glob("*.md"):
            frontmatter = _split_frontmatter(note_path.read_text(encoding="utf-8"), note_path)
            chunk_id = frontmatter.get("chunk_id") or note_path.stem
            pairs.append([chunk_id, _tag_projection(frontmatter)])

    pairs.sort(key=lambda pair: pair[0])
    return pairs


def _build_vault_snapshot_hash(vault_dir: Path) -> str:
    """A single sha256 hex digest over `_collect_snapshot_pairs(vault_dir)`,
    canonically serialized (sorted keys, compact separators) so the digest
    depends only on the pairs' own content and sort order, never on
    incidental JSON formatting."""
    pairs = _collect_snapshot_pairs(vault_dir)
    canonical = json.dumps(pairs, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def write_pin(
    name: str,
    vault_dir: Path | None = None,
    envelopes_dir: Path | None = None,
    sources_dir: Path | None = None,
    evals_dir: Path | None = None,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
    repo_root: Path | None = None,
) -> Path:
    """Compute and write the corpus-pin manifest to `<evals_dir>/<name>.json`
    (default `evals/corpus_pin/<name>.json`), returning the written path.

    `vault_dir`/`envelopes_dir`/`sources_dir` default to
    `config/pipeline.yaml`'s `paths.vault_dir`/`paths.envelopes_dir`/
    `paths.sources_dir`, all three resolved through `axial.paths` (issue
    #281 -- `_default_vault_dir`/`_default_sources_dir` from `axial.paths`,
    `_default_envelopes_dir` from `axial.envelope`), falling back to
    `data/vault`/`data/envelopes`/`data/sources` when the file/key is
    absent. `evals_dir` defaults to `EVALS_DIR` -- there is no config key
    or CLI flag for it (this codebase exposes no `--evals-dir` anywhere;
    see the module docstring).

    Deterministic and LLM-free: reruns over an unchanged vault + envelopes
    + raw sources + git HEAD write a byte-identical file (module
    docstring).
    """
    if vault_dir is None:
        vault_dir = _default_vault_dir(config_path)
    if envelopes_dir is None:
        envelopes_dir = _default_envelopes_dir(config_path)
    if sources_dir is None:
        sources_dir = _default_sources_dir(config_path)
    if evals_dir is None:
        evals_dir = EVALS_DIR

    manifest = {
        "sources": _build_sources(envelopes_dir, sources_dir),
        "ingest_code_sha": ingest_code_sha(repo_root),
        "vault_snapshot_hash": _build_vault_snapshot_hash(vault_dir),
    }

    evals_dir.mkdir(parents=True, exist_ok=True)
    out_path = evals_dir / f"{name}.json"
    out_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return out_path
