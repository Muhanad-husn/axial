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
- `vault_snapshot_hash` -- a single sha256 hex digest over two things, in a
  stated order (§7.12, D6, issue #486): every `data/vault/prose/*.md`
  note's `chunk_id`, sorted ascending; and the **name-layer index** --
  `data/names/index.json`'s canonical name set, `data/names/alias_map.json`'s
  `version`, and the count of non-null disagreement records in
  `data/names/disagreements.jsonl`. The name layer belongs in the hash
  because it is retrieval substrate now: `find_names`, `get_name`,
  `name_neighbors`, `who_cites` and `who_argues_against` all read it, so two
  runs over identical prose but a different alias map can reach different
  evidence and are not comparable. The hash moves when a Gather or Reconcile
  run changes what the engine can find -- correct behaviour, not spurious
  invalidation. It **covers** the canonical name set without ever writing
  the names themselves into the committed manifest: a canonical name is a
  surface form a source wrote, so it is source-derived content and stays
  under gitignored `data/`, exactly as DEC-23 already requires for
  `chunk_text`. `generated_at` in either name-layer file never enters the
  hash -- both move on every rebuild whether or not the content changed.
  (STRUCK: the v0 projection was `(chunk_id, tags)` pairs over a fixed
  `TAG_AXES` tuple; Phase A v1 deleted every one of those tag axes, so the
  tags half of every pair had silently degraded to `{}` while still looking
  like it tracked something. Retired rather than left in place.)

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

from axial.checkpoint import load_checkpoint_records
from axial.envelope import content_digest, _default_envelopes_dir
from axial.intake import SUPPORTED_EXTENSIONS
from axial.llm import DEFAULT_PIPELINE_CONFIG_PATH
from axial.paths import default_names_dir as _default_names_dir
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


class MissingNamesDirError(CorpusPinError):
    """Raised when the name-layer directory the snapshot hash reads
    `index.json`/`alias_map.json`/`disagreements.jsonl` from does not
    exist -- the name layer is retrieval substrate now (§7.12, D6), so a
    missing name-layer directory is a misconfigured install, never silently
    treated as an empty name set."""

    def __init__(self, path: Path):
        self.path = path
        super().__init__(
            f"no name-layer directory found at {path}; run `axial names merge` and "
            f"`axial names gather` first"
        )


class MissingNameIndexError(CorpusPinError):
    """Raised when `<names_dir>/index.json` -- the canonical name set
    `axial names merge` writes -- does not exist."""

    def __init__(self, path: Path):
        self.path = path
        super().__init__(f"no name index found at {path}; run `axial names merge` first")


class MalformedNameIndexError(CorpusPinError):
    """Raised when `<names_dir>/index.json` is not parseable JSON, or does
    not parse to a mapping carrying a `names` list -- a corrupted or
    hand-edited index, never silently treated as an empty name set."""

    def __init__(self, path: Path, cause: Exception):
        self.path = path
        self.cause = cause
        super().__init__(f"malformed name index at {path}: {cause}")


class MissingAliasMapError(CorpusPinError):
    """Raised when `<names_dir>/alias_map.json` -- Reconcile's own output --
    does not exist."""

    def __init__(self, path: Path):
        self.path = path
        super().__init__(f"no alias map found at {path}; run `axial names merge` first")


class MalformedAliasMapError(CorpusPinError):
    """Raised when `<names_dir>/alias_map.json` is not parseable JSON, or
    does not parse to a mapping carrying a `version` key."""

    def __init__(self, path: Path, cause: Exception):
        self.path = path
        self.cause = cause
        super().__init__(f"malformed alias map at {path}: {cause}")


class MissingDisagreementsError(CorpusPinError):
    """Raised when `<names_dir>/disagreements.jsonl` -- Gather's own
    checkpoint of what it decided about every name -- does not exist."""

    def __init__(self, path: Path):
        self.path = path
        super().__init__(f"no disagreement records found at {path}; run `axial names gather` first")


class MalformedDisagreementsError(CorpusPinError):
    """Raised when a line of `<names_dir>/disagreements.jsonl` is not
    parseable JSON -- a corrupted or hand-edited checkpoint file, mirroring
    `MalformedEnvelopeError`'s identical guard on the envelope path (never
    silently skipped)."""

    def __init__(self, path: Path, line_no: int, cause: Exception):
        self.path = path
        self.line_no = line_no
        self.cause = cause
        super().__init__(f"disagreement record {path} is corrupt at line {line_no}: {cause}")


class MissingCorpusPinError(CorpusPinError):
    """Raised when `resolve_pin_id` finds no manifest under `evals_dir` at
    all -- `axial brief run` (issue #257, §7.12) needs a corpus pin to
    record every run against; a missing pin is a misconfigured install
    (`axial pin write <name>` was never run), never silently skipped."""

    def __init__(self, evals_dir: Path):
        self.evals_dir = evals_dir
        super().__init__(
            f"no corpus-pin manifest found under {evals_dir}; run `axial pin write <name>` first"
        )


class AmbiguousCorpusPinError(CorpusPinError):
    """Raised when `resolve_pin_id` finds more than one manifest under
    `evals_dir` -- reconciling/selecting among multiple pins is explicitly
    out of scope for issue #257 (§7.12's own "detecting a pin mismatch" is a
    separate, later concern), so an ambiguous directory fails loudly rather
    than guessing one."""

    def __init__(self, evals_dir: Path, candidates: list[Path]):
        self.evals_dir = evals_dir
        self.candidates = candidates
        named = ", ".join(str(candidate) for candidate in candidates)
        super().__init__(
            f"ambiguous corpus pin under {evals_dir}: found {len(candidates)} "
            f"manifests ({named}); name one explicitly (issue #257 scopes out "
            f"multi-pin reconciliation)"
        )


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


def _collect_chunk_ids(vault_dir: Path) -> list[str]:
    """Every `<vault_dir>/prose/*.md` note's `chunk_id`, sorted ascending
    (§7.12, D6) -- so filesystem enumeration order never affects the
    result. Split out from `_build_vault_snapshot_hash` as its own, directly
    testable seam: a unit test can assert this list's own sort order
    without depending on whichever order the filesystem happens to hand
    back `Path.glob` (that order already happens to be alphabetical on
    common filesystems, which would make a test that merely varies WRITE
    order pass regardless of whether the `sort` below is even present).
    `<vault_dir>/prose/` absent (a vault dir that exists but holds no prose
    notes yet, e.g. only artifacts) yields the empty list; `vault_dir`
    itself absent is the loud failure (`MissingVaultDirError`)."""
    if not vault_dir.is_dir():
        raise MissingVaultDirError(vault_dir)

    prose_dir = vault_dir / "prose"
    chunk_ids: list[str] = []
    if prose_dir.is_dir():
        for note_path in prose_dir.glob("*.md"):
            frontmatter = _split_frontmatter(note_path.read_text(encoding="utf-8"), note_path)
            chunk_ids.append(frontmatter.get("chunk_id") or note_path.stem)

    chunk_ids.sort()
    return chunk_ids


def _require_names_dir(names_dir: Path) -> None:
    """The one existence check every name-layer loader below shares --
    `MissingNamesDirError` names the whole directory rather than each
    caller independently re-deriving the same missing-file error for
    whichever of the three files it happens to read first."""
    if not names_dir.is_dir():
        raise MissingNamesDirError(names_dir)


def _load_canonical_names(names_dir: Path) -> list[str]:
    """`<names_dir>/index.json`'s canonical name set (`axial names merge`'s
    own output, §7.16), deduplicated and sorted ascending so list-write
    order never affects the hash. Missing/malformed `index.json` fails
    loudly (`MissingNameIndexError`/`MalformedNameIndexError`) rather than
    silently degrading to an empty set."""
    _require_names_dir(names_dir)
    index_path = names_dir / "index.json"
    if not index_path.is_file():
        raise MissingNameIndexError(index_path)
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise MalformedNameIndexError(index_path, exc) from exc

    if not isinstance(index, dict) or not isinstance(index.get("names"), list):
        raise MalformedNameIndexError(
            index_path, TypeError("expected a mapping with a 'names' list")
        )
    return sorted(set(index["names"]))


def _load_alias_map_version(names_dir: Path) -> Any:
    """`<names_dir>/alias_map.json`'s own `version` field (Reconcile's
    output, §7.16) -- moves whenever Reconcile's decisions are re-cut over
    an unchanged corpus, which is exactly the "what the engine can find"
    signal §7.12/D6 wants the pin to carry."""
    _require_names_dir(names_dir)
    alias_map_path = names_dir / "alias_map.json"
    if not alias_map_path.is_file():
        raise MissingAliasMapError(alias_map_path)
    try:
        alias_map = json.loads(alias_map_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise MalformedAliasMapError(alias_map_path, exc) from exc

    if not isinstance(alias_map, dict) or "version" not in alias_map:
        raise MalformedAliasMapError(alias_map_path, TypeError("expected a 'version' key"))
    return alias_map["version"]


def _count_non_null_disagreements(names_dir: Path) -> int:
    """The count of `<names_dir>/disagreements.jsonl` records whose own
    `disagreement` field is non-null (Gather's output, §7.18) -- reused via
    `axial.checkpoint.load_checkpoint_records` (the same JSONL-checkpoint
    primitive `axial.gather.load_disagreements` itself is built on), parsed
    directly here rather than through `axial.gather.load_disagreements`
    itself: that function's module pulls in the whole interrogate/
    materialize/LLM-client import chain for one dict comprehension this
    module has no other use for."""
    _require_names_dir(names_dir)
    disagreements_path = names_dir / "disagreements.jsonl"
    if not disagreements_path.is_file():
        raise MissingDisagreementsError(disagreements_path)

    records = load_checkpoint_records(disagreements_path, MalformedDisagreementsError)
    return sum(1 for record in records if record.get("disagreement") is not None)


def _build_vault_snapshot_hash(vault_dir: Path, names_dir: Path) -> str:
    """A single sha256 hex digest over two things, in a stated order
    (§7.12, D6): `_collect_chunk_ids(vault_dir)`, and the name-layer index
    (`_load_canonical_names`, `_load_alias_map_version`,
    `_count_non_null_disagreements`, all under `names_dir`) -- canonically
    serialized (sorted keys, compact separators) so the digest depends only
    on the inputs' own content, never on incidental JSON formatting or
    dict/filesystem iteration order. `generated_at` from either name-layer
    file is deliberately never read here, so it can never enter the hash."""
    payload = {
        "chunk_ids": _collect_chunk_ids(vault_dir),
        "canonical_names": _load_canonical_names(names_dir),
        "alias_map_version": _load_alias_map_version(names_dir),
        "disagreement_count": _count_non_null_disagreements(names_dir),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def write_pin(
    name: str,
    vault_dir: Path | None = None,
    envelopes_dir: Path | None = None,
    sources_dir: Path | None = None,
    names_dir: Path | None = None,
    evals_dir: Path | None = None,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
    repo_root: Path | None = None,
) -> Path:
    """Compute and write the corpus-pin manifest to `<evals_dir>/<name>.json`
    (default `evals/corpus_pin/<name>.json`), returning the written path.

    `vault_dir`/`envelopes_dir`/`sources_dir`/`names_dir` default to
    `config/pipeline.yaml`'s `paths.vault_dir`/`paths.envelopes_dir`/
    `paths.sources_dir`/`paths.names_dir`, all four resolved through
    `axial.paths` (issue #281 -- `_default_vault_dir`/`_default_sources_dir`/
    `_default_names_dir` from `axial.paths`, `_default_envelopes_dir` from
    `axial.envelope`), falling back to `data/vault`/`data/envelopes`/
    `data/sources`/`data/names` when the file/key is absent. `evals_dir`
    defaults to `EVALS_DIR` -- there is no config key or CLI flag for it
    (this codebase exposes no `--evals-dir` anywhere; see the module
    docstring).

    Deterministic and LLM-free: reruns over an unchanged vault + name layer
    + envelopes + raw sources + git HEAD write a byte-identical file
    (module docstring).
    """
    if vault_dir is None:
        vault_dir = _default_vault_dir(config_path)
    if envelopes_dir is None:
        envelopes_dir = _default_envelopes_dir(config_path)
    if sources_dir is None:
        sources_dir = _default_sources_dir(config_path)
    if names_dir is None:
        names_dir = _default_names_dir(config_path)
    if evals_dir is None:
        evals_dir = EVALS_DIR

    manifest = {
        "sources": _build_sources(envelopes_dir, sources_dir),
        "ingest_code_sha": ingest_code_sha(repo_root),
        "vault_snapshot_hash": _build_vault_snapshot_hash(vault_dir, names_dir),
    }

    evals_dir.mkdir(parents=True, exist_ok=True)
    out_path = evals_dir / f"{name}.json"
    out_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return out_path


def resolve_pin_id(evals_dir: Path | None = None) -> str:
    """The corpus-pin id `axial brief run` (issue #257, §7.3/§7.12) records
    every analysis record against: the filename stem of the sole `*.json`
    manifest under `evals_dir` (default `EVALS_DIR`). There is no separate
    "id" field inside the manifest itself (`write_pin`'s own three-field
    shape carries none) -- the pin's NAME, the one thing distinguishing
    `evals/corpus_pin/<name>.json` from another pin, is the natural id.

    Requires exactly one manifest to exist: zero is a misconfigured install
    (`MissingCorpusPinError` -- run `axial pin write <name>` first), more
    than one is ambiguous (`AmbiguousCorpusPinError` -- reconciling multiple
    pins is out of this slice's scope, left to a later, measured decision).
    """
    if evals_dir is None:
        evals_dir = EVALS_DIR
    evals_dir = Path(evals_dir)
    if not evals_dir.is_dir():
        raise MissingCorpusPinError(evals_dir)

    candidates = sorted(evals_dir.glob("*.json"))
    if not candidates:
        raise MissingCorpusPinError(evals_dir)
    if len(candidates) > 1:
        raise AmbiguousCorpusPinError(evals_dir, candidates)
    return candidates[0].stem
