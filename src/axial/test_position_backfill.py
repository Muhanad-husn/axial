"""Inner unit tests for `axial.position_backfill`'s own write path
(`_rewrite_answers_file`) -- the end-to-end backfill pass has its own
acceptance coverage in `tests/ingestion/test_position_backfill.py`.

Covered here: the #705 fix routing `_rewrite_answers_file` through
`axial.paths.atomic_write_text`, so a transient Windows `PermissionError` on
the final rename (#653) is retried rather than aborting a whole corpus pass,
and the hand-rolled fixed `<name>.tmp` sibling (the #705 bug report's own
"orphaned .tmp files" symptom) is gone in favor of a unique `mkstemp` name
that is always cleaned up.
"""

from __future__ import annotations

import json

import pytest

from axial.position_backfill import _rewrite_answers_file


def test_rewrite_answers_file_retries_past_a_transient_permission_error(tmp_path, monkeypatch):
    import axial.paths

    path = tmp_path / "source-2020-aaaa.jsonl"
    path.write_text(json.dumps({"chunk_id": "old"}) + "\n", encoding="utf-8")

    real_replace = axial.paths.os.replace
    calls = {"count": 0}

    def flaky_replace(src, dst):
        calls["count"] += 1
        if calls["count"] < 3:
            raise PermissionError("[WinError 5] Access is denied")
        real_replace(src, dst)

    monkeypatch.setattr(axial.paths.os, "replace", flaky_replace)
    monkeypatch.setattr(axial.paths.time, "sleep", lambda seconds: None)

    records = [{"chunk_id": "new", "answers": {"position": "a stance"}}]
    _rewrite_answers_file(path, records)

    assert calls["count"] == 3
    assert [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] == records
    leftover_tmp_files = list(tmp_path.glob("*.tmp"))
    assert leftover_tmp_files == [], f"temp file(s) left behind: {leftover_tmp_files!r}"


def test_rewrite_answers_file_gives_up_and_raises_after_exhausting_retries(tmp_path, monkeypatch):
    """A `PermissionError` that never clears must surface loudly, leave the
    original file untouched, and not leave a predictable `<name>.tmp`
    orphan behind (issue #705's own bug report symptom)."""
    import axial.paths

    path = tmp_path / "source-2020-aaaa.jsonl"
    original = json.dumps({"chunk_id": "old"}) + "\n"
    path.write_text(original, encoding="utf-8")

    def always_denied(src, dst):
        raise PermissionError("[WinError 5] Access is denied")

    monkeypatch.setattr(axial.paths.os, "replace", always_denied)
    monkeypatch.setattr(axial.paths.time, "sleep", lambda seconds: None)

    with pytest.raises(PermissionError):
        _rewrite_answers_file(path, [{"chunk_id": "new", "answers": {"position": "a stance"}}])

    assert path.read_text(encoding="utf-8") == original
    assert not (tmp_path / (path.name + ".tmp")).exists()
    leftover_tmp_files = list(tmp_path.glob("*.tmp"))
    assert leftover_tmp_files == [], f"temp file(s) left behind: {leftover_tmp_files!r}"
