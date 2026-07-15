"""Outer acceptance test for issue #33, slice 01 (xref-detect).

Locked behavioral contract (DEC-1) -- do not edit once committed red.

Given a fixture source with prose chunks and classified artifacts, and
      AXIAL_LLM_PROVIDER=stub canned to reference one artifact
When  the user runs `axial xref <fixture>`
Then  it exits 0 and emits the detected (chunk_id, artifact_id) reference
      pairs as JSON
And   a referenced artifact_id not among the source's artifacts produces no
      pair (no dangling link)
And   a source with no detected references emits an empty pair list without
      error

See specs/PRODUCT.md section 5 stage 7 ("Cross-reference pass. Detect prose->
artifact references ('as Table 3 shows') and write bidirectional links into
both sides' frontmatter... Output: vault notes ... with backlinks."), section
7.2 ("Chunk-level: ... `artifact_refs`" / "Artifact notes carry: ... `cited_by`
back-references to prose chunks."), and section 8 P0-7 ("Prose->artifact
references produce bidirectional links in both notes' frontmatter." / "Runs
after both chunking and artifact classification have completed.") for the
source of truth. Writing those bidirectional links into vault notes'
frontmatter is slice 02 (per the slice plan's "Out of scope for this
slice"); this slice's contract ends at stdout, emitting the detected
`(chunk_id, artifact_id)` pairs only -- proving detection and dangling-link
filtering, not persistence.

Fixture reuse: tests/fixtures/extract/prose_and_table.pdf (see
tests/test_extract.py / tests/test_artifacts.py / tests/test_chunk.py) is a
two-section fixture -- "Introduction" (two paragraphs, then one artifact
node) followed by "Discussion" (two paragraphs, no artifact) -- already
proven (by tests/test_artifacts.py) to carry exactly one artifact node, and
(by tests/test_chunk.py's stub-chunking path) to yield at least one prose
chunk per section with body text. No new fixture is needed: this one already
supplies everything the xref acceptance criterion needs -- real chunks and a
real, singular artifact to reference (or dangle against).

Seam decision 1 -- extending the stub dispatch to a new pass, pass_name="xref"
-----------------------------------------------------------------------
src/axial/llm.py already dispatches StubLLMClient/RecordLLMClient's canned
response by pass_name for three passes ("chunk", "tag", "artifacts"; see
tests/test_chunk.py's seam decision 1 and tests/test_artifacts.py's seam
decision 1 for the collisions those already resolved). The slice plan locks
that the xref detection call is made "one LLM call per chunk
(pass_name="xref"), given the chunk text and the source's artifact list" --
a FOURTH pass sharing the same stub. This test does not dictate the dispatch
mechanism, nor the raw wire JSON shape the stub replies with -- it only
requires, behaviorally, that AXIAL_LLM_PROVIDER=stub configured for
`axial xref <fixture>` yields a response the xref pass can parse into a
(possibly empty) list of referenced artifact ids per chunk. Implementing
that fourth-pass response is this test's whole point for the
happy/empty/dangling paths, exactly as slice-05's chunk-shaped response was
for tests/test_chunk.py and the artifact-shaped response was for
tests/test_artifacts.py.

Seam decision 2 -- driving detected/dangling/empty references: a NEW env
var, AXIAL_STUB_XREF_TARGET
-----------------------------------------------------------------------
The acceptance criterion needs the stub to be canned, on demand, to
reference: (a) a real artifact id (happy path), (b) an id absent from the
source's actual artifacts (dangling-link path), or (c) nothing at all (empty
path) -- deterministically, without needing a real model to comply. Mirroring
tests/test_artifacts.py's AXIAL_STUB_ARTIFACT_ROLE seam (itself mirroring
AXIAL_FORCE_DOCLING_FAILURE in src/axial/extract.py), this test locks a new
environment variable, AXIAL_STUB_XREF_TARGET:

    unset / ""     -> the stub's pass_name="xref" response references NO
                       artifact for any chunk (the empty/no-references case).
                       This is the default.
    set, e.g. "S"  -> the stub's pass_name="xref" response references
                       EXACTLY the literal string S (valid or not) for EVERY
                       chunk-level xref call in the run. Setting S to a real,
                       discovered artifact_id drives the happy path (every
                       known chunk ends up paired with S); setting S to a
                       syntactically artifact-id-shaped but nonexistent
                       string drives the dangling-link path (no pair is
                       produced for any chunk, because S is not among the
                       source's real artifacts). Selecting this env var
                       without AXIAL_LLM_PROVIDER=stub is not exercised by
                       this test (left to the implementer).

This test never asserts what the raw stub response text looks like (no
JSON-shape lock on the model-facing wire format) -- only the env var's
black-box effect on the parsed, filtered (chunk_id, artifact_id) pairs that
end up on stdout. This keeps the implementer free to choose the internal
response envelope (e.g. {"referenced_artifact_ids": [...]} vs.
{"artifacts": [...]} vs. something else) exactly as
tests/test_artifacts.py's seam decision 2 left the raw JSON keys unlocked.

The dangling-link target this test picks, f"{source_id}_art_999" (see
_dangling_artifact_id below), deliberately SHARES the real prefix and
general shape locked by tests/test_artifacts.py's seam decision 3
(<source_id>_art_<order>) while naming an order ("999") that cannot be
among this fixture's real artifact nodes (a small, real extraction tree
whose dotted orders are single/double-digit at most -- see
tests/test_artifacts.py's own inspection). This proves the no-dangling-link
filter checks actual membership in the source's real artifact-id set, not
merely a prefix/shape heuristic that a superficially-plausible id could slip
past.

Seam decision 3 -- arranging real chunk_ids and a real artifact_id: computed,
never hardcoded
-----------------------------------------------------------------------
Neither chunk_ids nor this fixture's artifact_id are fixed values this test
could safely hardcode (tests/test_chunk.py deliberately does not pin an
exact chunk count/text, and tests/test_artifacts.py deliberately does not
pin an exact order suffix). So, mirroring both of those tests' "compute,
don't hardcode" approach, this test discovers the real facts it needs by
actually running the already-locked, already-green upstream commands first:
  - `axial envelope <fixture>` (stub) to produce the stored envelope
    `axial chunk` requires (chunk.py never recomputes one -- PRD section 10).
  - `axial chunk <fixture>` (stub) to discover the exact set of real
    chunk_ids this fixture yields.
  - `axial artifacts <fixture>` (stub, default role) to discover this
    fixture's one real artifact_id.
None of these three arrange calls exercises the new xref subcommand -- they
are all pre-existing, already-green behavior reused as fixtures for this
test, exactly as tests/test_chunk.py reuses `axial envelope` as its own
arrange step.

Seam decision 4 -- cross-pass chunk_id consistency is part of the contract
-----------------------------------------------------------------------
The slice plan's own INVEST "Independent" bullet states the xref pass
"consumes chunk records (via run_chunk)" -- i.e. it is not free to invent a
second, parallel chunk-identification scheme. This test holds the
implementer to that: the chunk_id values found in `axial xref`'s emitted
pairs must be drawn from the very same chunk_id set `axial chunk` produces
for the identical fixture, not a similarly-shaped but independent id space.
This is what makes the emitted pairs actually usable as a graph over the
system's real, addressable chunk records (the whole point of P0-7), rather
than merely shape-valid strings that happen to look like a chunk_id.

Seam decision 5 -- stdout shape: locking field names, leaving the envelope
shape lenient
-----------------------------------------------------------------------
As in tests/test_chunk.py's seam decision 4 and tests/test_artifacts.py's
seam decision 5, no source of truth dictates an exact stdout envelope shape,
so this test's parsing helper accepts any of: a bare top-level JSON array, a
JSON object with a top-level "pairs" array, or newline-delimited JSON (one
pair object per line). "pairs" is chosen as the wrapping key name (when an
object is used) as the smallest, least implementation-committal name for
"the list of reference pairs" -- mirroring "chunks"/"artifacts" naming.
Each pair record locks exactly the two field names the acceptance criterion
itself already names: "chunk_id" and "artifact_id" (PRD section 5 stage 7's
"(chunk_id -> artifact_id) link pairs" language, reproduced in the slice
plan's Goal section) -- no naming choice was needed here, unlike
tests/test_chunk.py's "section" or tests/test_artifacts.py's "section".

Test hygiene: this slice writes nothing to disk on its own account beyond
the stored envelope the `axial envelope` arrange step produces (records go
to stdout only -- writing backlinks into vault notes is slice 02's job), so
only that envelope file is cleaned up (mirrors tests/test_chunk.py's
clean_envelopes fixture). The one other thing this test's arrange steps
write -- the pre-placed tree fixture under data/trees/, see below -- is
isolated by tests/conftest.py's shared, content-snapshot-based
`_isolate_persisted_tree_and_envelope_state` autouse fixture.

Arrange-mechanism change (issue #45, tree-cache) -- no behavioral assertion
changed
-----------------------------------------------------------------------
This test's PURPOSE is xref detection -- it CONSUMES the stored envelope,
this fixture's chunk records, and its artifact records, never asserting
anything about extraction/tree shape itself (that is
tests/test_extract.py's contract). The arrange steps' `axial envelope`/
`axial chunk`/`axial artifacts` calls all internally call `axial.extract.
extract` for the same source, which -- per the now-locked tree-persist
contract (tests/test_tree_persist.py, PRD §7.4) -- reuses a persisted tree
verbatim at data/trees/<source_id>.json instead of re-running docling. So
`_arrange_stored_envelope` below now pre-places the committed REAL tree
fixture (tests/fixtures/extract/prose_and_table_tree.json -- exactly `axial
extract`'s own output for this fixture, see that directory's _generate.py
for the regeneration recipe) once, before the first of those calls; every
later call for the same source_id reuses that same cached tree. Every
existing assertion is unchanged.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from axial.chunk import run_chunk_recursive
from axial.envelope import compute_source_id

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "extract"
ENVELOPES_DIR = REPO_ROOT / "data" / "envelopes"
TREES_DIR = REPO_ROOT / "data" / "trees"

PROSE_AND_TABLE_PDF = FIXTURES_DIR / "prose_and_table.pdf"
PROSE_AND_TABLE_TREE_FIXTURE = FIXTURES_DIR / "prose_and_table_tree.json"

PROVIDER_ENV_VAR = "AXIAL_LLM_PROVIDER"
# New seam this test relies on -- see module docstring, seam decision 2.
STUB_XREF_TARGET_ENV_VAR = "AXIAL_STUB_XREF_TARGET"

# argparse's fallback error for an as-yet-nonexistent subcommand, e.g.
# "axial: error: argument command: invalid choice: 'xref' (choose from
# 'schema', 'intake', 'extract', 'envelope', 'chunk', 'tag', 'artifacts',
# 'vault')". Any of these substrings in the combined output means the target
# subcommand's logic was never actually exercised -- the process failed
# before real behavior ran. Reject that generic failure mode explicitly so
# this test can only pass once real `xref` behavior exists.
ARGPARSE_FALLBACK_MARKERS = (
    "invalid choice",
    "unrecognized arguments",
)


def _run_axial(
    command: str, *args: str, extra_env: dict[str, str] | None = None
) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env[PROVIDER_ENV_VAR] = "stub"
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["uv", "run", "axial", command, *args],
        cwd=REPO_ROOT,
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


def _existing_envelope_files() -> set[Path]:
    if not ENVELOPES_DIR.exists():
        return set()
    return set(ENVELOPES_DIR.glob("*.json"))


def _parse_json_records(stdout: str, wrapper_key: str, noun: str) -> list[dict]:
    """Parse records from stdout, tolerating any of the three stdout shapes
    this test module locks (see module docstring, seam decision 5): a bare
    JSON array, a JSON object with a wrapper_key array, or
    newline-delimited JSON (one record per line)."""
    stripped = stdout.strip()

    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        data = None

    if data is not None:
        if isinstance(data, dict):
            assert wrapper_key in data, (
                f"expected a top-level {wrapper_key!r} key when {noun} stdout "
                f"is a JSON object, got keys: {sorted(data.keys())}; stdout: {stdout!r}"
            )
            records = data[wrapper_key]
        else:
            records = data
        assert isinstance(records, list), (
            f"expected {noun} records to be a JSON array (bare, or under "
            f"{wrapper_key!r}), got {type(records).__name__}: {records!r}"
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
                f"expected {noun} stdout to be either one parseable JSON "
                f"document (a bare array, or an object with a top-level "
                f"{wrapper_key!r} array) or newline-delimited JSON (one "
                f"{noun} record object per line); line {line!r} failed to "
                f"parse ({exc}). Full stdout: {stdout!r}"
            ) from None
    return records


def _parse_artifact_records(stdout: str) -> list[dict]:
    return _parse_json_records(stdout, "artifacts", "artifact")


def _parse_xref_pairs(stdout: str) -> list[dict]:
    return _parse_json_records(stdout, "pairs", "xref pair")


@pytest.fixture
def clean_envelopes():
    """Snapshot data/envelopes/*.json before the test and delete any file
    the test caused to appear, so runs stay idempotent and the repo is never
    polluted by a real e2e-run artifact (mirrors tests/test_chunk.py)."""
    before = _existing_envelope_files()
    yield
    after = _existing_envelope_files()
    for created in after - before:
        created.unlink()


def _place_tree_fixture(source_pdf: Path, tree_fixture_path: Path) -> Path:
    """Pre-place the committed REAL tree fixture at
    data/trees/<source_id>.json (source_id via
    axial.envelope.compute_source_id) so `axial.extract.extract` reuses it
    verbatim instead of running docling (see module docstring, "Arrange-
    mechanism change"). Returns the tree path."""
    source_id = compute_source_id(source_pdf)
    tree_path = TREES_DIR / f"{source_id}.json"
    tree_path.parent.mkdir(parents=True, exist_ok=True)
    tree_path.write_bytes(tree_fixture_path.read_bytes())
    return tree_path


def _arrange_stored_envelope() -> None:
    """Pre-place the real tree fixture, then run `axial envelope` with the
    stub provider so a stored envelope exists on disk before chunking --
    `axial chunk` (and, per the slice plan, `axial xref` via run_chunk)
    never recomputes one (PRD section 10)."""
    _place_tree_fixture(PROSE_AND_TABLE_PDF, PROSE_AND_TABLE_TREE_FIXTURE)
    result = _run_axial("envelope", str(PROSE_AND_TABLE_PDF))
    _assert_not_argparse_fallback(result, "envelope")
    assert result.returncode == 0, (
        f"arrange step failed: expected exit code 0 for `axial envelope` on "
        f"the fixture with the stub LLM provider, got {result.returncode}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )


def _arrange_known_chunk_ids() -> set[str]:
    """Write the real, on-disk chunk artifact for this fixture IN-PROCESS
    (`axial.chunk.run_chunk_recursive`, the sole chunking mechanism)
    and return the exact set of chunk_ids it produced -- see module
    docstring, seam decision 3.

    Issue #154 slice 04: `axial xref` no longer computes chunks itself --
    it reads `data/chunks/<source_id>.jsonl` via `axial.chunk.read_chunks`
    (PRD §7.7) instead. So this arrange step now IS the thing that writes
    that artifact (cwd already REPO_ROOT, matching `_run_axial`'s own fixed
    `cwd=REPO_ROOT`, so the default `data/chunks/` resolution the CLI
    subprocess reads from and the one this in-process call writes to are the
    exact same path) -- the returned chunk_id set is simultaneously "the
    fixture's real chunk_ids" (seam decision 3) and "what `axial xref` will
    actually read" (seam decision 4)."""
    records = run_chunk_recursive(PROSE_AND_TABLE_PDF)
    chunk_ids = {r.get("chunk_id") for r in records}
    assert chunk_ids and all(isinstance(cid, str) and cid for cid in chunk_ids), (
        f"arrange step failed: expected run_chunk_recursive to write at least "
        f"one chunk record with a non-empty chunk_id, got records: {records!r}"
    )
    return chunk_ids


def _arrange_known_artifact_id() -> str:
    """Run `axial artifacts` (already green, per tests/test_artifacts.py) to
    discover this fixture's one real artifact_id -- see module docstring,
    seam decision 3."""
    result = _run_axial("artifacts", str(PROSE_AND_TABLE_PDF))
    _assert_not_argparse_fallback(result, "artifacts")
    assert result.returncode == 0, (
        f"arrange step failed: expected exit code 0 for `axial artifacts` "
        f"on the fixture with the stub LLM provider, got {result.returncode}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    records = _parse_artifact_records(result.stdout)
    assert len(records) == 1, (
        f"arrange step failed: expected exactly one artifact record from "
        f"this fixture (see tests/test_artifacts.py), got {len(records)}: "
        f"{records!r}"
    )
    artifact_id = records[0].get("artifact_id")
    assert isinstance(artifact_id, str) and artifact_id, (
        f"arrange step failed: expected the artifact record to carry a "
        f"non-empty 'artifact_id', got {artifact_id!r} (record: {records[0]!r})"
    )
    return artifact_id


def _dangling_artifact_id(real_artifact_id: str) -> str:
    """A syntactically artifact-id-shaped id that cannot be among this
    fixture's real artifacts -- see module docstring, seam decision 2."""
    source_id = real_artifact_id.rsplit("_art_", 1)[0]
    return f"{source_id}_art_999"


def test_xref_detects_pairs_filters_dangling_links_and_handles_the_empty_case(
    clean_envelopes,
):
    _arrange_stored_envelope()
    known_chunk_ids = _arrange_known_chunk_ids()
    known_artifact_id = _arrange_known_artifact_id()
    dangling_artifact_id = _dangling_artifact_id(known_artifact_id)
    assert dangling_artifact_id != known_artifact_id

    # --- Then: a source with no detected references emits an empty pair
    # list without error (AXIAL_STUB_XREF_TARGET unset -- the default) ---
    empty_result = _run_axial("xref", str(PROSE_AND_TABLE_PDF))
    _assert_not_argparse_fallback(empty_result, "xref")
    assert empty_result.returncode == 0, (
        f"expected exit code 0 for `axial xref` when the stub detects no "
        f"references, got {empty_result.returncode}\n"
        f"stdout: {empty_result.stdout!r}\nstderr: {empty_result.stderr!r}"
    )
    empty_pairs = _parse_xref_pairs(empty_result.stdout)
    assert empty_pairs == [], (
        f"expected an empty pair list when no references are detected (PRD "
        f"section 5 stage 7 / slice goal), got {empty_pairs!r}; stdout: "
        f"{empty_result.stdout!r}"
    )

    # --- Then: it exits 0 and emits the detected (chunk_id, artifact_id)
    # pairs as JSON (AXIAL_STUB_XREF_TARGET set to a REAL artifact_id -- the
    # stub references it from every chunk-level xref call) ---
    happy_result = _run_axial(
        "xref",
        str(PROSE_AND_TABLE_PDF),
        extra_env={STUB_XREF_TARGET_ENV_VAR: known_artifact_id},
    )
    _assert_not_argparse_fallback(happy_result, "xref")
    assert happy_result.returncode == 0, (
        f"expected exit code 0 for `axial xref` on a fixture with prose "
        f"chunks and classified artifacts, with the stub canned to "
        f"reference one real artifact, got {happy_result.returncode}\n"
        f"stdout: {happy_result.stdout!r}\nstderr: {happy_result.stderr!r}"
    )
    happy_pairs = _parse_xref_pairs(happy_result.stdout)
    assert happy_pairs, (
        f"expected at least one (chunk_id, artifact_id) pair when the stub "
        f"is canned to reference a real artifact from every chunk, got none; "
        f"stdout: {happy_result.stdout!r}"
    )

    seen_chunk_ids: set[str] = set()
    for pair in happy_pairs:
        assert isinstance(pair, dict), (
            f"expected each xref pair to be a JSON object with 'chunk_id' "
            f"and 'artifact_id' keys, got {type(pair).__name__}: {pair!r}"
        )
        chunk_id = pair.get("chunk_id")
        artifact_id = pair.get("artifact_id")
        assert chunk_id in known_chunk_ids, (
            f"expected every emitted pair's chunk_id to be drawn from this "
            f"fixture's real chunk_id set (the same on-disk chunk artifact "
            f"read via axial.chunk.read_chunks the xref pass itself "
            f"consumes, per the slice plan's INVEST 'Independent' bullet -- "
            f"see module docstring, seam decision 4), got "
            f"chunk_id={chunk_id!r} which is not "
            f"among the known chunk_ids {sorted(known_chunk_ids)}; full "
            f"pair: {pair!r}"
        )
        assert artifact_id == known_artifact_id, (
            f"expected every emitted pair's artifact_id to be the one real "
            f"artifact_id the stub was canned to reference "
            f"({known_artifact_id!r}), got {artifact_id!r} (full pair: {pair!r})"
        )
        seen_chunk_ids.add(chunk_id)

    assert seen_chunk_ids == known_chunk_ids, (
        f"expected every known chunk (the stub references the target "
        f"artifact from every chunk-level xref call -- see module "
        f"docstring, seam decision 2) to produce exactly one pair, got "
        f"pairs for chunk_ids {sorted(seen_chunk_ids)} but expected all of "
        f"{sorted(known_chunk_ids)}"
    )

    # --- And: a referenced artifact_id not among the source's artifacts
    # produces no pair -- no dangling link (AXIAL_STUB_XREF_TARGET set to a
    # syntactically-plausible but nonexistent artifact_id) ---
    dangling_result = _run_axial(
        "xref",
        str(PROSE_AND_TABLE_PDF),
        extra_env={STUB_XREF_TARGET_ENV_VAR: dangling_artifact_id},
    )
    _assert_not_argparse_fallback(dangling_result, "xref")
    assert dangling_result.returncode == 0, (
        f"expected exit code 0 for `axial xref` even when the stub "
        f"references an artifact_id absent from the source's real "
        f"artifacts (a dangling link must be silently filtered, not an "
        f"error -- PRD section 5 stage 7), got {dangling_result.returncode}\n"
        f"stdout: {dangling_result.stdout!r}\nstderr: {dangling_result.stderr!r}"
    )
    dangling_pairs = _parse_xref_pairs(dangling_result.stdout)
    assert dangling_pairs == [], (
        f"expected NO pair when the stub's referenced artifact_id "
        f"({dangling_artifact_id!r}) is not among the source's real "
        f"artifacts ({known_artifact_id!r}) -- no dangling link (PRD "
        f"section 5 stage 7, section 8 P0-7) -- got {dangling_pairs!r}; "
        f"stdout: {dangling_result.stdout!r}"
    )
