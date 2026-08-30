"""Slice 05's real-corpus run: the branch's code, the main checkout's data.

Run from D:/axial with the worktree's venv python. `run_map_build`'s own
injection seams are what makes this possible without touching either tree:
`config_path` points at the branch config (which alone carries the
`position_consolidate` pass entry), and every data directory resolves
relative to this process's cwd, which is the main checkout.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

LOGDIR = Path("data/logs/2026-08-29-consolidation-pass")
CONFIG = Path("D:/axial-wt/830-consolidation/config/pipeline.yaml")


def main() -> int:
    assert Path.cwd() == Path("D:/axial"), f"wrong cwd: {Path.cwd()}"
    import axial.argmap.build as build

    assert "axial-wt" in build.__file__, f"not the branch's code: {build.__file__}"
    LOGDIR.mkdir(parents=True, exist_ok=True)
    events = (LOGDIR / "run.jsonl").open("a", encoding="utf-8")

    def record(**fields):
        fields["t"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        events.write(json.dumps(fields, ensure_ascii=False) + "\n")
        events.flush()
        os.fsync(events.fileno())

    def log(line: str) -> None:
        print(line, flush=True)
        record(event="log", line=line)

    record(event="start", build_module=build.__file__, config=str(CONFIG), cwd=str(Path.cwd()))
    started = time.monotonic()
    try:
        manifest = build.run_map_build(
            config_path=CONFIG,
            grouping=build.GROUPING_CATEGORY,
            log=log,
        )
    except Exception as exc:  # noqa: BLE001 -- journal it, then fail loudly
        record(event="failed", error=repr(exc)[:500])
        raise
    record(event="done", wall_sec=time.monotonic() - started, counts=manifest.get("counts"))
    (LOGDIR / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
