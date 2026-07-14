"""Outer acceptance test for issue #16, slice 04 (structural envelope).

Locked behavioral contract (DEC-1) -- do not edit once committed red.

Given an extracted fixture source and the LLM provider configured to the
      stub client
When  the user runs `axial envelope <fixture>`
Then  it exits 0 and writes data/envelopes/<source_id>.json with thesis,
      toc, scope, and stated_argument
And   running `axial envelope <fixture>` again reuses the stored envelope
      without a second LLM call

See specs/PRODUCT.md §5 stage 3 ("Structural-envelope pass. One API call per
source extracts the author's stated thesis, table of contents, scope, and
stated argument from intro/abstract/conclusion. This 'envelope' is produced
once and reused by every later stage for that source. Output: envelope
(JSON).") and §7.3 ("One JSON per source in data/envelopes/:
{source_id, author, title, date, thesis, toc[], scope, stated_argument}.
Produced once in stage 3; consumed by stages 4 and 6...") and §8 P0-3
("One envelope JSON per source containing thesis, TOC, scope, stated
argument." / "The envelope is written once and read by chunking and
tagging (not recomputed).") and §10 ("Envelope reuse: chunking and tagging
read the stored envelope (verified: no recompute).") for the source of
truth.

Seam decision 1 -- provider selection (this test's locked contract; the
implementer builds to this shape)
-----------------------------------------------------------------------
The LLM provider is selected via an environment-variable override,
`AXIAL_LLM_PROVIDER`, mirroring the `AXIAL_FORCE_DOCLING_FAILURE`
fault-injection convention already established in `src/axial/extract.py`.
No `config/pipeline.yaml` edit and no network access are required to drive
this test. Two provider values are locked by this test and MUST be
implemented, selectable purely via the env var, with no live network call
in either:

    AXIAL_LLM_PROVIDER=stub     -> a StubLLMClient that returns a
                                     fixture-canned envelope response
                                     (non-empty thesis/toc/scope/
                                     stated_argument) without any network
                                     access.
    AXIAL_LLM_PROVIDER=explode  -> a poison client whose completion method
                                     raises if it is ever invoked. Selecting
                                     this provider must NOT itself be an
                                     error -- only calling its completion
                                     method is fatal. This is the seam this
                                     test uses to prove "no recompute" (see
                                     seam decision 2 below).

Seam decision 2 -- observing "no second LLM call" black-box
-----------------------------------------------------------------------
A subprocess-based outer test cannot observe an in-process call counter.
Instead of scraping a stderr log string (which would silently become part
of the locked contract), this test proves the "no recompute" guarantee
(§10) behaviorally: the SECOND run is executed with
`AXIAL_LLM_PROVIDER=explode` -- a provider that raises if its completion
method is ever invoked. If the envelope pass tried to recompute on the
second run, the process would crash (nonzero exit / exception). Because the
second run must still exit 0 and must leave the envelope file byte-for-byte
identical to the first run's output, a passing test is only possible if the
LLM was never called the second time. This is a hard behavioral assertion,
not a log-string scrape.

Seam decision 3 -- envelope contents asserted
-----------------------------------------------------------------------
This test asserts, at minimum, that `data/envelopes/<source_id>.json`:
  - exists after the first run and parses as JSON;
  - is an object carrying non-empty `thesis` (str), `toc` (a non-empty
    list), `scope` (str), and `stated_argument` (str) -- the four fields
    the acceptance criterion names explicitly.
It deliberately does NOT assert exact canned stub content (e.g. specific
thesis wording), since that would lock the stub's fixture text as part of
the behavioral contract rather than the shape of the envelope itself.

The exact `<source_id>` naming scheme is left to the implementer (it is not
specified by the PRD beyond "one JSON per source"). This test does not
hardcode a source_id: it snapshots `data/envelopes/*.json` before the first
run and asserts that running envelope produces exactly one new file there,
then operates on whichever file that is.

Fixture: tests/fixtures/envelope/thesis_paper.pdf -- a dedicated,
born-digital, deterministic fixture (see _generate.py in the same
directory) with a real Introduction (stating a thesis) and a real
Conclusion (restating the argument), the minimal shape the envelope pass
needs. tests/fixtures/extract/prose_and_table.pdf was not reused because
its second section is headed "Discussion", not "Conclusion".

Test hygiene: any envelope file this test creates under data/envelopes/ is
removed in fixture teardown so repeated runs are idempotent and the repo
is never polluted by a real e2e-run artifact.

Arrange-mechanism change (issue #45, tree-cache) -- no behavioral assertion
changed
-----------------------------------------------------------------------
This test's PURPOSE is the envelope pass's own behavior (thesis/toc/scope/
stated_argument written from the LLM's response; reuse without a second LLM
call) -- it consumes the structural tree only as input to the envelope
prompt, it never asserts anything about extraction/tree shape itself (that
is tests/test_extract.py's contract). `run_envelope` calls `axial.extract.
extract`, which -- per the now-locked tree-persist contract
(tests/test_tree_persist.py, PRD §7.4) -- reuses a persisted tree verbatim
at data/trees/<source_id>.json instead of re-running docling. So this test
now pre-places the committed REAL tree fixture (tests/fixtures/envelope/
thesis_paper_tree.json -- exactly `axial extract`'s own output for this
fixture, see that directory's _generate.py for the regeneration recipe)
before the first `axial envelope` run, exactly as it would look after a real
extraction, only without paying for one. Every existing assertion is
unchanged: the stub LLM response (and therefore the envelope's own written
content) does not depend on the source text at all, so this is purely an
arrange-mechanism speedup, not a behavior change. data/trees/ isolation is
handled by the shared, content-snapshot-based
`_isolate_persisted_tree_and_envelope_state` autouse fixture in
tests/conftest.py.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from axial.envelope import compute_source_id

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "envelope"
ENVELOPES_DIR = REPO_ROOT / "data" / "envelopes"
TREES_DIR = REPO_ROOT / "data" / "trees"

THESIS_PAPER_PDF = FIXTURES_DIR / "thesis_paper.pdf"
THESIS_PAPER_TREE_FIXTURE = FIXTURES_DIR / "thesis_paper_tree.json"

PROVIDER_ENV_VAR = "AXIAL_LLM_PROVIDER"

# argparse's fallback error for an as-yet-nonexistent `envelope` subcommand,
# e.g. "axial: error: argument command: invalid choice: 'envelope' (choose
# from 'schema', 'intake', 'extract')". Any of these substrings in the
# combined output means envelope logic was never actually exercised -- the
# process failed before real envelope code ran. Reject that generic failure
# mode explicitly so this test can only pass once real `envelope` behavior
# exists.
ARGPARSE_FALLBACK_MARKERS = (
    "invalid choice",
    "unrecognized arguments",
)


def _run_envelope(provider: str, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env[PROVIDER_ENV_VAR] = provider
    return subprocess.run(
        ["uv", "run", "axial", "envelope", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=env,
    )


def _assert_not_argparse_fallback(result: subprocess.CompletedProcess) -> None:
    combined = result.stdout + result.stderr
    for marker in ARGPARSE_FALLBACK_MARKERS:
        assert marker not in combined, (
            f"expected a real `envelope` behavior path, not an argparse "
            f"fallback (found {marker!r}) -- this means the `envelope` "
            f"subcommand does not exist yet or was never reached:\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )


def _existing_envelope_files() -> set[Path]:
    if not ENVELOPES_DIR.exists():
        return set()
    return set(ENVELOPES_DIR.glob("*.json"))


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


def test_envelope_writes_once_and_reuses_without_a_second_llm_call(clean_envelopes):
    before_files = _existing_envelope_files()

    # --- arrange: pre-place the real tree fixture so the envelope pass
    # doesn't pay for a real docling run for input it never asserts on
    # (issue #45; see module docstring, "Arrange-mechanism change") ---
    _place_tree_fixture(THESIS_PAPER_PDF, THESIS_PAPER_TREE_FIXTURE)

    # --- first run: stub provider, must produce exactly one new envelope file ---
    first = _run_envelope("stub", str(THESIS_PAPER_PDF))

    _assert_not_argparse_fallback(first)

    assert first.returncode == 0, (
        f"expected exit code 0 for `axial envelope` on a fixture source "
        f"with the stub LLM provider configured, got {first.returncode}\n"
        f"stdout: {first.stdout!r}\nstderr: {first.stderr!r}"
    )

    after_first_files = _existing_envelope_files()
    new_files = after_first_files - before_files
    assert len(new_files) == 1, (
        f"expected exactly one new file under {ENVELOPES_DIR} after the "
        f"first `axial envelope` run, got {len(new_files)}: {sorted(new_files)}\n"
        f"stdout: {first.stdout!r}\nstderr: {first.stderr!r}"
    )
    envelope_path = next(iter(new_files))

    first_bytes = envelope_path.read_bytes()
    try:
        envelope = json.loads(first_bytes)
    except json.JSONDecodeError as exc:
        raise AssertionError(
            f"expected {envelope_path} to contain a single parseable JSON "
            f"document, got a parse error ({exc}); contents: {first_bytes!r}"
        ) from None

    assert isinstance(envelope, dict), (
        f"expected the envelope JSON at {envelope_path} to be an object, "
        f"got {type(envelope).__name__}: {envelope!r}"
    )

    for field in ("thesis", "scope", "stated_argument"):
        assert field in envelope, (
            f"expected the envelope at {envelope_path} to carry a {field!r} "
            f"field (PRD §7.3), got keys: {sorted(envelope.keys())}"
        )
        value = envelope[field]
        assert isinstance(value, str) and value.strip(), (
            f"expected envelope field {field!r} to be a non-empty string, "
            f"got {value!r} (full envelope: {envelope!r})"
        )

    assert "toc" in envelope, (
        f"expected the envelope at {envelope_path} to carry a `toc` field "
        f"(PRD §7.3), got keys: {sorted(envelope.keys())}"
    )
    toc = envelope["toc"]
    assert isinstance(toc, list) and len(toc) > 0, (
        f"expected envelope field `toc` to be a non-empty list, got "
        f"{toc!r} (full envelope: {envelope!r})"
    )

    # --- second run: poison ("explode") provider -- must NOT be invoked ---
    # If the envelope pass recomputed instead of reusing the stored file,
    # the explode provider's completion method would raise and this run
    # would fail to exit 0. A passing test proves zero LLM calls happened.
    second = _run_envelope("explode", str(THESIS_PAPER_PDF))

    _assert_not_argparse_fallback(second)

    assert second.returncode == 0, (
        f"expected exit code 0 on the second `axial envelope` run for a "
        f"source that already has a stored envelope -- the poison "
        f"('explode') LLM provider is configured on this run and must "
        f"raise if invoked, so a nonzero exit here means the envelope pass "
        f"recomputed instead of reusing the stored file (PRD §10, "
        f"'no recompute'), got {second.returncode}\n"
        f"stdout: {second.stdout!r}\nstderr: {second.stderr!r}"
    )

    after_second_files = _existing_envelope_files()
    assert after_second_files == after_first_files, (
        f"expected no new or removed envelope files on the second run "
        f"(source already has a stored envelope), got new set "
        f"{sorted(after_second_files)} vs. first-run set "
        f"{sorted(after_first_files)}"
    )

    second_bytes = envelope_path.read_bytes()
    assert second_bytes == first_bytes, (
        f"expected {envelope_path} to be byte-for-byte unchanged after the "
        f"second run (the envelope must be reused, not recomputed/rewritten "
        f"-- PRD §10 'no recompute'), but its contents differ.\n"
        f"first run bytes: {first_bytes!r}\nsecond run bytes: {second_bytes!r}"
    )


def test_envelope_nonexistent_file_does_not_crash_uninformatively(clean_envelopes):
    missing = FIXTURES_DIR / "does_not_exist.pdf"
    result = _run_envelope("stub", str(missing))

    _assert_not_argparse_fallback(result)

    assert result.returncode != 0, (
        f"expected nonzero exit code for a nonexistent source file, got 0\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    combined = result.stdout + result.stderr
    assert missing.name in combined, (
        f"expected the error message to name the missing file "
        f"{missing.name!r}, got:\nstdout: {result.stdout!r}\n"
        f"stderr: {result.stderr!r}"
    )
