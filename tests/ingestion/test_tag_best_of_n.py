"""Outer acceptance test for issue #294 (best-of-N majority voting on the
blind tag axes, `claim_type` and `theory_school` -- DEC-31).

Given an extracted fixture source with its chunk records on disk
  And config sets `llm.votes_by_pass.tag = 3`
  And AXIAL_LLM_PROVIDER=record with a recorded call log
  And the tag pass's three draws for a first chunk are stubbed so two agree
      on a theory_school primary and the third differs
  And the tag pass's three draws for a second chunk are stubbed so all three
      theory_school primaries differ
When  the user runs `axial tag <fixture>`
Then  it exits 0 and emits one tagged record per chunk as JSON
  And the recorded log shows exactly three tag-pass calls per chunk
  And the first chunk's theory_school primary is the value the two agreeing
      draws shared, and that axis carries no `abstained` flag
  And the second chunk's theory_school record carries `abstained: true`, a
      null primary, and the three distinct draw values, and no fabricated tag

Seam decision 1 -- driving `N` deterministic draws per chunk through the
already-locked `AXIAL_STUB_TAG_RESPONSE_SEQUENCE` seam
-----------------------------------------------------------------------
`AXIAL_STUB_TAG_RESPONSE_SEQUENCE` (issue #102, `src/axial/llm.py`) is a
JSON array of raw tag-pass response bodies dispatched by the per-process,
1-indexed `_tag_pass_call_count`, which fires on EVERY tag-pass-family call.
With `N = 3` a six-element sequence therefore maps chunk `k` to elements
`3k+1 .. 3k+3` (mod 6): every even-indexed chunk draws the first three
payloads and every odd-indexed chunk the last three, whatever the fixture's
chunk count turns out to be. Element parity only self-sustains because every
payload here is fully in-vocabulary, so no #102 correction re-ask ever fires
and consumes an extra call.

Seam decision 2 -- counting the draws with the `record` provider, not
inferring them from the output
-----------------------------------------------------------------------
`axial tag` runs the tag pass alone (the chunker is LLM-free and runs as an
arrange step here), so every prompt in the `AXIAL_LLM_RECORD_PATH` log is a
tag-pass call. The tests assert `3 x chunk_count` exactly: too few would mean
best-of-N silently fell back to one draw, too many that it drew past `N`.
The chunk count is read from the on-disk chunk artifact, never hardcoded.

Seam decision 3 -- proving the vote is a VOTE, not a first-draw read
-----------------------------------------------------------------------
The decided chunk's three `theory_school` primaries are `[B, A, A]` and its
three `claim_type` primaries `[Y, X, X]`: the modal value is deliberately
NOT the first draw's, so a record carrying `A`/`X` can only have come from
counting ballots. The same payloads vary `role_in_argument` across the three
draws (`[R1, R2, R2]`) and assert the record keeps `R1` -- the head axes are
deliberately NOT voted in this slice (they take their first draw's value),
and a record carrying `R2` would mean head-axis voting leaked in.

Seam decision 4 -- `N = 1` is asserted as an exact no-op
-----------------------------------------------------------------------
The third test writes `votes_by_pass: {tag: 1}` and asserts one call per
chunk plus the absence of an `abstained` key anywhere in the emitted JSON:
the voting layer must not run at all at `N = 1`, which is what bounds this
change's blast radius on every other pass and on today's record shape.

Fixture reuse: exactly tests/ingestion/test_tag_vocab_reask.py's fixture
(tests/fixtures/envelope/thesis_paper.pdf + its committed real tree
fixture). `isolated_vault_root` (tests/conftest.py) gives each test a
private staging root -- with the domain directory copied in -- so the real
`data/` tree a concurrent ingestion run depends on is never touched.
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
from pathlib import Path

from axial.chunk import read_chunks, run_chunk_recursive
from axial.envelope import compute_source_id
from axial.schema import Schema, load_schema

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "envelope"
DOMAIN_DIR = REPO_ROOT / "config" / "domains" / "syria"

THESIS_PAPER_PDF = FIXTURES_DIR / "thesis_paper.pdf"
THESIS_PAPER_TREE_FIXTURE = FIXTURES_DIR / "thesis_paper_tree.json"

PROVIDER_ENV_VAR = "AXIAL_LLM_PROVIDER"
STUB_TAG_RESPONSE_SEQUENCE_ENV_VAR = "AXIAL_STUB_TAG_RESPONSE_SEQUENCE"
RECORD_PATH_ENV_VAR = "AXIAL_LLM_RECORD_PATH"

THEORY_SCHOOL_AXIS = "theory_school"
CLAIM_TYPE_AXIS = "claim_type"
ROLE_IN_ARGUMENT_AXIS = "role_in_argument"

ARGPARSE_FALLBACK_MARKERS = (
    "invalid choice",
    "unrecognized arguments",
)


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
    """Temporarily change the process cwd (mirrors
    tests/ingestion/test_tag_vocab_reask.py's helper of the same name):
    `run_chunk_recursive` resolves its persisted-tree read as a plain,
    cwd-relative path with no override parameter."""
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def _assert_not_argparse_fallback(result: subprocess.CompletedProcess, command: str) -> None:
    combined = result.stdout + result.stderr
    for marker in ARGPARSE_FALLBACK_MARKERS:
        assert marker not in combined, (
            f"expected a real `{command}` behavior path, not an argparse "
            f"fallback (found {marker!r}):\nstdout: {result.stdout!r}\n"
            f"stderr: {result.stderr!r}"
        )


def _arrange_chunks(root: Path) -> int:
    """Pre-place the committed real tree fixture and write the on-disk chunk
    artifact `axial tag` reads (the recursive chunker is LLM-free, so this
    arrange step makes no model call and never pollutes the record log).
    Returns the fixture's chunk count -- ground truth for the call-count
    assertions, never hardcoded."""
    source_id = compute_source_id(THESIS_PAPER_PDF)
    tree_path = root / "data" / "trees" / f"{source_id}.json"
    tree_path.parent.mkdir(parents=True, exist_ok=True)
    tree_path.write_bytes(THESIS_PAPER_TREE_FIXTURE.read_bytes())

    with _chdir(root):
        run_chunk_recursive(THESIS_PAPER_PDF)
        records = read_chunks(source_id)

    assert len(records) >= 2, (
        f"arrange step failed: this test needs at least two chunks (one "
        f"decided vote, one abstained vote), the fixture yielded {len(records)}"
    )
    return len(records)


def _write_votes_config(root: Path, votes: int) -> None:
    """Write the isolated root's own `config/pipeline.yaml` carrying only the
    `llm.votes_by_pass` block under test -- every other key stays absent so
    the module defaults (paths, provider) apply exactly as they do with no
    config file at all."""
    config_path = root / "config" / "pipeline.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(f"llm:\n  votes_by_pass:\n    tag: {votes}\n", encoding="utf-8")


def _distinct_values(schema: Schema, axis_name: str, count: int) -> list[str]:
    """`count` distinct, genuinely in-vocabulary values of `axis_name`, read
    from the real schema at test time and taken in a deterministic order."""
    values = sorted(schema.axes[axis_name].tag_ids)
    assert len(values) >= count, (
        f"test setup invariant broken: the schema's {axis_name!r} axis needs "
        f"at least {count} values to build this test's draws, it has {len(values)}"
    )
    return values[:count]


def _payload(
    schema: Schema,
    *,
    theory_school: str,
    claim_type: str,
    role_in_argument: str,
) -> str:
    """A complete, schema-valid raw tag-pass response body: every value is a
    real member of its own axis's vocabulary, so no #102 correction re-ask
    can fire and shift the response-sequence parity (seam decision 1)."""
    non_country_scopes = [
        scope
        for scope in sorted(schema.axes["empirical_scope"].tag_ids)
        if scope != "scope:country-case"
    ]
    assert non_country_scopes, (
        "test setup invariant broken: the schema's empirical_scope axis has "
        "no non-country-case value, so this payload would need a polity"
    )
    return json.dumps(
        {
            ROLE_IN_ARGUMENT_AXIS: role_in_argument,
            "empirical_scope": non_country_scopes[0],
            "polities_touched": [],
            "field": {"primary": sorted(schema.axes["field"].tag_ids)[0], "secondary": []},
            CLAIM_TYPE_AXIS: {"primary": claim_type, "secondary": None, "subtags": []},
            THEORY_SCHOOL_AXIS: {"primary": theory_school, "secondary": None},
        }
    )


def _recorded_call_count(record_path: Path) -> int:
    """Every recorded prompt (one JSON-encoded string per line, written by
    `axial.llm.RecordLLMClient`). `axial tag` runs the tag pass alone, so
    this is exactly the tag-pass call count (seam decision 2)."""
    if not record_path.exists():
        return 0
    return len(
        [line for line in record_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    )


def _tagged_records(result: subprocess.CompletedProcess) -> list[dict]:
    records = json.loads(result.stdout)
    assert isinstance(records, list) and records, (
        f"expected `axial tag` to emit a non-empty JSON list of tagged "
        f"records on stdout, got {result.stdout!r}"
    )
    return records


def test_blind_axes_are_majority_voted_across_three_draws(isolated_vault_root):
    """Issue #294's acceptance criterion: with `llm.votes_by_pass.tag = 3`,
    `axial tag` draws each chunk three times and majority-votes the blind
    axes -- a chunk whose draws hold a strict plurality records the modal
    value (never the first draw's, here), and a chunk whose three draws all
    differ records an explicit abstention instead of fabricating a tag."""
    root = isolated_vault_root
    chunk_count = _arrange_chunks(root)
    _write_votes_config(root, 3)

    schema = load_schema(str(DOMAIN_DIR))
    school_a, school_b, school_c = _distinct_values(schema, THEORY_SCHOOL_AXIS, 3)
    claim_x, claim_y = _distinct_values(schema, CLAIM_TYPE_AXIS, 2)
    role_first, role_other = _distinct_values(schema, ROLE_IN_ARGUMENT_AXIS, 2)

    sequence = [
        # Even-indexed chunks: a strict plurality on both blind axes, with
        # the winner deliberately NOT the first draw's value.
        _payload(schema, theory_school=school_b, claim_type=claim_y, role_in_argument=role_first),
        _payload(schema, theory_school=school_a, claim_type=claim_x, role_in_argument=role_other),
        _payload(schema, theory_school=school_a, claim_type=claim_x, role_in_argument=role_other),
        # Odd-indexed chunks: three distinct theory_school primaries (no
        # plurality -> abstention), claim_type unanimous (still decided).
        _payload(schema, theory_school=school_a, claim_type=claim_x, role_in_argument=role_first),
        _payload(schema, theory_school=school_b, claim_type=claim_x, role_in_argument=role_first),
        _payload(schema, theory_school=school_c, claim_type=claim_x, role_in_argument=role_first),
    ]
    record_path = root.parent / f"{root.name}_best_of_n_record.jsonl"

    result = _run_axial(
        ["tag", str(THESIS_PAPER_PDF)],
        "record",
        cwd=root,
        extra_env={
            STUB_TAG_RESPONSE_SEQUENCE_ENV_VAR: json.dumps(sequence),
            RECORD_PATH_ENV_VAR: str(record_path),
        },
    )
    _assert_not_argparse_fallback(result, "tag")
    assert result.returncode == 0, (
        f"expected exit code 0 for `axial tag` under best-of-3 voting, got "
        f"{result.returncode}\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    records = _tagged_records(result)
    assert len(records) == chunk_count, (
        f"expected one tagged record per chunk ({chunk_count}), got {len(records)}"
    )

    calls = _recorded_call_count(record_path)
    assert calls == 3 * chunk_count, (
        f"expected exactly {3 * chunk_count} tag-pass LLM call(s) "
        f"({chunk_count} chunk(s) x N=3 draws, issue #294: N comes from "
        f"`llm.votes_by_pass.tag`), got {calls} recorded call(s) in "
        f"{record_path}. Too few means best-of-N silently fell back to one "
        f"draw; too many means it drew past N."
    )

    decided = records[0]
    school = decided[THEORY_SCHOOL_AXIS]
    assert school.get("primary") == school_a, (
        f"expected the decided chunk's theory_school primary to be the value "
        f"two of its three draws shared ({school_a!r}) -- never the first "
        f"draw's {school_b!r} -- got {school!r}"
    )
    assert "abstained" not in school, (
        f"expected a decided axis to carry no `abstained` key at all (its "
        f"record shape is unchanged from a single draw), got {school!r}"
    )
    assert decided[CLAIM_TYPE_AXIS].get("primary") == claim_x, (
        f"expected the decided chunk's claim_type primary to be the modal "
        f"{claim_x!r}, never the first draw's {claim_y!r}, got "
        f"{decided[CLAIM_TYPE_AXIS]!r}"
    )
    assert decided[ROLE_IN_ARGUMENT_AXIS] == role_first, (
        f"expected the head axis role_in_argument to take its FIRST draw's "
        f"value ({role_first!r}) -- head axes are deliberately not voted in "
        f"this slice -- got {decided[ROLE_IN_ARGUMENT_AXIS]!r}"
    )

    abstained = records[1][THEORY_SCHOOL_AXIS]
    assert abstained.get("abstained") is True, (
        f"expected the chunk whose three theory_school draws all differ to "
        f"carry `abstained: true` (DEC-31: flag the contested chunk rather "
        f"than coin-flip it), got {abstained!r}"
    )
    assert abstained.get("primary") is None, (
        f"expected an abstained axis's primary to be null -- never a "
        f"fabricated tag -- got {abstained!r}"
    )
    assert abstained.get("draws") == [school_a, school_b, school_c], (
        f"expected the abstained axis to preserve its three distinct draw "
        f"values in draw order for operator review, got {abstained!r}"
    )
    assert records[1][CLAIM_TYPE_AXIS].get("primary") == claim_x, (
        f"expected abstention to be PER AXIS: this chunk's claim_type draws "
        f"were unanimous and must still decide, got "
        f"{records[1][CLAIM_TYPE_AXIS]!r}"
    )


def test_votes_default_to_three_when_config_omits_the_block(isolated_vault_root):
    """N is a config default, not a call-site literal: with no
    `config/pipeline.yaml` at all, the tag pass still draws its code-level
    default of three times per chunk."""
    root = isolated_vault_root
    chunk_count = _arrange_chunks(root)
    assert not (root / "config" / "pipeline.yaml").exists(), (
        "arrange step invariant broken: this test needs the isolated root to "
        "carry no pipeline.yaml, so the code-level default is what applies"
    )

    schema = load_schema(str(DOMAIN_DIR))
    school = _distinct_values(schema, THEORY_SCHOOL_AXIS, 1)[0]
    claim = _distinct_values(schema, CLAIM_TYPE_AXIS, 1)[0]
    role = _distinct_values(schema, ROLE_IN_ARGUMENT_AXIS, 1)[0]

    record_path = root.parent / f"{root.name}_default_votes_record.jsonl"
    result = _run_axial(
        ["tag", str(THESIS_PAPER_PDF)],
        "record",
        cwd=root,
        extra_env={
            STUB_TAG_RESPONSE_SEQUENCE_ENV_VAR: json.dumps(
                [_payload(schema, theory_school=school, claim_type=claim, role_in_argument=role)]
            ),
            RECORD_PATH_ENV_VAR: str(record_path),
        },
    )
    _assert_not_argparse_fallback(result, "tag")
    assert result.returncode == 0, (
        f"expected exit code 0 for `axial tag` with no pipeline.yaml, got "
        f"{result.returncode}\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    calls = _recorded_call_count(record_path)
    assert calls == 3 * chunk_count, (
        f"expected the code-level default of 3 draws per chunk "
        f"({3 * chunk_count} call(s) for {chunk_count} chunk(s)) when config "
        f"names no `votes_by_pass`, got {calls}"
    )


def test_single_vote_is_an_exact_no_op(isolated_vault_root):
    """`votes_by_pass.tag = 1` bypasses the voting layer entirely: one draw
    per chunk, and no `abstained` key anywhere in the emitted records --
    today's record shape exactly. This is what bounds the change's blast
    radius on every other pass."""
    root = isolated_vault_root
    chunk_count = _arrange_chunks(root)
    _write_votes_config(root, 1)

    schema = load_schema(str(DOMAIN_DIR))
    school = _distinct_values(schema, THEORY_SCHOOL_AXIS, 1)[0]
    claim = _distinct_values(schema, CLAIM_TYPE_AXIS, 1)[0]
    role = _distinct_values(schema, ROLE_IN_ARGUMENT_AXIS, 1)[0]

    record_path = root.parent / f"{root.name}_single_vote_record.jsonl"
    result = _run_axial(
        ["tag", str(THESIS_PAPER_PDF)],
        "record",
        cwd=root,
        extra_env={
            STUB_TAG_RESPONSE_SEQUENCE_ENV_VAR: json.dumps(
                [_payload(schema, theory_school=school, claim_type=claim, role_in_argument=role)]
            ),
            RECORD_PATH_ENV_VAR: str(record_path),
        },
    )
    _assert_not_argparse_fallback(result, "tag")
    assert result.returncode == 0, (
        f"expected exit code 0 for `axial tag` at N=1, got {result.returncode}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    calls = _recorded_call_count(record_path)
    assert calls == chunk_count, (
        f"expected exactly one tag-pass LLM call per chunk at N=1 "
        f"({chunk_count}), got {calls} -- N=1 must be an exact no-op"
    )

    assert "abstained" not in result.stdout, (
        f"expected no `abstained` key anywhere in the emitted records at "
        f"N=1 (the voting layer must not run at all), got stdout: "
        f"{result.stdout!r}"
    )
    for record in _tagged_records(result):
        assert record[THEORY_SCHOOL_AXIS].get("primary") == school, (
            f"expected the single draw's theory_school primary verbatim at "
            f"N=1, got {record[THEORY_SCHOOL_AXIS]!r}"
        )
