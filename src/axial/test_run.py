"""Inner unit tests for the axial run module (issue #277: slice 01 runner
core + pass registry + per-source failure isolation; slice 02 unified resume
ledger + per-pass done-predicate; slice 03 source sets + end-of-run summary).

Mirrors src/axial/test_ingest.py's own style: monkeypatch module-level names
so each behavior from the slice plans' "Inner loop" lists is pinned in
isolation, without touching a real pass, a real LLM provider, or real
docling. The outer, subprocess-level acceptance tests (tests/test_run.py,
tests/test_run_resume.py, tests/test_run_corpus.py) cover the end-to-end CLI
contract against real registered passes (`extract`/`envelope`/`chunk`); this
module covers the runner's own internal contract: registry resolution,
worklist/corpus source-set reading, failure isolation, the exit-code rule,
shared-client/config threading, the ledger read/append discipline, the
done-predicate skip branch, and (slice 03) the corpus resolver, the
exactly-one-source-set rule, and the returned `RunSummary`.

Every `run_pass(...)` call below passes an explicit `ledger_path=` under
`tmp_path` -- slice 02 gave `run_pass` a real default ledger
(`axial.run.LEDGER_PATH`, a repo-relative path), so a test that omitted this
would read/write the real repo's ledger file instead of a private one, the
same hygiene `src/axial/test_ingest.py` already applies to `results_path=`.
"""

from __future__ import annotations

import csv
import dataclasses
from pathlib import Path

import pytest

import axial.run as run_mod
from axial.run import (
    FAIL_STATUS,
    LEDGER_COLUMNS,
    OK_STATUS,
    PassDescriptor,
    RunSummary,
    SKIP_STATUS,
    THEORY_SCHOOL_RATES_COLUMNS,
    _append_ledger_row,
    _load_done_source_ids,
    attach_theory_school_rates,
    render_theory_school_rates,
    resolve_corpus_source_paths,
    run_pass,
)
from axial.tag import TheorySchoolSourceRate


class _FakeClient:
    """A sentinel client so tests can assert identity (constructed once,
    threaded unchanged into every pass invocation) without touching the real
    LLM provider machinery."""


class _DeclaredError(Exception):
    """Stand-in for a pass's own declared `*Error` base."""


class _UnexpectedError(Exception):
    """Stand-in for a genuine bug -- NOT the pass's declared error base."""


def _never_done(source_id, ledger_done_ids, config_path):
    """A done-predicate that always reports not-done -- the default for a
    fake registered pass in every slice-01-era test below, so adding the
    done-predicate field changes none of their existing behavior."""
    return False


def _register_fake_pass(
    monkeypatch, invoke, error=_DeclaredError, name="fake", done_predicate=None
):
    descriptor = PassDescriptor(name, invoke, error, done_predicate or _never_done)
    fake_registry = dict(run_mod.PASS_REGISTRY)
    fake_registry[name] = descriptor
    monkeypatch.setattr(run_mod, "PASS_REGISTRY", fake_registry)
    return descriptor


def _write_worklist(tmp_path: Path, lines: list[str]) -> Path:
    worklist = tmp_path / "worklist.txt"
    worklist.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return worklist


def _ledger_path(tmp_path: Path) -> Path:
    return tmp_path / "ledger.tsv"


def _write_ledger_tsv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=LEDGER_COLUMNS, delimiter="\t")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


# --- pass registry --------------------------------------------------------------


def test_known_pass_names_are_all_registered_with_a_callable_and_error_base():
    for name, descriptor in run_mod.PASS_REGISTRY.items():
        assert descriptor.name == name
        assert callable(descriptor.invoke)
        assert issubclass(descriptor.error, Exception)


def test_unknown_pass_name_is_fatal_before_any_source_is_touched(tmp_path, monkeypatch):
    worklist = _write_worklist(tmp_path, ["/fake/one.pdf"])
    calls: list[Path] = []
    monkeypatch.setattr(run_mod, "compute_source_id", lambda path: (calls.append(path), "id")[1])

    summary, exit_code = run_pass(
        "not-a-real-pass", worklist, client=_FakeClient(), ledger_path=_ledger_path(tmp_path)
    )
    outcomes = summary.outcomes

    assert exit_code == 1
    assert outcomes == []
    assert calls == []


# --- worklist reading ------------------------------------------------------------


def test_unreadable_worklist_is_fatal_and_attempts_no_source(tmp_path, monkeypatch):
    missing = tmp_path / "nope.txt"

    def _invoke(*args, **kwargs):
        raise AssertionError("no pass invocation for an unreadable worklist")

    _register_fake_pass(monkeypatch, _invoke)

    summary, exit_code = run_pass(
        "fake", missing, client=_FakeClient(), ledger_path=_ledger_path(tmp_path)
    )
    outcomes = summary.outcomes

    assert exit_code == 1
    assert outcomes == []


def test_blank_lines_in_worklist_are_skipped(tmp_path, monkeypatch):
    worklist = tmp_path / "worklist.txt"
    worklist.write_text("  /a/one.pdf  \n\n/a/two.pdf\n   \n", encoding="utf-8")

    seen: list[str] = []

    def _invoke(source_path, client, config_path, domain_dir):
        seen.append(source_path)

    _register_fake_pass(monkeypatch, _invoke)
    monkeypatch.setattr(run_mod, "compute_source_id", lambda path: str(path))

    summary, exit_code = run_pass(
        "fake", worklist, client=_FakeClient(), ledger_path=_ledger_path(tmp_path)
    )
    outcomes = summary.outcomes

    assert exit_code == 0
    assert [Path(path) for path in seen] == [Path("/a/one.pdf"), Path("/a/two.pdf")]
    assert [outcome.status for outcome in outcomes] == [OK_STATUS, OK_STATUS]


# --- source_id computation failure ------------------------------------------------


def test_source_whose_id_cannot_be_computed_is_recorded_fail_and_loop_continues(
    tmp_path, monkeypatch
):
    worklist = _write_worklist(tmp_path, ["/fake/missing.pdf", "/fake/good.pdf"])

    def _compute_source_id(path):
        if Path(path) == Path("/fake/missing.pdf"):
            raise run_mod.MissingSourceError(Path(path))
        return "good-id"

    monkeypatch.setattr(run_mod, "compute_source_id", _compute_source_id)

    seen: list[str] = []

    def _invoke(source_path, client, config_path, domain_dir):
        seen.append(source_path)

    _register_fake_pass(monkeypatch, _invoke)

    summary, exit_code = run_pass(
        "fake", worklist, client=_FakeClient(), ledger_path=_ledger_path(tmp_path)
    )
    outcomes = summary.outcomes

    assert exit_code == 0
    # The pass is never invoked for the source whose id could not be computed.
    assert [Path(path) for path in seen] == [Path("/fake/good.pdf")]
    assert len(outcomes) == 2

    missing_outcome = next(o for o in outcomes if Path(o.source_path) == Path("/fake/missing.pdf"))
    good_outcome = next(o for o in outcomes if Path(o.source_path) == Path("/fake/good.pdf"))
    assert missing_outcome.status == FAIL_STATUS
    assert missing_outcome.source_id == ""
    assert missing_outcome.reason
    assert good_outcome.status == OK_STATUS


# --- per-source failure isolation ---------------------------------------------------


def test_declared_error_is_recorded_fail_with_reason_and_loop_continues(tmp_path, monkeypatch):
    worklist = _write_worklist(tmp_path, ["/fake/bad.pdf", "/fake/good.pdf"])
    monkeypatch.setattr(run_mod, "compute_source_id", lambda path: f"id-{Path(path).stem}")

    def _invoke(source_path, client, config_path, domain_dir):
        if Path(source_path) == Path("/fake/bad.pdf"):
            raise _DeclaredError("boom")

    _register_fake_pass(monkeypatch, _invoke)

    summary, exit_code = run_pass(
        "fake", worklist, client=_FakeClient(), ledger_path=_ledger_path(tmp_path)
    )
    outcomes = summary.outcomes

    assert exit_code == 0
    by_path = {Path(outcome.source_path): outcome for outcome in outcomes}
    assert by_path[Path("/fake/bad.pdf")].status == FAIL_STATUS
    assert "boom" in by_path[Path("/fake/bad.pdf")].reason
    assert by_path[Path("/fake/good.pdf")].status == OK_STATUS


def test_undeclared_exception_propagates_and_is_not_swallowed(tmp_path, monkeypatch):
    worklist = _write_worklist(tmp_path, ["/fake/one.pdf"])
    monkeypatch.setattr(run_mod, "compute_source_id", lambda path: "id-1")

    def _invoke(source_path, client, config_path, domain_dir):
        raise _UnexpectedError("a genuine bug, not a recoverable per-source signal")

    _register_fake_pass(monkeypatch, _invoke)

    with pytest.raises(_UnexpectedError):
        run_pass("fake", worklist, client=_FakeClient(), ledger_path=_ledger_path(tmp_path))


# --- exit-code contract -------------------------------------------------------------


def test_exit_code_is_zero_when_some_sources_fail_but_loop_ran_to_completion(tmp_path, monkeypatch):
    worklist = _write_worklist(tmp_path, ["/fake/bad.pdf", "/fake/good.pdf"])
    monkeypatch.setattr(run_mod, "compute_source_id", lambda path: f"id-{Path(path).stem}")

    def _invoke(source_path, client, config_path, domain_dir):
        if Path(source_path) == Path("/fake/bad.pdf"):
            raise _DeclaredError("boom")

    _register_fake_pass(monkeypatch, _invoke)

    _summary, exit_code = run_pass(
        "fake", worklist, client=_FakeClient(), ledger_path=_ledger_path(tmp_path)
    )

    assert exit_code == 0


# --- shared client / config threading ------------------------------------------------


def test_client_config_path_and_domain_dir_are_threaded_into_every_invocation(
    tmp_path, monkeypatch
):
    worklist = _write_worklist(tmp_path, ["/fake/one.pdf", "/fake/two.pdf"])
    monkeypatch.setattr(run_mod, "compute_source_id", lambda path: f"id-{Path(path).stem}")

    received = []

    def _invoke(source_path, client, config_path, domain_dir):
        received.append((source_path, client, config_path, domain_dir))

    _register_fake_pass(monkeypatch, _invoke)

    client = _FakeClient()
    config_path = Path("some/pipeline.yaml")
    domain_dir = Path("some/domain")

    run_pass(
        "fake",
        worklist,
        client=client,
        config_path=config_path,
        domain_dir=domain_dir,
        ledger_path=_ledger_path(tmp_path),
    )

    assert len(received) == 2
    for _source_path, received_client, received_config_path, received_domain_dir in received:
        assert received_client is client
        assert received_config_path == config_path
        assert received_domain_dir == domain_dir


def test_client_is_constructed_once_when_not_supplied(tmp_path, monkeypatch):
    worklist = _write_worklist(tmp_path, ["/fake/one.pdf", "/fake/two.pdf"])
    monkeypatch.setattr(run_mod, "compute_source_id", lambda path: f"id-{Path(path).stem}")

    build_calls: list[_FakeClient] = []

    def _fake_get_client(config_path):
        client = _FakeClient()
        build_calls.append(client)
        return client

    monkeypatch.setattr(run_mod, "get_client", _fake_get_client)

    received_clients = []

    def _invoke(source_path, client, config_path, domain_dir):
        received_clients.append(client)

    _register_fake_pass(monkeypatch, _invoke)

    run_pass("fake", worklist, ledger_path=_ledger_path(tmp_path))

    assert len(build_calls) == 1
    assert received_clients == [build_calls[0], build_calls[0]]


# ---------------------------------------------------------------------------
# Slice 02: unified resume ledger + per-pass done-predicate
# ---------------------------------------------------------------------------


# --- ledger read/append helpers -------------------------------------------------


def test_load_done_source_ids_empty_when_ledger_absent(tmp_path):
    assert _load_done_source_ids(_ledger_path(tmp_path), "fake") == set()


def test_load_done_source_ids_filters_by_pass_and_ok_status(tmp_path):
    ledger = _ledger_path(tmp_path)
    _write_ledger_tsv(
        ledger,
        [
            {
                "pass": "fake",
                "source_path": "a.pdf",
                "source_id": "ok-1",
                "status": "OK",
                "reason": "",
                "timestamp": "t",
            },
            {
                "pass": "fake",
                "source_path": "b.pdf",
                "source_id": "fail-1",
                "status": "FAIL",
                "reason": "boom",
                "timestamp": "t",
            },
            {
                "pass": "other-pass",
                "source_path": "c.pdf",
                "source_id": "ok-1",
                "status": "OK",
                "reason": "",
                "timestamp": "t",
            },
        ],
    )

    # Only "fake"'s own OK row counts -- a same-source_id OK row recorded for
    # a different pass must not leak into this pass's done-set (the ledger
    # key is (pass, source_id), module docstring).
    assert _load_done_source_ids(ledger, "fake") == {"ok-1"}


def test_append_ledger_row_writes_header_once_then_appends(tmp_path):
    ledger = _ledger_path(tmp_path)
    row1 = {
        "pass": "fake",
        "source_path": "a.pdf",
        "source_id": "id-1",
        "status": "OK",
        "reason": "",
        "timestamp": "t1",
    }
    row2 = {**row1, "source_id": "id-2", "timestamp": "t2"}

    _append_ledger_row(ledger, row1)
    _append_ledger_row(ledger, row2)

    with ledger.open("r", newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))

    assert rows == [row1, row2]


def test_unappendable_ledger_is_fatal(tmp_path, monkeypatch):
    # A directory in place of the ledger file path can never be opened for
    # append -- OSError -> LedgerError -> fatal, non-zero exit, no source
    # attempted, mirroring axial.ingest.ResultsFileError.
    ledger = tmp_path / "ledger.tsv"
    ledger.mkdir()
    worklist = _write_worklist(tmp_path, ["/fake/one.pdf"])
    monkeypatch.setattr(run_mod, "compute_source_id", lambda path: "id-1")

    def _invoke(*args, **kwargs):
        raise AssertionError("no pass invocation once the ledger itself is unreadable")

    _register_fake_pass(monkeypatch, _invoke)

    summary, exit_code = run_pass("fake", worklist, client=_FakeClient(), ledger_path=ledger)
    outcomes = summary.outcomes

    assert exit_code == 1
    assert outcomes == []


# --- done-predicate skip branch -------------------------------------------------


def test_source_reported_done_is_skipped_with_zero_invocation_and_one_skip_line(
    tmp_path, monkeypatch, capsys
):
    worklist = _write_worklist(tmp_path, ["/fake/done.pdf"])
    monkeypatch.setattr(run_mod, "compute_source_id", lambda path: "done-id")

    def _invoke(*args, **kwargs):
        raise AssertionError("a done source must not invoke the pass callable")

    _register_fake_pass(monkeypatch, _invoke, done_predicate=lambda *a: True)

    summary, exit_code = run_pass(
        "fake", worklist, client=_FakeClient(), ledger_path=_ledger_path(tmp_path)
    )
    outcomes = summary.outcomes

    assert exit_code == 0
    assert len(outcomes) == 1
    assert outcomes[0].status == SKIP_STATUS

    captured = capsys.readouterr()
    skip_lines = [line for line in captured.out.splitlines() if line.startswith("skip:")]
    assert len(skip_lines) == 1
    assert "done.pdf" in skip_lines[0]
    assert "fake" in skip_lines[0]


def test_source_reported_done_appends_no_ledger_row(tmp_path, monkeypatch):
    ledger = _ledger_path(tmp_path)
    worklist = _write_worklist(tmp_path, ["/fake/done.pdf"])
    monkeypatch.setattr(run_mod, "compute_source_id", lambda path: "done-id")
    _register_fake_pass(monkeypatch, lambda *a, **k: None, done_predicate=lambda *a: True)

    run_pass("fake", worklist, client=_FakeClient(), ledger_path=ledger)

    assert not ledger.exists()


def test_done_predicate_receives_the_pass_own_loaded_done_set(tmp_path, monkeypatch):
    ledger = _ledger_path(tmp_path)
    _write_ledger_tsv(
        ledger,
        [
            {
                "pass": "fake",
                "source_path": "a.pdf",
                "source_id": "seen-id",
                "status": "OK",
                "reason": "",
                "timestamp": "t",
            }
        ],
    )
    worklist = _write_worklist(tmp_path, ["/fake/one.pdf"])
    monkeypatch.setattr(run_mod, "compute_source_id", lambda path: "seen-id")

    received_sets = []

    def _predicate(source_id, ledger_done_ids, config_path):
        received_sets.append(ledger_done_ids)
        return source_id in ledger_done_ids

    _register_fake_pass(
        monkeypatch,
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must be skipped")),
        done_predicate=_predicate,
    )

    summary, exit_code = run_pass("fake", worklist, client=_FakeClient(), ledger_path=ledger)
    outcomes = summary.outcomes

    assert exit_code == 0
    assert received_sets == [{"seen-id"}]
    assert outcomes[0].status == SKIP_STATUS


def test_not_done_source_runs_and_is_not_skipped(tmp_path, monkeypatch):
    worklist = _write_worklist(tmp_path, ["/fake/fresh.pdf"])
    monkeypatch.setattr(run_mod, "compute_source_id", lambda path: "fresh-id")

    calls = []
    _register_fake_pass(
        monkeypatch, lambda *a, **k: calls.append(a), done_predicate=lambda *a: False
    )

    summary, exit_code = run_pass(
        "fake", worklist, client=_FakeClient(), ledger_path=_ledger_path(tmp_path)
    )
    outcomes = summary.outcomes

    assert exit_code == 0
    assert len(calls) == 1
    assert outcomes[0].status == OK_STATUS


# --- one ledger row per non-skipped source, no duplicates on rerun --------------


def test_completed_source_appends_exactly_one_row_and_rerun_appends_no_duplicate(
    tmp_path, monkeypatch
):
    ledger = _ledger_path(tmp_path)
    worklist = _write_worklist(tmp_path, ["/fake/one.pdf"])
    monkeypatch.setattr(run_mod, "compute_source_id", lambda path: "one-id")
    invocations = []
    _register_fake_pass(monkeypatch, lambda *a, **k: invocations.append(a))

    run_pass("fake", worklist, client=_FakeClient(), ledger_path=ledger)
    with ledger.open("r", newline="", encoding="utf-8") as handle:
        rows_after_first = list(csv.DictReader(handle, delimiter="\t"))
    assert len(rows_after_first) == 1
    assert rows_after_first[0]["status"] == OK_STATUS

    # Re-run over the same worklist: the real (non-fake) ledger done-predicate
    # is what makes the second run skip -- re-register the pass with the
    # actual ledger-backed predicate this time.
    _register_fake_pass(
        monkeypatch,
        lambda *a, **k: invocations.append(a),
        done_predicate=run_mod._ledger_done_predicate,
    )
    run_pass("fake", worklist, client=_FakeClient(), ledger_path=ledger)

    with ledger.open("r", newline="", encoding="utf-8") as handle:
        rows_after_second = list(csv.DictReader(handle, delimiter="\t"))

    assert len(invocations) == 1, "the second run must not invoke the pass for a done source"
    assert rows_after_second == rows_after_first, (
        "no duplicate row appended and the first run's row survives unchanged"
    )


def test_fail_recorded_source_is_not_in_done_set_and_is_retried(tmp_path, monkeypatch):
    ledger = _ledger_path(tmp_path)
    worklist = _write_worklist(tmp_path, ["/fake/flaky.pdf"])
    monkeypatch.setattr(run_mod, "compute_source_id", lambda path: "flaky-id")

    attempt = {"count": 0}

    def _invoke(*args, **kwargs):
        attempt["count"] += 1
        if attempt["count"] == 1:
            raise _DeclaredError("boom")

    _register_fake_pass(monkeypatch, _invoke, done_predicate=run_mod._ledger_done_predicate)

    summary_1, exit_code_1 = run_pass("fake", worklist, client=_FakeClient(), ledger_path=ledger)
    outcomes_1 = summary_1.outcomes
    assert exit_code_1 == 0
    assert outcomes_1[0].status == FAIL_STATUS

    summary_2, exit_code_2 = run_pass("fake", worklist, client=_FakeClient(), ledger_path=ledger)
    outcomes_2 = summary_2.outcomes
    assert exit_code_2 == 0
    assert attempt["count"] == 2, "a FAIL-recorded source must be retried, not skipped"
    assert outcomes_2[0].status == OK_STATUS


# --- the real file-exists and ledger done-predicates ----------------------------


def test_tree_done_predicate_reports_done_iff_tree_file_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(run_mod, "tree_path", lambda source_id: tmp_path / f"{source_id}.json")

    assert run_mod._tree_done_predicate("abc", set(), Path("config/pipeline.yaml")) is False

    (tmp_path / "abc.json").write_text("{}", encoding="utf-8")
    assert run_mod._tree_done_predicate("abc", set(), Path("config/pipeline.yaml")) is True


def test_envelope_done_predicate_reports_done_iff_envelope_file_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(run_mod, "_default_envelopes_dir", lambda config_path: tmp_path)

    assert run_mod._envelope_done_predicate("abc", set(), Path("config/pipeline.yaml")) is False

    (tmp_path / "abc.json").write_text("{}", encoding="utf-8")
    assert run_mod._envelope_done_predicate("abc", set(), Path("config/pipeline.yaml")) is True


def test_ledger_done_predicate_reports_done_iff_source_id_in_done_set():
    assert run_mod._ledger_done_predicate("abc", {"abc"}, Path("config/pipeline.yaml")) is True
    assert run_mod._ledger_done_predicate("abc", {"xyz"}, Path("config/pipeline.yaml")) is False


def test_extract_and_envelope_use_file_exists_predicate_every_other_pass_uses_ledger():
    assert run_mod.PASS_REGISTRY["extract"].done_predicate is run_mod._tree_done_predicate
    assert run_mod.PASS_REGISTRY["envelope"].done_predicate is run_mod._envelope_done_predicate
    for name in ("chunk", "tag", "artifacts", "xref", "vault-write"):
        assert run_mod.PASS_REGISTRY[name].done_predicate is run_mod._ledger_done_predicate


# ---------------------------------------------------------------------------
# Slice 03: source-set inputs (corpus glob) + end-of-run summary
# ---------------------------------------------------------------------------


# --- corpus resolver --------------------------------------------------------------


def test_resolve_corpus_source_paths_returns_pdf_and_docx_sorted_ignoring_other_extensions(
    tmp_path,
):
    sources_dir = tmp_path / "sources"
    sources_dir.mkdir()
    (sources_dir / "b.pdf").write_bytes(b"")
    (sources_dir / "a.docx").write_bytes(b"")
    (sources_dir / "c.pdf").write_bytes(b"")
    (sources_dir / "ignored.txt").write_bytes(b"")
    (sources_dir / "ignored.md").write_bytes(b"")

    result = resolve_corpus_source_paths(sources_dir)

    # Sorted (deterministic) order, never raw filesystem enumeration order.
    assert result == sorted(result)
    assert [Path(path).name for path in result] == ["a.docx", "b.pdf", "c.pdf"]


def test_resolve_corpus_source_paths_empty_when_dir_absent(tmp_path):
    assert resolve_corpus_source_paths(tmp_path / "does-not-exist") == []


# --- exactly one source set --------------------------------------------------------


def test_worklist_and_corpus_together_is_a_usage_error_and_attempts_no_source(
    tmp_path, monkeypatch
):
    worklist = _write_worklist(tmp_path, ["/fake/one.pdf"])

    def _invoke(*args, **kwargs):
        raise AssertionError("no pass invocation for an invalid (both) source set")

    _register_fake_pass(monkeypatch, _invoke)

    summary, exit_code = run_pass(
        "fake",
        worklist,
        client=_FakeClient(),
        corpus=True,
        ledger_path=_ledger_path(tmp_path),
    )

    assert exit_code == 1
    assert summary.outcomes == []
    assert summary.total == 0


def test_neither_worklist_nor_corpus_is_a_usage_error_and_attempts_no_source(tmp_path, monkeypatch):
    def _invoke(*args, **kwargs):
        raise AssertionError("no pass invocation for an invalid (neither) source set")

    _register_fake_pass(monkeypatch, _invoke)

    summary, exit_code = run_pass("fake", client=_FakeClient(), ledger_path=_ledger_path(tmp_path))

    assert exit_code == 1
    assert summary.outcomes == []
    assert summary.total == 0


# --- corpus mode wiring -------------------------------------------------------------


def test_corpus_mode_drives_pass_over_resolved_sources_in_sorted_order(tmp_path, monkeypatch):
    sources_dir = tmp_path / "sources"
    sources_dir.mkdir()
    (sources_dir / "b.pdf").write_bytes(b"")
    (sources_dir / "a.docx").write_bytes(b"")
    (sources_dir / "ignored.txt").write_bytes(b"")

    monkeypatch.setattr(run_mod, "compute_source_id", lambda path: Path(path).stem)
    seen: list[str] = []
    _register_fake_pass(monkeypatch, lambda source_path, *a, **k: seen.append(source_path))

    summary, exit_code = run_pass(
        "fake",
        client=_FakeClient(),
        corpus=True,
        sources_dir=sources_dir,
        ledger_path=_ledger_path(tmp_path),
    )

    assert exit_code == 0
    assert seen == [str(sources_dir / "a.docx"), str(sources_dir / "b.pdf")]
    assert summary.total == 2


# --- the returned summary ------------------------------------------------------------


def test_summary_counts_sum_to_total_across_ok_fail_skip(tmp_path, monkeypatch):
    worklist = _write_worklist(tmp_path, ["/fake/ok.pdf", "/fake/bad.pdf", "/fake/done.pdf"])
    monkeypatch.setattr(run_mod, "compute_source_id", lambda path: f"id-{Path(path).stem}")

    def _invoke(source_path, client, config_path, domain_dir):
        if Path(source_path) == Path("/fake/bad.pdf"):
            raise _DeclaredError("boom")

    def _done_predicate(source_id, ledger_done_ids, config_path):
        return source_id == "id-done"

    _register_fake_pass(monkeypatch, _invoke, done_predicate=_done_predicate)

    summary, exit_code = run_pass(
        "fake", worklist, client=_FakeClient(), ledger_path=_ledger_path(tmp_path)
    )

    assert exit_code == 0
    assert summary.total == 3
    assert summary.ok_count == 1
    assert summary.fail_count == 1
    assert summary.skip_count == 1
    assert summary.ok_count + summary.fail_count + summary.skip_count == summary.total

    statuses_by_id = {outcome.source_id: outcome.status for outcome in summary.outcomes}
    assert statuses_by_id["id-ok"] == OK_STATUS
    assert statuses_by_id["id-bad"] == FAIL_STATUS
    assert statuses_by_id["id-done"] == SKIP_STATUS


def test_run_summary_outcome_rows_carry_only_ids_statuses_and_short_reasons():
    # DEC-23: the summary's per-source rows are ids, statuses, and short
    # reasons only -- never source text. Pinned at the schema level: Outcome
    # has no field that could ever hold extracted source content.
    field_names = {field.name for field in dataclasses.fields(run_mod.Outcome)}
    assert field_names == {"source_path", "source_id", "status", "reason"}


def test_summary_is_returned_as_structured_value_independent_of_stdout(
    tmp_path, monkeypatch, capsys
):
    worklist = _write_worklist(tmp_path, ["/fake/one.pdf"])
    monkeypatch.setattr(run_mod, "compute_source_id", lambda path: "id-1")
    _register_fake_pass(monkeypatch, lambda *args, **kwargs: None)

    summary, exit_code = run_pass(
        "fake", worklist, client=_FakeClient(), ledger_path=_ledger_path(tmp_path)
    )
    capsys.readouterr()  # drain printed output -- the return value stands alone

    assert exit_code == 0
    assert isinstance(summary, RunSummary)
    assert summary.pass_name == "fake"
    assert summary.outcomes[0].source_id == "id-1"
    # The named attachment point for #288's not-applicable/unlisted rates
    # report: this slice defines the seam and never computes it.
    assert summary.rates is None


# --- empty source set ----------------------------------------------------------------


def test_empty_worklist_source_set_exits_zero_with_total_zero_and_nothing_to_do_message(
    tmp_path, monkeypatch, capsys
):
    worklist = tmp_path / "empty.txt"
    worklist.write_text("\n\n", encoding="utf-8")

    def _invoke(*args, **kwargs):
        raise AssertionError("no pass invocation for an empty source set")

    _register_fake_pass(monkeypatch, _invoke)

    summary, exit_code = run_pass(
        "fake", worklist, client=_FakeClient(), ledger_path=_ledger_path(tmp_path)
    )

    assert exit_code == 0
    assert summary.total == 0
    assert summary.outcomes == []

    captured = capsys.readouterr()
    assert "nothing to do" in captured.out


def test_empty_corpus_source_set_exits_zero_with_total_zero(tmp_path, monkeypatch):
    sources_dir = tmp_path / "sources"  # never created -- an empty source set

    def _invoke(*args, **kwargs):
        raise AssertionError("no pass invocation for an empty corpus")

    _register_fake_pass(monkeypatch, _invoke)

    summary, exit_code = run_pass(
        "fake",
        client=_FakeClient(),
        corpus=True,
        sources_dir=sources_dir,
        ledger_path=_ledger_path(tmp_path),
    )

    assert exit_code == 0
    assert summary.total == 0
    assert summary.outcomes == []


# ---------------------------------------------------------------------------
# Issue #288: not-applicable/unlisted theory_school rates report attach
# ---------------------------------------------------------------------------


def test_attach_theory_school_rates_computes_from_ok_and_skip_excluding_fail(tmp_path, monkeypatch):
    worklist = _write_worklist(tmp_path, ["/fake/ok.pdf", "/fake/bad.pdf", "/fake/done.pdf"])
    monkeypatch.setattr(run_mod, "compute_source_id", lambda path: f"id-{Path(path).stem}")

    def _invoke(source_path, client, config_path, domain_dir):
        if Path(source_path) == Path("/fake/bad.pdf"):
            raise _DeclaredError("boom")

    def _done_predicate(source_id, ledger_done_ids, config_path):
        return source_id == "id-done"

    _register_fake_pass(monkeypatch, _invoke, done_predicate=_done_predicate)

    summary, _exit_code = run_pass(
        "fake", worklist, client=_FakeClient(), ledger_path=_ledger_path(tmp_path)
    )

    received = {}

    def _fake_report(source_ids, tags_dir=None, config_path=None):
        received["source_ids"] = set(source_ids)
        received["tags_dir"] = tags_dir
        received["config_path"] = config_path
        return ["canned-rate"]

    monkeypatch.setattr(run_mod, "theory_school_rates_report", _fake_report)

    updated = attach_theory_school_rates(summary, tags_dir=Path("some/tags"))

    # A FAILed source produced no tag output this run -- excluded. OK and
    # SKIP source_ids both go in.
    assert received["source_ids"] == {"id-ok", "id-done"}
    assert received["tags_dir"] == Path("some/tags")
    assert updated.rates == ["canned-rate"]

    # Every other field of the returned summary is the same summary,
    # untouched (an immutable attach, not a rebuild).
    assert updated.pass_name == summary.pass_name
    assert updated.outcomes == summary.outcomes
    assert updated.total == summary.total
    assert updated.ok_count == summary.ok_count
    assert updated.fail_count == summary.fail_count
    assert updated.skip_count == summary.skip_count


def test_attach_theory_school_rates_never_raises_on_an_unexpected_computation_failure(
    tmp_path, monkeypatch
):
    # The issue's own acceptance bar: "the summary never blocks or fails the
    # run." Even a genuinely unexpected bug in the rates computation must
    # not propagate past this seam -- the run itself already finished.
    worklist = _write_worklist(tmp_path, ["/fake/one.pdf"])
    monkeypatch.setattr(run_mod, "compute_source_id", lambda path: "id-1")
    _register_fake_pass(monkeypatch, lambda *a, **k: None)

    summary, _exit_code = run_pass(
        "fake", worklist, client=_FakeClient(), ledger_path=_ledger_path(tmp_path)
    )

    def _boom(source_ids, tags_dir=None, config_path=None):
        raise RuntimeError("a genuinely unexpected bug in the rates computation")

    monkeypatch.setattr(run_mod, "theory_school_rates_report", _boom)

    updated = attach_theory_school_rates(summary)  # must not raise

    assert updated.rates is None
    assert updated.outcomes == summary.outcomes


def test_render_theory_school_rates_returns_empty_string_for_no_rates():
    assert render_theory_school_rates([]) == ""


def test_render_theory_school_rates_formats_a_header_and_one_row_per_source():
    rates = [
        TheorySchoolSourceRate(
            source_id="src-1",
            total=100,
            not_applicable_count=27,
            not_applicable_pct=27.0,
            unlisted_count=3,
            unlisted_pct=3.0,
            unlisted_schools=["pluralist"],
        )
    ]

    rendered = render_theory_school_rates(rates)
    lines = rendered.splitlines()

    assert lines[0] == "\t".join(THEORY_SCHOOL_RATES_COLUMNS)
    assert len(lines) == 2
    assert "src-1" in lines[1]
    assert "27.0%" in lines[1]
    assert "3.0%" in lines[1]
    assert "pluralist" in lines[1]
