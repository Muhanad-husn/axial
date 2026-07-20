"""Corpus-pin manifest: a committed, reproducible corpus reference (issue
#248, specs/PHASE-B.md §7.12, §8 P0-10).

Scores are only comparable across two runs if both ran against the same
corpus. Because all of `data/` is gitignored (DEC-23), the pin is a
**manifest + hashes, not a commit**: `write_pin` computes and writes
`evals/corpus_pin/<name>.json` (a path that IS committed -- ids and hashes
only, never source prose) carrying three fields:

- `sources` -- one entry per `data/envelopes/*.json` envelope, each with the
  envelope's own `source_id` and a `content_hash`. The hash reuses
  `axial.envelope.content_digest`, the exact primitive
  `compute_source_id` already hashes a source's bytes with, so this module
  never invents a second hashing convention. It hashes the persisted
  envelope file itself (a raw source file is never retained on disk past
  ingestion -- there is no other content available at pin-write time to
  hash), so a re-ingested-but-unchanged source's envelope, byte for byte,
  yields the same content_hash.
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
hashing or serializing. An unchanged vault + unchanged envelopes + an
unchanged HEAD therefore write a byte-identical file on every rerun.

LLM-free by construction: this module calls no model and no embedding
client on any path -- it only reads JSON/YAML/Markdown already on disk and
shells `git rev-parse HEAD`.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

import yaml

from axial.envelope import content_digest, _default_envelopes_dir
from axial.llm import DEFAULT_PIPELINE_CONFIG_PATH
from axial.vault import _default_vault_dir

# The default write location (§7.12: "committed under evals/corpus_pin/").
# Deliberately a plain cwd-relative path -- like every other data/config
# directory in this codebase, `axial pin write` exposes no
# `--evals-dir` flag and reads no env-var override (see the outer
# acceptance test's isolation-seam docstring).
EVALS_DIR = Path("evals") / "corpus_pin"

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


class MalformedNoteError(CorpusPinError):
    """Raised when a vault prose note under `<vault_dir>/prose/` is not a
    well-formed `---`-delimited YAML-frontmatter note (`axial.vault.render_note`'s
    own shape) -- a corrupted or hand-edited note, never silently skipped."""

    def __init__(self, path: Path):
        self.path = path
        super().__init__(f"malformed vault note (no closing '---' frontmatter delimiter): {path}")


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


def _build_sources(envelopes_dir: Path) -> list[dict[str, str]]:
    """One entry per `<envelopes_dir>/*.json` envelope: its own `source_id`
    plus a `content_hash` over the envelope file's own bytes, reusing
    `axial.envelope.content_digest` -- the same hashing primitive
    `compute_source_id` already hashes source bytes with (§7.12: "reusing
    envelope.compute_source_id()'s existing hashing path"). Sorted by
    `source_id` so filesystem enumeration order never affects the result."""
    if not envelopes_dir.is_dir():
        raise MissingEnvelopesDirError(envelopes_dir)

    entries = []
    for envelope_path in envelopes_dir.glob("*.json"):
        envelope = json.loads(envelope_path.read_text(encoding="utf-8"))
        source_id = envelope.get("source_id") or envelope_path.stem
        entries.append({"source_id": source_id, "content_hash": content_digest(envelope_path)})

    entries.sort(key=lambda entry: entry["source_id"])
    return entries


def _split_frontmatter(text: str, note_path: Path) -> dict[str, Any]:
    """Parse a vault note's leading `---`-delimited YAML frontmatter block
    (`axial.vault.render_note`'s own shape) into a mapping. Raises
    `MalformedNoteError` when the note doesn't open with -- or never
    closes -- a frontmatter block, rather than silently skipping it."""
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
    data = yaml.safe_load(frontmatter_text)
    return data or {}


def _tag_projection(frontmatter: dict[str, Any]) -> dict[str, Any]:
    """The snapshot-hash tag payload for one note: exactly the schema tag
    axes present in `frontmatter` (`TAG_AXES`) -- never `chunk_text`, never
    `source_meta` (DEC-23)."""
    return {axis: frontmatter[axis] for axis in TAG_AXES if axis in frontmatter}


def _build_vault_snapshot_hash(vault_dir: Path) -> str:
    """A single sha256 hex digest over every `<vault_dir>/prose/*.md`
    note's `(chunk_id, tags)` pair, in an order sorted by `chunk_id` (§7.12,
    plan inner unit test 3) -- so filesystem enumeration order never
    affects the hash. `<vault_dir>/prose/` absent (a vault dir that exists
    but holds no prose notes yet, e.g. only artifacts) hashes the empty
    list, deterministically; `vault_dir` itself absent is the loud failure
    (`MissingVaultDirError`)."""
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
    canonical = json.dumps(pairs, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def write_pin(
    name: str,
    vault_dir: Path | None = None,
    envelopes_dir: Path | None = None,
    evals_dir: Path | None = None,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
    repo_root: Path | None = None,
) -> Path:
    """Compute and write the corpus-pin manifest to `<evals_dir>/<name>.json`
    (default `evals/corpus_pin/<name>.json`), returning the written path.

    `vault_dir`/`envelopes_dir` default to `config/pipeline.yaml`'s
    `paths.vault_dir`/`paths.envelopes_dir` (mirroring `axial.vault`/
    `axial.envelope`'s own resolution), falling back to `data/vault`/
    `data/envelopes` when the file/key is absent. `evals_dir` defaults to
    `EVALS_DIR` -- there is no config key or CLI flag for it (this codebase
    exposes no `--evals-dir` anywhere; see the module docstring).

    Deterministic and LLM-free: reruns over an unchanged vault + envelopes
    + git HEAD write a byte-identical file (module docstring).
    """
    if vault_dir is None:
        vault_dir = _default_vault_dir(config_path)
    if envelopes_dir is None:
        envelopes_dir = _default_envelopes_dir(config_path)
    if evals_dir is None:
        evals_dir = EVALS_DIR

    manifest = {
        "sources": _build_sources(envelopes_dir),
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
