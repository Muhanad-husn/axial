"""How the console runs `axial`: as a subprocess, always, never by importing
a pass module and driving it (issue #689's design rationale -- a console that
only calls the CLI cannot break the pipeline).

Two shapes, because the console needs exactly two:

- `run_axial` for a question that answers instantly and is worth waiting for
  (`axial sources --check`, `axial status`).
- `launch_detached` for a pass that runs for hours. **It must outlive the
  console.** A Streamlit server restarts on every file save and the operator
  closes the browser tab as a matter of course; a child that dies with either
  would take an eight-hour ingest with it. On Windows that means
  `DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP` -- no inherited console, so
  neither a Ctrl-C in the console's terminal nor the terminal closing reaches
  it -- and on POSIX the equivalent `start_new_session=True`. Once launched,
  the pass is tracked like any other run, through the run directory it opens
  under `data/logs/`, never through a handle this process holds.
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from axial.runlog import LOGS_ROOT, LOGS_ROOT_ENV_VAR

# `python -m axial.cli` rather than the `axial` console script: it is the same
# entry point (`axial.cli.main`) and it resolves through the interpreter
# already running the console, so it cannot pick up a different checkout's
# script shim from PATH.
_AXIAL_ARGV = (sys.executable, "-m", "axial.cli")


def _logs_root() -> Path:
    override = os.environ.get(LOGS_ROOT_ENV_VAR, "")
    return Path(override) if override else LOGS_ROOT


def run_axial(args: list[str], *, timeout: float = 120.0) -> subprocess.CompletedProcess[str]:
    """Run `axial <args>` to completion and capture its output. For the
    read-only commands only -- anything that runs a pass goes through
    `launch_detached`."""
    return subprocess.run(
        [*_AXIAL_ARGV, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        encoding="utf-8",
        errors="replace",
    )


def _detach_kwargs() -> dict[str, object]:
    """The platform's own "survive this process" flags (module docstring)."""
    if sys.platform == "win32":
        return {
            "creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
            "close_fds": True,
        }
    return {"start_new_session": True, "close_fds": True}


def launch_detached(args: list[str]) -> tuple[int, Path]:
    """Start `axial <args>` as a process that outlives this one, and return
    its pid and the file its console output is being written to.

    A detached process has no console to inherit, so its stdout/stderr are
    redirected to a file under the logs root -- without that, the pass's
    first `print` fails on Windows. The file is deliberately not a run
    directory: the pass opens its own, and that is what the monitor reads."""
    logs_root = _logs_root()
    logs_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    console_log = logs_root / f"console-launch-{stamp}.log"

    with console_log.open("ab") as sink:
        process = subprocess.Popen(  # noqa: S603 -- fixed argv, no shell
            [*_AXIAL_ARGV, *args],
            stdin=subprocess.DEVNULL,
            stdout=sink,
            stderr=subprocess.STDOUT,
            **_detach_kwargs(),
        )
    return process.pid, console_log


def parse_sources_report(stdout: str) -> list[dict[str, str]]:
    """`axial sources --check`'s tab-separated report, back into rows.
    `axial.sources.REPORT_COLUMNS` is the contract: a header line, then one
    `name/status/reason` row per listed item. Anything that does not split
    into the header's own column count is skipped rather than raised on --
    the console must still render when a warning line lands on stdout."""
    lines = [line for line in stdout.splitlines() if line.strip()]
    if not lines:
        return []
    header = lines[0].split("\t")
    rows = []
    for line in lines[1:]:
        cells = line.split("\t")
        if len(cells) != len(header):
            continue
        rows.append(dict(zip(header, cells)))
    return rows
