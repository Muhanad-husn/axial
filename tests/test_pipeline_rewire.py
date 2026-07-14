"""Outer acceptance test for issue #154, slice 04 of the chunk-redesign
subproject (charter #148): downstream passes consume the on-disk chunk
artifact instead of calling the retired LLM-echo chunker.

Locked behavioral contract (DEC-1) -- do not edit once committed red.

```gherkin
Given a source with data/chunks/<source_id>.jsonl already written by `axial
      chunk`
When  the user runs the downstream passes (tag, artifacts, xref, vault) on
      that source
Then  each pass reads chunks from data/chunks/<source_id>.jsonl (the
      artifact's records flow through to their output) and makes no LLM
      call to (re)chunk
And   the pipeline makes zero calls into the removed LLM-echo chunk path
And   running a downstream pass with no chunk artifact present fails with a
      clear message telling the operator to run `axial chunk` first (no
      silent re-derivation)
```

See specs/PRODUCT.md §7.7 (on-disk chunk artifact) and §8 P0-4b ("Downstream
tag, artifact, cross-reference, and vault stages consume the on-disk chunk
artifact (§7.7)."), and plans/chunk-redesign/04-pipeline-rewire.md (this
slice's plan, acceptance criterion at lines 38-46) for the source of truth.

Scope note -- why `artifacts` has no dedicated test here
-----------------------------------------------------------------------
The slice plan's own INVEST "Independent" note says the `artifacts` pass'
own classification is "unaffected by chunk source" -- it walks the
extraction tree directly for artifact (table/figure) nodes and never reads a
chunk record at all (verified by reading src/axial/artifacts.py: no
chunk.py import, no chunk_id in its own record shape). This test therefore
covers the three passes that DO consume chunk records today via
`axial.chunk.run_chunk` -- `tag`, `xref`, and `vault write` (which composes
`tag` and `xref` internally) -- exactly the call sites the plan's own
"Notes" section enumerates for this slice.

Seam decision 1 -- proving "reads the artifact, not a recompute": a SENTINEL
chunk record only the disk artifact could produce
-----------------------------------------------------------------------
Each test pre-writes a real fixture's stored envelope AND persisted tree
(so the OLD `run_chunk` mechanism, if a pass still calls it, runs to
completion rather than erroring out on a missing prerequisite -- keeping
this test's failure mode unambiguous: a mismatch in the FLOWED-THROUGH
CONTENT, not an unrelated missing-envelope error) -- and ALSO pre-writes
`data/chunks/<source_id>.jsonl` with exactly ONE hand-fabricated "sentinel"
chunk record whose `chunk_id`/`section`/`text` cannot be produced by
chunking the fixture's real tree (the stub embedder/LLM never emits this
exact wording, and the real tree carries different section headings). If a
downstream pass's output carries this sentinel's chunk_id/section/chunk_text
verbatim, it can only have come from reading the on-disk artifact -- never
from recomputing chunk boundaries against the real tree. Conversely, if a
pass still calls the old `run_chunk` mechanism today, its output reflects
the REAL tree's sections (multiple canned stub chunks, none matching the
sentinel), so this assertion is a genuine, non-tautological proof in both
directions.

Seam decision 2 -- proving "no LLM call to (re)chunk": the `record` provider
plus the chunk-pass prompt's own distinctive wording
-----------------------------------------------------------------------
`AXIAL_LLM_PROVIDER=record` (`axial.llm.RecordLLMClient`) appends every raw
prompt any pass sends to `AXIAL_LLM_RECORD_PATH`, one JSON-encoded string per
line, while still answering with the same canned responses `stub` would
(so every pass under test still completes normally). This test counts how
many recorded prompts contain `CHUNK_PROMPT_MARKER` -- a substring drawn
verbatim from `axial.chunk._CHUNK_PROMPT_TEMPLATE`'s own wording
("argumentative chunk boundaries"), which only a chunk-pass prompt can ever
contain (mirrors the exact same marker already locked by
tests/test_chunk_resilience.py, tests/test_tag_shape_coercion.py,
tests/test_tag_vocab_reask.py, and tests/test_vault_resume.py for the same
purpose) -- and asserts that count is exactly zero. A companion count for
the pass actually under test's OWN marker (`TAG_PROMPT_MARKER` /
`XREF_PROMPT_MARKER`, also reused verbatim from those same locked tests) is
asserted to be non-zero, so a trivially-vacuous "recorded nothing at all"
run (e.g. a crash before any LLM call) cannot masquerade as a pass.

Seam decision 3 -- "zero calls into the removed echo path" is the conjunction
of seam decisions 1 and 2, not a separate mechanism
-----------------------------------------------------------------------
`axial.chunk.run_chunk` (the retired mechanism) is a text-generating-LLM
call issuing exactly the chunk-pass prompt this test already fingerprints
(seam decision 2), driven by the real persisted tree this test also already
arranges (seam decision 1). Any invocation of it is therefore caught by
BOTH assertions at once: the sentinel would never flow through unmodified
(seam decision 1 fails), and a chunk-pass prompt would appear in the record
transcript (seam decision 2 fails). This test does not additionally
monkeypatch `axial.chunk.run_chunk` to raise, since the implementer is
expected to DELETE that function entirely in this slice (plan: "the old
LLM-echo chunker ... is removed") -- patching a symbol due to be deleted
would only ever assert an implementation detail, not a behavior.

Seam decision 4 -- the missing-artifact error path is proven against a
run that is ARRANGED TO SUCCEED under today's (pre-slice) mechanism
-----------------------------------------------------------------------
For the "no chunk artifact present" scenario, this test still arranges a
real stored envelope AND a real persisted tree for the fixture -- exactly
the two prerequisites the OLD `run_chunk` mechanism needs to complete
successfully -- then runs the downstream pass WITHOUT ever writing
`data/chunks/<source_id>.jsonl`. Today, with no rewire yet done, the pass
recomputes chunks via `run_chunk` regardless and exits 0 with real output:
exactly the "silent re-derivation" the Gherkin's last line forbids. This
makes the red failure direct and on-point (a bare `assert returncode != 0`
that trips because today's exit code actually is 0), rather than an
accidental failure from an unrelated missing prerequisite.

Fixture reuse: tests/fixtures/envelope/thesis_paper.pdf (+ its committed
tree fixture) for `tag` and `vault write` (mirrors tests/test_tag.py /
tests/test_vault_write.py); tests/fixtures/extract/prose_and_table.pdf (+
its committed tree fixture) for `xref`, since xref's dangling-link-free
happy path needs a fixture with a real artifact to reference (mirrors
tests/test_xref.py). No new fixtures are needed.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from axial.envelope import compute_source_id

REPO_ROOT = Path(__file__).resolve().parent.parent

ENVELOPE_FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "envelope"
EXTRACT_FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "extract"

THESIS_PAPER_PDF = ENVELOPE_FIXTURES_DIR / "thesis_paper.pdf"
THESIS_PAPER_TREE_FIXTURE = ENVELOPE_FIXTURES_DIR / "thesis_paper_tree.json"

PROSE_AND_TABLE_PDF = EXTRACT_FIXTURES_DIR / "prose_and_table.pdf"
PROSE_AND_TABLE_TREE_FIXTURE = EXTRACT_FIXTURES_DIR / "prose_and_table_tree.json"

PROVIDER_ENV_VAR = "AXIAL_LLM_PROVIDER"
RECORD_PATH_ENV_VAR = "AXIAL_LLM_RECORD_PATH"
STUB_XREF_TARGET_ENV_VAR = "AXIAL_STUB_XREF_TARGET"

# Marker substrings drawn verbatim from each pass's own current prompt
# template (see module docstring, seam decision 2) -- reused verbatim from
# the same markers already locked in tests/test_chunk_resilience.py,
# tests/test_tag_shape_coercion.py, tests/test_tag_vocab_reask.py, and
# tests/test_vault_resume.py.
CHUNK_PROMPT_MARKER = "argumentative chunk boundaries"
TAG_PROMPT_MARKER = "assigning tags for the CHUNK below"
XREF_PROMPT_MARKER = "the source's known artifacts"

# A sentinel chunk record only the pre-written disk artifact could ever
# produce -- its wording matches no fixture's real section text and no
# stub-canned chunk response (see module docstring, seam decision 1).
SENTINEL_SECTION = "Sentinel Section (Disk Artifact Only)"
SENTINEL_SECTION_ORDER = "99"
SENTINEL_TEXT = (
    "This sentinel prose text is planted directly into the on-disk chunk "
    "artifact by tests/test_pipeline_rewire.py and does not appear anywhere "
    "in any fixture source's own extracted tree or in any stub-canned chunk "
    "response. If it flows through to a downstream pass's own output "
    "verbatim, that pass read data/chunks/<source_id>.jsonl (PRD section "
    "7.7) rather than recomputing chunk boundaries itself."
)

# argparse's fallback error for an as-yet-nonexistent subcommand/flag --
# reused verbatim from every other outer test's identical guard.
ARGPARSE_FALLBACK_MARKERS = (
    "invalid choice",
    "unrecognized arguments",
)


def _trees_dir(root: Path) -> Path:
    return root / "data" / "trees"


def _envelopes_dir(root: Path) -> Path:
    return root / "data" / "envelopes"


def _chunks_dir(root: Path) -> Path:
    return root / "data" / "chunks"


def _prose_dir(root: Path) -> Path:
    return root / "data" / "vault" / "prose"


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


def _assert_not_argparse_fallback(result: subprocess.CompletedProcess, command: str) -> None:
    combined = result.stdout + result.stderr
    for marker in ARGPARSE_FALLBACK_MARKERS:
        assert marker not in combined, (
            f"expected a real `{command}` behavior path, not an argparse "
            f"fallback (found {marker!r}) -- this means the `{command}` "
            f"subcommand does not exist yet or was never reached:\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )


def _place_tree_fixture(source_path: Path, tree_fixture: Path, root: Path) -> Path:
    """Pre-place the committed REAL tree fixture at
    <root>/data/trees/<source_id>.json so `axial.extract.extract` reuses it
    verbatim instead of running docling (mirrors every other outer test's
    helper of the same name, e.g. tests/test_tag.py)."""
    source_id = compute_source_id(source_path)
    tree_path = _trees_dir(root) / f"{source_id}.json"
    tree_path.parent.mkdir(parents=True, exist_ok=True)
    tree_path.write_bytes(tree_fixture.read_bytes())
    return tree_path


def _existing_envelope_files(root: Path) -> set[Path]:
    envelopes_dir = _envelopes_dir(root)
    if not envelopes_dir.exists():
        return set()
    return set(envelopes_dir.glob("*.json"))


def _arrange_stored_envelope_and_tree(source_path: Path, tree_fixture: Path, root: Path) -> Path:
    """Pre-place the real tree fixture, then run `axial envelope` with the
    stub provider so a stored envelope also exists on disk -- the two
    prerequisites the OLD `run_chunk` mechanism needs to complete
    successfully (see module docstring, seam decisions 1 and 4). Returns the
    new envelope's path; asserts the arrange step itself succeeded."""
    _place_tree_fixture(source_path, tree_fixture, root)
    before_files = _existing_envelope_files(root)

    result = _run_axial(["envelope", str(source_path)], "stub", cwd=root)
    _assert_not_argparse_fallback(result, "envelope")
    assert result.returncode == 0, (
        f"arrange step failed: expected exit code 0 for `axial envelope` on "
        f"{source_path} with the stub LLM provider, got {result.returncode}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    new_files = _existing_envelope_files(root) - before_files
    assert len(new_files) == 1, (
        f"arrange step failed: expected exactly one new file under "
        f"{_envelopes_dir(root)} after `axial envelope`, got {len(new_files)}: "
        f"{sorted(new_files)}\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    return next(iter(new_files))


def _write_sentinel_chunk_artifact(source_id: str, root: Path) -> dict:
    """Pre-write data/chunks/<source_id>.jsonl carrying exactly ONE
    hand-fabricated sentinel chunk record (see module docstring, seam
    decision 1). Returns that record."""
    record = {
        "chunk_id": f"{source_id}_{SENTINEL_SECTION_ORDER}_sentinel-chunk-from-disk-artifact_001",
        "section": SENTINEL_SECTION,
        "section_order": SENTINEL_SECTION_ORDER,
        "text": SENTINEL_TEXT,
    }
    chunks_dir = _chunks_dir(root)
    chunks_dir.mkdir(parents=True, exist_ok=True)
    (chunks_dir / f"{source_id}.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
    return record


def _assert_no_chunk_artifact_present(source_id: str, root: Path) -> None:
    chunk_path = _chunks_dir(root) / f"{source_id}.jsonl"
    assert not chunk_path.exists(), (
        f"test setup invariant broken: {chunk_path} must not already exist, "
        f"or this test would not actually be exercising the missing-artifact "
        f"path"
    )


def _count_marker_occurrences(record_path: Path, marker: str) -> int:
    """Count how many recorded prompts (one JSON-encoded string per line,
    written by `axial.llm.RecordLLMClient`) contain `marker` (see module
    docstring, seam decision 2). Mirrors tests/test_vault_resume.py's helper
    of the same name exactly."""
    if not record_path.exists():
        return 0
    count = 0
    for line in record_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        prompt = json.loads(line)
        assert isinstance(prompt, str), (
            f"expected {record_path} to hold one JSON-encoded prompt string "
            f"per line (RecordLLMClient's own contract), got a "
            f"{type(prompt).__name__}: {prompt!r}"
        )
        if marker in prompt:
            count += 1
    return count


def _parse_json_records(stdout: str, wrapper_keys: tuple[str, ...], noun: str) -> list[dict]:
    """Parse output records from stdout, tolerating a bare JSON array, a
    JSON object with one of `wrapper_keys` as a top-level array, or
    newline-delimited JSON (one record per line) -- mirrors
    tests/test_tag.py's/tests/test_xref.py's identical parsing helper."""
    stripped = stdout.strip()

    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        data = None

    if data is not None:
        if isinstance(data, dict):
            found_key = next((key for key in wrapper_keys if key in data), None)
            assert found_key is not None, (
                f"expected a top-level key among {wrapper_keys} when {noun} "
                f"stdout is a JSON object, got keys: {sorted(data.keys())}; "
                f"stdout: {stdout!r}"
            )
            records = data[found_key]
        else:
            records = data
        assert isinstance(records, list), (
            f"expected {noun} records to be a JSON array (bare, or under "
            f"one of {wrapper_keys}), got {type(records).__name__}: {records!r}"
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
                f"document or newline-delimited JSON; line {line!r} failed "
                f"to parse ({exc}). Full stdout: {stdout!r}"
            ) from None
    return records


def _parse_tag_records(stdout: str) -> list[dict]:
    return _parse_json_records(stdout, ("records", "tags", "chunks"), "tag")


def _parse_xref_pairs(stdout: str) -> list[dict]:
    return _parse_json_records(stdout, ("pairs",), "xref pair")


def _arrange_known_artifact_id(source_path: Path, root: Path) -> str:
    """Run `axial artifacts` (unaffected by this slice -- see module
    docstring, "Scope note") to discover this fixture's one real
    artifact_id, needed to drive xref's happy path deterministically."""
    result = _run_axial(["artifacts", str(source_path)], "stub", cwd=root)
    _assert_not_argparse_fallback(result, "artifacts")
    assert result.returncode == 0, (
        f"arrange step failed: expected exit code 0 for `axial artifacts` "
        f"on {source_path} with the stub LLM provider, got "
        f"{result.returncode}\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    records = _parse_json_records(result.stdout, ("artifacts",), "artifact")
    assert len(records) == 1, (
        f"arrange step failed: expected exactly one artifact record from "
        f"this fixture (see tests/test_artifacts.py), got {len(records)}: {records!r}"
    )
    artifact_id = records[0].get("artifact_id")
    assert isinstance(artifact_id, str) and artifact_id, (
        f"arrange step failed: expected the artifact record to carry a "
        f"non-empty 'artifact_id', got {artifact_id!r} (record: {records[0]!r})"
    )
    return artifact_id


# ---------------------------------------------------------------------------
# Then: each pass reads chunks from the disk artifact and makes no chunk-
# pass LLM call (Gherkin lines 1-3).
# ---------------------------------------------------------------------------


def test_tag_reads_chunk_artifact_and_makes_no_chunk_pass_llm_call(tmp_path):
    _arrange_stored_envelope_and_tree(THESIS_PAPER_PDF, THESIS_PAPER_TREE_FIXTURE, REPO_ROOT)
    source_id = compute_source_id(THESIS_PAPER_PDF)
    sentinel = _write_sentinel_chunk_artifact(source_id, REPO_ROOT)

    record_path = tmp_path / "tag_prompts.jsonl"
    result = _run_axial(
        ["tag", str(THESIS_PAPER_PDF)],
        "record",
        cwd=REPO_ROOT,
        extra_env={RECORD_PATH_ENV_VAR: str(record_path)},
    )
    _assert_not_argparse_fallback(result, "tag")
    assert result.returncode == 0, (
        f"expected exit code 0 for `axial tag` on a fixture with a "
        f"pre-written data/chunks/<source_id>.jsonl artifact, got "
        f"{result.returncode}\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    tag_records = _parse_tag_records(result.stdout)
    assert len(tag_records) == 1, (
        f"expected exactly one tagged record -- the disk artifact's own "
        f"single sentinel chunk record (Gherkin: 'reads chunks from "
        f"data/chunks/<source_id>.jsonl') -- got {len(tag_records)}: "
        f"{tag_records!r}. More than one strongly suggests `axial tag` is "
        f"still recomputing chunk boundaries against the real tree instead "
        f"of reading the pre-written artifact."
    )
    record = tag_records[0]
    assert record.get("chunk_id") == sentinel["chunk_id"], (
        f"expected the tagged record's chunk_id to equal the disk "
        f"artifact's own sentinel chunk_id {sentinel['chunk_id']!r} "
        f"(Gherkin: 'the artifact's records flow through to their output'), "
        f"got {record.get('chunk_id')!r} (full record: {record!r})"
    )
    assert record.get("section") == sentinel["section"], (
        f"expected the tagged record's section to equal the disk "
        f"artifact's own sentinel section {sentinel['section']!r}, got "
        f"{record.get('section')!r} (full record: {record!r})"
    )
    assert record.get("chunk_text") == sentinel["text"], (
        f"expected the tagged record's chunk_text to equal the disk "
        f"artifact's own sentinel text verbatim, got "
        f"{record.get('chunk_text')!r} (full record: {record!r})"
    )

    chunk_calls = _count_marker_occurrences(record_path, CHUNK_PROMPT_MARKER)
    assert chunk_calls == 0, (
        f"expected ZERO recorded prompts containing the chunk-pass's own "
        f"distinctive wording ({CHUNK_PROMPT_MARKER!r}) -- Gherkin: 'makes "
        f"no LLM call to (re)chunk' / 'zero calls into the removed LLM-echo "
        f"chunk path' -- got {chunk_calls}. This means `axial tag` still "
        f"invoked the retired `axial.chunk.run_chunk` mechanism instead of "
        f"reading data/chunks/<source_id>.jsonl."
    )
    tag_calls = _count_marker_occurrences(record_path, TAG_PROMPT_MARKER)
    assert tag_calls >= 1, (
        f"expected at least one recorded prompt containing the tag-pass's "
        f"own distinctive wording ({TAG_PROMPT_MARKER!r}), got {tag_calls} "
        f"-- a zero count here would mean this test recorded no real "
        f"activity at all, making the chunk-call-count assertion above "
        f"vacuous"
    )


def test_xref_reads_chunk_artifact_and_makes_no_chunk_pass_llm_call(tmp_path):
    _arrange_stored_envelope_and_tree(PROSE_AND_TABLE_PDF, PROSE_AND_TABLE_TREE_FIXTURE, REPO_ROOT)
    known_artifact_id = _arrange_known_artifact_id(PROSE_AND_TABLE_PDF, REPO_ROOT)

    source_id = compute_source_id(PROSE_AND_TABLE_PDF)
    sentinel = _write_sentinel_chunk_artifact(source_id, REPO_ROOT)

    record_path = tmp_path / "xref_prompts.jsonl"
    result = _run_axial(
        ["xref", str(PROSE_AND_TABLE_PDF)],
        "record",
        cwd=REPO_ROOT,
        extra_env={
            RECORD_PATH_ENV_VAR: str(record_path),
            STUB_XREF_TARGET_ENV_VAR: known_artifact_id,
        },
    )
    _assert_not_argparse_fallback(result, "xref")
    assert result.returncode == 0, (
        f"expected exit code 0 for `axial xref` on a fixture with a "
        f"pre-written data/chunks/<source_id>.jsonl artifact, got "
        f"{result.returncode}\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    pairs = _parse_xref_pairs(result.stdout)
    assert len(pairs) == 1, (
        f"expected exactly one (chunk_id, artifact_id) pair -- the disk "
        f"artifact's own single sentinel chunk, referencing the one real "
        f"artifact the stub was canned to target for every chunk -- got "
        f"{len(pairs)}: {pairs!r}. More than one strongly suggests `axial "
        f"xref` is still recomputing chunk boundaries against the real tree "
        f"instead of reading the pre-written artifact."
    )
    pair = pairs[0]
    assert pair.get("chunk_id") == sentinel["chunk_id"], (
        f"expected the emitted pair's chunk_id to equal the disk "
        f"artifact's own sentinel chunk_id {sentinel['chunk_id']!r} "
        f"(Gherkin: 'the artifact's records flow through to their output'), "
        f"got {pair.get('chunk_id')!r} (full pair: {pair!r})"
    )
    assert pair.get("artifact_id") == known_artifact_id, (
        f"expected the emitted pair's artifact_id to equal the one real "
        f"artifact_id the stub was canned to reference ({known_artifact_id!r}), "
        f"got {pair.get('artifact_id')!r} (full pair: {pair!r})"
    )

    chunk_calls = _count_marker_occurrences(record_path, CHUNK_PROMPT_MARKER)
    assert chunk_calls == 0, (
        f"expected ZERO recorded prompts containing the chunk-pass's own "
        f"distinctive wording ({CHUNK_PROMPT_MARKER!r}) -- Gherkin: 'makes "
        f"no LLM call to (re)chunk' / 'zero calls into the removed LLM-echo "
        f"chunk path' -- got {chunk_calls}. This means `axial xref` still "
        f"invoked the retired `axial.chunk.run_chunk` mechanism instead of "
        f"reading data/chunks/<source_id>.jsonl."
    )
    xref_calls = _count_marker_occurrences(record_path, XREF_PROMPT_MARKER)
    assert xref_calls >= 1, (
        f"expected at least one recorded prompt containing the xref-pass's "
        f"own distinctive wording ({XREF_PROMPT_MARKER!r}), got {xref_calls} "
        f"-- a zero count here would mean this test recorded no real "
        f"activity at all, making the chunk-call-count assertion above "
        f"vacuous"
    )


def test_vault_write_reads_chunk_artifact_and_makes_no_chunk_pass_llm_call(
    isolated_vault_root, tmp_path
):
    root = isolated_vault_root
    _arrange_stored_envelope_and_tree(THESIS_PAPER_PDF, THESIS_PAPER_TREE_FIXTURE, root)
    source_id = compute_source_id(THESIS_PAPER_PDF)
    sentinel = _write_sentinel_chunk_artifact(source_id, root)

    record_path = tmp_path / "vault_prompts.jsonl"
    result = _run_axial(
        ["vault", "write", str(THESIS_PAPER_PDF)],
        "record",
        cwd=root,
        extra_env={RECORD_PATH_ENV_VAR: str(record_path)},
    )
    _assert_not_argparse_fallback(result, "vault write")
    assert result.returncode == 0, (
        f"expected exit code 0 for `axial vault write` on a fixture with a "
        f"pre-written data/chunks/<source_id>.jsonl artifact, got "
        f"{result.returncode}\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    prose_dir = _prose_dir(root)
    assert prose_dir.exists(), (
        f"expected `axial vault write` to create {prose_dir} and write at "
        f"least the sentinel chunk's prose note into it, but it does not "
        f"exist after a successful run"
    )
    prose_files = [p for p in prose_dir.iterdir() if p.is_file()]
    assert len(prose_files) == 1, (
        f"expected exactly one prose note -- the disk artifact's own single "
        f"sentinel chunk record -- got {len(prose_files)}: "
        f"{sorted(p.name for p in prose_files)}. More than one strongly "
        f"suggests `axial vault write` is still recomputing chunk "
        f"boundaries against the real tree instead of reading the "
        f"pre-written artifact."
    )

    note_path = prose_files[0]
    assert note_path.stem == sentinel["chunk_id"], (
        f"expected the sole prose note's filename stem to equal the disk "
        f"artifact's own sentinel chunk_id {sentinel['chunk_id']!r}, got "
        f"{note_path.stem!r}"
    )
    note_text = note_path.read_text(encoding="utf-8")
    assert sentinel["text"] in note_text, (
        f"expected {note_path} to carry the disk artifact's own sentinel "
        f"chunk text (Gherkin: 'the artifact's records flow through to "
        f"their output'), but it does not appear in the note's content:\n"
        f"{note_text[:1000]!r}"
    )

    chunk_calls = _count_marker_occurrences(record_path, CHUNK_PROMPT_MARKER)
    assert chunk_calls == 0, (
        f"expected ZERO recorded prompts containing the chunk-pass's own "
        f"distinctive wording ({CHUNK_PROMPT_MARKER!r}) -- Gherkin: 'makes "
        f"no LLM call to (re)chunk' / 'zero calls into the removed LLM-echo "
        f"chunk path' -- got {chunk_calls}. This means `axial vault write` "
        f"still invoked the retired `axial.chunk.run_chunk` mechanism "
        f"instead of reading data/chunks/<source_id>.jsonl."
    )
    tag_calls = _count_marker_occurrences(record_path, TAG_PROMPT_MARKER)
    assert tag_calls >= 1, (
        f"expected at least one recorded prompt containing the tag-pass's "
        f"own distinctive wording ({TAG_PROMPT_MARKER!r}), got {tag_calls} "
        f"-- a zero count here would mean this test recorded no real "
        f"activity at all, making the chunk-call-count assertion above "
        f"vacuous"
    )


# ---------------------------------------------------------------------------
# And: running a downstream pass with no chunk artifact present fails with a
# clear message telling the operator to run `axial chunk` first -- no
# silent re-derivation (Gherkin, last line).
# ---------------------------------------------------------------------------


def test_tag_with_missing_chunk_artifact_fails_clearly_without_silent_rederivation():
    _arrange_stored_envelope_and_tree(THESIS_PAPER_PDF, THESIS_PAPER_TREE_FIXTURE, REPO_ROOT)
    source_id = compute_source_id(THESIS_PAPER_PDF)
    _assert_no_chunk_artifact_present(source_id, REPO_ROOT)

    result = _run_axial(["tag", str(THESIS_PAPER_PDF)], "stub", cwd=REPO_ROOT)
    _assert_not_argparse_fallback(result, "tag")

    assert result.returncode != 0, (
        f"expected a non-zero exit code for `axial tag` when "
        f"data/chunks/<source_id>.jsonl does not exist yet, even though a "
        f"stored envelope and persisted tree DO exist (Gherkin: 'running a "
        f"downstream pass with no chunk artifact present fails with a "
        f"clear message ... no silent re-derivation'), got exit code 0 -- "
        f"this means the pass silently recomputed chunk boundaries instead "
        f"of refusing to run\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    combined = (result.stdout + result.stderr).lower()
    assert "axial chunk" in combined, (
        f"expected `axial tag`'s error message to tell the operator to run "
        f"`axial chunk` first (Gherkin: 'a clear message telling the "
        f"operator to run axial chunk first'), got combined output that "
        f"does not mention it:\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )


def test_xref_with_missing_chunk_artifact_fails_clearly_without_silent_rederivation():
    _arrange_stored_envelope_and_tree(PROSE_AND_TABLE_PDF, PROSE_AND_TABLE_TREE_FIXTURE, REPO_ROOT)
    source_id = compute_source_id(PROSE_AND_TABLE_PDF)
    _assert_no_chunk_artifact_present(source_id, REPO_ROOT)

    result = _run_axial(["xref", str(PROSE_AND_TABLE_PDF)], "stub", cwd=REPO_ROOT)
    _assert_not_argparse_fallback(result, "xref")

    assert result.returncode != 0, (
        f"expected a non-zero exit code for `axial xref` when "
        f"data/chunks/<source_id>.jsonl does not exist yet, even though a "
        f"stored envelope and persisted tree DO exist (Gherkin: 'running a "
        f"downstream pass with no chunk artifact present fails with a "
        f"clear message ... no silent re-derivation'), got exit code 0 -- "
        f"this means the pass silently recomputed chunk boundaries instead "
        f"of refusing to run\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    combined = (result.stdout + result.stderr).lower()
    assert "axial chunk" in combined, (
        f"expected `axial xref`'s error message to tell the operator to run "
        f"`axial chunk` first (Gherkin: 'a clear message telling the "
        f"operator to run axial chunk first'), got combined output that "
        f"does not mention it:\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )


def test_vault_write_with_missing_chunk_artifact_fails_clearly_without_silent_rederivation(
    isolated_vault_root,
):
    root = isolated_vault_root
    _arrange_stored_envelope_and_tree(THESIS_PAPER_PDF, THESIS_PAPER_TREE_FIXTURE, root)
    source_id = compute_source_id(THESIS_PAPER_PDF)
    _assert_no_chunk_artifact_present(source_id, root)

    result = _run_axial(["vault", "write", str(THESIS_PAPER_PDF)], "stub", cwd=root)
    _assert_not_argparse_fallback(result, "vault write")

    assert result.returncode != 0, (
        f"expected a non-zero exit code for `axial vault write` when "
        f"data/chunks/<source_id>.jsonl does not exist yet, even though a "
        f"stored envelope and persisted tree DO exist (Gherkin: 'running a "
        f"downstream pass with no chunk artifact present fails with a "
        f"clear message ... no silent re-derivation'), got exit code 0 -- "
        f"this means the pass silently recomputed chunk boundaries instead "
        f"of refusing to run\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    combined = (result.stdout + result.stderr).lower()
    assert "axial chunk" in combined, (
        f"expected `axial vault write`'s error message to tell the operator "
        f"to run `axial chunk` first (Gherkin: 'a clear message telling the "
        f"operator to run axial chunk first'), got combined output that "
        f"does not mention it:\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
