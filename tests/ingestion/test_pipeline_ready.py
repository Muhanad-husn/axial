"""Outer acceptance test for issue #121 (pipeline-ready canary gate).

Founder-ratified decisions this test encodes (see the dispatch for issue
#121 and docs/postmortem/gold-run-2026-07/canary-set.md, "The 'pipeline
ready' bar"):

  - A new CLI subcommand, `axial pipeline-ready --manifest <path>`, reads a
    TOML manifest of canaries, runs each one end-to-end, evaluates it
    against the "pipeline ready" bar, and prints a per-canary PASS/FAIL
    table.
  - Exit code is non-zero if ANY canary fails; 0 iff every canary passes.
  - Per-canary manifest entries carry `source_id`, `time_envelope_sec`, and
    `quarantine_budget` (a fraction, e.g. 0.02).
  - The bar (criteria 1-3 of the postmortem's four; criterion 4, suite-green,
    is explicitly out of THIS command's scope):
      1. The canary ingests end-to-end in a single attempt, unattended.
      2. Zero source-fatal errors; per-note problems resolve to a logged
         quarantine, and the quarantined fraction stays under the canary's
         own `quarantine_budget`.
      3. Bounded wall clock: the recorded duration stays within the
         canary's own `time_envelope_sec`.

Re-pointed at the interrogation pass (issue #414, D4/D5): `src/axial/
pipeline_ready.py`'s single-attempt ingest used to run through `axial.vault.
run_vault_write` (which composed the tag pass internally); `run_vault_write`
is now a stub that always raises (issue #411 rebuilds it), so this gate now
drives `axial.interrogate.run_interrogate` directly and reads its quarantine
signal off the interrogation-pass answer checkpoint instead of the tag-pass
checkpoint. Three consequences for this test, versus the version issue #121
originally locked:

  1. **No fault-injection-via-env-var quarantine case.** The tag pass's stub
     supported per-position response sequencing and a fail-at-call-N seam;
     the interrogation pass's stub (`AXIAL_STUB_NOTE_INTERROGATE_RESPONSE`)
     supports only ONE fixed override for the whole process, so scripting
     "note 1 of 2 fails, note 2 succeeds" via env var is not possible. This
     test instead drives quarantine through DATA: one note's chunk text is
     genuinely garbled (triggers the interrogation pass's own garble
     backstop, `axial.nonprose_guard.garble_only_skip_reason`, with zero LLM
     calls), the other is ordinary prose that answers normally -- a
     deterministic, real quarantined fraction, mirroring `src/axial/
     test_interrogate.py`'s own `test_a_source_whose_every_note_is_a_garble_
     skip_is_not_a_failure` fixture technique.
  2. **No source-fatal "out-of-vocab" case.** The original suite's third
     case forced `axial.tag.TagNotInSchemaError`, a persisting off-list-
     value hard error from the tag pass's closed-vocabulary validator. D9
     (`plans/phase-a-v1/README.md`) retires that validator outright -- the
     interrogation pass never validates a free answer against anything, so
     there is no equivalent fatal-value scenario to force. Dropped, not
     replaced: a source-fatal completion failure (postmortem criterion 1)
     is still covered structurally by `pipeline_ready.evaluate_canary`'s own
     `except InterrogateError` branch, exercised implicitly whenever every
     note in a canary fails (see `AllNotesFailedError` in `src/axial/
     test_interrogate.py`), but this outer test does not re-pin it -- doing
     so would need the same per-position scripting point 1 explains is gone.
  3. The all-PASS and time-envelope cases are mechanism-agnostic (they never
     depended on which pass ran) and are carried over unchanged in shape.

This is a STUB-provider test: the real 5-canary corpus
(docs/postmortem/gold-run-2026-07/canary-set.md) lives in the gitignored
`data/sources/` and is never read here (DEC-23, copyright: no book text in
this repo). Every source this test drives is a small, wholly synthetic
stand-in committed under tests/fixtures/pipeline_ready/ -- no real book
content anywhere in this file or its fixtures. The real production manifest
naming the 5 real canaries (`config/canary-manifest.toml`) is a SEPARATE
deliverable, out of scope here; this test only ever points `--manifest` at
its own synthetic fixture manifests.

Seam decision -- the per-canary table is asserted by COLUMN NAME, not
position or exact prose
-----------------------------------------------------------------------
This test locks the table's shape minimally: one line to stdout carrying, at
least, the tab-separated column names `source_id` and `verdict` (a header
row), followed by one tab-separated data row per canary in the manifest
(any order), each row's `verdict` value being exactly the literal string
`PASS` or `FAIL`. Every assertion below looks a canary's row up by its own
`source_id`, never by row position, and never by matching a whole line/
sentence verbatim.

Test hygiene: every path this test writes (the manifest, the worklist-free
per-canary trees/envelopes/vault/chunks/answers dirs) lives under
`isolated_vault_root` (tests/conftest.py, issue #68) -- a fresh
`tmp_path`-backed staging root outside this repo entirely. No real `data/`
directory is ever read, moved, or written by this test.
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
from pathlib import Path

import axial.chunk as chunk_module
from axial.chunk import run_chunk_recursive
from axial.envelope import compute_source_id

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "pipeline_ready"

CLEAN_PASS_1_DOCX = FIXTURES_DIR / "clean_pass_1.docx"
CLEAN_PASS_2_DOCX = FIXTURES_DIR / "clean_pass_2.docx"
QUARANTINE_FAIL_DOCX = FIXTURES_DIR / "quarantine_fail.docx"

SINGLE_SECTION_TREE_FIXTURE = FIXTURES_DIR / "single_section_tree.json"

PROVIDER_ENV_VAR = "AXIAL_LLM_PROVIDER"

# A generous time envelope no synthetic stub-driven run could plausibly
# exceed, and the flat 2% quarantine budget the postmortem's own bar names
# ("quarantined notes stay under 2% per source").
GENEROUS_TIME_ENVELOPE_SEC = 600
FLAT_QUARANTINE_BUDGET = 0.02

# Ordinary, low-non-alpha prose: answers normally, no quarantine.
_LEGIT_NOTE_TEXT = (
    "As shown above, the council's deliberations produced a durable "
    "compromise that satisfied few but was accepted by all as workable."
)
# Heavily non-alphabetic ("term, page" soup): triggers the interrogation
# pass's own garble backstop before any LLM call (mirrors src/axial/
# test_interrogate.py's own garble-skip fixture).
_GARBLED_NOTE_TEXT = "%%%% 1234 ;;;; ---- @@@@ 5678 //// ==== ++++ 9012 ****"

# argparse's fallback error for an as-yet-nonexistent subcommand -- any of
# these substrings in the combined output means `pipeline-ready` does not
# exist yet or was never reached (mirrors tests/test_ingest.py exactly).
ARGPARSE_FALLBACK_MARKERS = (
    "invalid choice",
    "unrecognized arguments",
)


def _trees_dir(root: Path) -> Path:
    return root / "data" / "trees"


def _envelopes_dir(root: Path) -> Path:
    return root / "data" / "envelopes"


def _run_axial(
    args: list[str],
    provider: str,
    *,
    cwd: Path,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env[PROVIDER_ENV_VAR] = provider
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["uv", "run", "--project", str(REPO_ROOT), "axial", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        env=env,
    )


def _run_envelope(provider: str, *args: str, cwd: Path) -> subprocess.CompletedProcess:
    return _run_axial(["envelope", *args], provider, cwd=cwd)


def _run_pipeline_ready(
    provider: str,
    manifest_path: Path,
    *,
    cwd: Path,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    return _run_axial(
        ["pipeline-ready", "--manifest", str(manifest_path)],
        provider,
        cwd=cwd,
        extra_env=extra_env,
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


def _existing_envelope_files(root: Path) -> set[Path]:
    envelopes_dir = _envelopes_dir(root)
    if not envelopes_dir.exists():
        return set()
    return set(envelopes_dir.glob("*.json"))


def _place_tree_fixture(source_path: Path, root: Path) -> Path:
    """Pre-place the shared, hand-authored single-section tree fixture at
    <root>/data/trees/<source_id>.json, so `axial.extract.extract` reuses it
    verbatim instead of running docling/Unstructured."""
    source_id = compute_source_id(source_path)
    tree_path = _trees_dir(root) / f"{source_id}.json"
    tree_path.parent.mkdir(parents=True, exist_ok=True)
    tree_path.write_bytes(SINGLE_SECTION_TREE_FIXTURE.read_bytes())
    return tree_path


@contextlib.contextmanager
def _chdir(path: Path):
    """Temporarily change the process cwd to `path`: `run_chunk_recursive`
    resolves its persisted-tree read (`axial.extract.tree_path`, via
    `axial.extract.TREES_DIR`) as a plain, cwd-relative path with no
    override parameter. Calling it in-process needs this to reproduce the
    exact resolution a `cwd=`-scoped subprocess would get."""
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def _arrange_stored_envelope(source_path: Path, root: Path, *, chunk: bool = True) -> str:
    """Pre-place the tree fixture, then run `axial envelope` with the stub
    provider so a stored envelope AND a stored source-metadata record exist
    on disk before `pipeline-ready` runs (`extract()` calls `intake()`
    first, which writes the source-metadata record as a side effect).
    Asserts the arrange step itself succeeded and produced exactly one new
    envelope file. Returns the computed source_id.

    When `chunk` is True (the default), also writes the real, on-disk chunk
    artifact via the LLM-stub-driven `run_chunk_recursive` -- fine for cases
    that don't care about a note's exact text. The quarantine case below
    passes `chunk=False` and writes its own chunk artifact directly, for
    deterministic control over which note is garbled."""
    _place_tree_fixture(source_path, root)
    before_files = _existing_envelope_files(root)

    result = _run_envelope("stub", str(source_path), cwd=root)
    _assert_not_argparse_fallback(result, "envelope")
    assert result.returncode == 0, (
        f"arrange step failed: expected exit code 0 for `axial envelope` on "
        f"{source_path.name} with the stub LLM provider, got {result.returncode}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    new_files = _existing_envelope_files(root) - before_files
    assert len(new_files) == 1, (
        f"arrange step failed: expected exactly one new file under "
        f"{_envelopes_dir(root)} after `axial envelope` on {source_path.name}, "
        f"got {len(new_files)}: {sorted(new_files)}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    if chunk:
        with _chdir(root):
            run_chunk_recursive(source_path)

    return compute_source_id(source_path)


def _write_chunk_artifact(root: Path, source_id: str, texts: list[str]) -> None:
    """Write a real on-disk chunk artifact with one record per element of
    `texts`, via the same `build_chunk_records`/`chunks_checkpoint_path`
    helpers `axial chunk` itself uses (mirrors tests/ingestion/
    test_source_router.py's own fixture-writing pattern)."""
    chunks_dir = root / "data" / "chunks"
    records = chunk_module.build_chunk_records(
        source_id, "1", "Body", [{"text": text} for text in texts]
    )
    out_path = chunk_module.chunks_checkpoint_path(source_id, chunks_dir)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")


def _toml_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _write_manifest(path: Path, canaries: list[dict]) -> None:
    """Write a TOML manifest of `[[canary]]` entries: every entry carries
    the three founder-ratified fields (`source_id`, `time_envelope_sec`,
    `quarantine_budget`) plus this test's own `source_path` field, an
    absolute path computed fresh at test run time -- never a
    machine-specific string baked into a committed fixture."""
    lines: list[str] = []
    for canary in canaries:
        lines.append("[[canary]]")
        lines.append(f'source_id = "{_toml_escape(canary["source_id"])}"')
        lines.append(f'source_path = "{_toml_escape(str(canary["source_path"]))}"')
        lines.append(f"time_envelope_sec = {canary['time_envelope_sec']}")
        lines.append(f"quarantine_budget = {canary['quarantine_budget']}")
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def _parse_pipeline_ready_table(stdout: str) -> dict[str, dict[str, str]]:
    """Parse `pipeline-ready`'s per-canary table from stdout ONLY: a header
    line whose tab-separated fields include (at least) `source_id` and
    `verdict` (a header row), followed by one tab-separated data row per
    canary carrying the same number of fields as the header. Returns a
    mapping of `source_id` -> that row's fields (by column name), so every
    assertion below looks a canary up by its own identity, never by row
    position or a whole-line/sentence match."""
    lines = [line for line in stdout.splitlines() if line.strip()]

    header_index = None
    header_cols: list[str] | None = None
    for index, line in enumerate(lines):
        cols = [col.strip() for col in line.split("\t")]
        if "source_id" in cols and "verdict" in cols:
            header_index = index
            header_cols = cols
            break

    assert header_index is not None and header_cols is not None, (
        "expected `axial pipeline-ready`'s stdout to contain a header row "
        "whose tab-separated columns include 'source_id' and 'verdict' "
        f"(issue #121's per-canary PASS/FAIL table), got stdout: {stdout!r}"
    )

    rows: dict[str, dict[str, str]] = {}
    for line in lines[header_index + 1 :]:
        cols = [col.strip() for col in line.split("\t")]
        if len(cols) != len(header_cols):
            continue
        row = dict(zip(header_cols, cols))
        rows[row["source_id"]] = row
    return rows


def _assert_verdict(
    table: dict[str, dict[str, str]], source_id: str, expected_verdict: str, canary_name: str
) -> None:
    assert source_id in table, (
        f"expected the pipeline-ready table to carry a row for canary "
        f"{canary_name!r} (source_id={source_id!r}), got rows for: "
        f"{sorted(table.keys())}"
    )
    actual = table[source_id].get("verdict")
    assert actual == expected_verdict, (
        f"expected canary {canary_name!r} (source_id={source_id!r}) to be "
        f"{expected_verdict!r} in the pipeline-ready table, got {actual!r} "
        f"(full row: {table[source_id]!r})"
    )


# ---------------------------------------------------------------------------
# Case 1: every canary ingests clean, under budget, within envelope -> PASS,
# exit 0.
# ---------------------------------------------------------------------------


def test_all_canaries_pass_when_clean_under_budget_and_within_envelope(isolated_vault_root):
    root = isolated_vault_root
    source_id_1 = _arrange_stored_envelope(CLEAN_PASS_1_DOCX, root)
    source_id_2 = _arrange_stored_envelope(CLEAN_PASS_2_DOCX, root)

    manifest_path = root / "canary_manifest_all_pass.toml"
    _write_manifest(
        manifest_path,
        [
            {
                "source_id": source_id_1,
                "source_path": CLEAN_PASS_1_DOCX,
                "time_envelope_sec": GENEROUS_TIME_ENVELOPE_SEC,
                "quarantine_budget": FLAT_QUARANTINE_BUDGET,
            },
            {
                "source_id": source_id_2,
                "source_path": CLEAN_PASS_2_DOCX,
                "time_envelope_sec": GENEROUS_TIME_ENVELOPE_SEC,
                "quarantine_budget": FLAT_QUARANTINE_BUDGET,
            },
        ],
    )

    result = _run_pipeline_ready("stub", manifest_path, cwd=root)
    _assert_not_argparse_fallback(result, "pipeline-ready")

    assert result.returncode == 0, (
        f"expected exit code 0 for `axial pipeline-ready` when every canary "
        f"ingests clean, under budget, and within its time envelope, got "
        f"{result.returncode}\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    table = _parse_pipeline_ready_table(result.stdout)
    assert len(table) == 2, (
        f"expected exactly 2 rows in the pipeline-ready table (one per "
        f"manifest entry), got {len(table)}: {sorted(table.keys())}"
    )
    _assert_verdict(table, source_id_1, "PASS", "clean_pass_1")
    _assert_verdict(table, source_id_2, "PASS", "clean_pass_2")


# ---------------------------------------------------------------------------
# Case 2: a canary's quarantined fraction exceeds its quarantine_budget ->
# that row is FAIL, non-zero exit (postmortem criterion 2).
# ---------------------------------------------------------------------------


def test_quarantine_fraction_over_budget_fails_that_canary(isolated_vault_root):
    root = isolated_vault_root
    source_id = _arrange_stored_envelope(QUARANTINE_FAIL_DOCX, root, chunk=False)

    # One legit note, one genuinely garbled note (module docstring): the
    # garbled note is caught by the interrogation pass's own garble
    # backstop before any LLM call, giving a deterministic quarantined
    # fraction of 1/2 = 50%, far over the 2% budget.
    _write_chunk_artifact(root, source_id, [_LEGIT_NOTE_TEXT, _GARBLED_NOTE_TEXT])

    manifest_path = root / "canary_manifest_quarantine_fail.toml"
    _write_manifest(
        manifest_path,
        [
            {
                "source_id": source_id,
                "source_path": QUARANTINE_FAIL_DOCX,
                "time_envelope_sec": GENEROUS_TIME_ENVELOPE_SEC,
                "quarantine_budget": FLAT_QUARANTINE_BUDGET,
            }
        ],
    )

    result = _run_pipeline_ready("stub", manifest_path, cwd=root)
    _assert_not_argparse_fallback(result, "pipeline-ready")

    assert result.returncode != 0, (
        f"expected a non-zero exit code for `axial pipeline-ready` when one "
        f"canary's quarantined-note fraction (50%) exceeds its declared "
        f"quarantine_budget (2%), got exit code 0\nstdout: {result.stdout!r}\n"
        f"stderr: {result.stderr!r}"
    )

    table = _parse_pipeline_ready_table(result.stdout)
    _assert_verdict(table, source_id, "FAIL", "quarantine_fail")


# ---------------------------------------------------------------------------
# Case 3: a canary's recorded duration exceeds its time_envelope_sec ->
# that row is FAIL, non-zero exit (postmortem criterion 3, "bounded wall
# clock").
# ---------------------------------------------------------------------------


def test_over_time_envelope_fails_that_canary(isolated_vault_root):
    root = isolated_vault_root
    source_id = _arrange_stored_envelope(CLEAN_PASS_1_DOCX, root)

    # `time_envelope_sec = 0`: no real ingestion (even a stub-driven one,
    # which still makes several real function calls and file writes) can
    # complete in a strictly non-positive recorded duration, so this
    # deterministically exercises the "duration exceeds its envelope" FAIL
    # path without depending on any particular measured wall-clock value.
    manifest_path = root / "canary_manifest_time_envelope_fail.toml"
    _write_manifest(
        manifest_path,
        [
            {
                "source_id": source_id,
                "source_path": CLEAN_PASS_1_DOCX,
                "time_envelope_sec": 0,
                "quarantine_budget": FLAT_QUARANTINE_BUDGET,
            }
        ],
    )

    result = _run_pipeline_ready("stub", manifest_path, cwd=root)
    _assert_not_argparse_fallback(result, "pipeline-ready")

    assert result.returncode != 0, (
        f"expected a non-zero exit code for `axial pipeline-ready` when a "
        f"canary's recorded duration exceeds its declared time_envelope_sec "
        f"(here, 0 -- any real recorded duration exceeds it), got exit code "
        f"0\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    table = _parse_pipeline_ready_table(result.stdout)
    _assert_verdict(table, source_id, "FAIL", "clean_pass_1 (zero time envelope)")
