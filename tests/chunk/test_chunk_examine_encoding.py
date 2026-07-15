"""Regression test (fix-lane, `/fix`): `axial chunk examine` must not crash
with `UnicodeEncodeError` when stdout uses a narrow codec (e.g. Windows'
default `cp1252`) and a chunk's text sample contains a non-cp1252 glyph.

Bug
-----------------------------------------------------------------------
`src/axial/cli.py`'s `_chunk_examine` does `print(format_examine_report(
stats))`. `print` encodes through `sys.stdout`'s own codec. On a console
whose stdout defaults to `cp1252` (the normal case on Windows), any
non-Latin glyph in the report -- most commonly a transliteration mark such
as `ʿ` (U+02BF, ubiquitous in transliterated Arabic in our real sources)
appearing in the chunk-text sample section of the report -- raises
`UnicodeEncodeError` and kills the whole command. On a UTF-8 stdout (the
dev machine, and the existing test suite, which invokes `axial chunk
examine` only under a UTF-8-locale subprocess) this path is never
exercised, so the suite stayed green over a real defect.

Correct behavior pinned here
-----------------------------------------------------------------------
`axial chunk examine` must render and emit its report regardless of the
console/stdout encoding -- a non-Latin glyph in the chunk-text sample must
NOT crash the command. The report's content and wording are unchanged;
only its *emission* must become encoding-safe.

Reproduction seam -- OS-independent, does not depend on actually running
on Windows
-----------------------------------------------------------------------
`PYTHONIOENCODING` overrides the encoding Python picks for `sys.stdout`
regardless of host platform or locale (verified: `PYTHONIOENCODING=cp1252
python -c "print('ʿ')"` raises `UnicodeEncodeError` on this very (non-
Windows-console) dev shell). Setting it for the `axial chunk examine`
subprocess deterministically reproduces the real Windows crash condition
without depending on the CI/dev host's own console codec, mirroring
`tests/chunk/test_chunk_examine.py`'s own subprocess + isolated-cwd seam
(reusing its `_build_isolated_root`/`_run_examine`-style pattern) so
`data/chunks/` resolves to a fixture directory, never the real repo's.

This file is intentionally separate from `tests/chunk/test_chunk_examine.
py`'s own locked outer acceptance test (that file's own docstring marks it
"do not edit once committed red" -- DEC-1); this is a new, small regression
test for a bug found after that contract, not an edit to it.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# The exact glyph the real bug report names: U+02BF MODIFIER LETTER LEFT
# HALF RING, common in transliterated Arabic ("ʿ" as in "Ba'ath" ->
# "Ba'ath" romanized with an ayn mark) -- not representable in cp1252.
NON_CP1252_GLYPH = "ʿ"
MARKER = f"MARKER-ENCODING-9d4a-{NON_CP1252_GLYPH}-glyph"


def _place_chunks_fixture(root: Path) -> Path:
    """Pre-place a minimal, single-chunk fixture directly under
    `<root>/data/chunks/source-encoding.jsonl` -- bypassing a real chunk
    run entirely (this test only needs the on-disk artifact shape `examine`
    reads, mirroring `tests/chunk/test_chunk_examine.py`'s own seam
    decision 2). The chunk's `text` embeds the non-cp1252 glyph so it lands
    in `format_examine_report`'s chunk-text sample section."""
    chunks_dir = root / "data" / "chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "chunk_id": "source-encoding_1_intro_001",
        "section": "Introduction",
        "section_order": "1",
        "text": (
            f"{MARKER} some ordinary prose surrounding a transliteration "
            f"mark ({NON_CP1252_GLYPH}) that cp1252 cannot encode."
        ),
    }
    path = chunks_dir / "source-encoding.jsonl"
    with path.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")
    return path


def _run_examine_with_narrow_stdout_codec(root: Path) -> subprocess.CompletedProcess:
    """Run `axial chunk examine` in a fresh, isolated cwd (so `data/
    chunks/` resolves to the fixture placed under `root`, never the real
    repo's) with `PYTHONIOENCODING=cp1252` forcing the child's `sys.stdout`
    to the narrow codec that crashes today -- deterministically, regardless
    of the actual host OS or its own console codec."""
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "cp1252"
    return subprocess.run(
        ["uv", "run", "--project", str(REPO_ROOT), "axial", "chunk", "examine"],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )


def test_chunk_examine_does_not_crash_on_narrow_stdout_codec(tmp_path):
    _place_chunks_fixture(tmp_path)

    result = _run_examine_with_narrow_stdout_codec(tmp_path)

    assert "UnicodeEncodeError" not in result.stderr, (
        f"`axial chunk examine` must not crash with UnicodeEncodeError when "
        f"stdout uses a narrow codec (cp1252) and a chunk's text sample "
        f"contains a non-cp1252 glyph ({NON_CP1252_GLYPH!r}, U+02BF) -- "
        f"src/axial/cli.py's `_chunk_examine` must emit its report in an "
        f"encoding-safe way regardless of stdout's codec.\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    assert result.returncode == 0, (
        f"expected exit code 0 for `axial chunk examine` over a fixture "
        f"containing a non-cp1252 glyph, even when stdout's codec is "
        f"cp1252 -- got {result.returncode}.\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    # The report's content/wording is unchanged by the fix -- only its
    # emission becomes encoding-safe -- so the fixture's own chunk count
    # and source id must still be present in the emitted report.
    assert "source-encoding" in result.stdout, (
        f"expected the report to still name the fixture source "
        f"'source-encoding' after an encoding-safe fix, got stdout: "
        f"{result.stdout!r}\nstderr: {result.stderr!r}"
    )
