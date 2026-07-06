"""Inner unit tests for the axial CLI skeleton (issue #6, slice 01)."""

import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - repo requires-python >=3.13
    import tomli as tomllib

import axial

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _declared_version() -> str:
    pyproject_path = REPO_ROOT / "pyproject.toml"
    with pyproject_path.open("rb") as f:
        data = tomllib.load(f)
    return data["project"]["version"]


def test_version_matches_pyproject():
    assert axial.__version__ == _declared_version()


def test_build_parser_recognises_version_flag():
    from axial.cli import build_parser

    parser = build_parser()
    args = parser.parse_args(["--version"])
    assert args.version is True


def test_main_returns_zero_for_version(capsys):
    from axial.cli import main

    exit_code = main(["--version"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert f"axial {axial.__version__}" in captured.out
