"""Regression test for issue #424: `axial run <pass>` must actually persist
what the pass produces, not just report a clean summary.

`_invoke_artifacts` (src/axial/run.py) called `run_artifacts(...)` without an
`artifacts_dir`, which defaults to `None` -- and `None` disables
`run_artifacts`'s own opt-in checkpoint entirely (its docstring: "OPT-IN,
active only when `artifacts_dir` is supplied"). The runner therefore made
every LLM call, reported `total=N ok=N`, appended an OK row to its own resume
ledger, and wrote zero files. Because `_ledger_done_predicate` treats an OK
ledger row as "already done", a resumed run then silently skips a source
whose output was never written -- the ledger says done, the disk says
nothing.

The same defect existed in `_invoke_xref` (retired along with the xref pass
itself, issue #414, `plans/phase-a-v1/README.md` D5).

This test's whole point is the disk assertion, not the return value: a test
that only checks `run_pass`'s summary/exit-code is exactly the blind spot
that let #424 through (a source can report OK with zero output). Every
assertion here is "does the checkpoint FILE exist and carry the expected
records", never just "did the process exit 0."

Fixture: tests/fixtures/artifacts/multi_artifact.pdf + its committed
multi_artifact_tree.json (already used by tests/ingestion/test_artifacts_resume.py) --
a real, docling-produced tree carrying four artifact nodes, pre-placed at
data/trees/<source_id>.json so no docling call is needed.

Test hygiene: every path this test writes lives under `isolated_vault_root`
(tests/conftest.py, issue #68) -- a fresh tmp_path-backed staging root
outside this repo entirely. No real data/ directory is ever read or written.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from axial.envelope import compute_source_id

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_ARTIFACTS = REPO_ROOT / "tests" / "fixtures" / "artifacts"

MULTI_ARTIFACT_PDF = FIXTURES_ARTIFACTS / "multi_artifact.pdf"
MULTI_ARTIFACT_TREE = FIXTURES_ARTIFACTS / "multi_artifact_tree.json"

PROVIDER_ENV_VAR = "AXIAL_LLM_PROVIDER"

ARGPARSE_FALLBACK_MARKERS = (
    "invalid choice",
    "unrecognized arguments",
)


def _run_axial(args: list[str], provider: str, *, cwd: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env[PROVIDER_ENV_VAR] = provider
    return subprocess.run(
        ["uv", "run", "--project", str(REPO_ROOT), "axial", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        env=env,
    )


def _assert_not_argparse_fallback(result: subprocess.CompletedProcess, command: str) -> None:
    combined = result.stdout + result.stderr
    for marker in ARGPARSE_FALLBACK_MARKERS:
        assert marker not in combined, (
            f"expected a real `{command}` behavior path, not an argparse "
            f"fallback (found {marker!r}) -- this means the `{command}` "
            f"subcommand does not exist yet or was never reached:\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )


def _place_tree_fixture(source_path: Path, root: Path) -> str:
    source_id = compute_source_id(source_path)
    tree_path = root / "data" / "trees" / f"{source_id}.json"
    tree_path.parent.mkdir(parents=True, exist_ok=True)
    tree_path.write_bytes(MULTI_ARTIFACT_TREE.read_bytes())
    return source_id


def _write_worklist(path: Path, source_paths: list[Path]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(str(p) for p in source_paths) + "\n", encoding="utf-8")


def _read_jsonl_lines(path: Path) -> list[str]:
    return [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_run_artifacts_persists_checkpoint_file_to_disk(isolated_vault_root):
    root = isolated_vault_root
    source_id = _place_tree_fixture(MULTI_ARTIFACT_PDF, root)

    worklist_path = root / "worklist.txt"
    _write_worklist(worklist_path, [MULTI_ARTIFACT_PDF])

    result = _run_axial(["run", "artifacts", "--worklist", str(worklist_path)], "stub", cwd=root)
    _assert_not_argparse_fallback(result, "run")
    assert result.returncode == 0, (
        f"expected exit 0, got {result.returncode}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    assert "total=1 ok=1" in result.stdout, (
        f"expected the run summary to report one OK source, got: {result.stdout!r}"
    )

    checkpoint_path = root / "data" / "artifacts" / f"{source_id}.jsonl"
    assert checkpoint_path.exists(), (
        f"the runner reported OK but wrote no checkpoint file at "
        f"{checkpoint_path} -- this is issue #424: `axial run artifacts` "
        f"making every LLM call and persisting nothing"
    )
    lines = _read_jsonl_lines(checkpoint_path)
    assert len(lines) >= 1, (
        f"expected at least one classified artifact record persisted to "
        f"{checkpoint_path}, got an empty file"
    )
    for line in lines:
        record = json.loads(line)
        assert isinstance(record.get("artifact_id"), str) and record["artifact_id"], (
            f"expected every checkpoint line to carry a non-empty 'artifact_id', got {record!r}"
        )
