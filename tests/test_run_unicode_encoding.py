"""Regression test (fix-lane, `/fix`): `axial run <pass>` must not crash with
`UnicodeEncodeError` when stdout uses a narrow codec (e.g. Windows' default
`cp1252`) and a worklist source path contains a character outside it.

Bug
-----------------------------------------------------------------------
`src/axial/run.py`'s `run_pass` loop prints every outcome row (and several
diagnostic lines) with a plain `print(...)`, which encodes through `sys.
stdout`'s own codec. On Windows, when `axial run <pass>` is driven as a
subprocess with its stdout piped (exactly how the real pipeline drives every
pass, `uv run axial run <pass> ...`), Python picks the OS's legacy codepage
(`cp1252` on the reporting machine) for `sys.stdout` instead of UTF-8. A
source path containing a diacritic outside cp1252 -- confirmed live during a
real 31-source ingestion run, e.g. "Siniša Malešević" (the "š" can appear as
the decomposed sequence "s" + U+030C COMBINING CARON) -- then raises
`UnicodeEncodeError` and crashes the *entire* `run_pass` invocation, not just
the one source: every registered pass (extract, chunk, envelope, tag,
artifacts, xref, vault-write) shares this same printing path.

Correct behavior pinned here
-----------------------------------------------------------------------
`axial run <pass>` must render and emit its outcome table regardless of the
stdout codec -- a non-cp1252 character in a source path must NOT crash the
run. Table content/wording is unchanged; only its *emission* becomes
encoding-safe (mirrors `src/axial/cli.py`'s own `_print_encoding_safe`, and
this repo's own prior fix for the identical class of bug in `axial chunk
examine`, `tests/chunk/test_chunk_examine_encoding.py`).

Reproduction seam -- OS-independent, does not depend on actually running on
Windows
-----------------------------------------------------------------------
`PYTHONIOENCODING` overrides the encoding Python picks for `sys.stdout`
regardless of host platform or locale, deterministically reproducing the
real Windows crash condition (mirrors `test_chunk_examine_encoding.py`'s own
seam).

Fault path chosen: a worklist naming one source path that does not exist.
`compute_source_id` then raises `MissingSourceError` (`axial.envelope`)
*before* any docling/LLM call -- fully deterministic, no fixture needed --
and the caught exception's message, plus the FAIL outcome row, both embed
the source path verbatim, exercising exactly the print calls that crashed
in the real incident.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# The exact case from the real incident: "š" as the decomposed sequence
# LATIN SMALL LETTER S + U+030C COMBINING CARON -- not representable in
# cp1252 in either its decomposed or precomposed form.
NON_CP1252_SEQUENCE = "š"
MISSING_SOURCE_NAME = f"Sini{NON_CP1252_SEQUENCE}a-Malesevic-source.pdf"


def _run_with_narrow_stdout_codec(worklist_path: Path, cwd: Path) -> subprocess.CompletedProcess:
    """Run `axial run extract --worklist <worklist_path>` with
    `PYTHONIOENCODING=cp1252` forcing the child's `sys.stdout` to the narrow
    codec that crashes today -- deterministically, regardless of the actual
    host OS or its own console codec."""
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "cp1252"
    env["AXIAL_LLM_PROVIDER"] = "stub"
    return subprocess.run(
        [
            "uv",
            "run",
            "--project",
            str(REPO_ROOT),
            "axial",
            "run",
            "extract",
            "--worklist",
            str(worklist_path),
        ],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )


def test_run_pass_does_not_crash_on_narrow_stdout_codec(isolated_vault_root):
    root = isolated_vault_root
    missing_source = root / "sources" / MISSING_SOURCE_NAME
    worklist_path = root / "worklist.txt"
    worklist_path.write_text(str(missing_source) + "\n", encoding="utf-8")

    result = _run_with_narrow_stdout_codec(worklist_path, root)

    assert "UnicodeEncodeError" not in result.stderr, (
        f"`axial run extract` must not crash with UnicodeEncodeError when "
        f"stdout uses a narrow codec (cp1252) and a worklist source path "
        f"contains a non-cp1252 character ({NON_CP1252_SEQUENCE!r}) -- "
        f"src/axial/run.py's `run_pass` must emit its outcome table in an "
        f"encoding-safe way regardless of stdout's codec.\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    assert result.returncode == 0, (
        f"a missing source is a per-source failure (isolated, loop "
        f"continues), so the run should still exit 0 even when the failing "
        f"source's own path is not cp1252-representable -- got "
        f"{result.returncode}.\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    # Content/wording is unchanged by the fix -- only emission becomes
    # encoding-safe -- so the FAIL row must still name the actual source
    # path, diacritic included, not garbled or silently dropped.
    assert str(missing_source) in result.stdout, (
        f"expected the outcome table to still carry the missing source's "
        f"own path (with its diacritic intact) after an encoding-safe fix, "
        f"got stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    assert "FAIL" in result.stdout, (
        f"expected a FAIL row for the missing source, got stdout: {result.stdout!r}"
    )
