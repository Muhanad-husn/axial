"""Inner unit tests for the axial run module (issue #277, slice 01: runner
core + pass registry + per-source failure isolation).

Mirrors src/axial/test_ingest.py's own style: monkeypatch module-level names
so each behavior from the slice plan's "Inner loop" list is pinned in
isolation, without touching a real pass, a real LLM provider, or real
docling. The outer, subprocess-level acceptance test (tests/test_run.py)
covers the end-to-end CLI contract against a real registered pass
(`extract`); this module covers the runner's own internal contract: registry
resolution, worklist reading, failure isolation, the exit-code rule, and
shared-client/config threading.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import axial.run as run_mod
from axial.run import FAIL_STATUS, OK_STATUS, PassDescriptor, run_pass


class _FakeClient:
    """A sentinel client so tests can assert identity (constructed once,
    threaded unchanged into every pass invocation) without touching the real
    LLM provider machinery."""


class _DeclaredError(Exception):
    """Stand-in for a pass's own declared `*Error` base."""


class _UnexpectedError(Exception):
    """Stand-in for a genuine bug -- NOT the pass's declared error base."""


def _register_fake_pass(monkeypatch, invoke, error=_DeclaredError, name="fake"):
    descriptor = PassDescriptor(name, invoke, error)
    fake_registry = dict(run_mod.PASS_REGISTRY)
    fake_registry[name] = descriptor
    monkeypatch.setattr(run_mod, "PASS_REGISTRY", fake_registry)
    return descriptor


def _write_worklist(tmp_path: Path, lines: list[str]) -> Path:
    worklist = tmp_path / "worklist.txt"
    worklist.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return worklist


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

    outcomes, exit_code = run_pass("not-a-real-pass", worklist, client=_FakeClient())

    assert exit_code == 1
    assert outcomes == []
    assert calls == []


# --- worklist reading ------------------------------------------------------------


def test_unreadable_worklist_is_fatal_and_attempts_no_source(tmp_path, monkeypatch):
    missing = tmp_path / "nope.txt"

    def _invoke(*args, **kwargs):
        raise AssertionError("no pass invocation for an unreadable worklist")

    _register_fake_pass(monkeypatch, _invoke)

    outcomes, exit_code = run_pass("fake", missing, client=_FakeClient())

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

    outcomes, exit_code = run_pass("fake", worklist, client=_FakeClient())

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

    outcomes, exit_code = run_pass("fake", worklist, client=_FakeClient())

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

    outcomes, exit_code = run_pass("fake", worklist, client=_FakeClient())

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
        run_pass("fake", worklist, client=_FakeClient())


# --- exit-code contract -------------------------------------------------------------


def test_exit_code_is_zero_when_some_sources_fail_but_loop_ran_to_completion(tmp_path, monkeypatch):
    worklist = _write_worklist(tmp_path, ["/fake/bad.pdf", "/fake/good.pdf"])
    monkeypatch.setattr(run_mod, "compute_source_id", lambda path: f"id-{Path(path).stem}")

    def _invoke(source_path, client, config_path, domain_dir):
        if Path(source_path) == Path("/fake/bad.pdf"):
            raise _DeclaredError("boom")

    _register_fake_pass(monkeypatch, _invoke)

    _outcomes, exit_code = run_pass("fake", worklist, client=_FakeClient())

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

    run_pass("fake", worklist, client=client, config_path=config_path, domain_dir=domain_dir)

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

    run_pass("fake", worklist)

    assert len(build_calls) == 1
    assert received_clients == [build_calls[0], build_calls[0]]
