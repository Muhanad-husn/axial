"""Subprocess harness for `test_worker_snapshot.py` (issue #684): a real
worker process, bound to one snapshot at process start, draining the shared
queue.

Two real OS processes are the point -- the binding is `os.chdir` into the
snapshot root, which is process-global exactly as the issue's own model
requires ("rolling a new corpus is a new worker image"). Two workers on two
snapshots therefore cannot be simulated with two objects in one process.

Run as:

    python _snapshot_worker.py <dsn> <snapshot_root> <work_dir> [<gate_dir>]

The engine is stubbed (`axial.service.worker.run_ask` is monkeypatched in
this process) so no model is called and nothing is paid for. The stub reads
the corpus through CWD-RELATIVE paths on purpose: `vault/prose/*.md` and
`evals/corpus_pin/`, which is precisely what a bound snapshot must make
resolve to itself. When `<gate_dir>` is given the stub reads the corpus
twice -- once before signalling, once after being released -- so a test can
publish a new snapshot in between and see whether the in-flight job moved.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from axial.answer.record import BriefRunResult
from axial.ask.engine import Turn
from axial.brief.intake import Brief
from axial.eval.corpus_pin import resolve_pin_id
from axial.service import worker as worker_mod
from axial.service.jobs import JobStore
from axial.service.snapshot import Snapshot
from axial.service.worker import Worker, run_ask_job

_GATE_TIMEOUT_SECONDS = 60.0


def _read_corpus() -> dict[str, str]:
    """What this process can see of the corpus right now, read entirely
    through cwd-relative paths."""
    passages = sorted(path.read_text(encoding="utf-8") for path in Path("vault/prose").glob("*.md"))
    return {"pin": resolve_pin_id(), "passage": "".join(passages).strip().splitlines()[-1]}


def _wait_for(path: Path) -> None:
    deadline = time.monotonic() + _GATE_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if path.exists():
            return
        time.sleep(0.05)
    raise RuntimeError(f"gate {path} never appeared")


def main() -> None:
    dsn, snapshot_root, work_dir = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
    gate_dir = Path(sys.argv[4]) if len(sys.argv) > 4 else None

    snapshot = Snapshot.open(snapshot_root)
    work_dir = work_dir.resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    if gate_dir is not None:
        gate_dir = gate_dir.resolve()

    def fake_ask(question, case, **kwargs):
        first = _read_corpus()
        if gate_dir is not None:
            (gate_dir / "claimed").write_text("1", encoding="utf-8")
            _wait_for(gate_dir / "go")
        second = _read_corpus()

        analyses_dir = Path(kwargs["analyses_dir"])
        analyses_dir.mkdir(parents=True, exist_ok=True)
        result_path = analyses_dir / "result.json"
        result_path.write_text(
            json.dumps({"first": first, "second": second, "map_pin": kwargs.get("map_pin")}),
            encoding="utf-8",
        )
        brief = Brief(brief_id="b1", case=case, request=question)
        return Turn(
            session_id="s1",
            turn_index=1,
            question=question,
            case=case,
            brief=brief,
            result=BriefRunResult(
                # The pin the engine itself resolved, from the corpus it
                # actually read -- never handed in by the caller. This is
                # what `run_ask_job`'s reconciliation check compares
                # against the snapshot's manifest.
                record={"corpus_pin": second["pin"]},
                path=result_path,
                markdown_path=result_path,
                report={},
                report_path=result_path,
            ),
        )

    worker_mod.run_ask = fake_ask

    # Bound once, at process start, for this process's whole life.
    snapshot.bind()

    store = JobStore(dsn)
    worker = Worker(
        store,
        run_job=lambda job: run_ask_job(
            job, client=None, store=store, snapshot=snapshot, work_dir=work_dir
        ),
        heartbeat_interval=0.2,
    )
    worker.run_once()


if __name__ == "__main__":
    main()
