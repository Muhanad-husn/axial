"""Inner unit tests for the name-page path budget (issue #411, Materialize):
`axial.paths.name_page_filename`/`name_page_path`. Mirrors
`axial.query.test_reader`'s own `_WINDOWS_MAX_PATH` monkeypatch seam for
`budgeted_chunk_filename`/`budgeted_artifact_filename`, so the over-budget
path is exercised deterministically regardless of the OS or the test's own
tmp dir depth.

Also pins the pipeline-config memo behind every `default_*_dir` helper
(issue #541)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

import axial.paths
from axial.paths import (
    NAMES_DIR,
    VAULT_DIR,
    atomic_write_text,
    default_names_dir,
    default_vault_dir,
    name_page_filename,
    name_page_path,
)

# Low enough that `path_overage` is positive for any real name under a real
# tmp_path -- same convention `axial.query.test_reader` uses.
_TEST_MAX_PATH = 25


def test_name_page_filename_is_verbatim_for_an_ordinary_short_name(tmp_path):
    directory = tmp_path / "names"
    assert name_page_filename(directory, "Ba'ath Party") == "Ba'ath Party.md"


def test_name_page_filename_sanitizes_illegal_windows_characters(tmp_path):
    directory = tmp_path / "names"
    filename = name_page_filename(directory, 'Question: "Who"/What?')
    assert filename == "Question- -Who--What-.md"
    assert not any(char in filename for char in '<>:"/\\|?*')


def test_name_page_filename_truncates_and_hashes_when_over_budget(monkeypatch, tmp_path):
    monkeypatch.setattr(axial.paths, "_WINDOWS_MAX_PATH", _TEST_MAX_PATH)
    directory = tmp_path / "names"

    name = "!Kung San of Namibia and Botswana"
    filename = name_page_filename(directory, name)

    assert filename != f"{name}.md"
    assert filename.endswith(".md")
    # 8 hex chars + "-" + ".md" -- the content hash suffix survives the
    # shrink verbatim; only the readable name prefix is ever shortened.
    stem = filename[: -len(".md")]
    assert len(stem.rsplit("-", 1)[-1]) == 8


def test_name_page_filename_is_deterministic_given_the_same_name(tmp_path):
    directory = tmp_path / "names"
    assert name_page_filename(directory, "Same Name") == name_page_filename(directory, "Same Name")


def test_name_page_filename_forces_a_hash_suffix_on_a_used_collision(tmp_path):
    """Two different canonical names that sanitize to the identical
    filename (an illegal character folded to the same '-') must not
    silently overwrite each other on disk: the second claim of an already-
    `used` filename is forced to the content-hashed form instead, even
    though it would otherwise fit comfortably under budget."""
    directory = tmp_path / "names"
    used: set[str] = set()

    first = name_page_filename(directory, "A/B", used)
    second = name_page_filename(directory, "A:B", used)

    assert first == "A-B.md"
    assert second != first
    assert second.endswith(".md")
    assert first.casefold() in used and second.casefold() in used


def test_name_page_filename_no_collision_without_a_used_case_insensitive_match(tmp_path):
    directory = tmp_path / "names"
    used: set[str] = set()

    first = name_page_filename(directory, "USA", used)
    second = name_page_filename(directory, "usa", used)

    # Windows filenames are case-insensitive: "USA.md" and "usa.md" are the
    # SAME file, so the second claim must be forced to a distinct name.
    assert first == "USA.md"
    assert second != first


def test_name_page_path_joins_the_vault_names_directory(tmp_path):
    vault_dir = tmp_path / "vault"
    path = name_page_path(vault_dir, "Kevin Attell")
    assert path == vault_dir / "names" / "Kevin Attell.md"


# --- The pipeline-config memo (issue #541) ---------------------------------


def _write_config(path: Path, names_dir: str) -> None:
    path.write_text(f"paths:\n  names_dir: {names_dir}\n", encoding="utf-8")


def test_the_pipeline_config_is_parsed_once_per_path_not_once_per_call(tmp_path, monkeypatch):
    """Every `default_*_dir` helper re-read and re-parsed the whole pipeline
    config on every call, which measured 28.7ms a call against the real
    26.6KB `config/pipeline.yaml` -- and `canonical_name_for_surface` pays
    it per surface per pair, ~4,000 times in one counter-position check
    (issue #541). Parse count, not wall clock, is the thing to pin: it is
    the cost, and it is deterministic."""
    config = tmp_path / "pipeline.yaml"
    _write_config(config, "data/other_names")

    parses = 0
    real_load = yaml.load

    def counting_load(stream, *args, **kwargs):
        nonlocal parses
        parses += 1
        return real_load(stream, *args, **kwargs)

    monkeypatch.setattr(axial.paths.yaml, "load", counting_load)

    for _ in range(5):
        assert default_names_dir(config) == Path("data/other_names")
        assert default_vault_dir(config) == VAULT_DIR

    assert parses == 1


def test_an_edited_pipeline_config_is_re_read(tmp_path):
    """The memo notices a changed file rather than needing to be told to
    forget one: an operator editing `config/pipeline.yaml` between runs, and
    any test that rewrites its own config, must see the new value."""
    config = tmp_path / "pipeline.yaml"
    _write_config(config, "data/first_names")
    assert default_names_dir(config) == Path("data/first_names")

    _write_config(config, "data/a_completely_different_names_dir")
    assert default_names_dir(config) == Path("data/a_completely_different_names_dir")


def test_a_deleted_pipeline_config_falls_back(tmp_path):
    config = tmp_path / "pipeline.yaml"
    _write_config(config, "data/other_names")
    assert default_names_dir(config) == Path("data/other_names")

    config.unlink()
    assert default_names_dir(config) == NAMES_DIR


def test_the_config_memo_does_not_leak_across_working_directories(tmp_path, monkeypatch):
    """`DEFAULT_PIPELINE_CONFIG_PATH` is the RELATIVE path
    `config/pipeline.yaml`, and several suites `monkeypatch.chdir` inside one
    process, so two cwds mean two different files under one identical
    relative path. The memo must key on where the path actually points."""
    for root, names_dir in ((tmp_path / "first", "data/aaa"), (tmp_path / "second", "data/bbb")):
        (root / "config").mkdir(parents=True)
        _write_config(root / "config" / "pipeline.yaml", names_dir)

    monkeypatch.chdir(tmp_path / "first")
    assert default_names_dir() == Path("data/aaa")

    monkeypatch.chdir(tmp_path / "second")
    assert default_names_dir() == Path("data/bbb")


# --- `os.replace` retry on a Windows-only `PermissionError` (issue #653) ---
#
# A real open-handle test (holding `names.jsonl` open while the write runs)
# lives in `tests/ingestion/test_materialize.py` against the actual
# `_write_name_page_index`, since only Windows' `os.replace` ever raises
# `PermissionError` for this reason -- on Linux/CI that test passes for a
# different reason (the swap simply succeeds under the open handle). The
# tests below force the `PermissionError` deterministically via monkeypatch
# so the retry path and the give-up-and-raise path are exercised on every
# platform.


def test_atomic_write_text_retries_past_a_transient_permission_error(tmp_path, monkeypatch):
    """A reader's handle on `path` is open for milliseconds -- a `Permission
    Error` from `os.replace` that clears within the retry budget must not
    fail the write."""
    path = tmp_path / "names.jsonl"
    path.write_text("old", encoding="utf-8")

    real_replace = os.replace
    calls = {"count": 0}

    def flaky_replace(src, dst):
        calls["count"] += 1
        if calls["count"] < 3:
            raise PermissionError("[WinError 5] Access is denied")
        real_replace(src, dst)

    monkeypatch.setattr(axial.paths.os, "replace", flaky_replace)
    monkeypatch.setattr(axial.paths.time, "sleep", lambda seconds: None)

    atomic_write_text(path, "new")

    assert calls["count"] == 3
    assert path.read_text(encoding="utf-8") == "new"


def test_atomic_write_text_gives_up_and_raises_after_exhausting_retries(tmp_path, monkeypatch):
    """A `PermissionError` that never clears (a reader that never lets go)
    must surface loudly rather than being swallowed or retried forever, and
    the destination must be left untouched -- the failed write is not
    allowed to lose the prior content."""
    path = tmp_path / "names.jsonl"
    path.write_text("old", encoding="utf-8")

    def always_denied(src, dst):
        raise PermissionError("[WinError 5] Access is denied")

    monkeypatch.setattr(axial.paths.os, "replace", always_denied)
    monkeypatch.setattr(axial.paths.time, "sleep", lambda seconds: None)

    with pytest.raises(PermissionError):
        atomic_write_text(path, "new")

    assert path.read_text(encoding="utf-8") == "old"
    leftover_tmp_files = list(tmp_path.glob(".names.jsonl.*.tmp"))
    assert leftover_tmp_files == [], f"temp file(s) left behind: {leftover_tmp_files!r}"


def test_atomic_write_text_does_not_retry_a_non_permission_oserror(tmp_path, monkeypatch):
    """A missing parent directory or similar real failure must propagate on
    the first attempt -- only `PermissionError` is treated as the transient,
    Windows-reader case."""
    path = tmp_path / "names.jsonl"
    path.write_text("old", encoding="utf-8")

    calls = {"count": 0}

    def broken_replace(src, dst):
        calls["count"] += 1
        raise FileNotFoundError("parent directory vanished")

    monkeypatch.setattr(axial.paths.os, "replace", broken_replace)
    monkeypatch.setattr(axial.paths.time, "sleep", lambda seconds: None)

    with pytest.raises(FileNotFoundError):
        atomic_write_text(path, "new")

    assert calls["count"] == 1, "a non-PermissionError OSError must not be retried"
    assert path.read_text(encoding="utf-8") == "old"
    leftover_tmp_files = list(tmp_path.glob(".names.jsonl.*.tmp"))
    assert leftover_tmp_files == [], f"temp file(s) left behind: {leftover_tmp_files!r}"
