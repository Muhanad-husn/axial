"""Outer acceptance test for issue #119 (`ingest_worker.sh` skips sources
already ingested -- vault=OK guard), recreated as a first-class CLI
subcommand.

Locked behavioral contract (DEC-1) -- do not edit once committed red.

Given a worklist file naming three sources, one of which already has a
      `vault_status=OK` row in the persistent results file
      (`data/gold/ingest.results.tsv`), and AXIAL_LLM_PROVIDER=stub
When  the user runs `axial ingest <worklist>`
Then  the already-completed source is skipped: exactly one
      `skip: ... already ingested` line names it, and NO pipeline work (no
      prose note, no artifact note) is produced for it
And   the other two sources are ingested via the existing vault-write path
      (chunk->tag->artifacts->xref->vault) and each gets exactly one newly
      appended results row recording vault_status=OK
And   the run exits 0
And   the results file grows by APPEND, not overwrite: the pre-seeded row
      for the skipped source is still present, byte-for-byte unchanged,
      alongside the two new rows

See GitHub issue #119 ("fix(ops): ingest_worker.sh skips sources already
ingested (vault=OK guard)") and its parent postmortem
docs/postmortem/gold-run-2026-07/README.md ("root cause D. No failure
isolation... the worker loop re-runs finished work" / "26 redundant
attempts, 14.7 h, 8% of all logged compute") for the behavior this recreates.
`data/gold/ingest_worker.sh` was an uncommitted, gitignored operator script
(all of `data/` is repo-gitignored, DEC-23) with no completed-source check;
it is recreated here as a tested, first-class CLI subcommand, `axial ingest
<worklist>` (module src/axial/ingest.py, entry in src/axial/cli.py),
implementing the same round-robin-worklist contract but WITH the missing
skip guard this issue adds. The founder-ratified per-source contract this
test locks: read a line-delimited worklist of source paths; for each, at the
top of the loop, skip -- logging exactly one line naming the source -- if a
prior `vault_status=OK` row already exists for that source's own computed
`source_id` in the persistent results file; otherwise ingest it via the
existing `axial.vault.run_vault_write` (the same internal pipeline `axial
vault write` already drives) and append one new results row recording the
outcome. Per-source failure resilience (a failing source records
`vault_status=FAIL` and the loop continues) is issue #119's stated context
but not this slice's locked acceptance surface -- kept out of this test so
it stays focused on the skip guard plus result recording, the #119
deliverable itself; a future slice's own test is expected to cover the
failure-resilience path if/when it needs its own explicit contract.

As of this commit, `src/axial/ingest.py` does not exist and `axial ingest`
is not a registered subcommand at all, so this test is expected to fail red
for exactly that reason (an argparse "invalid choice" fallback -- see
`_assert_not_argparse_fallback` below) -- not on an import error, a
fixture-arrangement error, or a call-signature mismatch in this test itself.

Seam decision 1 -- three genuinely DISTINCT, already-committed fixtures,
never one fixture reused as three fake "sources"
-----------------------------------------------------------------------
`source_id` is derived purely from a source file's own content
(`axial.envelope.compute_source_id`: filename stem + a content hash), so
listing the SAME underlying PDF three times in a worklist would collide on
one `source_id` and could never exercise "one already-completed source among
two fresh ones" as three independent rows. This test instead reuses three
fixtures already committed and already proven, end-to-end, against this
exact vault-write pipeline by sibling acceptance tests -- no new fixture is
introduced:
  - tests/fixtures/envelope/thesis_paper.pdf (+ thesis_paper_tree.json):
    three prose sections, NO artifact nodes (tests/test_vault_write.py).
  - tests/fixtures/extract/prose_and_table.pdf (+ prose_and_table_tree.json):
    two prose sections AND exactly one artifact node
    (tests/test_vault_artifacts.py, tests/test_vault_xref.py) -- used here
    as the ALREADY-INGESTED (pre-seeded, must-be-skipped) source, precisely
    because it carries BOTH surfaces (prose and artifact), making "no
    pipeline work happened for it" the strongest claim this fixture set can
    make.
  - tests/fixtures/artifacts/multi_artifact.pdf (+ multi_artifact_tree.json):
    one section, four artifact nodes (tests/test_artifacts_resume.py) --
    used here as a freshly-processed source, proving the non-skipped path
    correctly drives both the prose AND the artifact half of the pipeline,
    not merely the prose half thesis_paper.pdf alone would exercise.

Seam decision 2 -- arranging the stored-envelope precondition explicitly,
never asking `axial ingest` itself to compute one
-----------------------------------------------------------------------
`axial.vault.run_vault_write` (the ratified per-source action this issue's
contract names) reads an EXISTING stored envelope and raises
`MissingEnvelopeError` if none exists -- it never computes one itself (see
its own module docstring: "read the stored envelope, never recomputing
it"). A source is only ever a candidate for `axial ingest` after it has
already been through intake/extract/envelope, exactly mirroring how every
existing vault-write acceptance test (tests/test_vault_write.py's
`_arrange_stored_envelope`, tests/test_vault_artifacts.py's own copy of the
same helper) arranges this precondition before invoking the pass under
test. This test does the same, for all three sources, before ever invoking
`axial ingest`: pre-place each fixture's committed tree at
`data/trees/<source_id>.json` (so `axial.extract.extract` reuses it instead
of running docling -- no real PDF parsing, no network) and run `axial
envelope --provider stub` once per source. This is a test ARRANGE step
only, not a claim about what `axial ingest` itself must do about a source
with no stored envelope (out of scope; not asserted either way here).

Seam decision 3 -- deriving expected chunk_id/artifact_id sets
independently, never hardcoding them
-----------------------------------------------------------------------
Mirroring tests/test_vault_write.py's seam decision 2 and
tests/test_vault_artifacts.py's seam decision 1 exactly: this test never
hardcodes any chunk_id or artifact_id. For every source it independently
runs `axial chunk`/`axial artifacts` (stub provider, same fixture, same
stored envelope) to obtain the fixture's real chunk_id/artifact_id sets, and
treats those as: (a) for the SKIPPED source, the exact set of note stems
that must be absent from the vault after the run; (b) for the two FRESH
sources, the exact set of note stems `axial ingest`'s internal vault-write
call must produce. This is safe for the same reason the sibling tests'
identical derivation is safe: the standalone `axial chunk`/`axial artifacts`
CLI commands and `run_vault_write`'s own internal calls to the same passes
consume the same stored envelope/tree with the same stub provider, so they
must agree.

Migration note (issue #154, slice 04): as of this slice, deriving the
expected chunk_id set is no longer a side-effect-free observation --
`axial.chunk.run_chunk_recursive` (the sole chunking mechanism now) WRITES
the real, on-disk chunk artifact (`data/chunks/<source_id>.jsonl`) as its
whole point, and `axial ingest`'s own internal `axial.vault.run_vault_write`
call no longer chunks at all -- it only ever READS that same artifact (via
`axial.chunk.read_chunks`), and fails clearly if it is absent. So this
arrange step is now a REQUIRED precondition for the two fresh sources
`axial ingest` must actually process, not merely an inert observation (the
already-ingested source's artifact is written too, harmlessly, since it is
skipped by the results-file guard regardless).

Seam decision 4 -- the skip guard is checked two ways, one lenient and one
strict
-----------------------------------------------------------------------
(a) The lenient, literal-Gherkin check: exactly one line in the combined
    stdout+stderr contains both "skip" and "already ingested"
    (case-insensitive), and that one line names the skipped source (by its
    full path, its computed source_id, or its filename stem -- the issue's
    own Gherkin pins the substance ("logging one skip: <source> already
    ingested line"), not one exact byte-for-byte format, so this test
    accepts any of those three ways of "naming the source" rather than
    inventing a formatting requirement no source of truth states). No such
    line ever names either FRESH source.
(b) The strict, implementation-agnostic check, which is the real behavioral
    guarantee issue #119 demands ("performs no pipeline work for it"): none
    of the skipped source's own independently-derived chunk_ids or
    artifact_ids appear as a note filename stem anywhere under
    `data/vault/prose/` or `data/vault/artifacts/` after the run. A skip
    guard that logged the right line but still did the work underneath
    would pass (a) and fail (b); this test requires both.

Seam decision 5 -- the pre-seeded row's `source_id` is computed via the same
function the implementation itself must use
-----------------------------------------------------------------------
The pre-seeded "already ingested" row's `source_id` column is populated by
calling `axial.envelope.compute_source_id` on the fixture directly (never
guessed or hardcoded), because "already appears in the results file with
vault_status=OK" (the ratified contract's own wording) is a claim about
matching on that exact computed value -- a correct implementation deriving
`source_id` from the worklist's path entry and finding this row must match.

Seam decision 6 -- results-file shape locked by column NAME, not position;
sentinel values prove the skipped row was truly left untouched
-----------------------------------------------------------------------
This test locks the ratified contract's exact column set --
`source_path, source_id, vault_status, notes_count, duration_sec, exit_code,
timestamp` -- as a tab-separated file with a header row, parsed by column
NAME (`csv.DictReader`), never by fixed position: this test does not care
which order the implementer emits those seven columns in, only that all
seven exist and carry the stated semantics. The pre-seeded row's
`notes_count`/`duration_sec`/`timestamp` values are deliberately
implausible sentinels (`"999"`, `"0.001"`, `"1999-01-01T00:00:00Z"`) that no
real run of this fixture could organically reproduce -- so if the
post-run row for the skipped source is byte-for-byte identical to what was
seeded, that is direct proof no recomputation happened for it at all (not
merely that "some" row with `vault_status=OK` exists), a strictly stronger
claim than checking `vault_status` alone.

Test hygiene: everything this test writes (the worklist file, the results
TSV, the tree/envelope/vault directories) lives under `isolated_vault_root`
(tests/conftest.py, issue #68) -- a fresh `tmp_path`-backed staging root
outside this repo entirely. No real `data/` directory is ever read, moved,
or written by this test, and nothing needs manual teardown.
"""

from __future__ import annotations

import contextlib
import csv
import json
import os
import subprocess
from pathlib import Path

from axial.chunk import run_chunk_recursive
from axial.envelope import compute_source_id

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

THESIS_PAPER_PDF = REPO_ROOT / "tests" / "fixtures" / "envelope" / "thesis_paper.pdf"
THESIS_PAPER_TREE_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "envelope" / "thesis_paper_tree.json"

PROSE_AND_TABLE_PDF = REPO_ROOT / "tests" / "fixtures" / "extract" / "prose_and_table.pdf"
PROSE_AND_TABLE_TREE_FIXTURE = (
    REPO_ROOT / "tests" / "fixtures" / "extract" / "prose_and_table_tree.json"
)

MULTI_ARTIFACT_PDF = REPO_ROOT / "tests" / "fixtures" / "artifacts" / "multi_artifact.pdf"
MULTI_ARTIFACT_TREE_FIXTURE = (
    REPO_ROOT / "tests" / "fixtures" / "artifacts" / "multi_artifact_tree.json"
)

PROVIDER_ENV_VAR = "AXIAL_LLM_PROVIDER"

RESULTS_COLUMNS = (
    "source_path",
    "source_id",
    "vault_status",
    "notes_count",
    "duration_sec",
    "exit_code",
    "timestamp",
)

# Deliberately implausible values (module docstring, seam decision 6) --
# no real run of this fixture could organically produce these, so their
# survival byte-for-byte proves the skipped row was never recomputed.
SENTINEL_NOTES_COUNT = "999"
SENTINEL_DURATION_SEC = "0.001"
SENTINEL_TIMESTAMP = "1999-01-01T00:00:00Z"

# argparse's fallback error for an as-yet-nonexistent subcommand, e.g.
# "axial: error: argument command: invalid choice: 'ingest' (choose from
# 'schema', 'intake', 'extract', 'envelope', 'chunk', ...)". Any of these
# substrings in the combined output means `ingest`'s own logic was never
# actually exercised -- the process failed before real behavior ran.
ARGPARSE_FALLBACK_MARKERS = (
    "invalid choice",
    "unrecognized arguments",
)


def _trees_dir(root: Path) -> Path:
    return root / "data" / "trees"


def _envelopes_dir(root: Path) -> Path:
    return root / "data" / "envelopes"


def _vault_dir(root: Path) -> Path:
    return root / "data" / "vault"


def _prose_dir(root: Path) -> Path:
    return _vault_dir(root) / "prose"


def _artifacts_dir(root: Path) -> Path:
    return _vault_dir(root) / "artifacts"


def _results_path(root: Path) -> Path:
    return root / "data" / "gold" / "ingest.results.tsv"


@contextlib.contextmanager
def _chdir(path: Path):
    """Temporarily change the process cwd to `path` -- see
    `_expected_chunk_ids` below: `run_chunk_recursive` resolves its
    persisted-tree read (`axial.extract.tree_path`, via
    `axial.extract.TREES_DIR`) as a plain, cwd-relative path with no
    override parameter (only its OWN write target, `chunks_dir`, is
    overridable). Calling it in-process instead of shelling out to `axial
    chunk` needs this to reproduce the exact resolution a `cwd=`-scoped
    subprocess would get."""
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


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


def _run_artifacts(provider: str, *args: str, cwd: Path) -> subprocess.CompletedProcess:
    return _run_axial(["artifacts", *args], provider, cwd=cwd)


def _run_ingest(provider: str, *args: str, cwd: Path) -> subprocess.CompletedProcess:
    return _run_axial(["ingest", *args], provider, cwd=cwd)


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


def _place_tree_fixture(source_pdf: Path, tree_fixture_path: Path, root: Path) -> Path:
    """Pre-place the committed REAL tree fixture at
    <root>/data/trees/<source_id>.json so `axial.extract.extract` reuses it
    verbatim instead of running docling (module docstring, seam decision 2)."""
    source_id = compute_source_id(source_pdf)
    tree_path = _trees_dir(root) / f"{source_id}.json"
    tree_path.parent.mkdir(parents=True, exist_ok=True)
    tree_path.write_bytes(tree_fixture_path.read_bytes())
    return tree_path


def _arrange_stored_envelope(source_pdf: Path, tree_fixture_path: Path, root: Path) -> Path:
    """Pre-place the real tree fixture, then run `axial envelope` with the
    stub provider so a stored envelope exists on disk before `axial ingest`
    runs (module docstring, seam decision 2). Asserts the arrange step
    itself succeeded and produced exactly one new envelope file."""
    _place_tree_fixture(source_pdf, tree_fixture_path, root)
    before_files = _existing_envelope_files(root)

    result = _run_envelope("stub", str(source_pdf), cwd=root)
    _assert_not_argparse_fallback(result, "envelope")
    assert result.returncode == 0, (
        f"arrange step failed: expected exit code 0 for `axial envelope` on "
        f"{source_pdf.name} with the stub LLM provider, got {result.returncode}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    new_files = _existing_envelope_files(root) - before_files
    assert len(new_files) == 1, (
        f"arrange step failed: expected exactly one new file under "
        f"{_envelopes_dir(root)} after `axial envelope` on {source_pdf.name}, "
        f"got {len(new_files)}: {sorted(new_files)}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    return next(iter(new_files))


def _parse_json_records(stdout: str, *, array_key: str, kind: str) -> list[dict]:
    """Parse records from stdout, tolerating a bare JSON array, a JSON
    object with a top-level `array_key` array, or newline-delimited JSON
    (mirrors tests/test_vault_write.py's / tests/test_vault_artifacts.py's
    own parsing helper)."""
    stripped = stdout.strip()

    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        data = None

    if data is not None:
        if isinstance(data, dict):
            assert array_key in data, (
                f"expected a top-level {array_key!r} key when {kind} stdout "
                f"is a JSON object, got keys: {sorted(data.keys())}; stdout: {stdout!r}"
            )
            records = data[array_key]
        else:
            records = data
        assert isinstance(records, list), (
            f"expected {kind} records to be a JSON array (bare, or under "
            f"a {array_key!r} key), got {type(records).__name__}: {records!r}"
        )
        return records

    records = []
    for line in stripped.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise AssertionError(
                f"expected {kind} stdout to be either one parseable JSON "
                f"document or newline-delimited JSON; line {line!r} failed "
                f"to parse ({exc}). Full stdout: {stdout!r}"
            ) from None
    return records


def _expected_chunk_ids(source_pdf: Path, root: Path) -> set[str]:
    """Write the real, on-disk chunk artifact for `source_pdf` IN-PROCESS
    (`axial.chunk.run_chunk_recursive`, the sole chunking mechanism)
    and return the chunk_id set it produced (module docstring, seam
    decision 3). Requires a stored envelope (and tree fixture) to already
    exist for this source.

    Issue #154 slice 04: `axial ingest`'s own internal
    `axial.vault.run_vault_write` call no longer chunks internally at all
    -- it only ever READS `data/chunks/<source_id>.jsonl` (via
    `axial.chunk.read_chunks`). So for the two FRESH sources this test
    expects `axial ingest` to actually process, this arrange step is also
    what makes that possible: it must write each fresh source's own chunk
    artifact before `axial ingest` ever runs (the already-ingested source's
    artifact is written too, harmlessly, since it is skipped by the
    results-file guard regardless of whether a chunk artifact exists for
    it)."""
    with _chdir(root):
        records = run_chunk_recursive(source_pdf)
    ids = {
        record["chunk_id"]
        for record in records
        if isinstance(record.get("chunk_id"), str) and record["chunk_id"].strip()
    }
    assert ids, f"arrange step failed: expected at least one chunk_id for {source_pdf.name}"
    return ids


def _expected_artifact_ids(source_pdf: Path, root: Path) -> set[str]:
    """Independently run `axial artifacts` (stub) to obtain the real
    artifact_id set for `source_pdf` (module docstring, seam decision 3).
    May legitimately be empty for a source with no artifact nodes."""
    result = _run_artifacts("stub", str(source_pdf), cwd=root)
    _assert_not_argparse_fallback(result, "artifacts")
    assert result.returncode == 0, (
        f"arrange step failed: expected exit code 0 for `axial artifacts` "
        f"on {source_pdf.name}, got {result.returncode}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    records = _parse_json_records(result.stdout, array_key="artifacts", kind="artifacts")
    return {
        record["artifact_id"]
        for record in records
        if isinstance(record.get("artifact_id"), str) and record["artifact_id"].strip()
    }


def _write_results_tsv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=RESULTS_COLUMNS, delimiter="\t")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _read_results_tsv(path: Path) -> list[dict]:
    assert path.exists(), (
        f"expected the results file {path} to exist after `axial ingest` ran, but it does not"
    )
    with path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        assert reader.fieldnames is not None, f"expected {path} to have a header row"
        missing = [c for c in RESULTS_COLUMNS if c not in reader.fieldnames]
        assert not missing, (
            f"expected the results file header to carry columns "
            f"{RESULTS_COLUMNS} (module docstring, seam decision 6), missing "
            f"{missing}; got header {reader.fieldnames}"
        )
        return list(reader)


def _notes_matching_stems(directory: Path, stems: set[str]) -> list[Path]:
    if not stems or not directory.exists():
        return []
    return [path for path in directory.iterdir() if path.is_file() and path.stem in stems]


def test_ingest_skips_already_completed_source_and_processes_the_rest(isolated_vault_root):
    root = isolated_vault_root

    # ---- Arrange: stored envelopes for all three sources (seam decision 2).
    _arrange_stored_envelope(THESIS_PAPER_PDF, THESIS_PAPER_TREE_FIXTURE, root)
    _arrange_stored_envelope(PROSE_AND_TABLE_PDF, PROSE_AND_TABLE_TREE_FIXTURE, root)
    _arrange_stored_envelope(MULTI_ARTIFACT_PDF, MULTI_ARTIFACT_TREE_FIXTURE, root)

    # ---- Arrange: independently-derived expected note sets (seam decision 3).
    skipped_chunk_ids = _expected_chunk_ids(PROSE_AND_TABLE_PDF, root)
    skipped_artifact_ids = _expected_artifact_ids(PROSE_AND_TABLE_PDF, root)
    assert skipped_artifact_ids, (
        "sanity check on the fixture itself failed: expected "
        "prose_and_table.pdf to carry at least one artifact (needed to make "
        "'no pipeline work at all' the strongest claim -- module docstring, "
        "seam decision 1)"
    )

    thesis_chunk_ids = _expected_chunk_ids(THESIS_PAPER_PDF, root)

    multi_artifact_chunk_ids = _expected_chunk_ids(MULTI_ARTIFACT_PDF, root)
    multi_artifact_artifact_ids = _expected_artifact_ids(MULTI_ARTIFACT_PDF, root)
    assert multi_artifact_artifact_ids, (
        "sanity check on the fixture itself failed: expected "
        "multi_artifact.pdf to carry at least one artifact"
    )

    skipped_source_id = compute_source_id(PROSE_AND_TABLE_PDF)
    thesis_source_id = compute_source_id(THESIS_PAPER_PDF)
    multi_artifact_source_id = compute_source_id(MULTI_ARTIFACT_PDF)

    # ---- Arrange: pre-seed one vault_status=OK row for the already-
    # ---- ingested source, with implausible sentinel values (seam decision 6).
    preseeded_row = {
        "source_path": str(PROSE_AND_TABLE_PDF),
        "source_id": skipped_source_id,
        "vault_status": "OK",
        "notes_count": SENTINEL_NOTES_COUNT,
        "duration_sec": SENTINEL_DURATION_SEC,
        "exit_code": "0",
        "timestamp": SENTINEL_TIMESTAMP,
    }
    results_path = _results_path(root)
    _write_results_tsv(results_path, [preseeded_row])

    # ---- Arrange: the worklist, three sources, the already-ingested one in
    # ---- the middle.
    worklist_path = root / "ingest_worklist.txt"
    worklist_path.write_text(
        "\n".join([str(THESIS_PAPER_PDF), str(PROSE_AND_TABLE_PDF), str(MULTI_ARTIFACT_PDF)])
        + "\n",
        encoding="utf-8",
    )

    # ---- Act.
    result = _run_ingest("stub", str(worklist_path), cwd=root)
    _assert_not_argparse_fallback(result, "ingest")
    assert result.returncode == 0, (
        f"expected exit code 0 for `axial ingest` over a worklist with one "
        f"already-completed source and two fresh ones, got "
        f"{result.returncode}\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    combined_output = result.stdout + result.stderr

    # ---- Then: exactly one skip line, naming the already-ingested source
    # ---- (module docstring, seam decision 4a).
    skip_lines = [
        line
        for line in combined_output.splitlines()
        if "skip" in line.lower() and "already ingested" in line.lower()
    ]
    assert len(skip_lines) == 1, (
        f"expected exactly one 'skip: ... already ingested' line for the "
        f"pre-completed source (PRD issue #119 Gherkin: 'logging one "
        f"skip: <source> already ingested line'), got {len(skip_lines)}: "
        f"{skip_lines!r}\nfull combined output: {combined_output!r}"
    )
    skip_line = skip_lines[0]
    assert (
        str(PROSE_AND_TABLE_PDF) in skip_line
        or skipped_source_id in skip_line
        or PROSE_AND_TABLE_PDF.stem in skip_line
    ), (
        f"expected the one skip line to name the already-ingested source "
        f"(by path, computed source_id, or filename stem), got: {skip_line!r}"
    )
    for fresh_pdf, fresh_id in (
        (THESIS_PAPER_PDF, thesis_source_id),
        (MULTI_ARTIFACT_PDF, multi_artifact_source_id),
    ):
        assert not (
            str(fresh_pdf) in skip_line or fresh_id in skip_line or fresh_pdf.stem in skip_line
        ), (
            f"expected the skip line to name only the already-ingested "
            f"source, but it also appears to name the FRESH source "
            f"{fresh_pdf.name}, which must be processed, not skipped: "
            f"{skip_line!r}"
        )

    # ---- Then: NO pipeline work at all happened for the skipped source
    # ---- (module docstring, seam decision 4b -- the real guarantee).
    prose_dir = _prose_dir(root)
    artifacts_dir = _artifacts_dir(root)

    found_skipped_prose = _notes_matching_stems(prose_dir, skipped_chunk_ids)
    assert found_skipped_prose == [], (
        f"expected NO prose note for the already-ingested source's own "
        f"chunk_ids under {prose_dir} (issue #119: 'performs no pipeline "
        f"work for it'), got: {sorted(p.name for p in found_skipped_prose)}"
    )
    found_skipped_artifacts = _notes_matching_stems(artifacts_dir, skipped_artifact_ids)
    assert found_skipped_artifacts == [], (
        f"expected NO artifact note for the already-ingested source's own "
        f"artifact_ids under {artifacts_dir}, got: "
        f"{sorted(p.name for p in found_skipped_artifacts)}"
    )

    # ---- Then: both FRESH sources were actually processed -- one prose
    # ---- note per real chunk, one artifact note per real artifact.
    for chunk_id in thesis_chunk_ids | multi_artifact_chunk_ids:
        matches = (
            [p for p in prose_dir.iterdir() if p.is_file() and p.stem == chunk_id]
            if prose_dir.exists()
            else []
        )
        assert len(matches) == 1, (
            f"expected exactly one prose note under {prose_dir} for chunk_id "
            f"{chunk_id!r} (a fresh, non-skipped source), got {len(matches)}"
        )
    for artifact_id in multi_artifact_artifact_ids:
        matches = (
            [p for p in artifacts_dir.iterdir() if p.is_file() and p.stem == artifact_id]
            if artifacts_dir.exists()
            else []
        )
        assert len(matches) == 1, (
            f"expected exactly one artifact note under {artifacts_dir} for "
            f"artifact_id {artifact_id!r} (a fresh, non-skipped source), got "
            f"{len(matches)}"
        )

    # ---- Then: the results file grew by APPEND, not overwrite.
    rows_after = _read_results_tsv(results_path)
    assert len(rows_after) == 3, (
        f"expected 1 pre-seeded row + 2 newly appended rows (one per fresh "
        f"source) == 3 total rows in {results_path}, got {len(rows_after)}: "
        f"{rows_after!r}"
    )

    skipped_rows_after = [row for row in rows_after if row["source_id"] == skipped_source_id]
    assert len(skipped_rows_after) == 1, (
        f"expected exactly one row for the already-ingested source's "
        f"source_id {skipped_source_id!r} (no duplicate re-append), got "
        f"{len(skipped_rows_after)}: {skipped_rows_after!r}"
    )
    assert skipped_rows_after[0] == preseeded_row, (
        f"expected the pre-seeded row for the skipped source to be "
        f"byte-for-byte unchanged after the run (its sentinel values -- "
        f"module docstring, seam decision 6 -- prove no recomputation "
        f"happened), got {skipped_rows_after[0]!r} vs. seeded "
        f"{preseeded_row!r}"
    )

    for fresh_pdf, fresh_id in (
        (THESIS_PAPER_PDF, thesis_source_id),
        (MULTI_ARTIFACT_PDF, multi_artifact_source_id),
    ):
        matching = [row for row in rows_after if row["source_id"] == fresh_id]
        assert len(matching) == 1, (
            f"expected exactly one newly appended results row for "
            f"{fresh_pdf.name} (source_id {fresh_id!r}), got {len(matching)}: "
            f"{matching!r}"
        )
        row = matching[0]
        assert row["vault_status"] == "OK", (
            f"expected vault_status=OK for {fresh_pdf.name} (a stub-provider "
            f"run that never fails), got {row['vault_status']!r}"
        )
        assert row["exit_code"] == "0", (
            f"expected exit_code=0 for {fresh_pdf.name}'s successful "
            f"per-source pipeline run, got {row['exit_code']!r}"
        )
        assert row["source_path"].strip(), (
            f"expected a non-empty source_path column for {fresh_pdf.name}"
        )
        assert row["timestamp"].strip(), (
            f"expected a non-empty timestamp column for {fresh_pdf.name}"
        )
        try:
            duration = float(row["duration_sec"])
        except (TypeError, ValueError):
            duration = None
        assert duration is not None and duration >= 0, (
            f"expected a real, non-negative numeric duration_sec for "
            f"{fresh_pdf.name}, got {row['duration_sec']!r}"
        )
