"""Outer acceptance test for issue #104 (chunk-pass resilience: per-section
incremental checkpoint/resume; the existing bounded malformed-JSON retry in
`axial.model_json.complete_json` stays UNCHANGED).

Locked behavioral contract (DEC-1) -- do not edit once committed red.

CORRECTED SCOPE (superseding this file's original framing): `complete_json`
(`src/axial/model_json.py:119-194`) already re-asks up to `attempts=3` times
per call when a response is malformed JSON, for EVERY pass including chunk
-- this is existing, working behavior, not a gap. Production evidence (the
`ayubi` ingestion run) shows chunk-pass JSON failures are stochastic and
`complete_json`'s existing retry already recovers most of them. The real,
non-redundant gap issue #104 fixes is `run_chunk`'s ALL-OR-NOTHING
persistence: today, a section that still fails after `complete_json`
exhausts its own existing retry budget aborts the WHOLE pass, and because
`write_chunk_checkpoint` only runs once at the very end (after every
section), every already-produced section's records are lost too -- a
resume restarts chunking from section 0, wasting every LLM call the failed
run already paid for. This issue adds per-section incremental persistence
so a resume continues from the first unfinished section. It does NOT add a
new re-ask mechanism, and does NOT reduce `complete_json`'s existing
`attempts=3` budget for the chunk pass.

Given a source with several chunkable prose sections
When  one section's first chunking response is malformed JSON but a later
      attempt (within `complete_json`'s own existing, unmodified bounded
      retry) is valid
Then  the pass recovers via that EXISTING retry and completes normally,
      producing that section's chunks (a regression guard, not a new
      behavior)
And   when a section's response stays malformed across every attempt, the
      pass raises its typed parse error -- never silently, and never in an
      unbounded/looping number of calls (the EXISTING bound, unmodified)
And   when a section hard-fails mid-pass (after its own retry budget is
      exhausted), the sections completed before it are already durably
      checkpointed to `data/chunks/<source_id>.jsonl` (partial: neither
      zero records nor every section's records) -- THE PRIMARY, NEW
      behavior this issue adds
And   a resumed run completes the pass without re-issuing LLM calls for the
      sections already checkpointed
And   a fully healthy run (every response valid JSON) is unaffected: exactly
      one chunking LLM call per chunkable section, no extra call

See `src/axial/chunk.py` (~lines 382-431 as of this commit) for the one
real gap this test pins, plus the pre-existing (unchanged) retry this test
guards against regression:

  1. (PRE-EXISTING, UNCHANGED) `run_chunk`'s per-section loop calls
     `complete_json(client, prompt, pass_name=CHUNK_PASS_NAME)` with no
     explicit `attempts=`, so it already gets `complete_json`'s default
     `attempts=3` bounded internal retry on malformed JSON, per call, per
     section -- this is `complete_json`'s own already-locked contract
     (issue #72/#76), not something issue #104 introduces or touches.
  2. (THE ACTUAL GAP) `write_chunk_checkpoint(all_records, checkpoint_path)`
     (~line 430) runs ONLY once, after every section in the loop has
     finished -- an all-or-nothing write. A mid-pass hard failure at
     section N (a section whose response is STILL malformed after
     `complete_json` exhausts its own existing retry budget) today loses
     every already-produced record for sections 0..N-1: nothing is ever
     persisted, so a resume after any failure restarts chunking from
     scratch (the equally all-or-nothing resume check at ~line 382,
     `if checkpoint_path.exists(): return load_chunk_checkpoint(...)`, can
     never partially match). This test pins the fix: sections completed
     before a mid-pass failure are durably persisted, and a resume
     continues from the first unfinished section without re-issuing LLM
     calls for sections already done.

Seam decision 1 -- the stub seam this test SPECIFIES:
AXIAL_STUB_CHUNK_RESPONSE_SEQUENCE
-----------------------------------------------------------------------
Today's chunk-pass canned-response dispatch (`axial.llm._canned_response_for`,
`pass_name == CHUNK_PASS_NAME` branch) only honors a single-string override
(`AXIAL_STUB_CHUNK_RESPONSE`, verbatim for every call) -- it cannot script
"this call is malformed, the next one is valid" across a run, so it cannot
even EXERCISE `complete_json`'s existing retry deterministically from a
test, let alone drive a mid-pass hard failure at a chosen section. This
test locks a new seam, mirroring `AXIAL_STUB_TAG_RESPONSE_SEQUENCE`
(`STUB_TAG_RESPONSE_SEQUENCE_ENV_VAR`, `src/axial/llm.py`) exactly, but
scoped to the chunk pass:

    AXIAL_STUB_CHUNK_RESPONSE_SEQUENCE (env var): a JSON-encoded array of raw
    response strings. The Nth call any `LLMClient.complete()` implementation
    receives with `pass_name == axial.llm.CHUNK_PASS_NAME`, counted from the
    start of the CURRENT PROCESS (a fresh, dedicated chunk-pass counter --
    never shared with the tag-pass counter, and never persisted across
    processes), returns the (N-1)th element of the array (mod the array's
    length, mirroring the tag sequence's own wraparound). Unset or "" falls
    back to today's single canned/overridden chunk response for every call
    (this test's "no regression" scenario exercises exactly that path).
    Honored by the shared canned-response dispatch both `stub` and `record`
    delegate to, so either provider value can drive it. This seam is purely
    an OBSERVABILITY/SCRIPTING addition -- it does not itself change any
    retry or persistence behavior.

This test never imports or asserts on any particular Python exception class
name, and never asserts anything about the retry's own prompt wording
(mirroring `tests/test_tag_vocab_reask.py`'s own restraint on that point)
-- it proves behavior entirely through the OUTCOME (exit code, stderr,
checkpoint file contents, and the number of chunk-pass LLM calls recorded
via the `record` provider). Where a call count is asserted for the
EXISTING retry (tests 1 and 2), it is either an exact count that holds for
ANY `attempts >= 2` (test 1) or a generous upper bound that documents
"bounded", never "exactly `complete_json`'s current attempts value" (test
2) -- so this test never forces the implementer to retune
`complete_json`'s own already-locked retry budget.

Seam decision 2 -- driving the checkpoint/resume scenarios through
`axial vault write`, never the standalone `axial chunk`
-----------------------------------------------------------------------
Per `axial.chunk.run_chunk`'s own docstring, its checkpoint is OPT-IN,
threaded in only by `axial vault write` (`chunks_dir=_default_chunks_dir(...)`
in `axial.vault.run_vault_write`) -- the standalone `axial chunk` CLI passes
no `chunks_dir` at all (`src/axial/cli.py::_chunk`) and so never persists or
resumes anything. This test therefore drives every checkpoint/resume
scenario through `axial vault write` (mirroring
`tests/test_vault_resume.py` and `tests/test_artifacts_resume.py` exactly),
using the standalone `axial chunk` CLI only as an *arrange* step (in a
separate, independent CONTROL root) to derive this fixture's real,
deterministic chunk_id/section order -- never as the thing under test.

Seam decision 3 -- counting LLM calls through an ALREADY-EXISTING channel
-----------------------------------------------------------------------
Exactly like `tests/test_vault_resume.py`'s seam decision 3: this test
reuses the `record` provider (`AXIAL_LLM_PROVIDER=record` +
`AXIAL_LLM_RECORD_PATH`, `axial.llm.RecordLLMClient`) and matches each
recorded prompt against `_CHUNK_PROMPT_TEMPLATE`'s own opening sentence,
"argumentative chunk boundaries" -- a marker no other pass's prompt
template contains.

Seam decision 4 -- the fixture, and why it needs no new one
-----------------------------------------------------------------------
`tests/fixtures/envelope/thesis_paper.pdf` (+ its committed
`thesis_paper_tree.json`) already has exactly three chunkable top-level
sections, in this exact order: Introduction, Comparative Cases, Conclusion
(verified directly against `axial.chunk._section_nodes`/`_section_body_lines`
when this test was authored -- every one of the three has non-empty prose
body, so a never-interrupted run makes exactly 3 chunk-pass LLM calls, one
per section, in that order). That is exactly the shape this issue's
scenarios need: one section to recover via `complete_json`'s EXISTING
retry (Introduction, the first section called), one section to hard-fail
after the first section already succeeded (Comparative Cases, the
second), and a third, never-reached section (Conclusion) to prove the
resume completes the WHOLE pass, not just the failed section. No new
fixture is needed.

Seam decision 5 -- deriving expected chunk_ids/sections independently
-----------------------------------------------------------------------
Mirrors `tests/test_vault_resume.py`'s seam decision 5 exactly: a
dedicated, independent CONTROL root (`_build_isolated_root`, via
`tmp_path_factory`) runs `axial envelope` then `axial chunk` (stub, no
fault injection) to obtain this fixture's real chunk_id/section order as
ground truth, entirely separate from the root the interrupted-then-resumed
run under test uses -- so arranging the ground truth never contaminates the
very checkpoint file this test inspects.

Test hygiene: every root this test uses is pytest's own `tmp_path`/
`tmp_path_factory` (`isolated_vault_root`, issue #68) -- outside this repo
entirely, never touching the real `data/` tree, torn down automatically.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from axial.envelope import compute_source_id

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "envelope"

THESIS_PAPER_PDF = FIXTURES_DIR / "thesis_paper.pdf"
THESIS_PAPER_TREE_FIXTURE = FIXTURES_DIR / "thesis_paper_tree.json"

PROVIDER_ENV_VAR = "AXIAL_LLM_PROVIDER"
RECORD_PATH_ENV_VAR = "AXIAL_LLM_RECORD_PATH"

# The new fault-injection/sequencing seam this test specifies (see module
# docstring, seam decision 1). Not honored anywhere in src/axial/llm.py as
# of this commit for the chunk pass -- that is precisely why this test is
# expected to fail red.
CHUNK_RESPONSE_SEQUENCE_ENV_VAR = "AXIAL_STUB_CHUNK_RESPONSE_SEQUENCE"

# Marker substring drawn verbatim from the chunk pass's own current prompt
# template (`axial.chunk._CHUNK_PROMPT_TEMPLATE`'s opening sentence).
CHUNK_PROMPT_MARKER = "argumentative chunk boundaries"

# A raw response that is not parseable JSON under any circumstance (no
# markdown fence, no invalid-escape repair, nothing rescues it) -- forces
# `axial.model_json.parse_model_json` to raise `ModelJsonError`.
_MALFORMED_CHUNK_RESPONSE = "{this is not valid json at all, no closing brace"

# A well-formed chunk response carrying exactly 2 chunk-text objects --
# matching `axial.llm.StubLLMClient._CANNED_CHUNK_RESPONSE`'s own COUNT (2
# entries), reproduced here as independent test data (never imported from
# src, and never matching its exact wording) so that a section's chunk_ids
# under this injected response (`..._001`, `..._002`, positional) line up
# with the CONTROL run's own chunk_ids (which also come from
# `_CANNED_CHUNK_RESPONSE`'s 2 entries, via the plain `stub` provider) --
# required for the id-SET equality assertions in tests 1 and 3, which
# compare an injected-sequence run's checkpoint against that control's
# expected_ids verbatim.
_VALID_CHUNK_RESPONSE = json.dumps(
    {
        "chunks": [
            {"text": "Injected-sequence stub chunk one: a claim and its immediate support."},
            {"text": "Injected-sequence stub chunk two: a second argumentative unit."},
        ]
    }
)

# A long run of consecutive malformed entries -- long enough that, prefixed
# by one valid entry for an earlier section, wraparound indexing (module
# docstring, seam decision 1) never cycles back to the valid entry within a
# single section's own retry budget, however many attempts
# `complete_json` uses (today 3, unmodified by this issue) -- comfortably
# above that so this test never has to know or pin the exact number.
_PERSISTENT_MALFORMED_TAIL = [_MALFORMED_CHUNK_RESPONSE] * 9

# A generous upper bound on how many chunk-pass LLM calls a single,
# persistently-malformed section may consume before its failure is raised
# (module docstring: "bounded, not the exact retry count"). Comfortably
# above `complete_json`'s current `attempts=3` so a reasonable future
# retuning of that budget never breaks this test, while still catching a
# genuine unbounded/looping retry.
_BOUNDED_CALL_CEILING = 8

_DOMAIN_DIR_PARTS = ("config", "domains", "syria")
_DOMAIN_FILES = ("schema.yaml", "codebook.yaml")

# argparse's fallback error for an as-yet-nonexistent subcommand/flag.
ARGPARSE_FALLBACK_MARKERS = (
    "invalid choice",
    "unrecognized arguments",
)


def _build_isolated_root(base_dir: Path) -> Path:
    """Hand-built equivalent of tests/conftest.py's `isolated_vault_root`
    fixture body, used for the CONTROL root (module docstring, seam
    decision 5), mirrored verbatim from tests/test_vault_resume.py."""
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


def _run_axial(
    args: list[str],
    provider: str,
    *,
    cwd: Path,
    extra_env: dict[str, str] | None = None,
    timeout: float | None = None,
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
        timeout=timeout,
    )


def _run_envelope(provider: str, *args: str, cwd: Path) -> subprocess.CompletedProcess:
    return _run_axial(["envelope", *args], provider, cwd=cwd)


def _run_chunk(provider: str, *args: str, cwd: Path) -> subprocess.CompletedProcess:
    return _run_axial(["chunk", *args], provider, cwd=cwd)


def _run_vault_write(
    provider: str,
    *args: str,
    cwd: Path,
    extra_env: dict[str, str] | None = None,
    timeout: float | None = None,
) -> subprocess.CompletedProcess:
    return _run_axial(
        ["vault", "write", *args], provider, cwd=cwd, extra_env=extra_env, timeout=timeout
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


def _place_tree_fixture(source_path: Path, root: Path) -> Path:
    """Pre-place the committed REAL tree fixture at
    <root>/data/trees/<source_id>.json so `axial.extract.extract` reuses it
    verbatim instead of running docling."""
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
    stub provider so a stored envelope exists on disk before chunking/vault
    write. Returns the new envelope's path; asserts the arrange step itself
    succeeded."""
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


def _parse_chunk_records(stdout: str) -> list[dict]:
    """Parse chunk records from `axial chunk`'s stdout (reused verbatim
    from tests/test_vault_resume.py's helper of the same name)."""
    stripped = stdout.strip()

    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        data = None

    if data is not None:
        if isinstance(data, dict):
            assert "chunks" in data, (
                f"expected a top-level 'chunks' key when chunk stdout is a "
                f"JSON object, got keys: {sorted(data.keys())}; stdout: {stdout!r}"
            )
            records = data["chunks"]
        else:
            records = data
        assert isinstance(records, list), (
            f"expected chunk records to be a JSON array (bare, or under a "
            f"'chunks' key), got {type(records).__name__}: {records!r}"
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
                f"expected chunk stdout to be either one parseable JSON "
                f"document or newline-delimited JSON (one chunk record per "
                f"line); line {line!r} failed to parse ({exc}). Full stdout: "
                f"{stdout!r}"
            ) from None
    assert records, (
        f"expected at least one parseable chunk record in stdout, got none. stdout: {stdout!r}"
    )
    return records


def _arrange_expected_chunk_records(control_root: Path, source_path: Path) -> list[dict]:
    """Independently run `axial chunk` (stub, no fault injection) in a
    dedicated CONTROL root to obtain this fixture's real, deterministic
    chunk_id/section order -- ground truth this test compares the
    interrupted-then-resumed run's own checkpoint against (module
    docstring, seam decisions 2 and 5). Requires a stored envelope for
    `source_path` to already exist in `control_root`."""
    result = _run_chunk("stub", str(source_path), cwd=control_root)
    _assert_not_argparse_fallback(result, "chunk")
    assert result.returncode == 0, (
        f"arrange step failed: expected exit code 0 for `axial chunk` on "
        f"{source_path} with the stub LLM provider, got {result.returncode}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    records = _parse_chunk_records(result.stdout)
    for record in records:
        assert isinstance(record.get("chunk_id"), str) and record["chunk_id"].strip(), (
            f"arrange step failed: expected every chunk record to carry a "
            f"non-empty 'chunk_id', got {record!r}"
        )
        assert isinstance(record.get("section"), str) and record["section"].strip(), (
            f"arrange step failed: expected every chunk record to carry a "
            f"non-empty 'section', got {record!r}"
        )
    return records


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
            f"object carrying a string 'chunk_id' (issue #104), got {record!r}"
        )
    return [record["chunk_id"] for record in records]


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


def _section_labels_in_order(records: list[dict]) -> list[str]:
    """The distinct `section` values among `records`, in first-occurrence
    order -- i.e. the sequence of sections the chunk pass's own per-section
    loop actually calls the LLM for, once each (module docstring, seam
    decision 4: three real sections, each of which produces >=1 chunk
    record, so this is also the sequence of chunk-pass LLM calls a
    never-interrupted run makes)."""
    labels: list[str] = []
    for record in records:
        if record["section"] not in labels:
            labels.append(record["section"])
    return labels


def _arrange_ground_truth(tmp_path_factory, tag: str) -> tuple[list[dict], list[str]]:
    """Build a fresh CONTROL root, arrange a stored envelope + independently
    derive this fixture's real chunk records (module docstring, seam
    decision 5). Returns (expected_records_in_order, section_labels_in_order).
    NOTE: the number of RECORDS is not the number of chunk-pass LLM CALLS --
    each chunk-pass call yields one call regardless of how many chunk-text
    objects its response carries (`_VALID_CHUNK_RESPONSE` and
    `axial.llm.StubLLMClient._CANNED_CHUNK_RESPONSE`, used by the
    stub-provider control run, both carry exactly 2 chunk-text objects per
    call -- deliberately matched so a section's positional chunk_ids
    (`..._001`, `..._002`) line up between an injected-sequence run and the
    control's own expected_ids) -- call counts in this test file are always
    asserted per SECTION, via `_section_labels_in_order`, never per
    record."""
    control_root = _build_isolated_root(tmp_path_factory.mktemp(f"chunk_resilience_{tag}"))
    _arrange_stored_envelope(control_root, THESIS_PAPER_PDF)
    expected_records = _arrange_expected_chunk_records(control_root, THESIS_PAPER_PDF)
    return expected_records, _section_labels_in_order(expected_records)


def test_chunk_pass_recovers_via_existing_complete_json_retry_on_malformed_json(
    isolated_vault_root, tmp_path_factory
):
    """REGRESSION GUARD on EXISTING behavior (not a new mechanism this
    issue adds): a chunk pass where one section's first response is
    malformed JSON but a later attempt -- within `complete_json`'s own
    existing, unmodified bounded retry (`attempts=3`, `src/axial/
    model_json.py`) -- is valid, completes the whole pass and produces
    that section's chunks. The recorded LLM traffic proves a genuine extra
    call happened (the retry actually fired), not merely that the run
    happened to succeed by luck. This test is red today ONLY because the
    `AXIAL_STUB_CHUNK_RESPONSE_SEQUENCE` seam does not exist yet to script
    "malformed then valid" deterministically -- `complete_json`'s retry
    itself is untouched, unmodified, already-working code."""
    root = isolated_vault_root
    expected_records, section_labels = _arrange_ground_truth(tmp_path_factory, "recover")
    assert section_labels == ["Introduction", "Comparative Cases", "Conclusion"], (
        f"arrange step failed: expected this fixture's 3 known chunkable "
        f"sections in this exact order, got {section_labels!r} (records: "
        f"{expected_records!r})"
    )

    _arrange_stored_envelope(root, THESIS_PAPER_PDF)

    # Call 1 (Introduction, original ask): malformed. Call 2 (Introduction,
    # complete_json's own existing retry): valid. Calls 3-4 (Comparative
    # Cases, Conclusion): valid on their own first ask. 4 calls total for 3
    # sections -- the extra call IS complete_json's existing retry firing.
    # This exact count (4) holds for ANY `attempts >= 2` complete_json may
    # use for the chunk pass, so it never pins the implementer to a
    # specific retry budget.
    sequence = [
        _MALFORMED_CHUNK_RESPONSE,
        _VALID_CHUNK_RESPONSE,
        _VALID_CHUNK_RESPONSE,
        _VALID_CHUNK_RESPONSE,
    ]

    record_path = root.parent / f"{root.name}_recover_record.jsonl"
    result = _run_vault_write(
        "record",
        str(THESIS_PAPER_PDF),
        cwd=root,
        extra_env={
            CHUNK_RESPONSE_SEQUENCE_ENV_VAR: json.dumps(sequence),
            RECORD_PATH_ENV_VAR: str(record_path),
        },
    )
    _assert_not_argparse_fallback(result, "vault write")
    assert result.returncode == 0, (
        f"expected exit code 0: a malformed FIRST response for one section, "
        f"followed by a valid response on complete_json's own existing "
        f"retry, must let the whole chunk pass recover and complete "
        f"(issue #104: this existing behavior must be unaffected), got "
        f"{result.returncode}\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    chunk_calls = _count_marker_occurrences(record_path, CHUNK_PROMPT_MARKER)
    assert chunk_calls == 4, (
        f"expected exactly 4 chunk-pass LLM calls (3 chunkable sections + "
        f"exactly one extra call from complete_json's own existing retry "
        f"for the section whose first response was malformed) -- proving "
        f"the retry genuinely fired, not that the run trivially passed -- "
        f"got {chunk_calls} call(s) matching {CHUNK_PROMPT_MARKER!r} in "
        f"{record_path}"
    )

    source_id = compute_source_id(THESIS_PAPER_PDF)
    checkpoint_path = _chunks_checkpoint_path(root, source_id)
    assert checkpoint_path.exists(), (
        f"expected {checkpoint_path} to exist after a successful `axial vault write` run"
    )
    persisted_ids = set(_checkpoint_chunk_ids(checkpoint_path))
    expected_ids = {record["chunk_id"] for record in expected_records}
    assert persisted_ids == expected_ids, (
        f"expected the recovered section's chunks to be produced along "
        f"with every other section's, got {sorted(persisted_ids)!r} vs. "
        f"expected {sorted(expected_ids)!r}"
    )


def test_chunk_pass_persistently_malformed_response_raises_bounded_failure(
    isolated_vault_root,
):
    """Acceptance criterion 2 (bounded, EXISTING behavior guard -- this
    issue does not add or remove a re-ask mechanism): when a section's
    chunking response stays malformed on EVERY attempt (never recovering
    within `complete_json`'s own existing, unmodified retry budget), the
    pass raises its typed parse error -- non-zero exit, non-empty stderr --
    and does so within a small, finite number of calls, never looping
    unboundedly or silently swallowing the failure. This test deliberately
    does NOT pin the exact retry count (that is `complete_json`'s own
    already-locked, unmodified contract) -- it only locks the OUTCOME:
    persistent malformed JSON is fatal, and fatal within a bounded number
    of calls, not an infinite retry loop."""
    root = isolated_vault_root
    _arrange_stored_envelope(root, THESIS_PAPER_PDF)

    # A single-element sequence: every chunk-pass call, at any index,
    # returns malformed JSON (mod-1 wraparound always resolves to index 0)
    # -- "persistently malformed", regardless of how many attempts
    # complete_json's existing retry makes internally before giving up.
    sequence = [_MALFORMED_CHUNK_RESPONSE]

    record_path = root.parent / f"{root.name}_bounded_record.jsonl"
    result = _run_vault_write(
        "record",
        str(THESIS_PAPER_PDF),
        cwd=root,
        extra_env={
            CHUNK_RESPONSE_SEQUENCE_ENV_VAR: json.dumps(sequence),
            RECORD_PATH_ENV_VAR: str(record_path),
        },
        # Guards against a genuinely unbounded/looping retry hanging this
        # test forever -- a timeout is itself evidence of "not bounded".
        timeout=120,
    )
    _assert_not_argparse_fallback(result, "vault write")
    assert result.returncode != 0, (
        f"expected `axial vault write` to exit non-zero when a section's "
        f"chunking response stays malformed on every attempt (issue #104: "
        f"'no silent pass' -- this existing fatal-on-persistent-failure "
        f"behavior must be preserved), got exit code 0\nstdout: "
        f"{result.stdout!r}\nstderr: {result.stderr!r}"
    )
    assert result.stderr.strip(), (
        f"expected non-empty stderr for the persistently-malformed chunk "
        f"response (the CLI's error convention is `error: ...`), got empty "
        f"stderr\nstdout: {result.stdout!r}"
    )

    chunk_calls = _count_marker_occurrences(record_path, CHUNK_PROMPT_MARKER)
    assert 0 < chunk_calls <= _BOUNDED_CALL_CEILING, (
        f"expected a small, finite number of chunk-pass LLM calls (at "
        f"least 1, at most a generous ceiling of {_BOUNDED_CALL_CEILING} -- "
        f"comfortably above complete_json's current attempts=3 budget, "
        f"deliberately not pinned to that exact number) before the "
        f"persistently-malformed section's failure is raised -- proving "
        f"the failure is BOUNDED, never an unbounded/silent retry loop -- "
        f"got {chunk_calls} call(s) matching {CHUNK_PROMPT_MARKER!r} in "
        f"{record_path}"
    )


def test_chunk_pass_checkpoints_incrementally_and_resume_skips_completed_sections(
    isolated_vault_root, tmp_path_factory
):
    """THE PRIMARY, NEW contract of issue #104 (acceptance criteria 3 and
    4): a mid-pass hard failure at the SECOND section (its response stays
    malformed across every attempt within complete_json's own existing,
    unmodified retry budget) leaves the FIRST section's chunks durably
    checkpointed (partial -- neither zero nor all); re-running afterward
    with a clean sequence completes the whole pass and makes LLM calls
    only for the sections not already checkpointed -- proving the resume
    never re-pays for section 0's already-completed work."""
    root = isolated_vault_root
    expected_records, section_labels = _arrange_ground_truth(tmp_path_factory, "resume")
    assert section_labels == ["Introduction", "Comparative Cases", "Conclusion"], (
        f"arrange step failed: expected this fixture's sections in this "
        f"exact order, got {section_labels!r} (records: {expected_records!r})"
    )
    total_records = len(expected_records)
    remaining_sections = [label for label in section_labels if label != "Introduction"]

    first_section_ids = {r["chunk_id"] for r in expected_records if r["section"] == "Introduction"}
    remaining_ids = {r["chunk_id"] for r in expected_records if r["section"] != "Introduction"}
    all_ids = {r["chunk_id"] for r in expected_records}
    assert first_section_ids and remaining_ids, (
        f"arrange step failed: expected a genuinely partial split between "
        f"the first section and the rest, got first={first_section_ids!r} "
        f"remaining={remaining_ids!r}"
    )

    _arrange_stored_envelope(root, THESIS_PAPER_PDF)

    # --- Run 1: the interrupted run ---
    # Call 1 (Introduction, original ask): valid -- this section completes.
    # Calls 2+ (Comparative Cases, every attempt complete_json's own
    # existing retry makes): malformed, persistently -- the pass hard-fails
    # on this section once that existing retry budget is exhausted.
    # Conclusion (the 3rd section) is never reached. `_PERSISTENT_MALFORMED_TAIL`
    # is long enough that wraparound indexing never cycles back to the one
    # valid entry within this section's own retry budget, however many
    # attempts complete_json uses (today 3, unmodified by this issue) --
    # this test never has to know or pin that exact number.
    failing_sequence = [_VALID_CHUNK_RESPONSE, *_PERSISTENT_MALFORMED_TAIL]
    failing_result = _run_vault_write(
        "stub",
        str(THESIS_PAPER_PDF),
        cwd=root,
        extra_env={CHUNK_RESPONSE_SEQUENCE_ENV_VAR: json.dumps(failing_sequence)},
        timeout=120,
    )
    _assert_not_argparse_fallback(failing_result, "vault write")
    assert failing_result.returncode != 0, (
        f"expected `axial vault write` to exit non-zero when the second "
        f"section's chunking response stays malformed across every "
        f"attempt (exhausting complete_json's own existing, unmodified "
        f"retry budget), got exit code 0\nstdout: {failing_result.stdout!r}\n"
        f"stderr: {failing_result.stderr!r}"
    )
    assert failing_result.stderr.strip(), (
        f"expected non-empty stderr for the injected mid-pass chunk "
        f"failure, got empty stderr\nstdout: {failing_result.stdout!r}"
    )

    source_id = compute_source_id(THESIS_PAPER_PDF)
    checkpoint_path = _chunks_checkpoint_path(root, source_id)
    assert checkpoint_path.exists(), (
        f"expected {checkpoint_path} to exist after a mid-pass chunk "
        f"failure (issue #104 acceptance 3: sections completed before the "
        f"failure are durably persisted) -- got no file at all"
    )
    persisted_after_failure = set(_checkpoint_chunk_ids(checkpoint_path))
    assert persisted_after_failure == first_section_ids, (
        f"expected {checkpoint_path} to carry exactly the first section's "
        f"({sorted(first_section_ids)!r}) chunk records after the mid-pass "
        f"failure -- neither zero records nor every section's (issue #104 "
        f"acceptance 3: 'partial') -- got {sorted(persisted_after_failure)!r}"
    )
    assert persisted_after_failure != all_ids, (
        f"expected the post-failure checkpoint to be a PARTIAL set, not "
        f"every section's chunk_ids ({sorted(all_ids)!r}) -- got exactly "
        f"the full set, meaning the injected failure never actually "
        f"interrupted the pass"
    )
    assert persisted_after_failure, (
        "expected the post-failure checkpoint to carry at least the first "
        "section's records, got zero -- meaning nothing was persisted "
        "incrementally at all"
    )

    # --- Run 2: the healthy resume, with a clean sequence, observed via
    # the record provider to prove no LLM call is re-issued for the
    # already-checkpointed first section. ---
    record_path = root.parent / f"{root.name}_resume_record.jsonl"
    resume_result = _run_vault_write(
        "record",
        str(THESIS_PAPER_PDF),
        cwd=root,
        extra_env={
            CHUNK_RESPONSE_SEQUENCE_ENV_VAR: json.dumps([_VALID_CHUNK_RESPONSE]),
            RECORD_PATH_ENV_VAR: str(record_path),
        },
    )
    _assert_not_argparse_fallback(resume_result, "vault write")
    assert resume_result.returncode == 0, (
        f"expected exit code 0 for the healthy resume after the mid-pass "
        f"failure (issue #104 acceptance 4: 'completes the pass'), got "
        f"{resume_result.returncode}\nstdout: {resume_result.stdout!r}\n"
        f"stderr: {resume_result.stderr!r}"
    )

    chunk_calls = _count_marker_occurrences(record_path, CHUNK_PROMPT_MARKER)
    assert chunk_calls == len(remaining_sections), (
        f"expected the resumed run to make exactly one chunk-pass LLM call "
        f"per SECTION not already checkpointed by run 1 -- i.e. "
        f"{len(remaining_sections)} call(s) for the remaining sections "
        f"{remaining_sections!r} (issue #104 acceptance 4: 'does not "
        f"re-issue LLM calls for the already-checkpointed sections') -- "
        f"got {chunk_calls} call(s) matching {CHUNK_PROMPT_MARKER!r} in "
        f"{record_path}"
    )

    final_ids = set(_checkpoint_chunk_ids(checkpoint_path))
    assert final_ids == all_ids, (
        f"expected {checkpoint_path} to carry every section's chunk_ids "
        f"after the resumed run completes, got {sorted(final_ids)!r} vs. "
        f"expected {sorted(all_ids)!r}"
    )
    assert len(_checkpoint_chunk_ids(checkpoint_path)) == total_records, (
        f"expected exactly {total_records} checkpoint line(s) after the "
        f"resumed run (no chunk re-appended/duplicated), got "
        f"{len(_checkpoint_chunk_ids(checkpoint_path))}"
    )

    for chunk_id in all_ids:
        _find_note_for_chunk(chunk_id, root)
    prose_files = [p for p in _prose_dir(root).iterdir() if p.is_file()]
    assert len(prose_files) == total_records, (
        f"expected exactly {total_records} prose note(s) under "
        f"{_prose_dir(root)} after the resumed run (one per chunk), got "
        f"{len(prose_files)}: {sorted(p.name for p in prose_files)}"
    )


def test_chunk_pass_makes_no_extra_llm_call_when_every_response_is_valid(
    isolated_vault_root, tmp_path_factory
):
    """Acceptance criterion 5 (no regression): with every response valid
    JSON (today's baseline path, no sequence seam engaged at all), the
    chunk pass makes exactly one LLM call per chunkable section -- never an
    extra re-ask call."""
    root = isolated_vault_root
    _, section_labels = _arrange_ground_truth(tmp_path_factory, "baseline")
    assert section_labels == ["Introduction", "Comparative Cases", "Conclusion"]
    total_sections = len(section_labels)

    _arrange_stored_envelope(root, THESIS_PAPER_PDF)

    record_path = root.parent / f"{root.name}_baseline_record.jsonl"
    result = _run_vault_write(
        "record",
        str(THESIS_PAPER_PDF),
        cwd=root,
        extra_env={RECORD_PATH_ENV_VAR: str(record_path)},
    )
    _assert_not_argparse_fallback(result, "vault write")
    assert result.returncode == 0, (
        f"expected exit code 0 for a fully healthy run with no malformed "
        f"responses at all, got {result.returncode}\nstdout: "
        f"{result.stdout!r}\nstderr: {result.stderr!r}"
    )

    chunk_calls = _count_marker_occurrences(record_path, CHUNK_PROMPT_MARKER)
    assert chunk_calls == total_sections, (
        f"expected exactly {total_sections} chunk-pass LLM call(s) -- one "
        f"per chunkable section, no extra re-ask call -- when every "
        f"response is valid JSON (issue #104 acceptance 5: 'no "
        f"regression'), got {chunk_calls} call(s) matching "
        f"{CHUNK_PROMPT_MARKER!r} in {record_path}"
    )
