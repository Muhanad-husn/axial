"""Acceptance tests for `axial publish` (issue #684): a published corpus is
an immutable snapshot directory, and binding one is total -- no read path
escapes to the operator's live `data/`.

The two "done when" clauses that need a real queue and two real worker
processes live in `test_worker_snapshot.py`; nothing here needs Postgres,
a model, or the network.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from axial.service.snapshot import (
    MANIFEST_FILENAME,
    Snapshot,
    SnapshotExistsError,
    SnapshotPathTooLongError,
    publish,
)
from _corpus import CANONICAL, CHUNK_ID, PIN_NAME, build_corpus_root, write_map


@pytest.fixture
def corpus_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A complete operator corpus root, with the process's cwd inside it --
    the operator's own working position, which is what `axial publish`
    resolves `config/pipeline.yaml` and `evals/corpus_pin/` against."""
    root = build_corpus_root(tmp_path / "operator")
    monkeypatch.chdir(root)
    return root


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_publish_writes_every_read_side_artifact_and_no_raw_sources(
    corpus_root: Path, tmp_path: Path
):
    """The corrected third "done when" (see the issue's own read-side
    inventory comment): the vault markdown IS the query surface --
    `assemble_evidence` quotes `prose/*.md` and `get_name` reads the Gather
    section off `names/*.md` -- so it ships. The raw books do not."""
    snapshots_dir = tmp_path / "snapshots"

    snapshot = publish("v1", snapshots_dir=snapshots_dir)

    root = snapshot.root
    assert root == snapshots_dir / "v1"
    assert (root / "vault" / "prose" / f"{CHUNK_ID}.md").is_file()
    assert (root / "vault" / "names" / f"{CANONICAL}.md").is_file()
    assert (root / "vault" / "names.jsonl").is_file()
    assert (root / "vault" / "artifacts").is_dir()
    assert (root / "vault" / "notes.db").is_file()
    assert (root / "names" / "index.json").is_file()
    assert (root / "names" / "alias_map.json").is_file()
    assert (root / "names" / "disagreements.jsonl").is_file()
    assert (root / "names" / "embeddings.lance").is_dir()
    assert (root / "envelopes" / "alpha-0123456789ab.json").is_file()
    assert (root / "evals" / "corpus_pin" / f"{PIN_NAME}.json").is_file()
    assert (root / "config" / "pipeline.yaml").is_file()
    assert (root / "config" / "lenses" / "plain.md").is_file()

    assert not (root / "sources").exists()
    assert not (root / "data").exists()


def test_the_manifest_carries_the_pin_the_source_list_and_the_build_date(
    corpus_root: Path, tmp_path: Path
):
    snapshot = publish("v1", snapshots_dir=tmp_path / "snapshots")

    manifest = json.loads(_read(snapshot.root / MANIFEST_FILENAME))
    assert manifest["version"] == "v1"
    assert manifest["corpus_pin"] == PIN_NAME
    assert manifest["sources"] == ["alpha-0123456789ab"]
    assert manifest["built_at"].endswith("Z")
    # The pin manifest's own contents travel with the snapshot, so the
    # hashes a result is checkable against are inside it.
    assert manifest["pin"]["ingest_code_sha"] == "0" * 40
    assert snapshot.corpus_pin == PIN_NAME


def test_publishing_over_an_existing_version_is_refused(corpus_root: Path, tmp_path: Path):
    """Immutability is the whole point: a version, once published, is that
    corpus forever."""
    snapshots_dir = tmp_path / "snapshots"
    first = publish("v1", snapshots_dir=snapshots_dir)
    before = _read(first.root / "vault" / "prose" / f"{CHUNK_ID}.md")

    build_corpus_root(corpus_root, passage="a different passage", pin="sim-test-v2")

    with pytest.raises(SnapshotExistsError):
        publish("v1", snapshots_dir=snapshots_dir)

    assert _read(first.root / "vault" / "prose" / f"{CHUNK_ID}.md") == before


def test_publishing_a_new_version_leaves_the_published_one_byte_identical(
    corpus_root: Path, tmp_path: Path
):
    snapshots_dir = tmp_path / "snapshots"
    v1 = publish("v1", snapshots_dir=snapshots_dir)
    before = {
        path.relative_to(v1.root).as_posix(): path.read_bytes()
        for path in sorted(v1.root.rglob("*"))
        if path.is_file()
    }

    build_corpus_root(corpus_root, passage="a different passage", pin="sim-test-v2")
    v2 = publish("v2", snapshots_dir=snapshots_dir)

    after = {
        path.relative_to(v1.root).as_posix(): path.read_bytes()
        for path in sorted(v1.root.rglob("*"))
        if path.is_file()
    }
    assert after == before
    assert v2.corpus_pin == "sim-test-v2"
    assert v1.corpus_pin == PIN_NAME


def test_a_half_written_publish_is_never_observable_as_a_snapshot(
    corpus_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A snapshot is built in a staging directory and renamed into place in
    one filesystem operation, so a reader either sees the whole thing or
    nothing. Failure is injected at the last step before the rename, when
    the staging tree is at its most complete."""
    import axial.service.snapshot as snapshot_mod

    snapshots_dir = tmp_path / "snapshots"

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(snapshot_mod, "_write_manifest", boom)

    with pytest.raises(OSError):
        publish("v1", snapshots_dir=snapshots_dir)

    assert not (snapshots_dir / "v1").exists()
    assert list(snapshots_dir.iterdir()) == []


def test_a_note_that_would_not_fit_under_the_snapshot_refuses_before_copying(
    corpus_root: Path, tmp_path: Path
):
    """Found on the live corpus, not in a fixture: a note filename is
    budgeted against the VAULT's directory at write time, so publishing into
    a deeper directory can push a real, correctly-written note over Windows'
    path budget. The first cut discovered this 148 seconds into a 213 MB
    copy, as three `[WinError 3]`s that never said "too long". Now it is
    refused up front, by name."""
    from axial.paths import path_overage

    snapshots_dir = tmp_path / "snapshots"
    version = "2026-08-10-v1"
    names_dir = corpus_root / "data" / "vault" / "names"
    landing_dir = snapshots_dir / version / "vault" / "names"

    # A filename calibrated to the exact case: it FITS where the vault
    # writer put it, and does not fit where the snapshot would land it. The
    # length is computed from the two directories rather than hardcoded, so
    # this is the same test on Windows and on CI's Linux.
    # One character past the longest name that would fit at the landing site.
    length = len("x") - path_overage(landing_dir, "x") + 1
    long_name = "L" + "o" * (length - 4) + ".md"
    assert path_overage(names_dir, long_name) <= 0 < path_overage(landing_dir, long_name)
    (names_dir / long_name).write_text("---\nname: Long\n---\n", encoding="utf-8")

    with pytest.raises(SnapshotPathTooLongError) as caught:
        publish(version, snapshots_dir=snapshots_dir)

    assert long_name in str(caught.value.path)
    assert caught.value.overage > 0
    # Nothing was copied: the check runs before the first byte moves.
    assert not snapshots_dir.exists()


def test_binding_a_snapshot_resolves_every_read_path_inside_it(
    corpus_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """The binding must be TOTAL. `axial.query.names` resolves the name
    layer through `default_names_dir()` with no config path, and
    `DEFAULT_LENSES_DIR`/`corpus_pin.EVALS_DIR` are cwd-relative literals --
    so a snapshot is bound as a corpus root, and this test is what says no
    read path silently escapes to the operator's live `data/`."""
    from axial.analyze import synthesis
    from axial.envelope import _default_envelopes_dir
    from axial.eval.corpus_pin import resolve_pin_id
    from axial.paths import (
        default_map_dir,
        default_names_dir,
        default_sources_dir,
        default_vault_dir,
    )

    snapshot = publish("v1", snapshots_dir=tmp_path / "snapshots")
    monkeypatch.chdir(tmp_path)

    snapshot.bind()

    assert Path.cwd().resolve() == snapshot.root.resolve()
    assert default_vault_dir().resolve() == (snapshot.root / "vault").resolve()
    assert default_names_dir().resolve() == (snapshot.root / "names").resolve()
    assert _default_envelopes_dir().resolve() == (snapshot.root / "envelopes").resolve()
    assert default_map_dir().resolve() == (snapshot.root / "map").resolve()
    assert synthesis.DEFAULT_LENSES_DIR.resolve() == (snapshot.root / "config" / "lenses").resolve()
    assert resolve_pin_id() == PIN_NAME
    # The one path that must NOT resolve to anything: the raw books.
    sources = default_sources_dir().resolve()
    assert sources == (snapshot.root / "sources").resolve()
    assert not sources.exists()


def test_a_built_argument_map_travels_with_the_snapshot_under_its_pin(
    corpus_root: Path, tmp_path: Path
):
    """`positions_on` is a real retrieval tool, and `resolve_pinned_map_dir`
    derives the map's directory name by hashing every RAW SOURCE FILE. The
    snapshot has no raw sources, so the map pin is computed once here, at
    publish time on the operator's machine, and recorded in the manifest."""
    from axial.argmap.build import compute_corpus_pin

    map_pin = compute_corpus_pin(
        corpus_root / "data" / "envelopes", corpus_root / "data" / "sources"
    )
    write_map(corpus_root, map_pin)

    snapshot = publish("v1", snapshots_dir=tmp_path / "snapshots")

    assert snapshot.map_pin == map_pin
    assert (snapshot.root / "map" / map_pin / "positions.jsonl").is_file()
    assert Snapshot.open(snapshot.root).map_pin == map_pin


def test_a_corpus_with_no_argument_map_publishes_with_a_null_map_pin(
    corpus_root: Path, tmp_path: Path
):
    snapshot = publish("v1", snapshots_dir=tmp_path / "snapshots")

    assert snapshot.map_pin is None
    assert not (snapshot.root / "map").exists()


def test_the_publish_command_actually_publishes(
    corpus_root: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    """Through `main()`, not `publish()`. The first cut of this command was
    a silent no-op: its positional was spelled `version`, which is the dest
    of the parser's global `--version` store_true flag, and `main` checks
    `args.version` before dispatching -- so `axial publish 2026-08-10-v1`
    printed "axial 0.1.0", exited 0, and wrote nothing. Only a test that
    goes through the CLI surface can see that."""
    from axial.cli import main

    snapshots_dir = tmp_path / "snapshots"

    assert main(["publish", "v1", "--snapshots-dir", str(snapshots_dir)]) == 0

    assert (snapshots_dir / "v1" / MANIFEST_FILENAME).is_file()
    assert Snapshot.open(snapshots_dir / "v1").corpus_pin == PIN_NAME
    assert "axial 0.1.0" not in capsys.readouterr().out


def test_the_publish_command_reports_a_refused_overwrite_as_a_failure(
    corpus_root: Path, tmp_path: Path
):
    from axial.cli import main

    snapshots_dir = tmp_path / "snapshots"
    assert main(["publish", "v1", "--snapshots-dir", str(snapshots_dir)]) == 0

    assert main(["publish", "v1", "--snapshots-dir", str(snapshots_dir)]) == 1


def test_no_subcommand_argument_shadows_a_global_flag():
    """The bug above is a whole class, not one typo: `axial`'s only global
    option is `--version` (dest `version`), `main` reads it before any
    dispatch, and ANY subcommand argument that lands in a global dest turns
    that subcommand into a silent no-op. Pinned here for every subcommand at
    once rather than one command at a time."""
    import argparse

    from axial.cli import build_parser

    parser = build_parser()
    global_dests = {
        action.dest
        for action in parser._actions
        if not isinstance(action, argparse._SubParsersAction)
    } - {"help"}

    shadowed = []
    for action in parser._actions:
        if not isinstance(action, argparse._SubParsersAction):
            continue
        for name, subparser in action.choices.items():
            for sub_action in subparser._actions:
                if sub_action.dest in global_dests:
                    shadowed.append(f"{name}.{sub_action.dest}")

    assert shadowed == []


def test_open_reads_a_published_snapshot_back(corpus_root: Path, tmp_path: Path):
    published = publish("v1", snapshots_dir=tmp_path / "snapshots")

    reopened = Snapshot.open(published.root)

    assert reopened == published
