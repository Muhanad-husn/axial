"""Outer acceptance test for issue #6, slice 01 (cli-skeleton).

Locked behavioral contract (DEC-1) — do not edit once committed red.

Given the repo with dependencies installed (uv sync)
When  the user runs `uv run axial --version`
Then  it exits 0 and prints the version declared in pyproject.toml
      (e.g. "axial 0.1.0")
"""

import subprocess
import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - repo requires-python >=3.13
    import tomli as tomllib

REPO_ROOT = Path(__file__).resolve().parent.parent


def _declared_version() -> str:
    pyproject_path = REPO_ROOT / "pyproject.toml"
    with pyproject_path.open("rb") as f:
        data = tomllib.load(f)
    return data["project"]["version"]


def test_cli_version_prints_declared_version_and_exits_zero():
    version = _declared_version()

    result = subprocess.run(
        ["uv", "run", "axial", "--version"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, (
        f"expected exit code 0, got {result.returncode}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    assert version in result.stdout, (
        f"expected declared version {version!r} in stdout, got {result.stdout!r}"
    )
