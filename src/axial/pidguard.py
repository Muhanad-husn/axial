"""Single-instance guard for a long-running paid pass (issue #572).

This exists because of a real incident on 2026-08-01: `uv run python`
spawns a Windows `python.exe` child that SURVIVES its bash wrapper being
killed, and `ps` inside Git Bash never lists it. Two orphaned copies ran
concurrently against a stale prompt, held the output file open (so even
`rm` failed, "device busy"), and kept spending -- while the launching side
believed the run had been stopped. A long paid pass must be findable and
killable independently of its launcher, and must refuse to start a second
time over the same output directory while an earlier copy is still alive.

Generic over the caller's own output directory rather than owned by
`axial.argmap` alone -- any future long-running, resumable, paid pass can
reuse it the same way `axial.checkpoint`'s JSONL primitives are shared.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


class AlreadyRunningError(Exception):
    """Raised when another copy of this pass is already running over the
    same output directory -- carries the prior PID and the pid-file path so
    the caller can report (or kill) it."""

    def __init__(self, pid: int, pid_path: Path):
        self.pid = pid
        self.pid_path = pid_path
        super().__init__(
            f"refusing to start: pid {pid} is already running this pass ({pid_path}); kill it first"
        )


def _pid_alive(pid: int) -> bool:
    if os.name == "nt":
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def claim_single_instance(outdir: Path) -> None:
    """Refuse to start if another copy of this pass is already running over
    `outdir`, and leave a PID file (`outdir/RUNNING.pid`) so any copy can be
    found and killed independently of the shell that launched it. Raises
    `AlreadyRunningError` when a live prior PID is found; otherwise writes
    this process's own PID and returns. The caller removes the pid file on
    a clean finish (`outdir / "RUNNING.pid").unlink(missing_ok=True)`)."""
    pid_path = outdir / "RUNNING.pid"
    if pid_path.is_file():
        try:
            prior = int(pid_path.read_text(encoding="utf-8").strip())
        except ValueError:
            prior = None
        if prior is not None and _pid_alive(prior):
            raise AlreadyRunningError(prior, pid_path)
    pid_path.write_text(str(os.getpid()), encoding="utf-8")
