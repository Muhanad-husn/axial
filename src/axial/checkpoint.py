"""Generic JSONL checkpoint primitives shared by every per-record pass that
needs "append as each record is produced, resume by skip-set" persistence.

Built for `axial.tag`'s tag-pass checkpoint (issue #81) and reused unchanged
by `axial.artifacts`' per-artifact checkpoint (issue #98) -- the healing/
corruption rules are identical for both: a torn FINAL line (a hard kill
mid-append) is healed (dropped) rather than poisoning the resume, since each
append writes and flushes exactly one line before returning, so a kill can
only ever tear the line currently in flight, always the last one. A torn
line anywhere else is genuine corruption unrelated to a kill mid-append, and
still raises loudly, naming the checkpoint path and the offending 1-indexed
line number.

Callers keep their own typed corruption error (e.g.
`axial.tag.TagCheckpointCorruptError`) so an exception raised here always
carries the caller's own class identity; this module only supplies the
shared read/write/heal mechanics, never the vocabulary layered on top.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable


def heal_torn_checkpoint_tail(path: Path) -> None:
    """Truncate a torn tail left by a hard kill mid-append, so the next
    append always starts a fresh record on its own line. A no-op when the
    file doesn't exist yet or already ends cleanly (empty, or ends with
    '\\n')."""
    if not path.exists():
        return
    data = path.read_bytes()
    if not data or data.endswith(b"\n"):
        return
    last_newline = data.rfind(b"\n")
    healed = data[: last_newline + 1] if last_newline != -1 else b""
    path.write_bytes(healed)


def append_checkpoint_record(path: Path, record: dict[str, Any]) -> None:
    """Append one record to `path` AS IT IS PRODUCED: heal any torn tail
    left by an earlier hard kill, then open in append mode, write the JSON
    line, and close so the write is flushed to disk before the caller moves
    on. Creates parent directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    heal_torn_checkpoint_tail(path)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")


def load_checkpoint_records(
    path: Path,
    corrupt_error: Callable[[Path, int, json.JSONDecodeError], Exception],
) -> list[dict[str, Any]]:
    """Load already-persisted records from a checkpoint file (the inverse of
    `append_checkpoint_record`), skipping blank lines. Returns an empty list
    when the file does not exist yet (the first, never-interrupted run).

    A torn FINAL line is dropped silently (its record simply reappears in
    the caller's skip-set gap and is re-produced on the resume run); a torn
    line that is NOT the last one raises `corrupt_error(path, line_no,
    cause)` -- `line_no` is 1-indexed."""
    if not path.exists():
        return []
    numbered_lines = [
        (line_no, stripped)
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if (stripped := line.strip())
    ]
    records: list[dict[str, Any]] = []
    for index, (line_no, line) in enumerate(numbered_lines):
        is_last = index == len(numbered_lines) - 1
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as exc:
            if is_last:
                break
            raise corrupt_error(path, line_no, exc) from exc
    return records
