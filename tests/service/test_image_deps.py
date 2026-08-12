"""Issue #772: the shipping service image carries the ask path and nothing
else. This pins the `pyproject.toml`/`uv.lock` config a docker build reads,
not runtime behavior -- no `docker build` here (one budgeted build, run by
the orchestrator); `uv export` against the worktree's own lockfile is the
cheap, deterministic stand-in.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = REPO_ROOT / "Dockerfile"


def _export(*args: str) -> str:
    result = subprocess.run(
        ["uv", "export", "--frozen", "--offline", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def test_service_resolution_carries_only_the_ask_path() -> None:
    """`--no-default-groups --group service` is what the Dockerfile now
    asks `uv sync` for -- no GPU runtime, no ingest stack, no dev/operator
    tooling, and the two ask-path reads (#691's own trap) still present."""
    export = _export("--no-default-groups", "--group", "service")

    assert "nvidia-" not in export
    for excluded in ("docling", "unstructured", "google-api-python-client", "google-auth"):
        assert excluded not in export, f"{excluded} should not be in the service resolution"
    for dev_only in ("streamlit==", "pytest==", "ruff=="):
        assert dev_only not in export, f"{dev_only} should not be in the service resolution"

    assert "sentence-transformers==" in export
    assert "lancedb==" in export

    # CPU-only torch on Linux: PyPI's plain version string is the
    # CUDA-bundled default, `+cpu` is the local version identifier the
    # PyTorch CPU index publishes under.
    linux_torch_lines = [
        line
        for line in export.splitlines()
        if line.startswith("torch==") and "sys_platform == 'linux'" in line
    ]
    assert linux_torch_lines, "expected a Linux-marked torch line in the export"
    assert all("+cpu" in line for line in linux_torch_lines)


def test_bare_export_is_unchanged_for_the_ingest_stack() -> None:
    """A bare `uv sync`/CI's own `uv sync --group distill ...` calls carry
    no `--group ingest` -- `ingest` has to be a `default-groups` member so
    both still install docling exactly as they did before this split."""
    export = _export()
    assert "docling==" in export


def test_dockerfile_prefetches_before_the_full_src_copy_and_pins_offline_env() -> None:
    """The encoder pre-fetch's cache key is `src/axial/names.py` alone, so
    an edit anywhere else under `src/` no longer re-downloads the model --
    and the image never reaches the network mid-ask (issue #772's added
    scope): `HF_HUB_OFFLINE`/`TRANSFORMERS_OFFLINE` are set, but only AFTER
    the pre-fetch, which itself needs the network."""
    text = DOCKERFILE.read_text(encoding="utf-8")

    def _line_start(pattern: str) -> int:
        # Anchored to the start of an actual instruction line, not prose in
        # a `#` comment that happens to quote the same instruction.
        match = re.search(pattern, text, re.M)
        assert match, f"no Dockerfile line matches {pattern!r}"
        return match.start()

    narrow_copy = _line_start(r"^COPY src/axial/names\.py")
    prefetch_run = text.index("SentenceTransformer(model_name)")
    full_copy = _line_start(r"^COPY src \./src$")
    offline_env = _line_start(r"^ENV HF_HUB_OFFLINE=1$")

    assert narrow_copy < prefetch_run < full_copy
    assert prefetch_run < offline_env < full_copy
    assert "TRANSFORMERS_OFFLINE=1" in text
    assert re.search(r"^ENV HF_HOME=", text, re.M)
