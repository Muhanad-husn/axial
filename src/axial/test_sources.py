"""Inner unit tests for `axial.sources` (issue #528): the local folder
backend's scan/sync and the shared report renderer/backend resolver both
backends share with the Drive side (`axial.drive.run_drive_sources`,
covered in `test_drive.py`).

Every test builds its own `sources_dir`/`ledger_path` under `tmp_path` --
`data/` does not exist in a worktree, and even in the main checkout this
module must never read or write the real corpus/ledger by accident.
"""

from __future__ import annotations

from pathlib import Path

import axial.artifacts as artifacts_mod
import axial.chunk as chunk_mod
import axial.envelope as envelope_mod
import axial.extract as extract_mod
import axial.interrogate as interrogate_mod
from axial.envelope import compute_source_id
from axial.run import FAIL_STATUS, OK_STATUS, RunSummary, _append_ledger_row
from axial.sources import (
    CHANGED,
    DEFAULT_DONE_PASS,
    DEFAULT_INGEST_PASSES,
    DONE,
    MISSING,
    NEW,
    PARTIAL,
    REJECTED,
    SourceRecord,
    render_report,
    resolve_backend,
    scan_local,
    scan_orphaned_envelopes,
    sync_local,
)


def _write_source(sources_dir: Path, name: str, content: bytes = b"hello world") -> Path:
    sources_dir.mkdir(parents=True, exist_ok=True)
    path = sources_dir / name
    path.write_bytes(content)
    return path


def _ledger_row(pass_name: str, source_path: Path, source_id: str, status: str, reason: str = ""):
    return {
        "pass": pass_name,
        "source_path": str(source_path),
        "source_id": source_id,
        "status": status,
        "reason": reason,
        "timestamp": "2026-08-02T00:00:00+00:00",
    }


def _isolate_artifact_dirs(monkeypatch, tmp_path: Path) -> None:
    """Point every per-source artifact directory `axial.sources` checks at a
    fresh tmp location -- mirrors `src/axial/conftest.py`'s own
    `_isolate_checkpoint_dirs` fixture, never the real (gitignored, absent
    in this worktree) `data/` tree. Paired with a `config_path` pointing at
    a file that does not exist, so `_default_*_dir`'s config-then-fallback
    resolvers fall through to these patched module constants rather than
    reading the real `config/pipeline.yaml` (issue #528: reproducing the
    live bug needs a config that declares no `paths:` overrides, exactly
    like the real corpus run that surfaced it)."""
    monkeypatch.setattr(extract_mod, "TREES_DIR", tmp_path / "trees")
    monkeypatch.setattr(envelope_mod, "ENVELOPES_DIR", tmp_path / "envelopes")
    monkeypatch.setattr(chunk_mod, "CHUNKS_DIR", tmp_path / "chunks")
    monkeypatch.setattr(interrogate_mod, "ANSWERS_DIR", tmp_path / "answers")
    monkeypatch.setattr(artifacts_mod, "ARTIFACTS_DIR", tmp_path / "artifacts")


def _write_artifacts(tmp_path: Path, source_id: str, *, skip: tuple[str, ...] = ()) -> None:
    """Touch every per-source artifact file for `source_id` (paired with
    `_isolate_artifact_dirs`) except those named in `skip`. Content is
    irrelevant -- `axial.sources` only checks existence, never parses."""
    paths = {
        "tree": tmp_path / "trees" / f"{source_id}.json",
        "envelope": tmp_path / "envelopes" / f"{source_id}.json",
        "chunks": tmp_path / "chunks" / f"{source_id}.jsonl",
        "answers": tmp_path / "answers" / f"{source_id}.jsonl",
        "artifacts": tmp_path / "artifacts" / f"{source_id}.jsonl",
    }
    for name, path in paths.items():
        if name in skip:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")


# --- scan_local --------------------------------------------------------------


def test_scan_local_returns_empty_list_for_absent_sources_dir(tmp_path):
    assert scan_local(tmp_path / "nowhere", tmp_path / "ledger.tsv") == []


def test_scan_local_flags_unsupported_extension_as_rejected(tmp_path):
    sources_dir = tmp_path / "sources"
    _write_source(sources_dir, "notes.txt")

    records = scan_local(sources_dir, tmp_path / "ledger.tsv")

    assert len(records) == 1
    assert records[0].status == REJECTED
    assert "unsupported file type" in records[0].reason
    assert ".txt" in records[0].reason


def test_scan_local_never_seen_before_is_new(tmp_path):
    sources_dir = tmp_path / "sources"
    _write_source(sources_dir, "alpha.pdf")

    records = scan_local(sources_dir, tmp_path / "ledger.tsv")

    assert records == [SourceRecord("alpha.pdf", NEW)]


def test_scan_local_ok_ledger_row_for_current_bytes_is_done(tmp_path):
    sources_dir = tmp_path / "sources"
    path = _write_source(sources_dir, "alpha.pdf")
    source_id = compute_source_id(path)
    ledger_path = tmp_path / "ledger.tsv"
    _append_ledger_row(ledger_path, _ledger_row(DEFAULT_DONE_PASS, path, source_id, OK_STATUS))

    records = scan_local(sources_dir, ledger_path)

    assert records == [SourceRecord("alpha.pdf", DONE)]


def test_scan_local_edited_file_with_stale_ledger_row_is_changed(tmp_path):
    sources_dir = tmp_path / "sources"
    path = _write_source(sources_dir, "alpha.pdf", content=b"original bytes")
    stale_id = compute_source_id(path)
    ledger_path = tmp_path / "ledger.tsv"
    _append_ledger_row(ledger_path, _ledger_row(DEFAULT_DONE_PASS, path, stale_id, OK_STATUS))

    # Re-save with different content -- source_id changes, the ledger row
    # for this path now names a different source_id.
    path.write_bytes(b"a completely different revision")

    records = scan_local(sources_dir, ledger_path)

    assert records == [SourceRecord("alpha.pdf", CHANGED)]


def test_scan_local_prior_fail_under_current_bytes_stays_new_not_rejected(tmp_path):
    """A pipeline failure (not a gate rejection) leaves the source retryable
    -- mirrors Drive's own chain-error handling, which writes no manifest
    entry either (module docstring)."""
    sources_dir = tmp_path / "sources"
    path = _write_source(sources_dir, "alpha.pdf")
    source_id = compute_source_id(path)
    ledger_path = tmp_path / "ledger.tsv"
    _append_ledger_row(
        ledger_path, _ledger_row(DEFAULT_DONE_PASS, path, source_id, FAIL_STATUS, "boom")
    )

    records = scan_local(sources_dir, ledger_path)

    assert records == [SourceRecord("alpha.pdf", NEW)]


def test_scan_local_re_running_immediately_reports_all_done(tmp_path):
    sources_dir = tmp_path / "sources"
    path = _write_source(sources_dir, "alpha.pdf")
    source_id = compute_source_id(path)
    ledger_path = tmp_path / "ledger.tsv"
    _append_ledger_row(ledger_path, _ledger_row(DEFAULT_DONE_PASS, path, source_id, OK_STATUS))

    first = scan_local(sources_dir, ledger_path)
    second = scan_local(sources_dir, ledger_path)

    assert first == second == [SourceRecord("alpha.pdf", DONE)]


def test_scan_local_reports_new_changed_done_and_rejected_together(tmp_path):
    sources_dir = tmp_path / "sources"
    done_path = _write_source(sources_dir, "done.pdf", content=b"done bytes")
    new_path = _write_source(sources_dir, "new.pdf")
    _write_source(sources_dir, "stray.txt")
    ledger_path = tmp_path / "ledger.tsv"
    _append_ledger_row(
        ledger_path,
        _ledger_row(DEFAULT_DONE_PASS, done_path, compute_source_id(done_path), OK_STATUS),
    )

    records = {record.name: record for record in scan_local(sources_dir, ledger_path)}

    assert records["done.pdf"].status == DONE
    assert records["new.pdf"].status == NEW
    assert records["stray.txt"].status == REJECTED
    assert new_path.exists()  # sanity: file really is there, not consumed


# --- scan_local: artifacts are the truth (issue #528, live-corpus fix) -------
#
# The exact real-world bug: `--check` against the real 31-source corpus
# reported every source `new` because `data/run/ledger.tsv` (the unified
# ledger) had never been written there -- only an unrelated, differently-
# keyed `ledger-extract.tsv` existed -- even though every source's envelope,
# chunks, tree, and answers were on disk. A source is `done` when its
# artifacts say so, whatever the ledger says or fails to say.


def test_scan_local_all_artifacts_present_with_absent_ledger_is_done(tmp_path, monkeypatch):
    """Pins the live bug directly: an absent ledger (no data/run/ledger.tsv
    at all, the real corpus's actual state) must not read as `new` when
    every artifact for this exact content already exists."""
    _isolate_artifact_dirs(monkeypatch, tmp_path)
    sources_dir = tmp_path / "sources"
    path = _write_source(sources_dir, "mann-1986.pdf")
    source_id = compute_source_id(path)
    _write_artifacts(tmp_path, source_id)
    absent_ledger_path = tmp_path / "ledger.tsv"
    assert not absent_ledger_path.exists()  # sanity: this is the real bug's own state

    records = scan_local(
        sources_dir,
        absent_ledger_path,
        config_path=tmp_path / "no-such-pipeline.yaml",
    )

    assert records == [SourceRecord("mann-1986.pdf", DONE)]


def test_scan_local_some_artifacts_present_is_partial_and_names_what_is_missing(
    tmp_path, monkeypatch
):
    _isolate_artifact_dirs(monkeypatch, tmp_path)
    sources_dir = tmp_path / "sources"
    path = _write_source(sources_dir, "ayubi-1995.pdf")
    source_id = compute_source_id(path)
    _write_artifacts(tmp_path, source_id, skip=("chunks", "answers"))

    records = scan_local(
        sources_dir,
        tmp_path / "ledger.tsv",
        config_path=tmp_path / "no-such-pipeline.yaml",
    )

    assert len(records) == 1
    assert records[0].status == PARTIAL
    assert "chunks" in records[0].reason
    assert "answers" in records[0].reason
    assert "tree" not in records[0].reason
    assert "envelope" not in records[0].reason


def test_scan_local_no_artifacts_and_no_ledger_is_new_via_isolated_dirs(tmp_path, monkeypatch):
    """Companion to test_scan_local_never_seen_before_is_new, pinned with
    the artifact dirs explicitly isolated (and empty) rather than relying
    on the real data/ tree simply not existing in this worktree."""
    _isolate_artifact_dirs(monkeypatch, tmp_path)
    sources_dir = tmp_path / "sources"
    _write_source(sources_dir, "elcheroth-2017.pdf")

    records = scan_local(
        sources_dir,
        tmp_path / "ledger.tsv",
        config_path=tmp_path / "no-such-pipeline.yaml",
    )

    assert records == [SourceRecord("elcheroth-2017.pdf", NEW)]


def test_scan_local_ledger_ok_row_skips_artifact_checks_entirely(tmp_path, monkeypatch):
    """The ledger is a fast path, not a second source of truth to
    cross-check: when it already carries an OK row for the current bytes,
    scan_local must never touch the artifact directories at all."""
    sources_dir = tmp_path / "sources"
    path = _write_source(sources_dir, "alpha.pdf")
    source_id = compute_source_id(path)
    ledger_path = tmp_path / "ledger.tsv"
    _append_ledger_row(ledger_path, _ledger_row(DEFAULT_DONE_PASS, path, source_id, OK_STATUS))

    def _boom(*args, **kwargs):
        raise AssertionError("artifact stats must not run when the ledger already agrees")

    monkeypatch.setattr("axial.sources._artifact_status", _boom)

    records = scan_local(sources_dir, ledger_path)

    assert records == [SourceRecord("alpha.pdf", DONE)]


# --- render_report -------------------------------------------------------------


def test_render_report_header_plus_one_row_per_record():
    records = [SourceRecord("alpha.pdf", NEW), SourceRecord("bad.txt", REJECTED, "wrong type")]

    text = render_report(records)

    lines = text.splitlines()
    assert lines[0] == "name\tstatus\treason"
    assert lines[1] == "alpha.pdf\tnew\t"
    assert lines[2] == "bad.txt\trejected\twrong type"


# --- resolve_backend -----------------------------------------------------------


def test_resolve_backend_defaults_to_local_for_absent_config(tmp_path):
    assert resolve_backend(tmp_path / "absent.yaml") == "local"


def test_resolve_backend_reads_configured_backend(tmp_path):
    config_path = tmp_path / "pipeline.yaml"
    config_path.write_text("sources:\n  backend: drive\n", encoding="utf-8")

    assert resolve_backend(config_path) == "drive"


def test_resolve_backend_defaults_to_local_when_sources_block_absent(tmp_path):
    config_path = tmp_path / "pipeline.yaml"
    config_path.write_text("llm:\n  provider: openrouter\n", encoding="utf-8")

    assert resolve_backend(config_path) == "local"


# --- sync_local ----------------------------------------------------------------


def test_sync_local_calls_run_pass_once_per_ingest_pass_in_order(tmp_path, monkeypatch):
    calls = []

    def fake_run_pass(pass_name, **kwargs):
        calls.append((pass_name, kwargs))
        return RunSummary(pass_name, [], 0, 0, 0, 0), 0

    monkeypatch.setattr("axial.sources.run_pass", fake_run_pass)

    sources_dir = tmp_path / "sources"
    ledger_path = tmp_path / "ledger.tsv"

    summaries = sync_local(sources_dir, ledger_path)

    assert [name for name, _ in calls] == list(DEFAULT_INGEST_PASSES)
    for _name, kwargs in calls:
        assert kwargs["corpus"] is True
        assert kwargs["sources_dir"] == sources_dir
        assert kwargs["ledger_path"] == ledger_path
    assert len(summaries) == len(DEFAULT_INGEST_PASSES)


def test_sync_local_threads_one_shared_client_into_every_pass(tmp_path, monkeypatch):
    calls = []
    sentinel_client = object()

    def fake_run_pass(pass_name, **kwargs):
        calls.append(kwargs["client"])
        return RunSummary(pass_name, [], 0, 0, 0, 0), 0

    monkeypatch.setattr("axial.sources.run_pass", fake_run_pass)

    sync_local(tmp_path / "sources", tmp_path / "ledger.tsv", client=sentinel_client)

    assert calls == [sentinel_client] * len(DEFAULT_INGEST_PASSES)


# --- CLI wiring (axial sources) -------------------------------------------


def test_build_parser_recognises_sources_subcommand_with_optional_backend():
    from axial.cli import build_parser

    parser = build_parser()

    args = parser.parse_args(["sources"])
    assert args.command == "sources"
    assert args.backend is None
    assert args.check is False

    args_override = parser.parse_args(["sources", "--backend", "drive"])
    assert args_override.backend == "drive"

    args_check = parser.parse_args(["sources", "--check"])
    assert args_check.check is True


def test_main_sources_local_backend_reports_then_ingests_when_something_is_pending(monkeypatch):
    import axial.cli as cli_mod

    monkeypatch.setattr(cli_mod, "resolve_backend", lambda: "local")
    monkeypatch.setattr(cli_mod, "scan_local", lambda: [SourceRecord("alpha.pdf", NEW)])
    sync_calls = []
    monkeypatch.setattr(cli_mod, "sync_local", lambda **kwargs: sync_calls.append(kwargs) or [])
    monkeypatch.setattr(cli_mod, "get_client", lambda: "client-sentinel")

    exit_code = cli_mod.main(["sources"])

    assert exit_code == 0
    assert len(sync_calls) == 1
    assert sync_calls[0]["client"] == "client-sentinel"


def test_main_sources_local_backend_does_nothing_and_says_so_when_all_done(monkeypatch, capsys):
    import axial.cli as cli_mod

    monkeypatch.setattr(cli_mod, "resolve_backend", lambda: "local")
    monkeypatch.setattr(cli_mod, "scan_local", lambda: [SourceRecord("alpha.pdf", DONE)])
    sync_calls = []
    monkeypatch.setattr(cli_mod, "sync_local", lambda **kwargs: sync_calls.append(kwargs) or [])

    exit_code = cli_mod.main(["sources"])

    assert exit_code == 0
    assert sync_calls == [], "nothing new/changed must run zero pipeline work"
    captured = capsys.readouterr()
    assert "nothing new" in captured.out.lower()


def test_main_sources_local_backend_ingests_a_partial_source_to_finish_it(monkeypatch):
    """A partial source (a died-halfway run) must not be flattened into
    'nothing to do' -- axial.run.run_pass's own per-pass done-predicate is
    what finishes it, by resuming, not restarting."""
    import axial.cli as cli_mod

    monkeypatch.setattr(cli_mod, "resolve_backend", lambda: "local")
    monkeypatch.setattr(
        cli_mod,
        "scan_local",
        lambda: [SourceRecord("alpha.pdf", PARTIAL, "missing: chunks, answers")],
    )
    sync_calls = []
    monkeypatch.setattr(cli_mod, "sync_local", lambda **kwargs: sync_calls.append(kwargs) or [])
    monkeypatch.setattr(cli_mod, "get_client", lambda: "client-sentinel")

    exit_code = cli_mod.main(["sources"])

    assert exit_code == 0
    assert len(sync_calls) == 1


def test_main_sources_check_reports_but_never_calls_sync_local(monkeypatch, capsys):
    import axial.cli as cli_mod

    monkeypatch.setattr(cli_mod, "resolve_backend", lambda: "local")
    monkeypatch.setattr(cli_mod, "scan_local", lambda: [SourceRecord("alpha.pdf", NEW)])
    sync_calls = []
    monkeypatch.setattr(cli_mod, "sync_local", lambda **kwargs: sync_calls.append(kwargs) or [])

    exit_code = cli_mod.main(["sources", "--check"])

    assert exit_code == 0
    assert sync_calls == [], "--check must never reach sync_local, pending or not"
    captured = capsys.readouterr()
    assert "alpha.pdf" in captured.out
    assert "new" in captured.out


def test_main_sources_check_never_calls_run_pass_on_local_backend(monkeypatch):
    """The coordinator's own bar: prove --check cannot reach axial.run.
    run_pass on the local backend, using the REAL scan_local (data/ does
    not exist in this worktree, so it reports zero sources -- the point is
    that run_pass, patched to explode if called, never gets a chance to)."""
    import axial.cli as cli_mod

    def _boom(*args, **kwargs):
        raise AssertionError("run_pass must not be called when --check is passed")

    monkeypatch.setattr(cli_mod, "resolve_backend", lambda: "local")
    monkeypatch.setattr("axial.sources.run_pass", _boom)

    exit_code = cli_mod.main(["sources", "--check"])

    assert exit_code == 0


def test_main_sources_check_report_matches_ingesting_path_report_for_same_state(
    monkeypatch, capsys
):
    import axial.cli as cli_mod

    fixed_records = [SourceRecord("alpha.pdf", NEW), SourceRecord("beta.pdf", DONE)]
    monkeypatch.setattr(cli_mod, "resolve_backend", lambda: "local")
    monkeypatch.setattr(cli_mod, "scan_local", lambda: fixed_records)
    monkeypatch.setattr(cli_mod, "sync_local", lambda **kwargs: [])
    monkeypatch.setattr(cli_mod, "get_client", lambda: "client-sentinel")

    cli_mod.main(["sources", "--check"])
    check_report = capsys.readouterr().out.rstrip("\n")

    cli_mod.main(["sources"])
    ingesting_report = capsys.readouterr().out

    expected = render_report(fixed_records)
    assert check_report == expected
    assert ingesting_report.startswith(expected)


def test_main_sources_backend_flag_overrides_config(monkeypatch):
    import axial.cli as cli_mod

    monkeypatch.setattr(cli_mod, "resolve_backend", lambda: "local")
    drive_calls = []

    def fake_run_drive_sources(folder_id, **kwargs):
        drive_calls.append(folder_id)
        return [], 0

    monkeypatch.setattr(cli_mod, "run_drive_sources", fake_run_drive_sources)
    monkeypatch.setattr(
        cli_mod, "_load_drive_secrets", lambda path: {"books_folder_id": "BOOKS-ID"}
    )

    exit_code = cli_mod.main(["sources", "--backend", "drive"])

    assert exit_code == 0
    assert drive_calls == ["BOOKS-ID"]


def test_main_sources_drive_backend_halts_on_missing_secrets(monkeypatch, capsys):
    import axial.cli as cli_mod

    def _raise(_path):
        from axial.drive import DriveSecretsError

        raise DriveSecretsError("no [drive] secrets")

    monkeypatch.setattr(cli_mod, "resolve_backend", lambda: "drive")
    monkeypatch.setattr(cli_mod, "_load_drive_secrets", _raise)
    drive_calls = []

    def fake_run_drive_sources(folder_id):
        drive_calls.append(folder_id)
        return [], 0

    monkeypatch.setattr(cli_mod, "run_drive_sources", fake_run_drive_sources)

    exit_code = cli_mod.main(["sources"])

    assert exit_code != 0
    assert drive_calls == []
    captured = capsys.readouterr()
    assert "drive" in (captured.out + captured.err).lower()


def test_a_source_without_its_artifact_record_is_partial_not_done(tmp_path, monkeypatch):
    """Issue #623: `artifacts` was registered and alive but was not in
    `DEFAULT_INGEST_PASSES`, so `axial sources` reported a source `done` that
    had never had the pass run. Three books were ingested that way and
    materialize reported `artifact_sources: 31` against 34 sources -- their
    tables and figures were simply absent while every other book had them."""
    _isolate_artifact_dirs(monkeypatch, tmp_path)
    sources_dir = tmp_path / "sources"
    source_path = _write_source(sources_dir, "alpha.pdf")
    source_id = compute_source_id(source_path)
    _write_artifacts(tmp_path, source_id, skip=("artifacts",))

    records = scan_local(
        sources_dir, tmp_path / "ledger.tsv", config_path=tmp_path / "no-such-config.yaml"
    )

    assert records[0].status == PARTIAL
    assert "artifacts" in records[0].reason


def test_the_ingest_chain_runs_artifacts_and_the_done_pass_names_its_end():
    """The chain and the done-pass have to name the same finish line: the
    ledger fast path in `scan_local` trusts an OK row for `DEFAULT_DONE_PASS`
    and skips the artifact checks entirely, so a done-pass naming anything
    earlier than the chain's last pass reports `done` on a half-run source."""
    assert DEFAULT_INGEST_PASSES == ("extract", "envelope", "chunk", "interrogate", "artifacts")
    assert DEFAULT_DONE_PASS == DEFAULT_INGEST_PASSES[-1]
    assert "vault-write" not in DEFAULT_INGEST_PASSES


# --- scan_orphaned_envelopes -------------------------------------------------
#
# The reverse pass (issue #819): `scan_local` walks `sources_dir` forward and
# so cannot see an ingested source whose raw file is gone. The predicate is
# the corpus pin's own -- `axial.eval.corpus_pin.unresolvable_sources`, which
# carries its agreement tests -- so these cover the adapter and the wiring,
# not the rule. Every test builds its own dirs under `tmp_path`, for the same
# reason the module's other tests do.


def _write_envelope(envelopes_dir: Path, source_id: str) -> None:
    envelopes_dir.mkdir(parents=True, exist_ok=True)
    (envelopes_dir / f"{source_id}.json").write_text(
        f'{{"source_id": "{source_id}"}}', encoding="utf-8"
    )


def test_scan_orphaned_envelopes_is_empty_when_every_envelope_has_its_raw_file(tmp_path):
    sources_dir = tmp_path / "sources"
    path = _write_source(sources_dir, "alpha.pdf")
    _write_envelope(tmp_path / "envelopes", compute_source_id(path))

    assert scan_orphaned_envelopes(sources_dir, tmp_path / "envelopes") == []


def test_scan_orphaned_envelopes_reports_an_envelope_whose_raw_file_is_gone(tmp_path):
    sources_dir = tmp_path / "sources"
    sources_dir.mkdir(parents=True)
    _write_envelope(tmp_path / "envelopes", "beshara-2011-8410a9059300")

    records = scan_orphaned_envelopes(sources_dir, tmp_path / "envelopes")

    assert len(records) == 1
    assert records[0].name == "beshara-2011-8410a9059300"
    assert records[0].status == MISSING
    # The reason is the pin's own, naming the directory actually searched.
    assert "no raw source file" in records[0].reason
    assert str(sources_dir) in records[0].reason


def test_scan_orphaned_envelopes_names_every_missing_source_not_only_the_first(tmp_path):
    sources_dir = tmp_path / "sources"
    present = _write_source(sources_dir, "alpha.pdf")
    for source_id in (
        compute_source_id(present),
        "zulu-2020-ffffffffffff",
        "bravo-1999-000000000000",
    ):
        _write_envelope(tmp_path / "envelopes", source_id)

    records = scan_orphaned_envelopes(sources_dir, tmp_path / "envelopes")

    # Sorted, so the report reads the same way twice, and BOTH orphans are
    # named -- the live failure raised on the first one it reached.
    assert [record.name for record in records] == [
        "bravo-1999-000000000000",
        "zulu-2020-ffffffffffff",
    ]
    assert {record.status for record in records} == {MISSING}


def test_scan_orphaned_envelopes_does_not_fire_on_a_re_sourced_file(tmp_path):
    """Replacing a source with different bytes moves its `source_id` and
    leaves the old envelope behind under the same stem. The pin resolves by
    stem and still computes, so this must stay silent -- a check that fired
    here would fail `axial sources` forever over a state the pin does not
    care about, and the operator would have no way to know which envelope to
    delete."""
    sources_dir = tmp_path / "sources"
    path = _write_source(sources_dir, "alpha.pdf", content=b"the corrected scan")
    _write_envelope(tmp_path / "envelopes", compute_source_id(path))
    _write_envelope(tmp_path / "envelopes", "alpha-000000000000")

    assert scan_orphaned_envelopes(sources_dir, tmp_path / "envelopes") == []


def test_scan_orphaned_envelopes_returns_empty_list_for_absent_envelopes_dir(tmp_path):
    assert scan_orphaned_envelopes(tmp_path / "sources", tmp_path / "nowhere") == []


def test_scan_orphaned_envelopes_ignores_non_json_files_in_the_envelopes_dir(tmp_path):
    sources_dir = tmp_path / "sources"
    sources_dir.mkdir(parents=True)
    envelopes_dir = tmp_path / "envelopes"
    envelopes_dir.mkdir(parents=True)
    (envelopes_dir / "README.md").write_text("not an envelope", encoding="utf-8")
    (envelopes_dir / "nested").mkdir()

    assert scan_orphaned_envelopes(sources_dir, envelopes_dir) == []


def test_scan_orphaned_envelopes_reports_a_malformed_envelope_rather_than_raising(tmp_path):
    """The pin raises `MalformedEnvelopeError` here. The check must not: an
    operator asking "is my corpus sound" gets an answer, not a traceback."""
    sources_dir = tmp_path / "sources"
    sources_dir.mkdir(parents=True)
    envelopes_dir = tmp_path / "envelopes"
    envelopes_dir.mkdir(parents=True)
    (envelopes_dir / "alpha-2001-abcdefabcdef.json").write_text("{ not json", encoding="utf-8")

    records = scan_orphaned_envelopes(sources_dir, envelopes_dir)

    assert [record.name for record in records] == ["alpha-2001-abcdefabcdef"]
    assert records[0].status == MISSING


def test_scan_orphaned_envelopes_resolves_the_sources_dir_at_call_time(tmp_path, monkeypatch):
    """`CORPUS_SOURCES_DIR` is looked up when the function runs, not bound
    once as a default parameter value -- the trap `_ARTIFACT_PATH_FNS`'s own
    comment names. A default binding made the CLI read the real corpus while
    a demo thought it had repointed the module, and the command exited 0 on
    a corpus with a missing raw file."""
    import axial.sources as sources_mod

    sources_dir = tmp_path / "sources"
    sources_dir.mkdir(parents=True)
    _write_envelope(tmp_path / "envelopes", "alpha-2001-abcdefabcdef")
    monkeypatch.setattr(sources_mod, "CORPUS_SOURCES_DIR", sources_dir)

    records = scan_orphaned_envelopes(envelopes_dir=tmp_path / "envelopes")

    assert [record.name for record in records] == ["alpha-2001-abcdefabcdef"]
    assert str(sources_dir) in records[0].reason


def test_scan_local_resolves_the_sources_dir_at_call_time(tmp_path, monkeypatch):
    """The same call-time resolution as `scan_orphaned_envelopes` above, so
    repointing the module constant moves BOTH halves of the report and a
    demo or operator script cannot end up driving one against a fixture and
    the other against the real corpus."""
    import axial.sources as sources_mod

    sources_dir = tmp_path / "sources"
    _write_source(sources_dir, "alpha.pdf")
    monkeypatch.setattr(sources_mod, "CORPUS_SOURCES_DIR", sources_dir)

    assert scan_local(ledger_path=tmp_path / "ledger.tsv") == [SourceRecord("alpha.pdf", NEW)]


def test_sync_local_resolves_the_sources_dir_at_call_time(tmp_path, monkeypatch):
    """And the third: `sync_local` is the half that WRITES. A script that
    repointed the module and ran a plain `axial sources` would otherwise
    scan the fixture and ingest from the real corpus."""
    import axial.sources as sources_mod

    sources_dir = tmp_path / "sources"
    _write_source(sources_dir, "alpha.pdf")
    seen: list[Path] = []

    def _record_pass(pass_name, *, worklist_path=None, corpus=False, sources_dir=None, **kwargs):
        seen.append(sources_dir)
        return RunSummary(
            pass_name=pass_name, outcomes=[], total=0, ok_count=0, fail_count=0, skip_count=0
        ), 0

    monkeypatch.setattr(sources_mod, "CORPUS_SOURCES_DIR", sources_dir)
    monkeypatch.setattr(sources_mod, "run_pass", _record_pass)

    sync_local(ledger_path=tmp_path / "ledger.tsv", client=object())

    assert seen and all(seen_dir == sources_dir for seen_dir in seen)
