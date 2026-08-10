"""Published corpus snapshots (issue #684): `axial publish <version>` emits
an immutable `<snapshots_dir>/<version>/` directory, and a worker process
binds exactly one of them for its whole life.

**A snapshot is a whole corpus root, not one file.** The issue's own third
"done when" said the vault markdown is the human view rather than the query
surface; it is both. `axial.analyze.assembly.assemble_evidence` quotes every
cited passage out of `<vault>/prose/<chunk_id>.md`, and
`axial.query.names._name_page_from_store` reads the Gather disagreement
section off `<vault>/names/<name>.md`. `notes.db` is the index; the markdown
is the text. So a snapshot carries:

    <version>/manifest.json          the pin, the source list, the build date
    <version>/config/                pipeline.yaml (rewritten), lenses, domains
    <version>/evals/corpus_pin/      the pin manifest `resolve_pin_id` reads
    <version>/vault/                 prose, names, artifacts, names.jsonl, notes.db
    <version>/names/                 index, alias map, disagreements, embeddings
    <version>/envelopes/
    <version>/map/<map_pin>/         the argument map, when one is built

and deliberately does NOT carry `data/sources/` -- the raw, in-copyright
books. The only thing on the ask path that needs them is
`resolve_pinned_map_dir`, which hashes every source file to derive the
argument map's directory name; that hash is computed once here, at publish
time on the operator's own machine, recorded as `map_pin`, and handed to the
engine as the `map_pin` argument `run_brief` already accepts. The snapshot's
own `pipeline.yaml` points `sources_dir` at a directory inside the snapshot
that does not exist, so a leak fails inside the snapshot instead of quietly
reaching the operator's library.

**Binding is `os.chdir` into the snapshot root, once, at process start.**
The alternative -- threading the snapshot's directories through every call
-- cannot be made total: `axial.query.names` resolves the name layer with
`default_names_dir()` and no config path (`src/axial/query/names.py:429,
926, 1414`), `run_brief` has no `names_dir` parameter to thread one through,
and `analyze.synthesis.DEFAULT_LENSES_DIR` and `eval.corpus_pin.EVALS_DIR`
are cwd-relative literals. Missing one of those sites fails SILENTLY, by
reading the operator's live `data/`. Making the snapshot a corpus root with
relative `paths.*` closes all of them at once, and matches the issue's own
model: rolling a new corpus is a new worker image, not a mid-query swap.

Analyst writes (`analyses_dir`, `runs_dir`) are passed explicitly by the
worker, because they are not corpus and the snapshot is read-only.

Publishing is atomic: the tree is built in a staging directory beside the
target and renamed into place in one `os.replace` (`axial.paths.
replace_with_retry`, the same convention `atomic_write_text` and
`axial.query.store.write_store` already use), so a reader never observes a
half-published snapshot. Publishing over an existing version is refused --
immutability is the whole point.
"""

from __future__ import annotations

import json
import os
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from axial.envelope import _default_envelopes_dir
from axial.eval.corpus_pin import EVALS_DIR, resolve_pin_id
from axial.paths import (
    DEFAULT_PIPELINE_CONFIG_PATH,
    default_map_dir,
    default_names_dir,
    default_vault_dir,
    replace_with_retry,
)
from axial.yaml_loader import SAFE_LOADER

# Where published snapshots land on the operator's machine. A plain
# constant with a `--snapshots-dir` flag over it, not a `paths.*` config key:
# in production the snapshots directory is a deployment detail (a mounted
# volume, a bucket sync target), never something the pipeline config knows.
SNAPSHOTS_DIR = Path("data/snapshots")

MANIFEST_FILENAME = "manifest.json"

# The snapshot's own directory names. Relative, so a snapshot can be copied
# or mounted anywhere and still resolve against itself once bound.
_VAULT = "vault"
_NAMES = "names"
_ENVELOPES = "envelopes"
_MAP = "map"
_SOURCES = "sources"


class SnapshotError(Exception):
    """Base class for snapshot errors."""


class SnapshotExistsError(SnapshotError):
    """Raised when `publish` is asked for a version that already exists."""

    def __init__(self, version: str, root: Path) -> None:
        super().__init__(
            f"snapshot version {version!r} is already published at {root} -- "
            "a published snapshot is immutable; publish a new version instead"
        )
        self.version = version
        self.root = root


class SnapshotNotFoundError(SnapshotError):
    """Raised when a directory does not hold a published snapshot."""

    def __init__(self, root: Path) -> None:
        super().__init__(f"no snapshot manifest at {root / MANIFEST_FILENAME}")
        self.root = root


class SnapshotPinMismatchError(SnapshotError):
    """Raised when a completed run's own corpus pin is not the bound
    snapshot's pin -- i.e. the binding leaked and the engine read a corpus
    other than the one this worker was started on. Loud by design: a job
    labelled with the wrong pin is worse than a failed job."""

    def __init__(self, version: str, expected: str, recorded: str) -> None:
        super().__init__(
            f"the run recorded corpus pin {recorded!r} but this worker is bound to "
            f"snapshot {version!r} whose pin is {expected!r} -- the snapshot binding leaked"
        )
        self.version = version
        self.expected = expected
        self.recorded = recorded


@dataclass(frozen=True)
class Snapshot:
    """One published snapshot: where it is, which corpus it is, and the two
    pins a run needs. Resolved paths and identity, nothing else -- the
    behaviour lives in `publish` and in `bind`."""

    root: Path
    version: str
    corpus_pin: str
    map_pin: str | None
    sources: tuple[str, ...]
    built_at: str

    @classmethod
    def open(cls, root: Path | str) -> "Snapshot":
        """Read a published snapshot's manifest back. Raises
        `SnapshotNotFoundError` when `root` holds no manifest."""
        root = Path(root).resolve()
        manifest_path = root / MANIFEST_FILENAME
        if not manifest_path.is_file():
            raise SnapshotNotFoundError(root)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        return cls(
            root=root,
            version=manifest["version"],
            corpus_pin=manifest["corpus_pin"],
            map_pin=manifest.get("map_pin"),
            sources=tuple(manifest.get("sources", ())),
            built_at=manifest["built_at"],
        )

    def bind(self) -> "Snapshot":
        """Bind this process to this snapshot, for its whole life: every
        cwd-relative read the engine makes (`config/pipeline.yaml`,
        `config/lenses/`, `evals/corpus_pin/`, and through the config every
        `paths.*` directory) now resolves inside the snapshot. Called once,
        at worker process start -- never per job, and never unwound."""
        os.chdir(self.root)
        return self


def _copy_tree(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination)


def _snapshot_pipeline_config(config_path: Path) -> str:
    """The operator's pipeline config with its `paths` block repointed at
    the snapshot's own directories. Everything else (prompts, budgets,
    model tiers) travels unchanged, so a snapshot is reproducible against
    the settings it was built under.

    Serialized with `yaml.safe_dump`, which drops the operator file's
    comments -- acceptable, and deliberate: this copy is machine config
    read by a bound worker, not the file an operator edits."""
    document: dict[str, Any] = {}
    if config_path.is_file():
        with open(config_path, "r", encoding="utf-8") as handle:
            parsed = yaml.load(handle, Loader=SAFE_LOADER)
        if isinstance(parsed, dict):
            document = dict(parsed)
    document["paths"] = {
        "vault_dir": _VAULT,
        "names_dir": _NAMES,
        "envelopes_dir": _ENVELOPES,
        "map_dir": _MAP,
        # Deliberately a directory the snapshot does not contain: nothing on
        # the ask path may read raw source bytes (module docstring).
        "sources_dir": _SOURCES,
    }
    return yaml.safe_dump(document, sort_keys=False, allow_unicode=True)


def _write_manifest(staging: Path, manifest: dict[str, Any]) -> None:
    (staging / MANIFEST_FILENAME).write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _resolve_map(config_path: Path, staging: Path) -> str | None:
    """The built argument map for this corpus, copied into `staging` under
    its own pin, or `None` when there is no map. `resolve_pinned_map_dir` is
    imported here rather than at module scope for the same reason
    `axial.retrieve.tools` does: it pulls `axial.argmap.build` and with it
    the whole ingestion stack, ~9s of import a worker never needs."""
    if not default_map_dir(config_path).is_dir():
        return None
    from axial.argmap.ask import resolve_pinned_map_dir

    outdir = resolve_pinned_map_dir(config_path=config_path)
    if outdir is None:
        return None
    _copy_tree(outdir, staging / _MAP / outdir.name)
    return outdir.name


def publish(
    version: str,
    *,
    snapshots_dir: Path | None = None,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
) -> Snapshot:
    """Publish the corpus `config_path` describes as the immutable snapshot
    `<snapshots_dir>/<version>/`, and return it.

    Every directory is resolved the way the pipeline itself resolves it, so
    an operator publishes from the same working position they build from.
    Raises `SnapshotExistsError` if `version` is already published, and
    `axial.eval.corpus_pin.MissingCorpusPinError` if the corpus has no pin
    written yet (`axial pin write <name>` first) -- a corpus with no pin is
    not publishable, since the pin is what every answer is checkable
    against."""
    snapshots_dir = Path(snapshots_dir) if snapshots_dir is not None else SNAPSHOTS_DIR
    target = snapshots_dir / version
    if target.exists():
        raise SnapshotExistsError(version, target)

    corpus_pin = resolve_pin_id()
    pin_path = EVALS_DIR / f"{corpus_pin}.json"
    pin_manifest = json.loads(pin_path.read_text(encoding="utf-8"))

    snapshots_dir.mkdir(parents=True, exist_ok=True)
    staging = snapshots_dir / f".{version}.{uuid.uuid4().hex}.tmp"
    try:
        staging.mkdir()
        _copy_tree(default_vault_dir(config_path), staging / _VAULT)
        _copy_tree(default_names_dir(config_path), staging / _NAMES)
        _copy_tree(_default_envelopes_dir(config_path), staging / _ENVELOPES)
        _copy_tree(config_path.parent, staging / "config")
        (staging / "config" / config_path.name).write_text(
            _snapshot_pipeline_config(config_path), encoding="utf-8"
        )
        _copy_tree(EVALS_DIR, staging / EVALS_DIR)
        map_pin = _resolve_map(config_path, staging)

        manifest = {
            "version": version,
            "corpus_pin": corpus_pin,
            "map_pin": map_pin,
            "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "sources": [entry["source_id"] for entry in pin_manifest.get("sources", [])],
            "pin": pin_manifest,
        }
        _write_manifest(staging, manifest)
        replace_with_retry(staging, target)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    return Snapshot.open(target)
