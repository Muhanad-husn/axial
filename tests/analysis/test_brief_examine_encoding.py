"""Regression test for issue #489: `axial brief examine` must not crash with
`UnicodeEncodeError` when stdout uses a narrow codec (Windows' default
`cp1252`) and a note's own `claim` answer contains a non-cp1252 glyph.

Bug
-----------------------------------------------------------------------
Found by running `uv run axial brief examine config/briefs/sim/P3-01.yaml`
against the live corpus. The command completed all 20 retrieval turns, paid
for every model call, and then died emitting its own report:

    UnicodeEncodeError: 'charmap' codec can't encode character '\\u02bf'

`src/axial/cli.py`'s `_brief_examine` used a plain `print(...)`, which encodes
through `sys.stdout`'s own codec. This slice is what put corpus prose on that
path: the report used to list chunk_ids and per-polity counts, and now lists
each note's own one-sentence `claim`, so a transliterated Arabic ayn (`ʿ`,
U+02BF, ubiquitous in these sources) in a real note kills the command. Exit 1,
no report, after the whole retrieval budget was spent.

Correct behavior pinned here
-----------------------------------------------------------------------
`brief examine` renders and emits its report regardless of stdout's codec. The
report's content and wording are unchanged; only its *emission* is
encoding-safe (`_print_encoding_safe`, the same remedy `chunk examine` (#153)
and `names examine` already use).

Reproduction seam -- OS-independent, and no model call
-----------------------------------------------------------------------
`PYTHONIOENCODING` overrides the codec Python picks for `sys.stdout` on any
host, so `PYTHONIOENCODING=cp1252` reproduces the real Windows crash
deterministically -- the same seam
`tests/chunk/test_chunk_examine_encoding.py` and
`tests/test_run_unicode_encoding.py` use. Retrieval and interrogation are
scripted through `AXIAL_LLM_PROVIDER=stub` plus
`AXIAL_STUB_INTERROGATE_RESPONSE`/`AXIAL_STUB_TOOL_CALLS`, exactly as
`tests/analysis/test_brief_examine.py` scenario 1 does, so this test makes no
real model call. The glyph is placed in the fixture note's `claim` answer,
which is the field the new report renders.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURE_BRIEF_PATH = REPO_ROOT / "config" / "briefs" / "dev" / "fixture-syria-displacement.yaml"

PROVIDER_ENV_VAR = "AXIAL_LLM_PROVIDER"
STUB_INTERROGATE_RESPONSE_ENV_VAR = "AXIAL_STUB_INTERROGATE_RESPONSE"
STUB_TOOL_CALLS_ENV_VAR = "AXIAL_STUB_TOOL_CALLS"

# The exact glyph the live run died on: U+02BF MODIFIER LETTER LEFT HALF RING,
# the transliterated Arabic ayn -- not representable in cp1252.
AYN = "ʿ"
CHUNK_ID = "encfix_001_baath"
CLAIM = f"The Ba{AYN}ath party displaced the notables who collected the tax."
# A name carrying a non-cp1252 letter too (U+011F, in `Uğur Ümit Üngör`, a
# real canonical in the live index), because the report's per-name count block
# prints surface forms as the corpus said them.
NAME_SURFACE = "Uğur Ümit Üngör"


def _note_frontmatter() -> dict[str, Any]:
    return {
        "chunk_id": CHUNK_ID,
        "section": "Introduction",
        "chunk_text": f"Prose about the Ba{AYN}ath party and the notables.",
        "source_meta": {
            "author": "A. Synthetic Author",
            "title": "A Synthetic Fixture Source",
            "date": 2021,
            "thesis": "Synthetic thesis.",
            "scope": "Synthetic scope.",
        },
        "frame_version": "0.1",
        "answers": {
            "claim": CLAIM,
            "move": "stating a mechanism",
            "names": [{"name": NAME_SURFACE, "kind": "person"}],
        },
    }


@pytest.fixture
def fixture_root(tmp_path: Path) -> Path:
    prose_dir = tmp_path / "data" / "vault" / "prose"
    prose_dir.mkdir(parents=True, exist_ok=True)
    frontmatter = _note_frontmatter()
    text = (
        "---\n" + yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True) + "---\nBody.\n"
    )
    (prose_dir / f"{CHUNK_ID}.md").write_text(text, encoding="utf-8")
    return tmp_path


def _run_examine_with_narrow_stdout_codec(root: Path) -> subprocess.CompletedProcess:
    """`axial brief examine` in an isolated cwd (so `data/vault/` resolves to
    the fixture, never the real repo's), with the child's `sys.stdout` forced
    to the narrow codec that crashes today and both model calls scripted."""
    env = dict(os.environ)
    env[PROVIDER_ENV_VAR] = "stub"
    env[STUB_INTERROGATE_RESPONSE_ENV_VAR] = json.dumps(
        {"premises_found": [], "bounds_applied": [], "refusal": None}
    )
    env[STUB_TOOL_CALLS_ENV_VAR] = json.dumps(
        [{"tool": "get_chunk", "args": {"chunk_id": CHUNK_ID}}, None]
    )
    env["PYTHONIOENCODING"] = "cp1252"
    return subprocess.run(
        [
            "uv",
            "run",
            "--project",
            str(REPO_ROOT),
            "axial",
            "brief",
            "examine",
            str(FIXTURE_BRIEF_PATH),
        ],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )


def test_brief_examine_does_not_crash_on_narrow_stdout_codec(fixture_root: Path):
    result = _run_examine_with_narrow_stdout_codec(fixture_root)

    assert "UnicodeEncodeError" not in result.stderr, (
        "`axial brief examine` must not crash with UnicodeEncodeError when "
        f"stdout uses a narrow codec (cp1252) and a note's own `claim` answer "
        f"carries a non-cp1252 glyph ({AYN!r}, U+02BF) -- the report must be "
        "emitted encoding-safely, and the retrieval budget is already spent by "
        f"the time it is written.\nstdout: {result.stdout!r}\n"
        f"stderr: {result.stderr!r}"
    )
    assert result.returncode == 0, (
        f"expected exit 0, got {result.returncode}\nstdout: {result.stdout!r}\n"
        f"stderr: {result.stderr!r}"
    )
    # The report's content is unchanged by the fix -- only its emission -- so
    # the retrieved id, the note's claim and its name count are all still
    # there. `errors="replace"` above means the glyph itself may arrive as a
    # replacement character under the fallback path; the surrounding words
    # must survive either way.
    assert CHUNK_ID in result.stdout, result.stdout
    assert "party displaced the notables" in result.stdout, result.stdout
    assert "names in the assembled evidence" in result.stdout, result.stdout
