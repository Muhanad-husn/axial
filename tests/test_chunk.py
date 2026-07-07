"""Outer acceptance test for issue #17, slice 05 (argumentative chunking).

Locked behavioral contract (DEC-1) -- do not edit once committed red.

Given an extracted fixture source with a stored envelope and the stub LLM
      provider
When  the user runs `axial chunk <fixture>`
Then  it exits 0 and emits prose chunks each with a stable chunk_id and its
      section provenance
And   the chunking call received the stored envelope plus the section's
      neighbours (not the isolated section)
And   the stored envelope is read from disk, not recomputed

See specs/PRODUCT.md §5 stage 4 ("Argumentative chunking. For each prose
section, an API call decides chunk boundaries with the envelope plus
surrounding sections in context -- never the isolated section. Chunks
reflect argumentative units (a claim and its support), not fixed sizes.
Output: prose chunks."), §8 P0-4 ("The chunking call receives the envelope +
surrounding sections, not the isolated section." / "Output chunks carry
stable chunk_ids and preserve section provenance."), §7.3 (the envelope
contract: `{source_id, author, title, date, thesis, toc[], scope,
stated_argument}`, "Produced once in stage 3; consumed by stages 4 and 6"),
and §10 ("Envelope reuse: chunking and tagging read the stored envelope
(verified: no recompute).") for the source of truth.

Fixture reuse: tests/fixtures/envelope/thesis_paper.pdf (see
tests/test_envelope.py and its _generate.py) has three top-level sections in
this exact order -- Introduction, Comparative Cases, Conclusion. "Comparative
Cases" is the only section with a neighbour on BOTH sides, so this test
targets it: proving both-sided "surrounding sections" (plural, per the
Gherkin) requires a section with two real neighbours, and no new fixture is
needed since this one already has that shape. Its text is reproduced here
(see _generate.py) only to pick disambiguating markers below -- never to
assert the LLM said anything about it (that would lock stub wording into the
contract, exactly what tests/test_envelope.py's seam decision 3 warns
against).

Seam decision 1 -- provider values, and resolving the shared-stub collision
-----------------------------------------------------------------------
tests/test_envelope.py already locks two `AXIAL_LLM_PROVIDER` values: `stub`
(canned, no network) and `explode` (poison; raises if `.complete()` is ever
called). This test reuses `stub` for the arrange step (`axial envelope`,
unchanged) and locks its extension, plus one new value, for the chunk pass:

    AXIAL_LLM_PROVIDER=stub    -> Today, StubLLMClient._CANNED_RESPONSE is a
                                    single hardcoded ENVELOPE-shaped JSON
                                    (thesis/toc/scope/stated_argument). The
                                    chunk pass calls `client.complete()` with
                                    a CHUNKING prompt and needs a CHUNK-shaped
                                    response back to parse into chunk records.
                                    This test does not dictate the dispatch
                                    mechanism (e.g. inspecting the prompt for
                                    a pass-specific marker, or threading a
                                    response-kind through the client) -- it
                                    only requires, behaviorally, that
                                    `axial envelope ...` and `axial chunk ...`
                                    BOTH work correctly end-to-end against
                                    the very same `AXIAL_LLM_PROVIDER=stub`
                                    selection, in separate process runs. That
                                    is impossible with today's single
                                    hardcoded envelope-only canned response,
                                    so implementing it is this test's whole
                                    point: it is the collision this test
                                    forces the implementer to resolve, not an
                                    assumption this test papers over.

    AXIAL_LLM_PROVIDER=record  -> NEW. Behaves exactly like `stub` for
                                    `.complete()`'s return value (i.e. it
                                    must reuse/delegate to whatever
                                    canned-response logic `stub` ends up
                                    using, so its replies are indistinguishable
                                    from `stub`'s for the same prompt), with
                                    exactly one side effect added: every
                                    prompt received by `.complete()` is
                                    appended, JSON-encoded on its own line
                                    (`json.dumps(prompt) + "\\n"`), to the
                                    file named by the new env var
                                    `AXIAL_LLM_RECORD_PATH` (creating parent
                                    directories as needed), before returning.
                                    Selecting `record` without
                                    `AXIAL_LLM_RECORD_PATH` set is not
                                    exercised by this test (left to the
                                    implementer). This is the seam that makes
                                    the assembled chunk prompt(s) observable
                                    black-box from a subprocess test --
                                    mirroring slice-04's provider-as-seam
                                    pattern (there, `explode` proves the
                                    ABSENCE of a call; here, `record` proves
                                    the PRESENCE and CONTENT of calls).
                                    Reusing `stub`'s response logic (rather
                                    than inventing a second, independent
                                    canned chunk-response contract) sidesteps
                                    having to predict, from the test side,
                                    the LLM-facing raw response shape the
                                    implementer's own parser will expect --
                                    this test only needs the calls to
                                    complete successfully so every section
                                    gets a chance to be recorded, not to
                                    dictate that shape itself.

Seam decision 2 -- observing "envelope + neighbours, not the isolated
section" black-box
-----------------------------------------------------------------------
A subprocess-based outer test cannot see an in-process prompt. Using the
`record` provider above, this test locates the one recorded prompt that
targets the "Comparative Cases" section (identified by a sentence that
appears ONLY in that section's own text -- see _TARGET_SECTION_MARKER below)
and asserts that SAME prompt also contains:

  (a) a clause from the Introduction section's own text that the stored
      envelope's fields do NOT restate (_INTRO_NEIGHBOUR_MARKER) -- proving
      the previous neighbour's actual text, not just an envelope paraphrase,
      was forwarded;
  (b) a clause from the Conclusion section's own text that the stored
      envelope's fields do NOT restate (_CONCLUSION_NEIGHBOUR_MARKER) --
      same proof for the next neighbour;
  (c) the stored envelope's own `stated_argument` value, read back from the
      envelope JSON on disk at test time (never hardcoded here -- see seam
      decision 3) -- proving the envelope itself, not just neighbouring
      prose, reached the same call.

Because (a), (b), and (c) can only ALL be true simultaneously if the
assembled prompt combined the target section, both its neighbours, and the
envelope, this is a hard behavioral proof of "envelope + neighbours, not the
isolated section" (PRD §5 stage 4 / §8 P0-4), not a scrape of an incidental
log line.

Disambiguation matters here because this fixture's body text and the stub's
canned envelope fields are deliberately close paraphrases of each other (see
tests/fixtures/envelope/_generate.py's docstring). The markers below are
chosen so their presence in the prompt cannot be explained away as "the
envelope again" or "the target section again":
  - _INTRO_NEIGHBOUR_MARKER and _CONCLUSION_NEIGHBOUR_MARKER are the exact
    clauses of Introduction/Conclusion that the stub's canned envelope
    response (see StubLLMClient._CANNED_RESPONSE in src/axial/llm.py) never
    restates at all, or restates with different case/punctuation at the
    exact position that would make a literal-substring match succeed by
    coincidence (verified by inspection against that constant when this test
    was authored).
  - the envelope's `stated_argument` is checked as an exact-case substring;
    Conclusion's own paraphrase of it differs in leading case and trailing
    punctuation at precisely that point, so a literal match can only be
    explained by the envelope field being forwarded, not by Conclusion (a
    neighbour) supplying the same words independently.

Seam decision 3 -- observing "the stored envelope is read from disk, not
recomputed" black-box
-----------------------------------------------------------------------
Unlike the envelope pass (tests/test_envelope.py), the chunk pass itself
makes an LLM call (to decide chunk boundaries), so slice-04's `explode`
poison-provider trick does not transfer wholesale -- configuring `explode`
here would only prove the chunking call itself never happened, not that the
envelope specifically was reused rather than rebuilt. Instead this test
proves "read, not recomputed" two ways:
  (a) the envelope's own `stated_argument` field value (read from the
      envelope JSON file on disk, never hardcoded) appears inside the
      chunking prompt -- proving it was read (seam decision 2(c) above);
  (b) `data/envelopes/<source_id>.json` is byte-for-byte identical before and
      after the `axial chunk` run that consumed it (captured and compared
      exactly as tests/test_envelope.py compares first_bytes/second_bytes)
      -- proving the chunk pass never rewrote/regenerated it.

This test deliberately does NOT assert a "no envelope on disk" error path
(e.g. running `axial chunk` before `axial envelope`); that is left as an
inner unit test for the implementer, per the slice plan's inner-loop list,
to keep this outer test focused on the acceptance criterion itself.

Seam decision 4 -- chunk record shape locked by this test
-----------------------------------------------------------------------
Neither the PRD nor the slice plan names an exact stdout envelope shape or
an exact field name for "section provenance" beyond intent, so this test
locks the minimum needed to make the acceptance criterion executable:
  - stdout must contain one or more chunk record JSON objects, either as
    (i) a single JSON document that is a bare top-level array, (ii) a single
    JSON document that is an object with a top-level "chunks" array, or
    (iii) newline-delimited JSON (one chunk record object per line). This
    test's parsing helper accepts any of the three, since none is dictated
    by the source of truth and picking exactly one here would over-commit
    the contract to an accidental implementation choice.
  - each chunk record carries "chunk_id" (a non-empty string, unique within
    a single run, and stable/deterministic across repeat runs on the same
    input -- proven behaviorally: two consecutive stub runs over the same
    fixture must yield the identical set of chunk_id values) and "section"
    (the section's own verbatim heading text -- one of "Introduction",
    "Comparative Cases", "Conclusion" for this fixture). This test locks the
    field name `section` for "section provenance" since a name must be
    chosen to write an executable contract, and "section" is the smallest,
    least implementation-committal name that satisfies the plan bullet
    ("chunk records preserve the section's verbatim label").
  - this test deliberately does NOT assert exact chunk text/count/boundaries
    (which stub content and boundary heuristics produce), only the shape and
    stability of chunk_id + section -- mirroring tests/test_envelope.py's
    refusal to lock exact canned stub wording into the contract.

Test hygiene: any envelope file this test creates under data/envelopes/ is
removed in fixture teardown (mirrors tests/test_envelope.py's
clean_envelopes). The recorded-prompt file lives under pytest's `tmp_path`,
so it is never written into the repo and needs no manual cleanup.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "envelope"
ENVELOPES_DIR = REPO_ROOT / "data" / "envelopes"

THESIS_PAPER_PDF = FIXTURES_DIR / "thesis_paper.pdf"

PROVIDER_ENV_VAR = "AXIAL_LLM_PROVIDER"
RECORD_PATH_ENV_VAR = "AXIAL_LLM_RECORD_PATH"

KNOWN_SECTION_LABELS = {"Introduction", "Comparative Cases", "Conclusion"}

# Sentence that appears ONLY in the "Comparative Cases" section's own body
# text (see tests/fixtures/envelope/_generate.py) -- identifies which
# recorded prompt targeted that section.
_TARGET_SECTION_MARKER = "is not itself part of the envelope this fixture exercises"

# Clause from Introduction's own text that the stub's canned envelope
# response never restates (StubLLMClient._CANNED_RESPONSE's "thesis" field
# stops at "...coercive force alone." and never mentions "the remainder of
# the paper..."). Its presence in a chunk prompt can only be explained by the
# Introduction section (the previous neighbour) itself being forwarded.
_INTRO_NEIGHBOUR_MARKER = (
    "The remainder of the paper develops this thesis across a survey of comparative cases."
)

# Clause from Conclusion's own text that the stub's canned envelope response
# never restates (StubLLMClient._CANNED_RESPONSE's "stated_argument" field
# stops at "...coercive capacity alone." and never mentions "restating the
# paper's stated thesis..."). Its presence in a chunk prompt can only be
# explained by the Conclusion section (the next neighbour) itself being
# forwarded.
_CONCLUSION_NEIGHBOUR_MARKER = "restating the paper's stated thesis in light of the cases surveyed"

# argparse's fallback error for an as-yet-nonexistent subcommand, e.g.
# "axial: error: argument command: invalid choice: 'chunk' (choose from
# 'schema', 'intake', 'extract', 'envelope')". Any of these substrings in the
# combined output means the target subcommand's logic was never actually
# exercised -- the process failed before real behavior ran. Reject that
# generic failure mode explicitly so this test can only pass once real
# `chunk` behavior exists.
ARGPARSE_FALLBACK_MARKERS = (
    "invalid choice",
    "unrecognized arguments",
)


def _run_axial(
    command: str,
    provider: str,
    *args: str,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env[PROVIDER_ENV_VAR] = provider
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["uv", "run", "axial", command, *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=env,
    )


def _run_envelope(provider: str, *args: str) -> subprocess.CompletedProcess:
    return _run_axial("envelope", provider, *args)


def _run_chunk(
    provider: str, *args: str, extra_env: dict[str, str] | None = None
) -> subprocess.CompletedProcess:
    return _run_axial("chunk", provider, *args, extra_env=extra_env)


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


def _parse_chunk_records(stdout: str) -> list[dict]:
    """Parse chunk records from `axial chunk`'s stdout, tolerating any of
    the three stdout shapes this test locks (see module docstring, seam
    decision 4): a bare JSON array, a JSON object with a "chunks" array, or
    newline-delimited JSON (one record per line)."""
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
                f"document (a bare array, or an object with a top-level "
                f"'chunks' array) or newline-delimited JSON (one chunk "
                f"record object per line); line {line!r} failed to parse "
                f"({exc}). Full stdout: {stdout!r}"
            ) from None
    assert records, (
        f"expected at least one parseable chunk record in stdout, got none. stdout: {stdout!r}"
    )
    return records


@pytest.fixture
def clean_envelopes():
    """Snapshot data/envelopes/*.json before the test and delete any file
    the test caused to appear, so runs stay idempotent and the repo is
    never polluted by a real e2e-run artifact."""
    before = _existing_envelope_files()
    yield
    after = _existing_envelope_files()
    for created in after - before:
        created.unlink()


def _arrange_stored_envelope() -> Path:
    """Run `axial envelope` with the stub provider so a stored envelope
    exists on disk before chunking, and return its path. Asserts the arrange
    step itself succeeded and produced exactly one new envelope file."""
    before_files = _existing_envelope_files()

    result = _run_envelope("stub", str(THESIS_PAPER_PDF))
    _assert_not_argparse_fallback(result, "envelope")
    assert result.returncode == 0, (
        f"arrange step failed: expected exit code 0 for `axial envelope` on "
        f"the fixture with the stub LLM provider, got {result.returncode}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    new_files = _existing_envelope_files() - before_files
    assert len(new_files) == 1, (
        f"arrange step failed: expected exactly one new file under "
        f"{ENVELOPES_DIR} after `axial envelope`, got {len(new_files)}: "
        f"{sorted(new_files)}\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    return next(iter(new_files))


def test_chunk_emits_stable_chunk_ids_with_section_provenance(clean_envelopes):
    envelope_path = _arrange_stored_envelope()
    envelope_bytes_before = envelope_path.read_bytes()

    # --- first run: stub provider ---
    first = _run_chunk("stub", str(THESIS_PAPER_PDF))
    _assert_not_argparse_fallback(first, "chunk")
    assert first.returncode == 0, (
        f"expected exit code 0 for `axial chunk` on a fixture source with a "
        f"stored envelope and the stub LLM provider configured, got "
        f"{first.returncode}\nstdout: {first.stdout!r}\nstderr: {first.stderr!r}"
    )

    first_records = _parse_chunk_records(first.stdout)
    assert len(first_records) >= 1, (
        f"expected at least one prose chunk record on stdout, got "
        f"{len(first_records)}; stdout: {first.stdout!r}"
    )

    first_chunk_ids: set[str] = set()
    for record in first_records:
        assert isinstance(record, dict), (
            f"expected each chunk record to be a JSON object, got "
            f"{type(record).__name__}: {record!r}"
        )

        chunk_id = record.get("chunk_id")
        assert isinstance(chunk_id, str) and chunk_id.strip(), (
            f"expected chunk record to carry a non-empty string 'chunk_id' "
            f"(PRD §8 P0-4, 'stable chunk_ids'), got {chunk_id!r} "
            f"(full record: {record!r})"
        )
        assert chunk_id not in first_chunk_ids, (
            f"expected chunk_ids to be unique within a single run, got a duplicate: {chunk_id!r}"
        )
        first_chunk_ids.add(chunk_id)

        section = record.get("section")
        assert section in KNOWN_SECTION_LABELS, (
            f"expected chunk record to carry a 'section' field naming one of "
            f"this fixture's verbatim section headings {sorted(KNOWN_SECTION_LABELS)} "
            f"(PRD §8 P0-4, 'preserve section provenance'), got {section!r} "
            f"(full record: {record!r})"
        )

    # --- second run: same fixture, same stub provider -- chunk_ids must be stable ---
    second = _run_chunk("stub", str(THESIS_PAPER_PDF))
    _assert_not_argparse_fallback(second, "chunk")
    assert second.returncode == 0, (
        f"expected exit code 0 on a repeat `axial chunk` run over the same "
        f"fixture, got {second.returncode}\n"
        f"stdout: {second.stdout!r}\nstderr: {second.stderr!r}"
    )

    second_records = _parse_chunk_records(second.stdout)
    second_chunk_ids = {r.get("chunk_id") for r in second_records}

    assert second_chunk_ids == first_chunk_ids, (
        f"expected stable/deterministic chunk_ids across repeat runs on the "
        f"same input (PRD §8 P0-4, 'stable chunk_ids'), got "
        f"{sorted(first_chunk_ids)} on the first run and "
        f"{sorted(second_chunk_ids)} on the second run"
    )

    # --- the stored envelope itself must be untouched by chunking ---
    assert envelope_path.read_bytes() == envelope_bytes_before, (
        f"expected {envelope_path} to be unchanged after `axial chunk` runs "
        f"(the envelope must be read, not recomputed/rewritten -- PRD §10 "
        f"'no recompute'; see also "
        f"test_chunk_call_receives_envelope_and_neighbouring_sections_not_isolated_section)"
    )


def test_chunk_call_receives_envelope_and_neighbouring_sections_not_isolated_section(
    clean_envelopes, tmp_path
):
    envelope_path = _arrange_stored_envelope()
    envelope_bytes_before = envelope_path.read_bytes()
    envelope = json.loads(envelope_bytes_before)

    stated_argument = envelope.get("stated_argument")
    assert isinstance(stated_argument, str) and stated_argument.strip(), (
        f"arrange step failed: expected the stored envelope to carry a "
        f"non-empty 'stated_argument' field, got {stated_argument!r} "
        f"(full envelope: {envelope!r})"
    )

    record_path = tmp_path / "chunk_prompts.jsonl"

    result = _run_chunk(
        "record",
        str(THESIS_PAPER_PDF),
        extra_env={RECORD_PATH_ENV_VAR: str(record_path)},
    )
    _assert_not_argparse_fallback(result, "chunk")
    assert result.returncode == 0, (
        f"expected exit code 0 for `axial chunk` with "
        f"AXIAL_LLM_PROVIDER=record configured -- this provider must behave "
        f"exactly like `stub` for response purposes (see this test module's "
        f"docstring, seam decision 1), so a nonzero exit here means either "
        f"the `record` provider was not implemented or it does not delegate "
        f"to the same response logic `stub` uses, got {result.returncode}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    assert record_path.exists(), (
        f"expected `AXIAL_LLM_PROVIDER=record` (with "
        f"{RECORD_PATH_ENV_VAR}={str(record_path)!r}) to write each "
        f"received chunking prompt to that file (this test's locked seam -- "
        f"see module docstring seam decision 1); the file was never created, "
        f"meaning either the `record` provider does not exist yet or it "
        f"never honored {RECORD_PATH_ENV_VAR}"
    )

    recorded_prompts: list[str] = []
    for line in record_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        recorded_prompts.append(json.loads(line))

    assert recorded_prompts, (
        f"expected at least one recorded chunking prompt at {record_path}, "
        f"got none -- the chunking pass never called the LLM client with "
        f"AXIAL_LLM_PROVIDER=record configured"
    )

    target_prompts = [p for p in recorded_prompts if _TARGET_SECTION_MARKER in p]
    assert target_prompts, (
        f"expected at least one recorded chunking prompt to contain the "
        f"'Comparative Cases' section's own text (marker: "
        f"{_TARGET_SECTION_MARKER!r}), proving that section was ever sent "
        f"to the chunking call at all; got {len(recorded_prompts)} recorded "
        f"prompt(s), none matching. Recorded prompts (truncated each): "
        f"{[p[:500] for p in recorded_prompts]!r}"
    )

    matched = next(
        (
            prompt
            for prompt in target_prompts
            if _INTRO_NEIGHBOUR_MARKER in prompt
            and _CONCLUSION_NEIGHBOUR_MARKER in prompt
            and stated_argument in prompt
        ),
        None,
    )
    assert matched is not None, (
        f"expected the recorded chunking prompt for the 'Comparative Cases' "
        f"section (identified by marker {_TARGET_SECTION_MARKER!r}) to also "
        f"contain: the Introduction neighbour's own text (marker "
        f"{_INTRO_NEIGHBOUR_MARKER!r}), the Conclusion neighbour's own text "
        f"(marker {_CONCLUSION_NEIGHBOUR_MARKER!r}), and the stored "
        f"envelope's stated_argument field ({stated_argument!r}) -- proving "
        f"the chunking call received the envelope plus the section's "
        f"neighbours, not the isolated section (PRD §5 stage 4, §8 P0-4). "
        f"Found {len(target_prompts)} prompt(s) mentioning 'Comparative "
        f"Cases' but none contained all three. First such prompt "
        f"(truncated): {target_prompts[0][:2000]!r}"
    )

    # "read from disk, not recomputed": the envelope file itself must be
    # byte-for-byte unchanged after the chunk run that consumed it.
    assert envelope_path.read_bytes() == envelope_bytes_before, (
        f"expected {envelope_path} to be byte-for-byte unchanged after "
        f"`axial chunk` ran (the envelope must be read, not "
        f"recomputed/rewritten -- PRD §10 'no recompute'), but its contents "
        f"differ"
    )
