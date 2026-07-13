"""Outer acceptance test for issue #121 (pipeline-ready canary gate).

Locked behavioral contract (DEC-1) -- do not edit once committed red.

Founder-ratified decisions this test encodes (see the dispatch for issue
#121 and docs/postmortem/gold-run-2026-07/canary-set.md, "The 'pipeline
ready' bar"):

  - A new CLI subcommand, `axial pipeline-ready --manifest <path>`, reads a
    TOML manifest of canaries, ingests each one, evaluates it against the
    "pipeline ready" bar, and prints a per-canary PASS/FAIL table.
  - Exit code is non-zero if ANY canary fails; 0 iff every canary passes.
  - Per-canary manifest entries carry `source_id`, `time_envelope_sec`, and
    `quarantine_budget` (a fraction, e.g. 0.02).
  - The bar (criteria 1-3 of the postmortem's four; criterion 4, suite-green,
    is explicitly out of THIS command's scope):
      1. The canary ingests end-to-end in a single attempt, unattended.
      2. Zero source-fatal chunk errors; per-chunk problems resolve to a
         logged quarantine, and the quarantined fraction stays under the
         canary's own `quarantine_budget`.
      3. Bounded wall clock: the recorded duration stays within the
         canary's own `time_envelope_sec`.

This is a STUB-provider test: the real 5-canary corpus
(docs/postmortem/gold-run-2026-07/canary-set.md) lives in the gitignored
`data/sources/` and is never read here (DEC-23, copyright: no book text in
this repo). Every source this test drives is a small, wholly synthetic
stand-in committed under tests/fixtures/pipeline_ready/ -- no real book
content anywhere in this file or its fixtures. The real production manifest
naming the 5 real canaries (`config/canary-manifest.toml`) is a SEPARATE
deliverable (the implementer's/orchestrator's), out of scope here; this test
only ever points `--manifest` at its own synthetic fixture manifests.

Seam decision 1 -- the manifest schema this test locks includes a fourth
field, `source_path`, beyond the three founder-ratified ones
-----------------------------------------------------------------------
The ratified fields (`source_id`, `time_envelope_sec`, `quarantine_budget`)
describe the substantive per-canary bar this command evaluates; they say
nothing about how the command locates each canary's actual file on disk.
Nothing else in this codebase establishes a source-directory convention
today (verified: no `data/sources/`-shaped constant or config key exists
anywhere under src/axial), so this test -- the FIRST thing to define this
manifest's on-disk shape at all -- adds `source_path` (an absolute path,
computed fresh at test run time, never a hardcoded machine-specific string
baked into a committed file) as the fourth field every canary entry carries.
This is additive, not a deviation from the ratified three: every manifest
this test writes still carries all three ratified fields, verbatim, with
their ratified names and semantics.

Seam decision 2 -- `source_id` is computed, never invented
-----------------------------------------------------------------------
Mirroring tests/test_ingest.py's seam decision 5 exactly: each manifest
entry's `source_id` is `axial.envelope.compute_source_id(source_path)`,
computed directly from the real fixture file at test time, never a
hand-picked label. This is the safer of the two possible designs regardless
of whether the implementer's own `pipeline-ready` treats the manifest's
`source_id` as a mere display label or re-derives/verifies it against the
file it resolves via `source_path` -- either way, this test's manifest is
correct.

Seam decision 3 -- the per-canary table is asserted by COLUMN NAME, not
position or exact prose
-----------------------------------------------------------------------
This test locks the table's shape minimally: one line to stdout carrying, at
least, the tab-separated column names `source_id` and `verdict` (a header
row), followed by one tab-separated data row per canary in the manifest
(any order), each row's `verdict` value being exactly the literal string
`PASS` or `FAIL`. Every assertion below looks a canary's row up by its own
`source_id`, never by row position, and never by matching a whole line/
sentence verbatim -- so the implementer is free to add further columns
(e.g. a human-readable reason, or criterion-level detail) without breaking
this test, and free to order rows however is natural to implement.

Seam decision 4 -- driving each FAIL scenario as its OWN single-canary
manifest/invocation, never several canaries sharing one fault-injection
budget
-----------------------------------------------------------------------
`AXIAL_STUB_TAG_FAIL_AT` / `AXIAL_STUB_TAG_RESPONSE_SEQUENCE` (src/axial/
llm.py) drive their fault injection off a PER-PROCESS call counter shared
across every canary `pipeline-ready` ingests in one invocation -- so
scripting "canary A's 3rd chunk misbehaves, but canary B stays clean" inside
a single process would require hardcoding the exact number of LLM calls
canary A makes AND the exact order `pipeline-ready` processes canaries in,
neither of which any founder ruling or existing code pins down (that
processing order is an internal implementation detail this test must not
assume). Each FAIL-path test below therefore drives its own single-canary
manifest in its own `pipeline-ready` invocation, keeping its fault-injection
sequence unambiguous and independent of any cross-canary processing-order
assumption. The all-PASS test needs no fault injection at all, so it alone
safely carries more than one canary per invocation, proving the table lists
one row per manifest entry.

Cross-test differentiation against a trivial/hardcoded implementation: the
all-PASS test (clean canaries -> PASS, exit 0) and each FAIL test (a single
specific fault -> that canary's row is FAIL, exit non-zero) sit in the same
module and are both run by the outer suite -- an implementation that always
prints PASS would fail every FAIL-path test here; one that always prints
FAIL would fail the all-PASS test. No single test needs to mix PASS and FAIL
canaries in one manifest to prove the gate is not a constant.

Seam decision 5 -- fixtures: synthetic .docx sources + one shared,
hand-authored tree fixture
-----------------------------------------------------------------------
`axial.extract.extract` always calls `axial.intake.intake` FIRST, even when a
source's structural tree is already persisted (src/axial/extract.py's own
`extract()`: intake, then check the cache) -- so every synthetic source here
must be a genuinely valid, minimal `.docx` with a real (if trivial) text
layer, not an arbitrary placeholder file. `.docx` (not `.pdf`) is chosen
because `python-docx` (already a dependency; `axial.intake` imports it
directly) makes generating one trivial, from committed source cheap. Four
such fixtures are committed under tests/fixtures/pipeline_ready/
(clean_pass_1.docx, clean_pass_2.docx, quarantine_fail.docx,
fatal_out_of_vocab.docx), each a few sentences of wholly synthetic,
copyright-clean placeholder prose, each with genuinely distinct bytes (so
`compute_source_id`, a content hash, never collides across them).

The persisted structural TREE these sources resolve to, however, is
independent of the real .docx bytes once cached (mirrors
tests/test_ingest.py's / tests/test_tag_vocab_reask.py's own
`_place_tree_fixture` pattern exactly: the tree is pre-placed at
`data/trees/<source_id>.json` so `extract()` reuses it verbatim instead of
running docling) -- and the stub chunk-pass response is itself a fixed
canned two-chunk array regardless of the tree's own text
(`StubLLMClient._CANNED_CHUNK_RESPONSE`, src/axial/llm.py) -- so one shared,
hand-authored tree fixture (a single section, single body paragraph:
tests/fixtures/pipeline_ready/single_section_tree.json) is copied under
every canary's own source_id-keyed path, exactly like
tests/test_ingest.py's shared-fixture-content-under-distinct-keys technique.
Every canary built this way yields exactly 2 chunks via exactly one
chunk-pass LLM call (verified empirically while drafting this test), which
is what lets the malformed_json quarantine scenario below poison exactly one
of two chunks deterministically.

Seam decision 6 -- driving quarantine-over-budget via `malformed_json`
only, never `content_filter`
-----------------------------------------------------------------------
`ContentRefusedError` (the `content_filter` quarantine reason,
tests/test_tag_quarantine.py) is raised only inside the REAL
`OpenRouterClient`'s own content-moderation handling
(`src/axial/llm.py`'s `_reroute_content_filter`) -- verified directly: no
existing `AXIAL_LLM_PROVIDER=stub` seam can raise it (`AXIAL_STUB_TAG_FAIL_AT`
raises a plain `StubInjectedTagFailureError`, an ordinary `LLMError` that
propagates as today's transient/hard-failure path, never a quarantine).
`malformed_json`, by contrast, IS reachable from the real stub: a raw,
non-JSON string from `AXIAL_STUB_TAG_RESPONSE_SEQUENCE` exhausts
`complete_json`'s bounded retry budget exactly as a real model's malformed
output would. Since `run_tag`'s classification of WHICH failure classes
quarantine (`content_filter`, `malformed_json`) vs. hard-error
(out-of-vocab) is already locked, separately, by tests/test_tag_quarantine.py
and tests/test_tag_vocab_reask.py, this test only needs ONE quarantine-class
example to prove `pipeline-ready`'s OWN new logic -- computing a per-source
quarantined fraction and comparing it to `quarantine_budget` -- works;
re-proving both quarantine reason classes here would just duplicate already-
locked coverage, not strengthen this issue's own acceptance surface.

Seam decision 7 -- this test asserts only OBSERVABLE gate behavior (the
printed table + exit code), never internal wiring
-----------------------------------------------------------------------
`axial.vault.run_vault_write` today discards `run_tag`'s own
`quarantine_count`, and `axial.ingest`'s results TSV has no quarantine
column at all -- the implementer must bridge this gap somehow (e.g. reading
the tag checkpoint's `.jsonl` quarantine records directly, or threading
`quarantine_count` up through a new return path). This test never reads any
internal checkpoint/results file itself and never asserts which bridge was
chosen -- only `pipeline-ready`'s own printed table and exit code, so it
stays valid regardless of which internal implementation the implementer
picks.

Test hygiene: every path this test writes (the manifest, the worklist-free
per-canary trees/envelopes/vault/tags/chunks dirs) lives under
`isolated_vault_root` (tests/conftest.py, issue #68) -- a fresh
`tmp_path`-backed staging root outside this repo entirely. No real `data/`
directory is ever read, moved, or written by this test.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from axial.envelope import compute_source_id

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "pipeline_ready"

CLEAN_PASS_1_DOCX = FIXTURES_DIR / "clean_pass_1.docx"
CLEAN_PASS_2_DOCX = FIXTURES_DIR / "clean_pass_2.docx"
QUARANTINE_FAIL_DOCX = FIXTURES_DIR / "quarantine_fail.docx"
FATAL_OUT_OF_VOCAB_DOCX = FIXTURES_DIR / "fatal_out_of_vocab.docx"

SINGLE_SECTION_TREE_FIXTURE = FIXTURES_DIR / "single_section_tree.json"

PROVIDER_ENV_VAR = "AXIAL_LLM_PROVIDER"
STUB_TAG_RESPONSE_ENV_VAR = "AXIAL_STUB_TAG_RESPONSE"
STUB_TAG_RESPONSE_SEQUENCE_ENV_VAR = "AXIAL_STUB_TAG_RESPONSE_SEQUENCE"

# A generous time envelope no synthetic stub-driven run could plausibly
# exceed, and the flat 2% quarantine budget the postmortem's own bar names
# ("quarantined chunks stay under 2% per source").
GENEROUS_TIME_ENVELOPE_SEC = 600
FLAT_QUARANTINE_BUDGET = 0.02

# A schema-valid multi-axis tag-pass payload (every value a real member of
# config/domains/syria/schema.yaml's respective axis) -- the same shape
# StubLLMClient._CANNED_TAG_RESPONSE already uses.
_VALID_TAG_PAYLOAD = (
    '{"role_in_argument": "role:claim", "empirical_scope": "scope:country-case", '
    '"country": "Syria", "field": {"primary": "state", "secondary": ["ideology"]}, '
    '"claim_type": {"primary": "state-formation", "subtags": ["formation:bellicist"]}, '
    '"theory_school": {"primary": "bellicist", "status": "candidate"}}'
)
# Non-JSON text: exhausts complete_json's bounded retry budget, raising
# ModelJsonError -> quarantine_reason "malformed_json" (issue #120).
_MALFORMED_JSON_PAYLOAD = "this is not JSON at all, sorry {"
# A `claim_type.subtags` value declared under NEITHER `state-formation` nor
# any other claim_type entry in the real schema -- genuinely out-of-vocab,
# mirroring tests/test_tag_vocab_reask.py's own OUT_OF_VOCAB_SUBTAG pattern.
_OUT_OF_VOCAB_TAG_PAYLOAD = (
    '{"role_in_argument": "role:claim", "empirical_scope": "scope:country-case", '
    '"country": "Syria", "field": {"primary": "state", "secondary": ["ideology"]}, '
    '"claim_type": {"primary": "state-formation", "subtags": ["formation:NOT-A-REAL-SUBTAG"]}, '
    '"theory_school": {"primary": "bellicist", "status": "candidate"}}'
)

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
    <root>/data/trees/<source_id>.json (module docstring, seam decision 5),
    so `axial.extract.extract` reuses it verbatim instead of running
    docling/Unstructured."""
    source_id = compute_source_id(source_path)
    tree_path = _trees_dir(root) / f"{source_id}.json"
    tree_path.parent.mkdir(parents=True, exist_ok=True)
    tree_path.write_bytes(SINGLE_SECTION_TREE_FIXTURE.read_bytes())
    return tree_path


def _arrange_stored_envelope(source_path: Path, root: Path) -> None:
    """Pre-place the tree fixture, then run `axial envelope` with the stub
    provider so a stored envelope exists on disk before `pipeline-ready`
    runs (mirrors tests/test_ingest.py's helper of the same name). Asserts
    the arrange step itself succeeded and produced exactly one new envelope
    file."""
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


def _toml_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _write_manifest(path: Path, canaries: list[dict]) -> None:
    """Write a TOML manifest of `[[canary]]` entries (module docstring,
    seam decisions 1-2): every entry carries the three founder-ratified
    fields (`source_id`, `time_envelope_sec`, `quarantine_budget`) plus this
    test's own `source_path` field, an absolute path computed fresh at test
    run time -- never a machine-specific string baked into a committed
    fixture."""
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
    """Parse `pipeline-ready`'s per-canary table from stdout ONLY (module
    docstring, seam decision 3): a header line whose tab-separated fields
    include (at least) `source_id` and `verdict`, followed by one
    tab-separated data row per canary carrying the same number of fields as
    the header. Returns a mapping of `source_id` -> that row's fields (by
    column name), so every assertion below looks a canary up by its own
    identity, never by row position or a whole-line/sentence match."""
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
    _arrange_stored_envelope(CLEAN_PASS_1_DOCX, root)
    _arrange_stored_envelope(CLEAN_PASS_2_DOCX, root)

    source_id_1 = compute_source_id(CLEAN_PASS_1_DOCX)
    source_id_2 = compute_source_id(CLEAN_PASS_2_DOCX)

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
    _arrange_stored_envelope(QUARANTINE_FAIL_DOCX, root)
    source_id = compute_source_id(QUARANTINE_FAIL_DOCX)

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

    # This fixture yields exactly 2 chunks via one chunk-pass call (module
    # docstring, seam decision 5). The first chunk's tag-pass call is
    # malformed on all 3 of complete_json's bounded retry attempts (issue
    # #120: quarantine_reason "malformed_json"); the second chunk's single
    # call is valid -- a quarantined fraction of 1/2 = 50%, far over the 2%
    # budget (module docstring, seam decision 6).
    sequence = [
        _MALFORMED_JSON_PAYLOAD,
        _MALFORMED_JSON_PAYLOAD,
        _MALFORMED_JSON_PAYLOAD,
        _VALID_TAG_PAYLOAD,
    ]
    result = _run_pipeline_ready(
        "stub",
        manifest_path,
        cwd=root,
        extra_env={STUB_TAG_RESPONSE_SEQUENCE_ENV_VAR: json.dumps(sequence)},
    )
    _assert_not_argparse_fallback(result, "pipeline-ready")

    assert result.returncode != 0, (
        f"expected a non-zero exit code for `axial pipeline-ready` when one "
        f"canary's quarantined-chunk fraction (50%) exceeds its declared "
        f"quarantine_budget (2%), got exit code 0\nstdout: {result.stdout!r}\n"
        f"stderr: {result.stderr!r}"
    )

    table = _parse_pipeline_ready_table(result.stdout)
    _assert_verdict(table, source_id, "FAIL", "quarantine_fail")


# ---------------------------------------------------------------------------
# Case 3: a canary hits a non-quarantined, source-fatal chunk error
# (persisting out-of-vocab, P0-6) -> that row is FAIL, non-zero exit
# (postmortem criterion 2, "zero source-fatal chunk errors").
# ---------------------------------------------------------------------------


def test_source_fatal_chunk_error_fails_that_canary(isolated_vault_root):
    root = isolated_vault_root
    _arrange_stored_envelope(FATAL_OUT_OF_VOCAB_DOCX, root)
    source_id = compute_source_id(FATAL_OUT_OF_VOCAB_DOCX)

    manifest_path = root / "canary_manifest_source_fatal.toml"
    _write_manifest(
        manifest_path,
        [
            {
                "source_id": source_id,
                "source_path": FATAL_OUT_OF_VOCAB_DOCX,
                "time_envelope_sec": GENEROUS_TIME_ENVELOPE_SEC,
                "quarantine_budget": FLAT_QUARANTINE_BUDGET,
            }
        ],
    )

    # A `claim_type.subtags` value that is out-of-vocab on EVERY tag-pass
    # call, including the bounded P0-6 correction re-ask -- a persisting
    # TagNotInSchemaError, which `run_tag` does NOT quarantine (founder
    # ruling: out_of_vocab stays a hard, source-fatal error -- see
    # tests/test_tag_quarantine.py's own module docstring). This aborts the
    # whole canary's ingestion on its very first chunk.
    result = _run_pipeline_ready(
        "stub",
        manifest_path,
        cwd=root,
        extra_env={STUB_TAG_RESPONSE_ENV_VAR: _OUT_OF_VOCAB_TAG_PAYLOAD},
    )
    _assert_not_argparse_fallback(result, "pipeline-ready")

    assert result.returncode != 0, (
        f"expected a non-zero exit code for `axial pipeline-ready` when one "
        f"canary hits a persisting, non-quarantined, source-fatal chunk "
        f"error (out-of-vocab, P0-6), got exit code 0\nstdout: "
        f"{result.stdout!r}\nstderr: {result.stderr!r}"
    )

    table = _parse_pipeline_ready_table(result.stdout)
    _assert_verdict(table, source_id, "FAIL", "fatal_out_of_vocab")


# ---------------------------------------------------------------------------
# Case 4: a canary's recorded duration exceeds its time_envelope_sec ->
# that row is FAIL, non-zero exit (postmortem criterion 3, "bounded wall
# clock").
# ---------------------------------------------------------------------------


def test_over_time_envelope_fails_that_canary(isolated_vault_root):
    root = isolated_vault_root
    _arrange_stored_envelope(CLEAN_PASS_1_DOCX, root)
    source_id = compute_source_id(CLEAN_PASS_1_DOCX)

    # `time_envelope_sec = 0`: no real ingestion (even a stub-driven one,
    # which still makes several real function calls and file writes) can
    # complete in a strictly non-positive recorded duration, so this
    # deterministically exercises the "duration exceeds its envelope" FAIL
    # path without depending on any particular measured wall-clock value
    # (module docstring: the comparison mechanism itself is what this case
    # locks, not a specific timing).
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
