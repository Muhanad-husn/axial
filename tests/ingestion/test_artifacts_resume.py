"""Outer acceptance test for issue #98 (per-artifact checkpoint/resume for
the artifacts pass inside `axial vault write`).

Locked behavioral contract (DEC-1) -- do not edit once committed red.

Given a source with several artifact nodes, and the artifacts pass scripted
      to fail partway (stub provider fails at artifact k)
When  the user re-runs `axial vault write` with the provider now healthy
Then  the rerun classifies ONLY the artifacts not already checkpointed by
      the failed run (observable via the LLM call count), and succeeds
And   a torn final checkpoint line is healed (dropped) rather than poisoning
      the resume: the retry re-classifies only that one artifact and
      succeeds
And   every checkpoint is keyed by the source's own computed source_id --
      an unrelated/edited source gets its own independent checkpoint,
      never reusing or mutating another source's

See issue #98's "Fix"/"Acceptance" sections (mirroring issue #81's chunk/tag
checkpoint design, extending PRD §7.3/§7.4's "no recompute" persist-and-reuse
principle to the artifacts pass's output) for the three points this test
pins:

  1. Checkpoint file `data/artifacts/<source_id>.jsonl`, one JSON line per
     successfully classified artifact record, appended (and flushed) AS IT
     IS PRODUCED -- so a mid-pass failure still leaves every artifact
     classified before the failure durably on disk.
  2. On entry, a torn final checkpoint line (a hard-kill mid-append) is
     healed (dropped), never treated as poison; the artifact it belonged to
     is simply re-classified on the next run. (A torn NON-final line is
     genuine corruption and is explicitly left untested here -- issue #98
     locks only the torn-FINAL-line healing path as its acceptance
     criterion, mirroring `axial.tag._heal_torn_checkpoint_tail`'s own
     scope.)
  3. Already-checkpointed artifacts (keyed by `artifact_id`) are skipped;
     only the remainder are (re)classified. This must hold for the FULL
     `axial vault write` retry, not just its first internal call to
     `axial.artifacts.run_artifacts` -- see seam decision 3 below for why
     that distinction actually matters here.

Fixture: tests/fixtures/artifacts/multi_artifact.pdf (+ its committed
multi_artifact_tree.json) -- a NEW fixture this test introduces, since every
existing artifact-bearing fixture in this repo
(tests/fixtures/extract/prose_and_table.pdf) carries exactly ONE artifact
node, which cannot exercise a partial "some classified, some not" split.
multi_artifact.pdf's real, docling-produced tree (see
tests/fixtures/artifacts/_generate.py for the regeneration recipe) carries
exactly FOUR artifact nodes (four small bordered-grid tables), all nested
under one section, "Findings" -- verified directly via `axial extract`
before committing this tree fixture.

Seam decision 1 -- the fail-at-artifact-N seam this test SPECIFIES
-----------------------------------------------------------------------
Mirroring tests/test_vault_resume.py's seam decision 2 (`AXIAL_STUB_TAG_FAIL_AT`,
issue #81) exactly, but for the artifacts pass, this test locks a new seam
for the implementer to build:

    AXIAL_STUB_ARTIFACT_FAIL_AT (env var, a positive base-10 integer string,
    1-indexed): when set, the Nth call any `LLMClient.complete()`
    implementation receives with `pass_name == axial.llm.ARTIFACTS_PASS_NAME`,
    counted from the start of the CURRENT PROCESS (a fresh counter per
    `axial` subprocess invocation -- never persisted across processes),
    raises an `axial.llm.LLMError` subclass instead of returning a canned
    response. Every call before the Nth still returns the normal canned
    artifact response; the counter is read/incremented at call time
    (mirroring the "read fresh from the environment on every call"
    convention `AXIAL_STUB_TAG_FAIL_AT`/`AXIAL_STUB_ARTIFACT_ROLE` already
    establish). Unset, empty, or non-positive means "never fail" (today's
    behavior, unchanged). Honored by the shared canned-response dispatch
    both `stub` and `record` delegate to.

    The raised exception must be a subclass of `axial.llm.LLMError` so it
    propagates through `axial.model_json.complete_json` and is caught by
    `axial.artifacts.run_artifacts`'s existing `except (LLMError,
    httpx.HTTPError)` -> `LLMFailedError` -> `axial.vault.run_vault_write`'s
    existing `except (ArtifactsError, TagError)` ->
    `ArtifactClassificationFailedError` -> the CLI's existing `except
    VaultError: print(f"error: {exc}", ...); return 1` path -- i.e. exactly
    today's typed "error: ..." / non-zero-exit contract, never a bare
    traceback and never a new CLI-level branch.

This test asserts through the *outcome* of this seam (checkpoint files on
disk, process exit code, stderr, and recorded LLM call counts) -- never by
importing or asserting on any particular Python exception class name.

Seam decision 2 -- counting LLM calls through an ALREADY-EXISTING channel
-----------------------------------------------------------------------
Exactly like tests/test_vault_resume.py's seam decision 3: this test reuses
the `record` provider (`AXIAL_LLM_PROVIDER=record` + `AXIAL_LLM_RECORD_PATH`,
`axial.llm.RecordLLMClient`) to observe how many artifacts-pass LLM calls a
run actually makes, matching each recorded prompt against a marker substring
drawn verbatim from `axial.artifacts._ARTIFACT_PROMPT_TEMPLATE`'s own opening
sentence: "classifying a single non-text artifact". This substring appears in
no other pass's prompt template (chunk: "argumentative chunk boundaries";
tag: "assigning tags for the CHUNK below"), so it unambiguously identifies an
artifacts-pass call in the shared record log.

Seam decision 3 -- why this test counts calls across the WHOLE retry, not
just one internal call site
-----------------------------------------------------------------------
`axial.vault.run_vault_write` calls `axial.artifacts.run_artifacts` TWICE
today for the same source in the same process: once directly (to build the
artifact notes) and once more indirectly, inside `axial.xref.run_xref`
(which reuses `run_artifacts` for the source's real artifact-id set rather
than inventing a parallel scheme). Because of this, "the retry classifies
ONLY the remaining artifacts" (issue #98's Acceptance wording) is only a
true, non-trivial claim at the level of the FULL retry's aggregate call
count across both internal call sites -- if only the checkpoint dir were
threaded into the first call site, the second (xref-internal) call would
silently re-classify every artifact a second time, and the aggregate
call-count evidence this test inspects would catch that regression even
though the first call site alone "resumed correctly". This test therefore
never inspects which call site made which call -- only the total count of
artifacts-pass prompts recorded across one entire `axial vault write`
subprocess invocation -- which is both the correct black-box observable and
exactly what "observable via the stub call count" (issue #98's own words)
names.

Seam decision 4 -- torn-tail corruption is injected as raw bytes, mirroring
`axial.tag._heal_torn_checkpoint_tail`'s own recipe
-----------------------------------------------------------------------
This test never imports or calls any artifacts-checkpoint internals (none
exist to import as of this commit). To simulate a hard-kill mid-append, it
reads the real checkpoint file `axial vault write` itself produced, takes
its last complete JSON line, and rewrites the file with that line replaced
by a short, non-`}`-terminated byte prefix of itself and no trailing
newline -- byte-for-byte the same shape
`src/axial/test_resume.py::test_load_tag_checkpoint_drops_torn_final_line_and_resume_retags_it`
already locks for the tag-checkpoint's own torn-tail case (issue #81
hardening), applied here at the black-box/subprocess level instead of via a
direct function import.

Seam decision 5 -- deriving the expected artifact_id order independently
-----------------------------------------------------------------------
Mirroring tests/test_vault_artifacts.py's seam decision 1: `axial artifacts
<fixture>` (opt-in checkpoint wiring is scoped to `axial vault write` alone,
per issue #98's own "Fix" section -- "direct axial artifacts/axial xref
invocations unchanged") is run standalone, stub provider, no fault
injection, to obtain the fixture's real, deterministic artifact_id order.
This never writes any checkpoint file (the pass is never opt-in outside
`vault write`), so it is safe to run in the SAME isolated root the
interrupted-then-resumed run under test also uses, without seeding or
contaminating `data/artifacts/`.

Test hygiene: every root this test uses is pytest's own `tmp_path` (via
`isolated_vault_root`, tests/conftest.py, issue #68) -- outside this repo
entirely, never touching the real `data/` tree, torn down automatically.
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
from pathlib import Path

from axial.chunk import run_chunk_recursive
from axial.envelope import compute_source_id

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "artifacts"

MULTI_ARTIFACT_PDF = FIXTURES_DIR / "multi_artifact.pdf"
MULTI_ARTIFACT_TREE_FIXTURE = FIXTURES_DIR / "multi_artifact_tree.json"

PROVIDER_ENV_VAR = "AXIAL_LLM_PROVIDER"
RECORD_PATH_ENV_VAR = "AXIAL_LLM_RECORD_PATH"

# The new fault-injection seam this test specifies (see module docstring,
# seam decision 1). Not yet implemented anywhere in src/axial/llm.py as of
# this commit -- that is precisely why this test is expected to fail red.
ARTIFACT_FAIL_AT_ENV_VAR = "AXIAL_STUB_ARTIFACT_FAIL_AT"

# Marker substring drawn verbatim from the artifacts pass's own current
# prompt template (see module docstring, seam decision 2).
ARTIFACT_PROMPT_MARKER = "classifying a single non-text artifact"

_DOMAIN_DIR_PARTS = ("config", "domains", "syria")
_DOMAIN_FILES = ("schema.yaml", "codebook.yaml")

# argparse's fallback error for an as-yet-nonexistent subcommand/flag.
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


def _artifacts_vault_dir(root: Path) -> Path:
    return _vault_dir(root) / "artifacts"


def _artifacts_checkpoint_path(root: Path, source_id: str) -> Path:
    return root / "data" / "artifacts" / f"{source_id}.jsonl"


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


def _run_artifacts(
    provider: str, *args: str, cwd: Path, extra_env: dict[str, str] | None = None
) -> subprocess.CompletedProcess:
    return _run_axial(["artifacts", *args], provider, cwd=cwd, extra_env=extra_env)


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
    running docling."""
    source_id = compute_source_id(source_path)
    tree_path = _trees_dir(root) / f"{source_id}.json"
    tree_path.parent.mkdir(parents=True, exist_ok=True)
    tree_path.write_bytes(MULTI_ARTIFACT_TREE_FIXTURE.read_bytes())
    return tree_path


def _existing_envelope_files(root: Path) -> set[Path]:
    envelopes_dir = _envelopes_dir(root)
    if not envelopes_dir.exists():
        return set()
    return set(envelopes_dir.glob("*.json"))


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


def _arrange_stored_envelope(root: Path, source_path: Path) -> Path:
    """Pre-place the real tree fixture, then run `axial envelope` with the
    stub provider so a stored envelope exists on disk before vault write.
    Returns the new envelope's path. Asserts the arrange step itself
    succeeded.

    Also writes the real, on-disk chunk artifact for `source_path` (issue
    #154 slice 04: `axial vault write` no longer computes chunks itself --
    it reads `data/chunks/<source_id>.jsonl` via `axial.chunk.read_chunks`,
    a required precondition regardless of whether this test's own subject
    -- the artifacts-pass checkpoint -- is otherwise unaffected by the
    chunk redesign)."""
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

    with _chdir(root):
        run_chunk_recursive(source_path)

    return next(iter(new_files))


def _parse_artifact_records(stdout: str) -> list[dict]:
    """Parse artifact records from `axial artifacts`'s stdout, tolerating
    any of: a bare JSON array, a JSON object with a top-level 'artifacts'
    array, or newline-delimited JSON (one record per line) -- mirrors
    tests/test_artifacts.py's own parsing helper."""
    stripped = stdout.strip()

    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        data = None

    if data is not None:
        if isinstance(data, dict):
            assert "artifacts" in data, (
                f"expected a top-level 'artifacts' key when artifacts stdout "
                f"is a JSON object, got keys: {sorted(data.keys())}; stdout: {stdout!r}"
            )
            records = data["artifacts"]
        else:
            records = data
        assert isinstance(records, list), (
            f"expected artifact records to be a JSON array (bare, or under "
            f"an 'artifacts' key), got {type(records).__name__}: {records!r}"
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
                f"expected artifacts stdout to be either one parseable JSON "
                f"document or newline-delimited JSON (one artifact record "
                f"per line); line {line!r} failed to parse ({exc}). Full "
                f"stdout: {stdout!r}"
            ) from None
    assert records, (
        f"expected at least one parseable artifact record in stdout, got none. stdout: {stdout!r}"
    )
    return records


def _arrange_expected_artifact_ids(root: Path, source_path: Path) -> list[str]:
    """Independently run `axial artifacts` (stub, no fault injection) to
    obtain this fixture's real, deterministic artifact_id order (see module
    docstring, seam decision 5). Never writes a checkpoint file (opt-in
    wiring is scoped to `vault write` alone), so this is safe to run in the
    same root the interrupted-then-resumed run under test also uses."""
    result = _run_artifacts("stub", str(source_path), cwd=root)
    _assert_not_argparse_fallback(result, "artifacts")
    assert result.returncode == 0, (
        f"arrange step failed: expected exit code 0 for `axial artifacts` on "
        f"{source_path} with the stub LLM provider, got {result.returncode}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    records = _parse_artifact_records(result.stdout)
    ids = []
    for record in records:
        artifact_id = record.get("artifact_id")
        assert isinstance(artifact_id, str) and artifact_id.strip(), (
            f"arrange step failed: expected every artifact record to carry "
            f"a non-empty 'artifact_id', got {record!r}"
        )
        ids.append(artifact_id)
    return ids


def _read_jsonl_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _checkpoint_artifact_ids(path: Path) -> list[str]:
    ids = []
    for line in _read_jsonl_lines(path):
        record = json.loads(line)
        assert isinstance(record, dict) and isinstance(record.get("artifact_id"), str), (
            f"expected every line of checkpoint file {path} to be a JSON "
            f"object carrying a string 'artifact_id' (issue #98), got {record!r}"
        )
        ids.append(record["artifact_id"])
    return ids


def _count_marker_occurrences(record_path: Path, marker: str) -> int:
    """Count how many recorded prompts (one JSON-encoded string per line,
    written by `axial.llm.RecordLLMClient`) contain `marker`."""
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


def _find_artifact_note(artifact_id: str, root: Path) -> Path:
    artifacts_dir = _artifacts_vault_dir(root)
    assert artifacts_dir.exists(), (
        f"expected {artifacts_dir} to exist after `axial vault write` ran, but it does not"
    )
    matches = [p for p in artifacts_dir.iterdir() if p.is_file() and p.stem == artifact_id]
    assert len(matches) == 1, (
        f"expected exactly one note file under {artifacts_dir} whose "
        f"filename stem equals artifact_id {artifact_id!r}, got "
        f"{len(matches)}: {sorted(matches)}"
    )
    return matches[0]


def test_vault_write_resumes_from_artifact_checkpoint_after_partial_failure(isolated_vault_root):
    """Core resume scenario (issue #98's Acceptance, point 1): an artifacts
    pass scripted to fail partway through a source leaves per-artifact
    checkpoints on disk; a healthy rerun of the FULL `axial vault write`
    classifies only the artifacts not already checkpointed (aggregate call
    count across the whole retry -- see module docstring, seam decision 3)
    and succeeds."""
    root = isolated_vault_root
    source_id = compute_source_id(MULTI_ARTIFACT_PDF)

    _arrange_stored_envelope(root, MULTI_ARTIFACT_PDF)
    expected_ids_in_order = _arrange_expected_artifact_ids(root, MULTI_ARTIFACT_PDF)
    total = len(expected_ids_in_order)
    assert total >= 3, (
        f"arrange step failed: this test needs the fixture to yield at "
        f"least 3 artifacts so a meaningful partial-failure split exists "
        f"(some done, some remaining), got {total}"
    )

    fail_at = total // 2 + 1
    already_done_expected = set(expected_ids_in_order[: fail_at - 1])
    missing_expected = set(expected_ids_in_order[fail_at - 1 :])
    assert already_done_expected and missing_expected, (
        f"arrange step failed: expected a genuinely partial split for "
        f"total={total}, fail_at={fail_at}, got already_done="
        f"{already_done_expected!r} missing={missing_expected!r}"
    )

    # --- Run 1: the interrupted run ---
    failing_result = _run_vault_write(
        "stub",
        str(MULTI_ARTIFACT_PDF),
        cwd=root,
        extra_env={ARTIFACT_FAIL_AT_ENV_VAR: str(fail_at)},
    )
    _assert_not_argparse_fallback(failing_result, "vault write")
    assert failing_result.returncode != 0, (
        f"expected `axial vault write` to exit non-zero when the artifacts "
        f"pass is scripted to fail at artifact {fail_at} of {total} (issue "
        f"#98: 'a vault write that fails mid-artifacts-pass'), got exit "
        f"code 0\nstdout: {failing_result.stdout!r}\nstderr: "
        f"{failing_result.stderr!r}"
    )
    assert failing_result.stderr.strip(), (
        f"expected non-empty stderr for the injected artifacts-pass "
        f"failure (the CLI's error convention is `error: ...`), got empty "
        f"stderr\nstdout: {failing_result.stdout!r}"
    )

    checkpoint_path = _artifacts_checkpoint_path(root, source_id)
    assert checkpoint_path.exists(), (
        f"expected {checkpoint_path} to exist after a partial artifacts-"
        f"pass failure (issue #98: 'append+flush as each lands') -- got no "
        f"file at all"
    )
    persisted_ids_after_failure = _checkpoint_artifact_ids(checkpoint_path)
    assert set(persisted_ids_after_failure) == already_done_expected, (
        f"expected {checkpoint_path} to carry exactly the "
        f"{fail_at - 1} artifact(s) classified before the injected failure "
        f"at artifact {fail_at}, i.e. {sorted(already_done_expected)!r}, "
        f"got {sorted(persisted_ids_after_failure)!r}"
    )
    assert len(persisted_ids_after_failure) == len(already_done_expected), (
        f"expected no duplicate lines in {checkpoint_path} after the "
        f"interrupted run, got {len(persisted_ids_after_failure)} line(s) "
        f"for {len(already_done_expected)} expected id(s)"
    )

    # --- Run 2: the healthy rerun, observed via the record provider ---
    record_path = root.parent / f"{root.name}_rerun_record.jsonl"
    rerun_result = _run_vault_write(
        "record",
        str(MULTI_ARTIFACT_PDF),
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

    artifact_calls = _count_marker_occurrences(record_path, ARTIFACT_PROMPT_MARKER)
    assert artifact_calls == len(missing_expected), (
        f"expected the healthy rerun of the FULL `axial vault write` "
        f"(aggregated across its internal calls to "
        f"axial.artifacts.run_artifacts -- see module docstring, seam "
        f"decision 3) to make exactly one artifacts-pass LLM call per "
        f"artifact NOT already checkpointed by run 1 (issue #98: 'the "
        f"retry classifies ONLY the remaining artifacts'), i.e. "
        f"{len(missing_expected)} call(s) for {sorted(missing_expected)!r}, "
        f"got {artifact_calls} prompt(s) matching the artifacts pass's own "
        f"prompt template ({ARTIFACT_PROMPT_MARKER!r}) in {record_path}"
    )

    final_ids = _checkpoint_artifact_ids(checkpoint_path)
    assert set(final_ids) == set(expected_ids_in_order), (
        f"expected {checkpoint_path} to carry every artifact_id after the "
        f"healthy rerun completes, got {sorted(final_ids)!r} vs. expected "
        f"{sorted(expected_ids_in_order)!r}"
    )
    assert len(final_ids) == total, (
        f"expected exactly {total} line(s) in {checkpoint_path} after the "
        f"rerun (no artifact re-appended/duplicated), got {len(final_ids)}"
    )

    artifacts_dir = _artifacts_vault_dir(root)
    artifact_files = [p for p in artifacts_dir.iterdir() if p.is_file()]
    assert len(artifact_files) == total, (
        f"expected exactly {total} artifact note(s) under {artifacts_dir} "
        f"after the resumed run (one per artifact), got "
        f"{len(artifact_files)}: {sorted(p.name for p in artifact_files)}"
    )
    for artifact_id in expected_ids_in_order:
        _find_artifact_note(artifact_id, root)


def test_vault_write_heals_torn_artifact_checkpoint_tail_and_reclassifies_only_that_artifact(
    isolated_vault_root,
):
    """Torn-tail healing (issue #98's Acceptance, point 2): a checkpoint's
    final line torn mid-JSON (simulating a hard kill mid-append -- see
    module docstring, seam decision 4) is healed (dropped) rather than
    poisoning the resume; the retry re-classifies ONLY that one artifact
    and succeeds."""
    root = isolated_vault_root
    source_id = compute_source_id(MULTI_ARTIFACT_PDF)

    _arrange_stored_envelope(root, MULTI_ARTIFACT_PDF)
    expected_ids_in_order = _arrange_expected_artifact_ids(root, MULTI_ARTIFACT_PDF)
    total = len(expected_ids_in_order)
    assert total >= 2, (
        f"arrange step failed: this test needs at least 2 artifacts so "
        f"tearing the last one still leaves at least one intact line to "
        f"prove selective healing, got {total}"
    )

    # --- A complete, healthy run establishes a full checkpoint ---
    first_result = _run_vault_write("stub", str(MULTI_ARTIFACT_PDF), cwd=root)
    _assert_not_argparse_fallback(first_result, "vault write")
    assert first_result.returncode == 0, (
        f"arrange step failed: expected exit code 0 for the first, "
        f"never-interrupted `axial vault write` run, got "
        f"{first_result.returncode}\nstdout: {first_result.stdout!r}\n"
        f"stderr: {first_result.stderr!r}"
    )

    checkpoint_path = _artifacts_checkpoint_path(root, source_id)
    assert checkpoint_path.exists(), (
        f"arrange step failed: expected {checkpoint_path} to exist after a "
        f"complete, healthy `axial vault write` run"
    )
    intact_lines = _read_jsonl_lines(checkpoint_path)
    assert len(intact_lines) == total, (
        f"arrange step failed: expected {total} checkpoint line(s) after a "
        f"complete run, got {len(intact_lines)}"
    )

    # --- Corrupt the checkpoint's FINAL line: truncate mid-JSON, no
    # trailing newline (mirrors src/axial/test_resume.py's own torn-tail
    # recipe for the tag checkpoint -- see module docstring, seam
    # decision 4). ---
    last_line = intact_lines[-1]
    torn_record = json.loads(last_line)
    torn_artifact_id = torn_record["artifact_id"]
    torn_fragment = last_line[:20]
    assert not torn_fragment.endswith("}"), (
        f"test setup invariant broken: the torn fragment must not "
        f"accidentally be complete/valid JSON, got {torn_fragment!r}"
    )
    healed_prefix = "\n".join(intact_lines[:-1])
    corrupted_bytes = ((healed_prefix + "\n" if healed_prefix else "") + torn_fragment).encode(
        "utf-8"
    )
    assert not corrupted_bytes.endswith(b"\n"), (
        "test setup invariant broken: the corrupted checkpoint must NOT "
        "end with a trailing newline, or it no longer simulates a torn "
        "in-flight write"
    )
    checkpoint_path.write_bytes(corrupted_bytes)

    # --- The retry: healthy provider, observed via the record provider ---
    record_path = root.parent / f"{root.name}_heal_record.jsonl"
    retry_result = _run_vault_write(
        "record",
        str(MULTI_ARTIFACT_PDF),
        cwd=root,
        extra_env={RECORD_PATH_ENV_VAR: str(record_path)},
    )
    _assert_not_argparse_fallback(retry_result, "vault write")
    assert retry_result.returncode == 0, (
        f"expected exit code 0 for the retry after a torn final checkpoint "
        f"line (issue #98: 'a torn final checkpoint line is healed'), got "
        f"{retry_result.returncode}\nstdout: {retry_result.stdout!r}\n"
        f"stderr: {retry_result.stderr!r}"
    )

    artifact_calls = _count_marker_occurrences(record_path, ARTIFACT_PROMPT_MARKER)
    assert artifact_calls == 1, (
        f"expected the retry to re-classify EXACTLY the one torn artifact "
        f"({torn_artifact_id!r}) and no other (issue #98: 'the affected "
        f"artifact is re-classified'), got {artifact_calls} artifacts-pass "
        f"prompt(s) matching {ARTIFACT_PROMPT_MARKER!r} in {record_path}"
    )

    healed_ids = _checkpoint_artifact_ids(checkpoint_path)
    assert set(healed_ids) == set(expected_ids_in_order), (
        f"expected {checkpoint_path} to carry every artifact_id after "
        f"healing + re-classification, got {sorted(healed_ids)!r} vs. "
        f"expected {sorted(expected_ids_in_order)!r}"
    )
    assert len(healed_ids) == total, (
        f"expected exactly {total} line(s) in {checkpoint_path} after "
        f"healing (the torn line dropped and re-appended exactly once, "
        f"never duplicated), got {len(healed_ids)}"
    )

    _find_artifact_note(torn_artifact_id, root)
    artifacts_dir = _artifacts_vault_dir(root)
    artifact_files = [p for p in artifacts_dir.iterdir() if p.is_file()]
    assert len(artifact_files) == total, (
        f"expected exactly {total} artifact note(s) under {artifacts_dir} "
        f"after the healed retry, got {len(artifact_files)}: "
        f"{sorted(p.name for p in artifact_files)}"
    )


def test_vault_write_artifact_checkpoint_is_keyed_by_source_id_not_hardcoded(
    isolated_vault_root,
):
    """Generality (issue #98's Acceptance, point 3): the checkpoint is keyed
    by the source's own computed source_id, for ANY source -- an unrelated
    (edited-copy) source gets its own, fully independent checkpoint, never
    reusing or mutating the original source's. Proves the mechanism is not
    coupled to any hardcoded source name."""
    root = isolated_vault_root

    original_id = compute_source_id(MULTI_ARTIFACT_PDF)

    _arrange_stored_envelope(root, MULTI_ARTIFACT_PDF)
    original_result = _run_vault_write("stub", str(MULTI_ARTIFACT_PDF), cwd=root)
    _assert_not_argparse_fallback(original_result, "vault write")
    assert original_result.returncode == 0, (
        f"arrange step failed: expected exit code 0 for the original "
        f"source's own `axial vault write` run, got "
        f"{original_result.returncode}\nstdout: {original_result.stdout!r}\n"
        f"stderr: {original_result.stderr!r}"
    )

    original_checkpoint = _artifacts_checkpoint_path(root, original_id)
    assert original_checkpoint.exists(), (
        f"arrange step failed: expected {original_checkpoint} to exist after a healthy run"
    )
    original_bytes_before = original_checkpoint.read_bytes()
    original_count = len(_checkpoint_artifact_ids(original_checkpoint))
    assert original_count >= 1

    # --- Build a byte-identical copy under a different filename -- a
    # genuinely different source_id per compute_source_id's own
    # stem+content-hash contract (mirrors tests/test_vault_resume.py's
    # "edited file" seam decision 4). ---
    edited_dir = root / "edited_fixture"
    edited_dir.mkdir(parents=True, exist_ok=True)
    edited_path = edited_dir / "multi_artifact_edited.pdf"
    edited_path.write_bytes(MULTI_ARTIFACT_PDF.read_bytes())
    edited_id = compute_source_id(edited_path)
    assert edited_id != original_id, (
        f"arrange step failed: expected the edited copy's source_id to "
        f"differ from the original's, got the same id {edited_id!r} for both"
    )

    _arrange_stored_envelope(root, edited_path)

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
        f"(different source_id) copy, got {edited_result.returncode}\n"
        f"stdout: {edited_result.stdout!r}\nstderr: {edited_result.stderr!r}"
    )

    artifact_calls = _count_marker_occurrences(record_path, ARTIFACT_PROMPT_MARKER)
    assert artifact_calls > 0, (
        f"expected `axial vault write` on the edited copy (a new "
        f"source_id, {edited_id!r}) to make real artifacts-pass LLM calls "
        f"-- a source_id change must ignore all prior checkpoints, not "
        f"silently reuse the original source_id {original_id!r}'s "
        f"checkpoint -- got {artifact_calls} call(s) in {record_path}"
    )

    edited_checkpoint = _artifacts_checkpoint_path(root, edited_id)
    assert edited_checkpoint.exists(), (
        f"expected the edited copy to receive its own checkpoint file "
        f"keyed by its own source_id {edited_id!r}, distinct from the "
        f"original's ({original_id!r})"
    )
    edited_ids = _checkpoint_artifact_ids(edited_checkpoint)
    edited_count = len(edited_ids)
    assert edited_count == original_count, (
        f"expected the edited copy (byte-identical content, only the "
        f"filename differs) to produce the same NUMBER of artifacts as the "
        f"original ({original_count}), got {edited_count}"
    )
    for artifact_id in edited_ids:
        assert artifact_id.startswith(edited_id), (
            f"expected every artifact_id in {edited_checkpoint} to be "
            f"namespaced under the edited copy's own source_id "
            f"{edited_id!r}, got {artifact_id!r}"
        )

    # The ORIGINAL source_id's checkpoint must be untouched.
    assert original_checkpoint.read_bytes() == original_bytes_before, (
        f"expected the original source_id's artifact checkpoint "
        f"({original_checkpoint}) to be byte-for-byte unchanged after "
        f"running `axial vault write` on a DIFFERENT source_id -- a "
        f"source_id change must never mutate another source_id's checkpoint"
    )
