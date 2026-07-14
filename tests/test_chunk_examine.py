"""Outer acceptance test for issue #153, slice 03 of the chunk-redesign
subproject (charter #148): `axial chunk examine`.

Locked behavioral contract (DEC-1) -- do not edit once committed red.

Given a fixture data/chunks/ (in an isolated tmp cwd) with KNOWN chunk counts
      (total + per-source, across MULTIPLE source .jsonl files), a KNOWN size
      distribution (min/max/mean/median over `text` lengths computed exactly
      off the fixture), one section split into multiple chunks (multiple
      records sharing the same section_order in one source), and one
      recorded garbage-skip (via a companion sidecar, see below)
When  the user runs `axial chunk examine`
Then  it exits 0 and reports total + per-source chunk counts, the size
      distribution (min/max/mean/median), and boundary sanity (count of
      chunks above `max`, count below `min`, count of sections split into
      multiple chunks, and sections skipped-as-garbage with reasons), plus a
      chunk-text sample
And   the reported numbers match the fixture exactly and NO chunk above
      `max` is reported
And   the command makes zero LLM calls and zero embedding-model calls, and
      never mutates any file under data/chunks/

See specs/PRODUCT.md §7.7 ("Inspection (examine)") and §8 P0-4b for the
source of truth, and plans/chunk-redesign/03-chunk-examine.md for the slice
plan this test encodes.

Seam decision 1 -- the garbage-skip sidecar (founder-approved Option A)
-----------------------------------------------------------------------
Slice 01 (`axial.chunk.run_chunk_embedding`) does NOT persist skip reasons
today -- it only prints them to stderr during the chunk run itself, which
`examine` (a separate, later, read-only invocation) can never see. The
founder approved persisting them via a companion sidecar the implementer
produces: one JSON object per line at `data/chunks/<source_id>.skips.jsonl`,
alongside `data/chunks/<source_id>.jsonl`, each line carrying exactly
`{"section": <verbatim heading>, "section_order": <str>, "reason": <human-
readable reason string>}`. This test authors exactly one such sidecar line
(mirroring `axial.chunk._garbage_section_skip_reason`'s own real wording,
`"high non-alpha ratio (73.4%)"`, so the fixture reads as a realistic
garbage-skip, though `examine` itself does not re-derive or validate the
reason string -- it only surfaces whatever the sidecar carries) and asserts
`examine` reports that section as skipped-as-garbage WITH its reason.

Seam decision 2 -- the chunks-dir isolation seam: an isolated cwd, no
`--chunks-dir` flag
-----------------------------------------------------------------------
`axial.chunk._default_chunks_dir` resolves `data/chunks/` as a plain,
cwd-relative path, honoring `config/pipeline.yaml`'s `paths.chunks_dir` when
declared, else falling back to `CHUNKS_DIR` (`data/chunks`) -- there is no
env-var or CLI-flag override (verified by reading src/axial/chunk.py and
src/axial/cli.py). The one seam available from tests/ alone (mirroring
tests/conftest.py's own `isolated_vault_root`, and tests/test_chunk_
resilience.py's identical reasoning) is to run the CLI subprocess from a
fresh, isolated tmp directory as `cwd`, with no `config/pipeline.yaml` under
it -- `data/chunks/` then resolves to `<isolated_root>/data/chunks/`, never
aliasing the real repo's `data/chunks/`. This test pre-places the fixture
JSONL/sidecar files directly under that isolated `data/chunks/`, bypassing
`run_chunk_embedding` entirely (it does not need a real chunk run -- only
the on-disk artifact shape `examine` reads).

Seam decision 3 -- proving zero LLM / zero embedding-model calls
-----------------------------------------------------------------------
Two complementary, independent proofs, since no poison ("explode"-style)
embedder seam exists in the repo yet (only the LLM client has one,
`AXIAL_LLM_PROVIDER=explode` / `axial.llm.ExplodingLLMClient`):

  1. The main subprocess test below runs with `AXIAL_LLM_PROVIDER=explode`
     (mirroring tests/test_chunk.py's seam decision 2 exactly): if `examine`
     ever called a text-generating LLM for any reason, the process would
     crash and the exit-code-0 assertion would fail. No `AXIAL_EMBEDDER` is
     set either, so the plain default embedder path (whatever it resolves
     to) is exercised too -- `examine` must succeed regardless.
  2. `test_chunk_examine_constructs_no_embedder_or_llm_client` below invokes
     `axial.cli.main(["chunk", "examine"])` IN-PROCESS (not a subprocess) and
     monkeypatches `axial.chunk.get_embedder`, `axial.chunk.get_client`, and
     `axial.chunk.HashingEmbedder.encode` to raise `AssertionError` the
     instant any of them is called. This is a direct, unambiguous proof at
     the construction/use seam itself, not an inference from the absence of
     a log line or network call -- it fails loudly if `examine` ever
     constructs or uses an embedder or an LLM client, regardless of whether
     that would otherwise succeed offline.

Seam decision 4 -- the fixture's exact, hand-computed size distribution
-----------------------------------------------------------------------
Six chunk records across two source files, with character lengths chosen so
every headline statistic (min/max/mean/median) is an unambiguous integer,
computed by hand and cross-checked in a module-level comment below. The
sizes are chosen relative to `axial.chunk.CHUNK_MIN`/`CHUNK_MAX` (imported,
never hardcoded band values -- mirroring tests/test_chunk.py's seam decision
3) with an explicit guard block asserting the fixture's own assumptions
(exactly one chunk below `CHUNK_MIN`, none above `CHUNK_MAX`) hold against
whatever the CURRENT band constants are, so a future retuning of
`CHUNK_MIN`/`CHUNK_MAX` fails this test LOUDLY with a clear "fixture
assumption broke" message rather than silently asserting the wrong numbers.

Seam decision 5 -- loose, format-agnostic report assertions
-----------------------------------------------------------------------
Neither the PRD (§7.7) nor the slice plan dictates `examine`'s exact output
layout/wording -- only that the listed numbers are reported and match the
fixture. Mirroring tests/test_chunk.py's own restraint on stderr wording
("only the heading + a skip-indicating word are locked ... exact wording is
left to the implementer"), every assertion here uses `_number_flanked_by`: a
computed integer must appear as a bare token within a small window of the
relevant keyword(s) (e.g. `900` near `"min"`, `0` near `"above"` and
`"max"` together) -- loose about formatting, but still requires the actual
correct value to appear in the actually-relevant context, not merely
floating anywhere in the output.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest

from axial.chunk import CHUNK_MAX, CHUNK_MIN

REPO_ROOT = Path(__file__).resolve().parent.parent

PROVIDER_ENV_VAR = "AXIAL_LLM_PROVIDER"

_DOMAIN_DIR_PARTS = ("config", "domains", "syria")
_DOMAIN_FILES = ("schema.yaml", "codebook.yaml")

# -----------------------------------------------------------------------
# Fixture text-length design (seam decision 4). Six records, two sources:
#
#   source-alpha.jsonl:
#     "Introduction" (section_order "1"):        1 record,  1200 chars
#     "Findings"     (section_order "2"):         3 records: 1050, 1600, 900
#                                                 (900 is the SECTION'S OWN
#                                                 LAST chunk -- the documented
#                                                 below-CHUNK_MIN tail
#                                                 exception, §7.7/§8 P0-4)
#     -> "Findings" is the one section split into multiple chunks.
#     source-alpha.skips.jsonl: one skipped-as-garbage section,
#       "Appendix Tables" (section_order "3"), reason "high non-alpha ratio
#       (73.4%)".
#
#   source-beta.jsonl:
#     "Overview"          (section_order "1"): 1 record, 2000 chars
#     "Historical Notes"  (section_order "2"): 1 record, 2850 chars
#
# Totals: 6 chunks (source-alpha=4, source-beta=2).
# sizes = [1200, 1050, 1600, 900, 2000, 2850]
#   min    = 900
#   max    = 2850
#   mean   = 9600 / 6 = 1600.0
#   median = sorted [900, 1050, 1200, 1600, 2000, 2850] -> avg(1200, 1600)
#          = 1400.0
# Boundary sanity: above CHUNK_MAX = 0, below CHUNK_MIN = 1 (the 900-char
# "Findings" tail), sections split = 1 ("Findings"), sections skipped as
# garbage = 1 ("Appendix Tables", with its reason).
# -----------------------------------------------------------------------

SIZE_INTRO = 1200
SIZE_FIND_1 = 1050
SIZE_FIND_2 = 1600
SIZE_FIND_3 = 900  # legitimate below-CHUNK_MIN section-tail exception
SIZE_OVERVIEW = 2000
SIZE_HIST = 2850

ALL_SIZES = [SIZE_INTRO, SIZE_FIND_1, SIZE_FIND_2, SIZE_FIND_3, SIZE_OVERVIEW, SIZE_HIST]

EXPECTED_TOTAL = 6
EXPECTED_ALPHA_COUNT = 4
EXPECTED_BETA_COUNT = 2
EXPECTED_MIN = 900
EXPECTED_MAX = 2850
EXPECTED_MEAN = 1600
EXPECTED_MEDIAN = 1400
EXPECTED_ABOVE_MAX = 0
EXPECTED_BELOW_MIN = 1
EXPECTED_SPLIT_SECTIONS = 1
EXPECTED_SKIPPED_SECTIONS = 1

GARBAGE_SECTION_HEADING = "Appendix Tables"
GARBAGE_SECTION_ORDER = "3"
GARBAGE_REASON = "high non-alpha ratio (73.4%)"

# A handful of ordinary, low-non-alpha filler prose, cycled to pad each
# fixture chunk's text out to its exact target length (seam decision 4).
_FILLER = (
    "The provincial council convened to review reconstruction plans and "
    "coordinate humanitarian access across contested districts. "
)

# One distinct marker prefixed onto each fixture chunk's own text, so this
# test can assert a genuine chunk-TEXT sample (not merely a count) is
# present in the report without dictating WHICH chunk(s) the implementer's
# sampling logic happens to choose to show.
MARK_INTRO = "MARKER-INTRO-7f3a"
MARK_FIND_1 = "MARKER-FIND1-9c2d"
MARK_FIND_2 = "MARKER-FIND2-4b1e"
MARK_FIND_3 = "MARKER-FIND3-2e8f"
MARK_OVERVIEW = "MARKER-OVERVIEW-6a5c"
MARK_HIST = "MARKER-HIST-3d9b"
ALL_MARKERS = (MARK_INTRO, MARK_FIND_1, MARK_FIND_2, MARK_FIND_3, MARK_OVERVIEW, MARK_HIST)


def _chunk_text(marker: str, length: int) -> str:
    """Build ordinary prose of EXACTLY `length` characters, prefixed with
    `marker` (see module docstring's marker note). Fails loudly if `length`
    is too short to hold the marker plus its trailing space."""
    prefix = f"{marker} "
    filler_needed = length - len(prefix)
    assert filler_needed > 0, f"fixture assumption: length {length} too short for marker {marker!r}"
    body = (_FILLER * (filler_needed // len(_FILLER) + 2))[:filler_needed]
    text = prefix + body
    assert len(text) == length, f"internal fixture bug: built {len(text)} chars, wanted {length}"
    return text


def _record(chunk_id: str, section: str, section_order: str, text: str) -> dict:
    return {
        "chunk_id": chunk_id,
        "section": section,
        "section_order": section_order,
        "text": text,
    }


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")


def _place_chunks_fixture(root: Path) -> dict[str, Path]:
    """Pre-place the fixture JSONL artifact + skips sidecar directly under
    `<root>/data/chunks/` -- bypassing `run_chunk_embedding` entirely, since
    this test only needs the on-disk artifact shape `examine` reads, not a
    real chunk run (see module docstring, seam decision 2)."""
    chunks_dir = root / "data" / "chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)

    alpha_path = chunks_dir / "source-alpha.jsonl"
    _write_jsonl(
        alpha_path,
        [
            _record(
                "source-alpha_1_introduction_001",
                "Introduction",
                "1",
                _chunk_text(MARK_INTRO, SIZE_INTRO),
            ),
            _record(
                "source-alpha_2_findings_001",
                "Findings",
                "2",
                _chunk_text(MARK_FIND_1, SIZE_FIND_1),
            ),
            _record(
                "source-alpha_2_findings_002",
                "Findings",
                "2",
                _chunk_text(MARK_FIND_2, SIZE_FIND_2),
            ),
            _record(
                "source-alpha_2_findings_003",
                "Findings",
                "2",
                _chunk_text(MARK_FIND_3, SIZE_FIND_3),
            ),
        ],
    )

    alpha_skips_path = chunks_dir / "source-alpha.skips.jsonl"
    with alpha_skips_path.open("w", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "section": GARBAGE_SECTION_HEADING,
                    "section_order": GARBAGE_SECTION_ORDER,
                    "reason": GARBAGE_REASON,
                }
            )
            + "\n"
        )

    beta_path = chunks_dir / "source-beta.jsonl"
    _write_jsonl(
        beta_path,
        [
            _record(
                "source-beta_1_overview_001",
                "Overview",
                "1",
                _chunk_text(MARK_OVERVIEW, SIZE_OVERVIEW),
            ),
            _record(
                "source-beta_2_historical-notes_001",
                "Historical Notes",
                "2",
                _chunk_text(MARK_HIST, SIZE_HIST),
            ),
        ],
    )

    return {
        "chunks_dir": chunks_dir,
        "alpha_path": alpha_path,
        "alpha_skips_path": alpha_skips_path,
        "beta_path": beta_path,
    }


def _build_isolated_root(base_dir: Path) -> Path:
    """A fresh, isolated cwd for the CLI subprocess: only the domain schema
    files are copied in (needed by other passes, harmless here), mirroring
    tests/conftest.py's `isolated_vault_root` exactly. No
    `config/pipeline.yaml` exists under it, so `axial.chunk._default_chunks_
    dir` falls back to its plain, cwd-relative default (`data/chunks`) --
    which then resolves to `<base_dir>/data/chunks`, never the real repo's."""
    domain_src = REPO_ROOT.joinpath(*_DOMAIN_DIR_PARTS)
    domain_dst = base_dir.joinpath(*_DOMAIN_DIR_PARTS)
    domain_dst.mkdir(parents=True, exist_ok=True)
    for filename in _DOMAIN_FILES:
        (domain_dst / filename).write_bytes((domain_src / filename).read_bytes())
    return base_dir


def _run_examine(root: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env[PROVIDER_ENV_VAR] = "explode"  # poison: any text-gen LLM call crashes the run
    return subprocess.run(
        ["uv", "run", "--project", str(REPO_ROOT), "axial", "chunk", "examine"],
        cwd=root,
        capture_output=True,
        text=True,
        env=env,
    )


def _snapshot_bytes(paths: list[Path]) -> dict[Path, bytes]:
    return {path: path.read_bytes() for path in paths}


def _number_flanked_by(
    haystack: str, number: int, keywords: tuple[str, ...], window: int = 100
) -> bool:
    """True if `number` (as a bare integer token) appears somewhere in
    `haystack` with EVERY one of `keywords` (case-insensitive substrings)
    present within `window` characters on either side of that occurrence.
    Deliberately loose about exact report layout/wording (see module
    docstring, seam decision 5) while still requiring the real computed
    value to appear in the actually-relevant context, not merely floating
    anywhere in the output."""
    num_pattern = re.compile(r"(?<!\d)" + re.escape(str(number)) + r"(?!\d)")
    lowered_keywords = tuple(keyword.lower() for keyword in keywords)
    for match in num_pattern.finditer(haystack):
        start = max(0, match.start() - window)
        end = min(len(haystack), match.end() + window)
        context = haystack[start:end].lower()
        if all(keyword in context for keyword in lowered_keywords):
            return True
    return False


@pytest.fixture
def examine_fixture_root(tmp_path_factory):
    root = _build_isolated_root(tmp_path_factory.mktemp("chunk_examine"))
    placed = _place_chunks_fixture(root)
    return root, placed


def test_chunk_examine_reports_fixture_stats_with_zero_mutation(examine_fixture_root):
    root, placed = examine_fixture_root
    watched_paths = [placed["alpha_path"], placed["alpha_skips_path"], placed["beta_path"]]
    before_bytes = _snapshot_bytes(watched_paths)
    before_listing = sorted(p.name for p in placed["chunks_dir"].iterdir())

    # --- fixture self-check: the band constants this run's assertions rely
    # on (imported, never hardcoded -- module docstring, seam decision 4). ---
    assert SIZE_FIND_3 < CHUNK_MIN, (
        f"fixture assumption broke: SIZE_FIND_3 ({SIZE_FIND_3}) must be below "
        f"CHUNK_MIN ({CHUNK_MIN}) for the below-min boundary case to hold"
    )
    for size in (SIZE_INTRO, SIZE_FIND_1, SIZE_FIND_2, SIZE_OVERVIEW, SIZE_HIST):
        assert size >= CHUNK_MIN, (
            f"fixture assumption broke: {size} must be >= CHUNK_MIN ({CHUNK_MIN})"
        )
    for size in ALL_SIZES:
        assert size <= CHUNK_MAX, (
            f"fixture assumption broke: {size} must be <= CHUNK_MAX ({CHUNK_MAX})"
        )

    result = _run_examine(root)
    combined = result.stdout + result.stderr

    assert result.returncode == 0, (
        f"expected exit code 0 for `axial chunk examine` over a fixture "
        f"data/chunks/ with AXIAL_LLM_PROVIDER=explode (any text-generating "
        f"LLM call would crash the run) -- a nonzero exit here most likely "
        f"means the `examine` subcommand does not exist yet (PRD §7.7/§8 "
        f"P0-4b, plans/chunk-redesign/03-chunk-examine.md), or that examine "
        f"made a text-generating LLM call it must never make.\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    # --- total + per-source counts (PRD §7.7 examine paragraph) ---
    assert _number_flanked_by(combined, EXPECTED_TOTAL, ("total",)), (
        f"expected the total chunk count ({EXPECTED_TOTAL}) to be reported "
        f"near the word 'total'.\nstdout: {result.stdout!r}\n"
        f"stderr: {result.stderr!r}"
    )
    assert _number_flanked_by(combined, EXPECTED_ALPHA_COUNT, ("source-alpha",)), (
        f"expected source-alpha's own chunk count ({EXPECTED_ALPHA_COUNT}) "
        f"to be reported near its source id 'source-alpha'.\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    assert _number_flanked_by(combined, EXPECTED_BETA_COUNT, ("source-beta",)), (
        f"expected source-beta's own chunk count ({EXPECTED_BETA_COUNT}) "
        f"to be reported near its source id 'source-beta'.\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    # --- size distribution: min/max/mean/median, computed exactly off the
    # fixture (PRD §7.7: 'from which the two-sided band is verifiable'). ---
    assert _number_flanked_by(combined, EXPECTED_MIN, ("min",)), (
        f"expected the size-distribution minimum ({EXPECTED_MIN}) to be "
        f"reported near 'min'.\nstdout: {result.stdout!r}\n"
        f"stderr: {result.stderr!r}"
    )
    assert _number_flanked_by(combined, EXPECTED_MAX, ("max",)), (
        f"expected the size-distribution maximum ({EXPECTED_MAX}) to be "
        f"reported near 'max'.\nstdout: {result.stdout!r}\n"
        f"stderr: {result.stderr!r}"
    )
    assert _number_flanked_by(combined, EXPECTED_MEAN, ("mean",)) or _number_flanked_by(
        combined, EXPECTED_MEAN, ("average",)
    ), (
        f"expected the size-distribution mean ({EXPECTED_MEAN}) to be "
        f"reported near 'mean'/'average'.\nstdout: {result.stdout!r}\n"
        f"stderr: {result.stderr!r}"
    )
    assert _number_flanked_by(combined, EXPECTED_MEDIAN, ("median",)), (
        f"expected the size-distribution median ({EXPECTED_MEDIAN}) to be "
        f"reported near 'median'.\nstdout: {result.stdout!r}\n"
        f"stderr: {result.stderr!r}"
    )

    # --- boundary sanity (PRD §7.7/§8 P0-4b) ---
    assert _number_flanked_by(combined, EXPECTED_ABOVE_MAX, ("above", "max")), (
        f"expected the count of chunks ABOVE max ({EXPECTED_ABOVE_MAX} -- "
        f"none of this fixture's chunks exceed CHUNK_MAX) to be reported "
        f"near 'above'/'max' -- this is the 'no chunk above max is "
        f"reported' contract (PRD §7.7).\nstdout: {result.stdout!r}\n"
        f"stderr: {result.stderr!r}"
    )
    assert _number_flanked_by(combined, EXPECTED_BELOW_MIN, ("below", "min")), (
        f"expected the count of chunks BELOW min ({EXPECTED_BELOW_MIN} -- "
        f"the 'Findings' section's legitimate tail chunk) to be reported "
        f"near 'below'/'min'.\nstdout: {result.stdout!r}\n"
        f"stderr: {result.stderr!r}"
    )
    assert _number_flanked_by(combined, EXPECTED_SPLIT_SECTIONS, ("split",)), (
        f"expected the count of sections split into multiple chunks "
        f"({EXPECTED_SPLIT_SECTIONS} -- 'Findings', which has 3 records "
        f"sharing section_order '2') to be reported near 'split'.\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    # --- garbage-skip reporting, from the sidecar (PRD §7.7, §8 P0-4b) ---
    assert GARBAGE_SECTION_HEADING.lower() in combined.lower(), (
        f"expected the skipped-as-garbage section's own heading "
        f"({GARBAGE_SECTION_HEADING!r}, read from source-alpha.skips.jsonl) "
        f"to appear in the report.\nstdout: {result.stdout!r}\n"
        f"stderr: {result.stderr!r}"
    )
    assert GARBAGE_REASON.lower() in combined.lower(), (
        f"expected the skipped section's own reason ({GARBAGE_REASON!r}) to "
        f"appear verbatim in the report (PRD §7.7/§8 P0-4b: 'sections "
        f"skipped as garbage with their reasons').\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    assert _number_flanked_by(combined, EXPECTED_SKIPPED_SECTIONS, ("skip",)), (
        f"expected the count of sections skipped as garbage "
        f"({EXPECTED_SKIPPED_SECTIONS}) to be reported near 'skip'.\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    # --- chunk-text sample (PRD §7.7: 'an eyeball sample of chunk texts
    # showing where boundaries fall') -- any ONE of the fixture's per-chunk
    # markers proves a genuine text sample is present, without dictating
    # which chunk(s) the implementer's sampling logic picks. ---
    assert any(marker in combined for marker in ALL_MARKERS), (
        f"expected at least one fixture chunk's own text (identified by one "
        f"of its unique markers {ALL_MARKERS!r}) to appear in the report as "
        f"an eyeball sample.\nstdout: {result.stdout!r}\n"
        f"stderr: {result.stderr!r}"
    )

    # --- no-mutation guarantee (PRD §7.7: '... never mutates the "
    # artifact'). ---
    after_bytes = _snapshot_bytes(watched_paths)
    assert after_bytes == before_bytes, (
        f"expected `axial chunk examine` to leave every fixture file under "
        f"data/chunks/ byte-for-byte unchanged, but at least one differs.\n"
        f"changed: "
        f"{sorted(str(p) for p in watched_paths if after_bytes[p] != before_bytes[p])}"
    )
    after_listing = sorted(p.name for p in placed["chunks_dir"].iterdir())
    assert after_listing == before_listing, (
        f"expected the set of files under data/chunks/ to be unchanged by "
        f"`axial chunk examine` (no new file written, none removed), got "
        f"{after_listing!r} vs. original {before_listing!r}"
    )


def test_chunk_examine_constructs_no_embedder_or_llm_client(tmp_path, monkeypatch):
    """Direct, construction-seam-level proof of the zero-inference guarantee
    (module docstring, seam decision 3, proof 2): `examine` must never
    construct or use an embedder or an LLM client. A minimal one-record
    fixture is enough here -- this test's only job is the zero-inference
    contract, not the stats reported by the other test above."""

    def _poison(*_args, **_kwargs):
        raise AssertionError(
            "axial chunk examine must construct NO embedder and NO LLM "
            "client (PRD §7.7/§8 P0-4b: 'zero LLM and zero embedding-model "
            "calls') -- this seam was called during an `examine` run"
        )

    monkeypatch.setattr("axial.chunk.get_embedder", _poison, raising=False)
    monkeypatch.setattr("axial.chunk.get_client", _poison, raising=False)
    monkeypatch.setattr("axial.chunk.HashingEmbedder.encode", _poison, raising=False)

    chunks_dir = tmp_path / "data" / "chunks"
    _write_jsonl(
        chunks_dir / "source-solo.jsonl",
        [_record("source-solo_1_intro_001", "Intro", "1", _chunk_text("MARKER-SOLO", 1200))],
    )

    monkeypatch.chdir(tmp_path)

    from axial.cli import main

    exit_code = main(["chunk", "examine"])

    assert exit_code == 0, (
        f"expected `axial chunk examine` (invoked in-process, with "
        f"axial.chunk.get_embedder/get_client/HashingEmbedder.encode all "
        f"poisoned to raise if called) to exit 0 -- a nonzero exit here "
        f"means either the `examine` subcommand does not exist yet, or it "
        f"failed for some other reason before ever reaching one of the "
        f"poisoned construction/use seams; got {exit_code}"
    )
