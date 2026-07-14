"""Outer acceptance test for issue #81 (per-chunk checkpoint/resume for the
chunk+tag passes inside `axial vault write`).

Locked behavioral contract (DEC-1) -- do not edit once committed red.

Given a source whose tag pass fails partway (stub provider scripted to fail
      at chunk N)
When  the user re-runs `axial vault write` with the provider now healthy
Then  the rerun makes no chunking LLM calls and tags only the chunks not
      already checkpointed
And   the vault receives one note per chunk, identical in content to a
      never-failed run
And   a source_id change (edited file) ignores all prior checkpoints

See issue #81's "Behavior" list (the spec, extending PRD §7.3/§7.4's
"no recompute" persist-and-reuse principle to the chunk/tag outputs) for the
five numbered contract points this test pins:

  1. Chunk-pass checkpoint: after the chunking pass produces a source's
     chunk records, persist them to `data/chunks/<source_id>.jsonl` (one
     record per line). A later run that finds this file reuses it and makes
     NO chunking LLM calls.
  2. Tag-pass checkpoint: persist each tagged record to
     `data/tags/<source_id>.jsonl` AS IT IS PRODUCED (append, one line per
     chunk). A later run skips any chunk_id already present there; tagging
     proceeds for the missing ones only.
  3. A mid-tag failure still surfaces exactly today's typed error (non-zero
     exit), but progress up to the failed chunk is on disk.
  4. When all chunks are tagged, vault write proceeds exactly as today.
  5. Whether `axial chunk`/`axial tag` (the standalone CLI passes) also read
     these checkpoints is explicitly left to test-author/implementer
     judgment, "stated in the outer test": THIS test locks `axial vault
     write` alone. It never invokes `axial chunk`/`axial tag` as the thing
     under test (only as an *arrange* step, exactly as
     tests/test_vault_write.py already does, to derive an independent
     expected chunk-id list) and asserts nothing about whether those two
     standalone subcommands themselves honor the checkpoints.

Seam decision 1 -- isolation (issue #68), reused unchanged
-----------------------------------------------------------------------
Exactly like tests/test_vault_write.py and tests/test_vault_xref.py, every
`axial` subprocess this test spawns runs with `cwd` set to an isolated
staging root (`isolated_vault_root`, or a hand-built second one for tests
that need two independent roots -- see seam decision 5) so `data/trees/`,
`data/envelopes/`, `data/vault/`, and the two new checkpoint directories
(`data/chunks/`, `data/tags/`) never alias the real, concurrently-written
`data/` tree.

Seam decision 2 -- the fail-at-chunk-N seam this test SPECIFIES
-----------------------------------------------------------------------
Neither `stub` nor `record` (src/axial/llm.py) can fail partway through a
run today: `StubLLMClient`/`RecordLLMClient` always return a well-formed
canned response, and the one existing tag-pass fault-injection seam
(`AXIAL_STUB_TAG_RESPONSE`) always substitutes a *raw string* for every tag
call uniformly -- it cannot let the first K calls succeed and the (K+1)th
fail. This test locks a new seam, precisely, for the implementer to build:

    AXIAL_STUB_TAG_FAIL_AT (env var, a positive base-10 integer string,
    1-indexed): when set, the Nth call any `LLMClient.complete()`
    implementation receives with `pass_name == axial.llm.TAG_PASS_NAME`,
    counted from the start of the CURRENT PROCESS (a fresh counter per
    `axial` subprocess invocation -- never persisted across processes),
    raises an `axial.llm.LLMError` subclass instead of returning a canned
    response. Every call before the Nth still returns the normal canned tag
    response; the counter is read/incremented at call time (mirroring the
    "read fresh from the environment on every call" convention the module
    docstring already establishes for `AXIAL_STUB_TAG_RESPONSE_ENV_VAR` and
    `AXIAL_STUB_ARTIFACT_ROLE_ENV_VAR`). Unset, empty, or non-positive means
    "never fail" (today's behavior, unchanged). This must be honored by the
    shared canned-response dispatch both `stub` and `record` delegate to, so
    either provider value can drive it -- this test only exercises it under
    `stub` (see test 1's arrange), but nothing about the seam is
    `stub`-specific.

    The raised exception must be a subclass of `axial.llm.LLMError` so it
    propagates through `axial.model_json.complete_json` (which never catches
    transport-level errors, only reparses malformed JSON) and is caught by
    `axial.tag.run_tag`'s existing `except (LLMError, httpx.HTTPError)` ->
    `LLMFailedError` -> `axial.vault.run_vault_write`'s existing
    `except TagError` -> `TaggingFailedError` -> the CLI's existing
    `except VaultError: print(f"error: {exc}", ...); return 1` path
    (src/axial/cli.py) -- i.e. it must surface as exactly today's typed
    "error: ..." / non-zero-exit contract (issue #81 point 3), never a bare
    traceback and never a new CLI-level branch.

This test asserts through the *outcome* of this seam (checkpoint files on
disk, process exit code, stderr) -- never by importing or asserting on any
particular Python exception class name, which would be an implementation
detail invisible across the CLI subprocess boundary anyway.

Seam decision 3 -- counting LLM calls through an ALREADY-EXISTING channel
-----------------------------------------------------------------------
This test never counts LLM calls by timing or by patching internals. It
reuses the `record` provider (`AXIAL_LLM_PROVIDER=record` +
`AXIAL_LLM_RECORD_PATH=<path>`, already implemented in src/axial/llm.py's
`RecordLLMClient`, already the seam tests/test_chunk.py locks for observing
an assembled prompt from a subprocess): every prompt any pass sends is
appended, JSON-encoded, one per line, to that file, *regardless of which
pass sent it*. Since the chunking pass's prompt template
(`axial.chunk._CHUNK_PROMPT_TEMPLATE`) and the tag pass's prompt template
(`axial.tag._MULTI_AXIS_TAG_PROMPT_TEMPLATE`) open with distinct, stable
wording, this test tells the two passes' calls apart in the recorded log by
matching each line against a marker substring drawn verbatim from that
pass's own already-committed prompt template:

  - chunk-pass calls: lines containing "argumentative chunk boundaries"
    (`_CHUNK_PROMPT_TEMPLATE`'s own opening sentence).
  - tag-pass calls: lines containing "assigning tags for the CHUNK below"
    (`_MULTI_AXIS_TAG_PROMPT_TEMPLATE`'s own opening sentence).

These are the two passes' *current* prompt wording, asserted here as the
observable proxy for "which pass called the LLM" -- exactly as
tests/test_vault_write.py's seam decision 2 already treats a fixture's own
deterministic chunk output as ground truth rather than hardcoding it. This
is testing OBSERVABLE BEHAVIOR (how many times, and via which pass, the LLM
was actually invoked), not an implementation detail: the number of chunk-
pass and tag-pass LLM calls a run makes is precisely what issue #81's
Gherkin claims about ("no chunking LLM calls", "tags only the chunks not
already checkpointed").

Seam decision 4 -- the "edited file" is a distinct copy, not mutated bytes
-----------------------------------------------------------------------
`axial.envelope.compute_source_id` derives `source_id` from the filename
STEM plus a content hash (`f"{path.stem}-{sha256(bytes)[:12]}"`). This test
simulates "a source_id change (edited file)" by copying the fixture PDF's
bytes VERBATIM to a new path with a different filename
(`thesis_paper_edited.pdf`) rather than mutating the PDF's bytes in place.
This is deliberate: `axial.extract.extract` runs `axial.intake.intake`
(which opens the file with `pypdf.PdfReader` to probe for a text layer)
BEFORE it ever reaches the persisted-tree-cache short-circuit, so corrupting
the PDF's own byte stream would risk `pypdf` choking on malformed input for
reasons that have nothing to do with this test's actual subject (checkpoint
isolation) -- an accidental coupling to `pypdf`'s tolerance for garbage
bytes, not a real correctness signal. A stem-only rename produces a
genuinely different `source_id` (per `compute_source_id`'s own contract:
"distinct files never collide") while keeping the byte stream byte-for-byte
identical to the real, known-good fixture, so `intake`'s text-layer probe
behaves identically. Exactly as tests/test_vault_write.py's arrange step
does for the original fixture, this test pre-places a COPY of the
committed, real tree fixture (tests/fixtures/envelope/thesis_paper_tree.json)
at `data/trees/<edited_source_id>.json` before running `axial envelope`/
`axial vault write` on the edited copy, so no real docling parse is ever
paid for or risked on either file.

Seam decision 5 -- two independent isolated roots in test 1
-----------------------------------------------------------------------
Test 1 needs (a) an independent, ground-truth source of "how many chunks
does this fixture really produce, in what chunk_id order" and (b) an
independent, ground-truth "what does a never-interrupted vault-write run's
notes actually look like" to compare the resumed run's notes against
byte-for-byte (the Gherkin's own wording: "identical in content to a
never-failed run"). Deriving either of these INSIDE the same isolated root
the interrupted-then-resumed run uses would contaminate the very checkpoint
files under test (e.g. running `axial chunk` first would plausibly also
seed `data/chunks/<source_id>.jsonl` before this test ever gets to exercise
its own interrupted run's own persistence of that file). So test 1 builds a
SECOND, wholly independent isolated root (`_build_isolated_root`, mirroring
`tests/conftest.py`'s own `isolated_vault_root` fixture body -- the same
domain-file copy, just built by hand via `tmp_path_factory` since a fixture
function cannot be invoked a second time directly within one test) purely
as this control/ground-truth root, and never re-uses any path or file from
it in the interrupted-then-resumed root under test.

Test hygiene: every root this test uses is pytest's own `tmp_path`/
`tmp_path_factory` -- outside this repo entirely, never touching the real
`data/` tree, torn down automatically with no explicit cleanup step needed
(mirrors tests/test_vault_write.py's post-issue-#68 arrangement).
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
from pathlib import Path

from axial.chunk import HashingEmbedder, run_chunk_embedding
from axial.envelope import compute_source_id

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "envelope"

THESIS_PAPER_PDF = FIXTURES_DIR / "thesis_paper.pdf"
THESIS_PAPER_TREE_FIXTURE = FIXTURES_DIR / "thesis_paper_tree.json"

PROVIDER_ENV_VAR = "AXIAL_LLM_PROVIDER"
RECORD_PATH_ENV_VAR = "AXIAL_LLM_RECORD_PATH"

# The new fault-injection seam this test specifies (see module docstring,
# seam decision 2). Not yet implemented anywhere in src/axial/llm.py as of
# this commit -- that is precisely why this test is expected to fail red.
TAG_FAIL_AT_ENV_VAR = "AXIAL_STUB_TAG_FAIL_AT"

# Marker substrings drawn verbatim from each pass's own current prompt
# template (see module docstring, seam decision 3).
CHUNK_PROMPT_MARKER = "argumentative chunk boundaries"
TAG_PROMPT_MARKER = "assigning tags for the CHUNK below"

_DOMAIN_DIR_PARTS = ("config", "domains", "syria")
_DOMAIN_FILES = ("schema.yaml", "codebook.yaml")

# argparse's fallback error for an as-yet-nonexistent subcommand/flag --
# reused verbatim from tests/test_vault_write.py's own guard so this test
# can only pass once real `vault write` behavior (not a CLI parsing miss)
# actually ran.
ARGPARSE_FALLBACK_MARKERS = (
    "invalid choice",
    "unrecognized arguments",
)


def _build_isolated_root(base_dir: Path) -> Path:
    """Hand-built equivalent of tests/conftest.py's `isolated_vault_root`
    fixture body (see module docstring, seam decision 5): copies the domain
    schema/codebook into `base_dir` so `axial tag`/`axial artifacts`/`axial
    vault write` (which resolve the domain dir as a plain path relative to
    cwd) can find it, and returns `base_dir` itself as the staging root."""
    domain_src = REPO_ROOT.joinpath(*_DOMAIN_DIR_PARTS)
    domain_dst = base_dir.joinpath(*_DOMAIN_DIR_PARTS)
    domain_dst.mkdir(parents=True, exist_ok=True)
    for filename in _DOMAIN_FILES:
        (domain_dst / filename).write_bytes((domain_src / filename).read_bytes())
    return base_dir


def _trees_dir(root: Path) -> Path:
    return root / "data" / "trees"


def _envelopes_dir(root: Path) -> Path:
    return root / "data" / "envelopes"


def _vault_dir(root: Path) -> Path:
    return root / "data" / "vault"


def _prose_dir(root: Path) -> Path:
    return _vault_dir(root) / "prose"


def _chunks_checkpoint_path(root: Path, source_id: str) -> Path:
    return root / "data" / "chunks" / f"{source_id}.jsonl"


def _tags_checkpoint_path(root: Path, source_id: str) -> Path:
    return root / "data" / "tags" / f"{source_id}.jsonl"


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


@contextlib.contextmanager
def _chdir(path: Path):
    """Temporarily change the process cwd to `path` -- see
    `_arrange_chunk_artifact`/`_arrange_expected_chunk_records` below:
    `run_chunk_embedding` resolves its persisted-tree read
    (`axial.extract.tree_path`, via `axial.extract.TREES_DIR`) as a plain,
    cwd-relative path with no override parameter (only its OWN write
    target, `chunks_dir`, is overridable). Calling it in-process instead of
    shelling out to `axial chunk` needs this to reproduce the exact
    resolution a `cwd=`-scoped subprocess would get."""
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def _run_envelope(provider: str, *args: str, cwd: Path) -> subprocess.CompletedProcess:
    return _run_axial(["envelope", *args], provider, cwd=cwd)


def _run_vault_write(
    provider: str,
    *args: str,
    cwd: Path,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    return _run_axial(["vault", "write", *args], provider, cwd=cwd, extra_env=extra_env)


def _assert_not_argparse_fallback(result: subprocess.CompletedProcess, command: str) -> None:
    combined = result.stdout + result.stderr
    for marker in ARGPARSE_FALLBACK_MARKERS:
        assert marker not in combined, (
            f"expected a real `{command}` behavior path, not an argparse "
            f"fallback (found {marker!r}) -- this means the `{command}` "
            f"subcommand does not exist yet or was never reached:\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )


def _place_tree_fixture(source_path: Path, root: Path) -> Path:
    """Pre-place the committed REAL tree fixture at
    <root>/data/trees/<source_id>.json (source_id computed from
    `source_path`) so `axial.extract.extract` reuses it verbatim instead of
    running docling (mirrors tests/test_vault_write.py's helper of the same
    name)."""
    source_id = compute_source_id(source_path)
    tree_path = _trees_dir(root) / f"{source_id}.json"
    tree_path.parent.mkdir(parents=True, exist_ok=True)
    tree_path.write_bytes(THESIS_PAPER_TREE_FIXTURE.read_bytes())
    return tree_path


def _existing_envelope_files(root: Path) -> set[Path]:
    envelopes_dir = _envelopes_dir(root)
    if not envelopes_dir.exists():
        return set()
    return set(envelopes_dir.glob("*.json"))


def _arrange_stored_envelope(root: Path, source_path: Path) -> Path:
    """Pre-place the real tree fixture, then run `axial envelope` with the
    stub provider so a stored envelope exists on disk before vault write.
    Returns the new envelope's path. Asserts the arrange step itself
    succeeded (mirrors tests/test_vault_write.py's helper of the same
    name, generalized to an arbitrary `source_path`)."""
    _place_tree_fixture(source_path, root)
    before_files = _existing_envelope_files(root)

    result = _run_envelope("stub", str(source_path), cwd=root)
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


def _arrange_chunk_artifact(root: Path, source_path: Path) -> list[dict]:
    """Write the real, on-disk chunk artifact for `source_path` IN-PROCESS
    (`axial.chunk.run_chunk_embedding`, the stub/offline `HashingEmbedder`)
    at `<root>/data/chunks/<source_id>.jsonl`, and return the records it
    produced.

    Issue #154 slice 04: `axial vault write` no longer chunks internally at
    all -- chunking is LLM-free (embedding-based) and lives entirely
    upstream, in the separate, required `axial chunk` step; `axial vault
    write` only ever READS the already-persisted artifact (via
    `axial.tag.run_tag`'s/`axial.xref.run_xref`'s own `axial.chunk.
    read_chunks` calls) and fails clearly if it is absent (locked by
    tests/test_pipeline_rewire.py). So every arrange step below that needs
    a chunk artifact on disk before running `axial vault write` must write
    it explicitly first -- this helper is that arrange step, for either the
    control root or the root under test."""
    with _chdir(root):
        records = run_chunk_embedding(source_path, embedder=HashingEmbedder())
    for record in records:
        assert isinstance(record.get("chunk_id"), str) and record["chunk_id"].strip(), (
            f"arrange step failed: expected every chunk record to carry a "
            f"non-empty 'chunk_id', got {record!r}"
        )
    return records


def _arrange_expected_chunk_records(control_root: Path, source_path: Path) -> list[dict]:
    """Write the on-disk chunk artifact in a dedicated CONTROL root (never
    the root under test -- see module docstring, seam decision 5) and
    return the real, deterministic chunk_id/section order for
    `source_path`, used as ground truth."""
    return _arrange_chunk_artifact(control_root, source_path)


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        records.append(json.loads(line))
    return records


def _checkpoint_chunk_ids(path: Path) -> list[str]:
    records = _read_jsonl(path)
    for record in records:
        assert isinstance(record, dict) and isinstance(record.get("chunk_id"), str), (
            f"expected every line of checkpoint file {path} to be a JSON "
            f"object carrying a string 'chunk_id' (issue #81 points 1/2), "
            f"got {record!r}"
        )
    return [record["chunk_id"] for record in records]


def _count_marker_occurrences(record_path: Path, marker: str) -> int:
    """Count how many recorded prompts (one JSON-encoded string per line,
    written by `axial.llm.RecordLLMClient`) contain `marker` -- the
    call-counting channel this test specifies (module docstring, seam
    decision 3)."""
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


def _find_note_for_chunk(chunk_id: str, root: Path) -> Path:
    prose_dir = _prose_dir(root)
    assert prose_dir.exists(), (
        f"expected {prose_dir} to exist after `axial vault write` ran, but it does not"
    )
    matches = [p for p in prose_dir.iterdir() if p.is_file() and p.stem == chunk_id]
    assert len(matches) == 1, (
        f"expected exactly one note file under {prose_dir} whose filename "
        f"stem equals chunk_id {chunk_id!r}, got {len(matches)}: {sorted(matches)}"
    )
    return matches[0]


def test_vault_write_resumes_from_tag_checkpoint_after_partial_failure(
    isolated_vault_root, tmp_path_factory
):
    """Core resume scenario (issue #81's full Gherkin): a tag pass scripted
    to fail partway through a source leaves per-chunk checkpoints on disk;
    a healthy rerun makes zero chunking LLM calls, tags only the chunks not
    already checkpointed, and produces a vault identical to a never-failed
    run."""
    root = isolated_vault_root
    control_root = _build_isolated_root(tmp_path_factory.mktemp("resume_control"))

    source_id = compute_source_id(THESIS_PAPER_PDF)

    # --- Ground truth, from the independent control root (seam decision 5) ---
    _arrange_stored_envelope(control_root, THESIS_PAPER_PDF)
    expected_records = _arrange_expected_chunk_records(control_root, THESIS_PAPER_PDF)
    expected_chunk_ids_in_order = [record["chunk_id"] for record in expected_records]
    total = len(expected_chunk_ids_in_order)
    assert total >= 2, (
        f"arrange step failed: this test needs the fixture to yield at "
        f"least 2 chunks so a meaningful partial-failure split exists, got "
        f"{total}"
    )
    fail_at = total // 2 + 1
    already_tagged_expected = set(expected_chunk_ids_in_order[: fail_at - 1])
    missing_expected = set(expected_chunk_ids_in_order[fail_at - 1 :])
    assert already_tagged_expected and missing_expected, (
        f"arrange step failed: expected a genuinely partial split (some "
        f"chunks tagged, some missing) for total={total}, fail_at={fail_at}, "
        f"got already_tagged={already_tagged_expected!r} "
        f"missing={missing_expected!r}"
    )

    # A separate, never-interrupted control run of `axial vault write`
    # (same fixture, same stub provider, no fault injection) -- the "never-
    # failed run" the Gherkin's notes must be identical to.
    control_write_result = _run_vault_write("stub", str(THESIS_PAPER_PDF), cwd=control_root)
    _assert_not_argparse_fallback(control_write_result, "vault write")
    assert control_write_result.returncode == 0, (
        f"arrange step failed: expected exit code 0 for the control "
        f"(never-interrupted) `axial vault write` run, got "
        f"{control_write_result.returncode}\nstdout: {control_write_result.stdout!r}\n"
        f"stderr: {control_write_result.stderr!r}"
    )
    control_notes = {
        chunk_id: _find_note_for_chunk(chunk_id, control_root).read_text(encoding="utf-8")
        for chunk_id in expected_chunk_ids_in_order
    }

    # --- Run 1: the interrupted run, in the isolated root under test ---
    _arrange_stored_envelope(root, THESIS_PAPER_PDF)
    # Issue #154 slice 04: `axial vault write` no longer chunks internally
    # -- the on-disk chunk artifact is a required precondition it only ever
    # reads (tests/test_pipeline_rewire.py locks the "missing artifact
    # fails clearly" contract), so it must be arranged here, once, up
    # front, exactly as the control root's own ground truth was above.
    _arrange_chunk_artifact(root, THESIS_PAPER_PDF)
    chunks_checkpoint_bytes_before_failure = _chunks_checkpoint_path(root, source_id).read_bytes()

    failing_result = _run_vault_write(
        "stub",
        str(THESIS_PAPER_PDF),
        cwd=root,
        extra_env={TAG_FAIL_AT_ENV_VAR: str(fail_at)},
    )
    _assert_not_argparse_fallback(failing_result, "vault write")
    assert failing_result.returncode != 0, (
        f"expected `axial vault write` to exit non-zero when the tag pass "
        f"is scripted to fail at chunk {fail_at} of {total} (issue #81 "
        f"point 3: 'a mid-tag failure still surfaces exactly today's typed "
        f"error, non-zero exit'), got exit code 0\nstdout: "
        f"{failing_result.stdout!r}\nstderr: {failing_result.stderr!r}"
    )
    assert failing_result.stderr.strip(), (
        f"expected non-empty stderr for the injected tag-pass failure "
        f"(the CLI's error convention is `error: ...`), got empty stderr\n"
        f"stdout: {failing_result.stdout!r}"
    )

    # Contract point 1, reframed for issue #154 slice 04: the chunk artifact
    # is no longer written BY the chunking pass as part of `axial vault
    # write`'s own resumable pipeline -- chunking is LLM-free and lives
    # entirely upstream (the arrange step above already wrote it). What
    # remains of this contract point is that a downstream tag-pass failure
    # must never delete or corrupt that pre-existing, read-only dependency
    # -- it is left byte-for-byte untouched, independent of the tag pass's
    # own outcome.
    chunks_checkpoint = _chunks_checkpoint_path(root, source_id)
    assert chunks_checkpoint.exists(), (
        f"expected {chunks_checkpoint} to still exist after `axial vault "
        f"write` ran (even though the tag pass failed partway) -- it is a "
        f"read-only precondition `axial vault write` never deletes"
    )
    assert chunks_checkpoint.read_bytes() == chunks_checkpoint_bytes_before_failure, (
        f"expected {chunks_checkpoint} to be byte-for-byte unchanged by a "
        f"downstream tag-pass failure (issue #154 slice 04: `axial vault "
        f"write` only ever reads this artifact, never rewrites it)"
    )
    persisted_chunk_ids = _checkpoint_chunk_ids(chunks_checkpoint)
    assert set(persisted_chunk_ids) == set(expected_chunk_ids_in_order), (
        f"expected {chunks_checkpoint} to carry exactly this fixture's real "
        f"chunk_ids {sorted(expected_chunk_ids_in_order)!r}, got "
        f"{sorted(persisted_chunk_ids)!r}"
    )

    # Contract point 2/3: the tag-pass checkpoint carries exactly the
    # chunks that were successfully tagged before the injected failure --
    # no more, no less.
    tags_checkpoint = _tags_checkpoint_path(root, source_id)
    assert tags_checkpoint.exists(), (
        f"expected {tags_checkpoint} to exist after a partial tag-pass "
        f"failure (issue #81 point 2: tagged records are appended 'as it "
        f"is produced', one line per chunk) -- got no file at all"
    )
    persisted_tag_ids = _checkpoint_chunk_ids(tags_checkpoint)
    assert set(persisted_tag_ids) == already_tagged_expected, (
        f"expected {tags_checkpoint} to carry exactly the "
        f"{fail_at - 1} chunk(s) tagged before the injected failure at "
        f"chunk {fail_at}, i.e. {sorted(already_tagged_expected)!r}, got "
        f"{sorted(persisted_tag_ids)!r}"
    )

    # --- Run 2: the healthy rerun ---
    record_path = root.parent / f"{root.name}_rerun_record.jsonl"
    rerun_result = _run_vault_write(
        "record",
        str(THESIS_PAPER_PDF),
        cwd=root,
        extra_env={RECORD_PATH_ENV_VAR: str(record_path)},
    )
    _assert_not_argparse_fallback(rerun_result, "vault write")
    assert rerun_result.returncode == 0, (
        f"expected exit code 0 for the healthy rerun of `axial vault "
        f"write` on the same source after the provider is healthy again, "
        f"got {rerun_result.returncode}\nstdout: {rerun_result.stdout!r}\n"
        f"stderr: {rerun_result.stderr!r}"
    )

    chunk_calls = _count_marker_occurrences(record_path, CHUNK_PROMPT_MARKER)
    assert chunk_calls == 0, (
        f"expected the healthy rerun to make NO chunking LLM calls at all "
        f"(issue #81's Gherkin: 'the rerun makes no chunking LLM calls' -- "
        f"issue #154 slice 04 makes this unconditional: `axial vault write` "
        f"never chunks internally at all, resumed or not, so this also "
        f"regression-guards against ever reintroducing a chunk-pass LLM "
        f"call on this path), got {chunk_calls} prompt(s) matching the "
        f"chunk pass's own prompt template ({CHUNK_PROMPT_MARKER!r}) in "
        f"{record_path}"
    )

    tag_calls = _count_marker_occurrences(record_path, TAG_PROMPT_MARKER)
    assert tag_calls == len(missing_expected), (
        f"expected the healthy rerun to make exactly one tag-pass LLM call "
        f"per chunk NOT already checkpointed by run 1 (issue #81's "
        f"Gherkin: 'tags only the chunks not already checkpointed'), "
        f"i.e. {len(missing_expected)} call(s) for {sorted(missing_expected)!r}, "
        f"got {tag_calls} prompt(s) matching the tag pass's own prompt "
        f"template ({TAG_PROMPT_MARKER!r}) in {record_path}"
    )

    # The tag checkpoint must now cover every chunk exactly once -- the
    # already-tagged chunks must not have been re-sent or duplicated.
    final_tag_ids = _checkpoint_chunk_ids(tags_checkpoint)
    assert set(final_tag_ids) == set(expected_chunk_ids_in_order), (
        f"expected {tags_checkpoint} to carry every chunk_id after the "
        f"healthy rerun completes, got {sorted(final_tag_ids)!r} vs. "
        f"expected {sorted(expected_chunk_ids_in_order)!r}"
    )
    assert len(final_tag_ids) == total, (
        f"expected exactly {total} line(s) in {tags_checkpoint} after the "
        f"rerun (no chunk re-appended/duplicated), got {len(final_tag_ids)}"
    )

    # Contract point 4 + the Gherkin's own wording: the vault receives one
    # note per chunk, identical in content to the never-failed control run.
    for chunk_id in expected_chunk_ids_in_order:
        resumed_note_text = _find_note_for_chunk(chunk_id, root).read_text(encoding="utf-8")
        assert resumed_note_text == control_notes[chunk_id], (
            f"expected chunk {chunk_id!r}'s note after the interrupted-"
            f"then-resumed run to be byte-for-byte identical to the same "
            f"chunk's note from a never-failed control run (issue #81's "
            f"Gherkin: 'the vault receives one note per chunk, identical "
            f"in content to a never-failed run'), but they differ.\n"
            f"resumed:\n{resumed_note_text!r}\ncontrol:\n{control_notes[chunk_id]!r}"
        )

    prose_files = [p for p in _prose_dir(root).iterdir() if p.is_file()]
    assert len(prose_files) == total, (
        f"expected exactly {total} prose note(s) under {_prose_dir(root)} "
        f"after the resumed run (one per chunk), got {len(prose_files)}: "
        f"{sorted(p.name for p in prose_files)}"
    )


def test_vault_write_source_id_change_ignores_prior_checkpoints(
    isolated_vault_root, tmp_path_factory
):
    """The Gherkin's third clause: a source_id change (an edited/renamed
    file, per module docstring seam decision 4) must ignore all prior
    checkpoints -- neither reusing them for the new source_id nor mutating
    the original source_id's own checkpoint files.

    Issue #154 slice 04 note: the on-disk chunk artifact is now
    source_id-keyed exactly like every other checkpoint here
    (`data/chunks/<source_id>.jsonl`, read via `axial.chunk.read_chunks`),
    but `axial vault write` no longer WRITES it itself -- it is a required,
    read-only precondition arranged by a separate `axial chunk` step. So
    the CHUNK dimension of "a source_id change ignores all prior
    checkpoints" is proven differently than the (still-real) TAG dimension:
    an edited copy with no chunk artifact of its own must fail clearly
    (never silently fall back to the original source_id's artifact), and
    only once its OWN artifact is arranged does `axial vault write` succeed
    -- at which point it must still make zero chunking LLM calls (chunking
    is LLM-free, full stop) while making real tag-pass calls for its own,
    not-previously-tagged chunks."""
    root = isolated_vault_root

    original_id = compute_source_id(THESIS_PAPER_PDF)

    # --- A complete, healthy run for the ORIGINAL source establishes its
    # checkpoints. ---
    _arrange_stored_envelope(root, THESIS_PAPER_PDF)
    _arrange_chunk_artifact(root, THESIS_PAPER_PDF)
    original_result = _run_vault_write("stub", str(THESIS_PAPER_PDF), cwd=root)
    _assert_not_argparse_fallback(original_result, "vault write")
    assert original_result.returncode == 0, (
        f"arrange step failed: expected exit code 0 for the original "
        f"source's own `axial vault write` run, got {original_result.returncode}\n"
        f"stdout: {original_result.stdout!r}\nstderr: {original_result.stderr!r}"
    )

    original_chunks_checkpoint = _chunks_checkpoint_path(root, original_id)
    original_tags_checkpoint = _tags_checkpoint_path(root, original_id)
    assert original_chunks_checkpoint.exists() and original_tags_checkpoint.exists(), (
        f"arrange step failed: expected both checkpoint files to exist "
        f"for the original source_id {original_id!r} after a healthy run, "
        f"got chunks exists={original_chunks_checkpoint.exists()} tags "
        f"exists={original_tags_checkpoint.exists()}"
    )
    original_chunks_bytes_before = original_chunks_checkpoint.read_bytes()
    original_tags_bytes_before = original_tags_checkpoint.read_bytes()
    original_chunk_count = len(_checkpoint_chunk_ids(original_chunks_checkpoint))

    # --- Build the "edited" file: a byte-identical copy under a different
    # filename (module docstring, seam decision 4), a genuinely different
    # source_id via `compute_source_id`'s own stem+hash contract. ---
    edited_dir = root / "edited_fixture"
    edited_dir.mkdir(parents=True, exist_ok=True)
    edited_path = edited_dir / "thesis_paper_edited.pdf"
    edited_path.write_bytes(THESIS_PAPER_PDF.read_bytes())
    edited_id = compute_source_id(edited_path)
    assert edited_id != original_id, (
        f"arrange step failed: expected the edited copy's source_id to "
        f"differ from the original's (compute_source_id incorporates the "
        f"filename stem), got the same id {edited_id!r} for both"
    )

    _arrange_stored_envelope(root, edited_path)

    # --- CHUNK dimension: without its OWN chunk artifact, the edited copy
    # must fail clearly -- never silently fall back to reading the original
    # source_id's artifact (issue #154 slice 04, tests/test_pipeline_rewire.py's
    # locked "missing artifact" contract, applied here as the chunk-side
    # proof of "a source_id change ignores all prior checkpoints"). ---
    missing_artifact_result = _run_vault_write("stub", str(edited_path), cwd=root)
    _assert_not_argparse_fallback(missing_artifact_result, "vault write")
    assert missing_artifact_result.returncode != 0, (
        f"expected `axial vault write` on the edited copy (a new "
        f"source_id, {edited_id!r}) to fail before its own chunk artifact "
        f"exists -- a source_id change must ignore all prior checkpoints "
        f"(issue #81's Gherkin), never silently fall back to the original "
        f"source_id {original_id!r}'s chunk artifact, got exit code 0\n"
        f"stdout: {missing_artifact_result.stdout!r}\n"
        f"stderr: {missing_artifact_result.stderr!r}"
    )
    missing_artifact_combined = (
        missing_artifact_result.stdout + missing_artifact_result.stderr
    ).lower()
    assert "axial chunk" in missing_artifact_combined, (
        f"expected the edited copy's missing-chunk-artifact error to tell "
        f"the operator to run `axial chunk` first, got combined output "
        f"that does not mention it:\nstdout: {missing_artifact_result.stdout!r}\n"
        f"stderr: {missing_artifact_result.stderr!r}"
    )

    _arrange_chunk_artifact(root, edited_path)

    record_path = root.parent / f"{root.name}_edited_record.jsonl"
    edited_result = _run_vault_write(
        "record",
        str(edited_path),
        cwd=root,
        extra_env={RECORD_PATH_ENV_VAR: str(record_path)},
    )
    _assert_not_argparse_fallback(edited_result, "vault write")
    assert edited_result.returncode == 0, (
        f"expected exit code 0 for `axial vault write` on the edited "
        f"(different source_id) copy once its own chunk artifact is "
        f"arranged, got {edited_result.returncode}\nstdout: "
        f"{edited_result.stdout!r}\nstderr: {edited_result.stderr!r}"
    )

    chunk_calls = _count_marker_occurrences(record_path, CHUNK_PROMPT_MARKER)
    assert chunk_calls == 0, (
        f"expected `axial vault write` to make zero chunking LLM calls "
        f"regardless of source_id (issue #154 slice 04: chunking is "
        f"LLM-free and `axial vault write` never chunks internally at "
        f"all), got {chunk_calls} chunk-pass call(s) in {record_path}"
    )
    tag_calls = _count_marker_occurrences(record_path, TAG_PROMPT_MARKER)
    assert tag_calls > 0, (
        f"expected `axial vault write` on the edited copy to make real "
        f"tag-pass LLM calls for every one of its own chunks -- a "
        f"source_id change must ignore the original source_id's tag "
        f"checkpoint too -- got {tag_calls} tag-pass call(s) in {record_path}"
    )

    # The edited copy gets its OWN, separate checkpoint files.
    edited_chunks_checkpoint = _chunks_checkpoint_path(root, edited_id)
    edited_tags_checkpoint = _tags_checkpoint_path(root, edited_id)
    assert edited_chunks_checkpoint.exists() and edited_tags_checkpoint.exists(), (
        f"expected the edited copy to receive its own checkpoint files "
        f"keyed by its own source_id {edited_id!r}, distinct from the "
        f"original's ({original_id!r}), got chunks exists="
        f"{edited_chunks_checkpoint.exists()} tags exists="
        f"{edited_tags_checkpoint.exists()}"
    )
    edited_chunk_count = len(_checkpoint_chunk_ids(edited_chunks_checkpoint))
    assert edited_chunk_count == original_chunk_count, (
        f"expected the edited copy (byte-identical content, only the "
        f"filename differs) to produce the same NUMBER of chunks as the "
        f"original ({original_chunk_count}), got {edited_chunk_count}"
    )
    for chunk_id in _checkpoint_chunk_ids(edited_chunks_checkpoint):
        assert chunk_id.startswith(edited_id), (
            f"expected every chunk_id in {edited_chunks_checkpoint} to be "
            f"namespaced under the edited copy's own source_id "
            f"{edited_id!r}, got {chunk_id!r}"
        )

    # The ORIGINAL source_id's checkpoint files must be untouched -- proof
    # the edited-file run never read from or wrote into the wrong
    # checkpoint namespace.
    assert original_chunks_checkpoint.read_bytes() == original_chunks_bytes_before, (
        f"expected the original source_id's chunk checkpoint "
        f"({original_chunks_checkpoint}) to be byte-for-byte unchanged "
        f"after running `axial vault write` on a DIFFERENT source_id -- "
        f"a source_id change must never mutate another source_id's "
        f"checkpoint"
    )
    assert original_tags_checkpoint.read_bytes() == original_tags_bytes_before, (
        f"expected the original source_id's tag checkpoint "
        f"({original_tags_checkpoint}) to be byte-for-byte unchanged "
        f"after running `axial vault write` on a DIFFERENT source_id -- "
        f"a source_id change must never mutate another source_id's "
        f"checkpoint"
    )
