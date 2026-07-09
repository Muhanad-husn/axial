"""Outer acceptance test for issue #32, slice 02 (artifact-pool-write).

Locked behavioral contract (DEC-1) -- do not edit once committed red.

Given an extracted fixture source with artifacts including one classified
      `discard`, and AXIAL_LLM_PROVIDER=stub
When  the user runs `axial vault write <fixture>`
Then  one artifact note per artifact appears under data/vault/artifacts/ (a
      separate surface from data/vault/prose/)
And   each carries `artifact_role`, `field`, and source/section provenance
      in its frontmatter
And   the `discard`-roled artifact note is present but flagged
      `retrievable: false`
And   the prose notes are unaffected and re-running is idempotent

See specs/PRODUCT.md §5 stage 5 ("Artifact classification & routing...
routed to a separate artifact pool with metadata... Output: tagged artifacts
in the artifact pool."), §7.2 ("Artifact notes carry: artifact_role, fields,
source/section provenance, and cited_by back-references to prose chunks." --
`cited_by` is the xref feature's job, out of scope here per the plan), §8
P0-5 ("Artifacts are written to the artifact pool, not embedded in prose
notes."; "`discard`-tagged artifacts are retained in the pool but flagged
non-retrievable.") and P0-8 ("Prose pool and artifact pool are separate,
independently queryable surfaces sharing metadata conventions."), and
Appendix D (the closed artifact_role vocabulary, including `discard`) for
the source of truth. Plan: plans/artifacts/02-artifact-pool-write.md.

Fixture reuse: tests/fixtures/extract/prose_and_table.pdf (+ its committed
prose_and_table_tree.json), the same fixture tests/test_artifacts.py already
locks a contract against. It carries a stored-envelope-eligible structure
(two top-level sections, "Introduction" and "Discussion") *and* exactly one
artifact node (a table, nested under "Introduction"), so it is the one
fixture in this repo that exercises `axial vault write`'s BOTH halves --
prose (via the chunking pass) and artifacts (via the classification pass)
-- in a single run. This was verified directly before committing to it:
pre-placing the committed tree fixture and running, in order, `axial
envelope`, `axial chunk`, and `axial artifacts` (all with
AXIAL_LLM_PROVIDER=stub) against this exact PDF each exits 0 and produces
the expected shape (a stored envelope; four chunk records across the two
sections; one artifact record for the one table). No new fixture was
needed, and no committed fixture had to be rejected.

Seam decision 1 -- deriving expected sets independently, never hardcoding
-----------------------------------------------------------------------
Mirroring tests/test_vault_write.py's seam decision 2 and
tests/test_artifacts.py's own discipline, this test never hardcodes
chunk_id/artifact_id/section/artifact_role values. It independently runs
`axial chunk <fixture>` (for the expected prose set) and `axial artifacts
<fixture>` (for the expected artifact set, including the real,
schema-validated `artifact_role` each artifact classifies to) with the same
stub provider and fixture, and treats those as the expected sets `vault
write` must reproduce one-for-one when it internally reruns the same
passes. This is safe for the same reason tests/test_vault_write.py's
analogous derivation is safe: both `axial artifacts`/`axial chunk` and
`vault write`'s own internal calls consume the same stored envelope/tree
with the same stub provider, so they must agree.

The one thing NOT derivable from `axial artifacts`'s own stdout is `field`:
slice 01's artifact records (tests/test_artifacts.py) carry only
artifact_id/artifact_role/source_id/section, no `field` -- classifying
`field` for artifacts is THIS slice's job. So `field` expectations are
derived from the domain schema directly (config/domains/syria/schema.yaml,
loaded via axial.schema.load_schema), never from any stub wording: this
test asserts `field`'s shape (a `{primary, secondary}` mapping) and that
`primary`/every `secondary` entry is a real member of the schema's `field`
axis -- never a specific fixed value, since no source of truth pins one.

Seam decision 2 -- forcing the discard branch: the existing
AXIAL_STUB_ARTIFACT_ROLE seam
-----------------------------------------------------------------------
tests/test_artifacts.py's module docstring (seam decision 2) already locked
`AXIAL_STUB_ARTIFACT_ROLE` as the fault-injection env var that forces the
stub's `pass_name="artifacts"` response to carry a specific role string.
This test reuses that exact seam, set to `"discard"` (a real, in-schema
value per Appendix D -- unlike test_artifacts.py's deliberately-bogus
forced value), to drive the `discard` branch deterministically: every
artifact node in the one run gets classified `discard` (the stub dispatches
by pass_name, not per-node, so with this fixture's single artifact node that
is exactly the record this test needs). The happy-path test below leaves
the env var unset, so the artifacts pass's ordinary default in-schema role
applies instead -- this test does not hardcode which one, only that an
independent `axial artifacts` run (same env) confirms it is NOT `discard`,
since a happy-path test whose "happy" role secretly collided with `discard`
would fail to prove `retrievable: true`'s branch at all.

Seam decision 3 -- frontmatter key names locked by this test
-----------------------------------------------------------------------
The Gherkin names `artifact_role`, `field`, and "source/section
provenance" literally, plus a `retrievable` flag; this test locks the
minimum needed to make all four executable, reusing names already locked
elsewhere rather than inventing new ones:
  - "artifact_role": reused verbatim from tests/test_artifacts.py's own
    locked record field name for this exact concept.
  - "field": reused verbatim from the Gherkin's own wording and from
    src/axial/tag.py's/src/axial/llm.py's existing `field` axis parsing
    convention -- a `{"primary": <str>, "secondary": [<str>, ...]}` mapping
    (see src/axial/llm.py's `_CANNED_TAG_RESPONSE` and
    src/axial/tag.py's `parse_multi_value_tag`, which both already use this
    exact primary/secondary shape for the schema's `primary_plus_secondary`
    cardinality axes -- `field` is one, per schema.yaml). This test does
    NOT hardcode which primary/secondary values appear (see seam decision
    1), only the shape and schema membership.
  - "source_id" and "section": reused verbatim from
    tests/test_artifacts.py's own locked record field names for the same
    provenance concepts (source-level and section-level provenance,
    PRD §7.2's "source/section provenance" umbrella covering both prose and
    artifacts).
  - "retrievable": the Gherkin's own literal wording for the discard flag
    (PRD §8 P0-5, "flagged non-retrievable"). This test asserts it is a
    real YAML boolean (`True`/`False`), not the string `"true"`/`"false"`,
    since a stringly-typed flag would silently defeat any downstream
    boolean filter on this field.
  - "artifact_id": reused verbatim from tests/test_artifacts.py's own
    locked, stable id field, doubling as this note's filename stem (the
    plan's own inner-loop wording: "write an artifact note at
    `data/vault/artifacts/<artifact_id>.md`").

This test does NOT lock: exact frontmatter key ordering, exact YAML
serialization style, a `cited_by` back-references key (the xref feature's
job, explicitly out of scope for this slice per the plan), or a
`source_meta` block on artifact notes (the Gherkin only asks for
"source/section provenance", already covered by `source_id`/`section`; a
richer nested source-level block, if the implementer adds one, is not
asserted against here either way).

Seam decision 4 -- artifact/prose pool separation, both directions
-----------------------------------------------------------------------
Unlike tests/test_vault_write.py's slice (where the artifact pool stayed
empty and only a one-directional check made sense), THIS slice actually
writes into both pools, so this test checks separation both ways: no
artifact's note is ever found under data/vault/prose/, and no chunk's note
is ever found under data/vault/artifacts/ (PRD §8 P0-8, "separate,
independently queryable surfaces").

Seam decision 5 -- idempotence
-----------------------------------------------------------------------
The Gherkin's closing clause ("re-running is idempotent") is checked by
running `axial vault write` twice over the same fixture+env and asserting
the artifact pool's file set and every artifact note's full byte content
are identical after both runs -- proving the second run overwrote in place
rather than duplicating or drifting (mirrors the plan's inner-loop item,
"re-running overwrites an artifact note idempotently rather than
duplicating it").

Test hygiene: this test relies on tests/conftest.py's autouse
`_isolate_persisted_tree_and_envelope_state` fixture for data/trees/ and
data/envelopes/ isolation (not re-implemented here); `data/vault/` is not
one of that fixture's protected directories, so this test defines its own
`clean_vault` fixture (mirroring tests/test_vault_write.py's fixture of the
same name) to remove any file/directory it newly creates there.

Arrange-mechanism change (issue #68, vault isolation) -- no behavioral
assertion changed
-----------------------------------------------------------------------
Exactly as tests/test_vault_write.py and tests/test_vault_tag_frontmatter.py
now document: once real gold-corpus notes started landing in the real
`data/vault/prose/`, this test's own count-based assertions ("exactly one
artifact/prose note per record") broke against the real, populated vault --
a genuine isolation gap, not a cleanup-timing one, since the real notes are
present WHILE the test runs (the former `clean_vault` fixture described
above only cleans up afterward). No CLI flag or env var exists to redirect
`vault_dir`/`envelopes_dir`/the domain directory, and editing the real
`config/pipeline.yaml` is out of bounds. So every `axial` subprocess this
test spawns now runs with `cwd` set to `isolated_vault_root`
(tests/conftest.py's opt-in fixture, issue #68): a fresh per-test staging
directory outside this repo entirely, with its own copy of
`config/domains/syria/{schema.yaml,codebook.yaml}` (needed because
`axial artifacts`/`axial vault write` resolve the default domain directory
as the plain relative path `config/domains/syria`). `TREES_DIR`/
`VAULT_DIR`/`PROSE_DIR`/`ARTIFACTS_DIR` are now computed from that root
instead of hardcoded at `REPO_ROOT`; the former `clean_vault` fixture above
is superseded by `isolated_vault_root` and removed. The real `data/vault/`
is never read, moved, or written by this test. Every behavioral assertion
below is unchanged -- only where the CLI runs and where this test looks for
its own output moved.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import yaml

from axial.envelope import compute_source_id

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "extract"
# The REAL domain dir, read in-process (never via the CLI subprocess) only
# to load the schema's own `field` axis tag_ids for the "never a hardcoded
# domain value" assertions (module docstring, seam decision 1) -- read-only,
# so no isolation is needed here; the CLI subprocess itself uses its own
# copy under `isolated_vault_root` (see "Arrange-mechanism change (issue
# #68...)" above).
DEFAULT_DOMAIN_DIR = REPO_ROOT / "config" / "domains" / "syria"

PROSE_AND_TABLE_PDF = FIXTURES_DIR / "prose_and_table.pdf"
PROSE_AND_TABLE_TREE_FIXTURE = FIXTURES_DIR / "prose_and_table_tree.json"

PROVIDER_ENV_VAR = "AXIAL_LLM_PROVIDER"
# The existing fault-injection seam this test reuses to force the discard
# branch -- see module docstring, seam decision 2.
STUB_ARTIFACT_ROLE_ENV_VAR = "AXIAL_STUB_ARTIFACT_ROLE"
DISCARD_ROLE = "discard"

# argparse's fallback error for an as-yet-nonexistent subcommand/argument.
# Any of these substrings in the combined output means the target
# subcommand's logic was never actually exercised -- the process failed
# before real behavior ran.
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
    # `--project REPO_ROOT` tells uv which project/venv to run against while
    # `cwd` (which may be `isolated_vault_root`, outside this repo entirely
    # -- see module docstring, "Arrange-mechanism change (issue #68...)")
    # controls the actual process working directory `axial`'s own relative
    # path resolution sees.
    return subprocess.run(
        ["uv", "run", "--project", str(REPO_ROOT), "axial", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        env=env,
    )


def _run_envelope(provider: str, *args: str, cwd: Path) -> subprocess.CompletedProcess:
    return _run_axial(["envelope", *args], provider, cwd=cwd)


def _run_chunk(provider: str, *args: str, cwd: Path) -> subprocess.CompletedProcess:
    return _run_axial(["chunk", *args], provider, cwd=cwd)


def _run_artifacts(
    provider: str, *args: str, cwd: Path, extra_env: dict[str, str] | None = None
) -> subprocess.CompletedProcess:
    return _run_axial(["artifacts", *args], provider, cwd=cwd, extra_env=extra_env)


def _run_vault_write(
    provider: str, *args: str, cwd: Path, extra_env: dict[str, str] | None = None
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


def _existing_envelope_files(root: Path) -> set[Path]:
    envelopes_dir = _envelopes_dir(root)
    if not envelopes_dir.exists():
        return set()
    return set(envelopes_dir.glob("*.json"))


def _place_tree_fixture(source_pdf: Path, tree_fixture_path: Path, root: Path) -> Path:
    """Pre-place the committed REAL tree fixture at
    <root>/data/trees/<source_id>.json so `axial.extract.extract` reuses it
    verbatim instead of running docling (PRD §7.4)."""
    source_id = compute_source_id(source_pdf)
    tree_path = _trees_dir(root) / f"{source_id}.json"
    tree_path.parent.mkdir(parents=True, exist_ok=True)
    tree_path.write_bytes(tree_fixture_path.read_bytes())
    return tree_path


def _arrange_stored_envelope(root: Path) -> Path:
    """Pre-place the real tree fixture, then run `axial envelope` with the
    stub provider so a stored envelope exists on disk before vault write,
    and return its path. Asserts the arrange step itself succeeded and
    produced exactly one new envelope file."""
    _place_tree_fixture(PROSE_AND_TABLE_PDF, PROSE_AND_TABLE_TREE_FIXTURE, root)
    before_files = _existing_envelope_files(root)

    result = _run_envelope("stub", str(PROSE_AND_TABLE_PDF), cwd=root)
    _assert_not_argparse_fallback(result, "envelope")
    assert result.returncode == 0, (
        f"arrange step failed: expected exit code 0 for `axial envelope` on "
        f"the fixture with the stub LLM provider, got {result.returncode}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    new_files = _existing_envelope_files(root) - before_files
    assert len(new_files) == 1, (
        f"arrange step failed: expected exactly one new file under "
        f"{_envelopes_dir(root)} after `axial envelope`, got {len(new_files)}: "
        f"{sorted(new_files)}\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    return next(iter(new_files))


def _parse_json_records(stdout: str, *, array_key: str, kind: str) -> list[dict]:
    """Parse records from stdout, tolerating any of: a bare JSON array, a
    JSON object with a top-level `array_key` array, or newline-delimited
    JSON (one record per line). Shared parsing leniency for both the
    `chunk` and `artifacts` commands' stdout (mirrors
    tests/test_vault_write.py's and tests/test_artifacts.py's own parsing
    helpers)."""
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
                f"document (a bare array, or an object with a top-level "
                f"{array_key!r} array) or newline-delimited JSON (one "
                f"record object per line); line {line!r} failed to parse "
                f"({exc}). Full stdout: {stdout!r}"
            ) from None
    return records


def _arrange_expected_chunk_records(root: Path) -> list[dict]:
    """Independently run `axial chunk` (stub) to obtain the real chunk
    records for the fixture -- the expected prose set `vault write` must
    reproduce (see module docstring, seam decision 1)."""
    result = _run_chunk("stub", str(PROSE_AND_TABLE_PDF), cwd=root)
    _assert_not_argparse_fallback(result, "chunk")
    assert result.returncode == 0, (
        f"arrange step failed: expected exit code 0 for `axial chunk` on "
        f"the fixture with the stub LLM provider, got {result.returncode}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    records = _parse_json_records(result.stdout, array_key="chunks", kind="chunk")
    assert len(records) >= 1, (
        f"arrange step failed: expected at least one chunk record from "
        f"`axial chunk`, got {len(records)}; stdout: {result.stdout!r}"
    )
    for record in records:
        assert isinstance(record.get("chunk_id"), str) and record["chunk_id"].strip(), (
            f"arrange step failed: expected every chunk record to carry a "
            f"non-empty 'chunk_id', got {record!r}"
        )
    return records


def _arrange_expected_artifact_records(
    root: Path, *, extra_env: dict[str, str] | None = None
) -> list[dict]:
    """Independently run `axial artifacts` (stub) to obtain the real
    artifact records for the fixture -- the expected artifact set `vault
    write` must reproduce (see module docstring, seam decision 1). Passing
    `extra_env={STUB_ARTIFACT_ROLE_ENV_VAR: DISCARD_ROLE}` drives the
    discard branch deterministically (seam decision 2)."""
    result = _run_artifacts("stub", str(PROSE_AND_TABLE_PDF), cwd=root, extra_env=extra_env)
    _assert_not_argparse_fallback(result, "artifacts")
    assert result.returncode == 0, (
        f"arrange step failed: expected exit code 0 for `axial artifacts` on "
        f"the fixture with the stub LLM provider, got {result.returncode}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    records = _parse_json_records(result.stdout, array_key="artifacts", kind="artifacts")
    assert len(records) == 1, (
        f"arrange step failed: expected exactly one artifact record (this "
        f"fixture carries exactly one artifact node -- see "
        f"tests/test_artifacts.py's module docstring, 'Fixture reuse'), got "
        f"{len(records)}; stdout: {result.stdout!r}"
    )
    for record in records:
        assert isinstance(record.get("artifact_id"), str) and record["artifact_id"].strip(), (
            f"arrange step failed: expected every artifact record to carry "
            f"a non-empty 'artifact_id', got {record!r}"
        )
        assert isinstance(record.get("artifact_role"), str) and record["artifact_role"].strip(), (
            f"arrange step failed: expected every artifact record to carry "
            f"a non-empty 'artifact_role', got {record!r}"
        )
    return records


def _in_schema_field_axis():
    """The schema's `field` axis object (tag_ids + cardinality), loaded from
    the default domain (config/domains/syria/schema.yaml, Appendix A) -- read
    at test time, never hardcoded (see module docstring, seam decision 1)."""
    from axial.schema import load_schema

    schema = load_schema(DEFAULT_DOMAIN_DIR)
    return schema.axes["field"]


def _split_frontmatter(text: str, note_path: Path) -> tuple[dict, str]:
    """Split a note's text into its parsed YAML frontmatter mapping and its
    body string, per the standard `---`-delimited convention already locked
    by tests/test_vault_write.py."""
    lines = text.splitlines()
    assert lines and lines[0].strip() == "---", (
        f"expected {note_path} to open with a YAML frontmatter block "
        f"delimited by a leading '---' line, got first line "
        f"{(lines[0] if lines else None)!r}. Full text (truncated): {text[:500]!r}"
    )

    closing_index = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            closing_index = index
            break
    assert closing_index is not None, (
        f"expected {note_path} to have a closing '---' line ending its "
        f"YAML frontmatter block, found none. Full text (truncated): {text[:1000]!r}"
    )

    frontmatter_text = "\n".join(lines[1:closing_index])
    body = "\n".join(lines[closing_index + 1 :])

    frontmatter = yaml.safe_load(frontmatter_text)
    assert isinstance(frontmatter, dict), (
        f"expected {note_path}'s YAML frontmatter block to parse to a "
        f"mapping/object, got {type(frontmatter).__name__}: {frontmatter!r}"
    )
    return frontmatter, body


def _find_note_for_id(directory: Path, id_: str, id_field_name: str) -> Path:
    assert directory.exists(), (
        f"expected {directory} to exist after `axial vault write` ran, but it does not"
    )
    matches = [p for p in directory.iterdir() if p.is_file() and p.stem == id_]
    assert len(matches) == 1, (
        f"expected exactly one note file under {directory} whose filename "
        f"stem equals {id_field_name} {id_!r}, got {len(matches)}: {sorted(matches)}"
    )
    return matches[0]


def _assert_field_matches_schema(field_value, note_path: Path, field_axis) -> None:
    """Assert `field_value` is a `{primary, secondary}` mapping whose values
    are real members of the schema's `field` axis (never a hardcoded
    domain value -- see module docstring, seam decision 1)."""
    assert isinstance(field_value, dict), (
        f"expected {note_path}'s frontmatter 'field' to be a mapping "
        f"(PRD Appendix A: field is one primary + zero-or-more secondary), "
        f"got {type(field_value).__name__}: {field_value!r}"
    )

    primary = field_value.get("primary")
    assert primary in field_axis.tag_ids, (
        f"expected {note_path}'s frontmatter 'field.primary' to be a "
        f"member of the schema's field axis {sorted(field_axis.tag_ids)} "
        f"(config/domains/syria/schema.yaml), got {primary!r}"
    )

    secondary = field_value.get("secondary", [])
    if secondary is None:
        secondary = []
    assert isinstance(secondary, list), (
        f"expected {note_path}'s frontmatter 'field.secondary' to be a "
        f"list (zero-or-more secondary tags), got "
        f"{type(secondary).__name__}: {secondary!r}"
    )
    for tag in secondary:
        assert tag in field_axis.tag_ids, (
            f"expected every entry of {note_path}'s frontmatter "
            f"'field.secondary' to be a member of the schema's field axis "
            f"{sorted(field_axis.tag_ids)}, got {tag!r} (full field value: {field_value!r})"
        )


def _assert_artifact_note_matches_expected(note_path: Path, expected: dict, field_axis) -> dict:
    """Parse `note_path`'s frontmatter and assert it carries artifact_role,
    field, and source/section provenance matching `expected` (derived from
    an independent `axial artifacts` run, seam decision 1). Returns the
    parsed frontmatter for further assertions (e.g. `retrievable`)."""
    frontmatter, body = _split_frontmatter(note_path.read_text(encoding="utf-8"), note_path)

    assert frontmatter.get("artifact_id") == expected["artifact_id"], (
        f"expected {note_path}'s frontmatter 'artifact_id' to equal "
        f"{expected['artifact_id']!r}, got {frontmatter.get('artifact_id')!r}"
    )
    assert frontmatter.get("artifact_role") == expected["artifact_role"], (
        f"expected {note_path}'s frontmatter 'artifact_role' to equal this "
        f"artifact's own role as produced by `axial artifacts` on the same "
        f"fixture+env (PRD §7.2/§8 P0-5), got {frontmatter.get('artifact_role')!r} "
        f"vs. expected {expected['artifact_role']!r}"
    )
    assert frontmatter.get("source_id") == expected["source_id"], (
        f"expected {note_path}'s frontmatter 'source_id' to equal "
        f"{expected['source_id']!r} (source provenance, PRD §7.2), got "
        f"{frontmatter.get('source_id')!r}"
    )
    assert frontmatter.get("section") == expected["section"], (
        f"expected {note_path}'s frontmatter 'section' to equal this "
        f"artifact's own enclosing section {expected['section']!r} "
        f"(section provenance, PRD §7.2), got {frontmatter.get('section')!r}"
    )

    _assert_field_matches_schema(frontmatter.get("field"), note_path, field_axis)

    return frontmatter


def test_vault_write_creates_one_artifact_note_per_artifact_with_role_field_and_provenance(
    isolated_vault_root,
):
    root = isolated_vault_root
    prose_dir = _prose_dir(root)
    artifacts_dir = _artifacts_dir(root)

    field_axis = _in_schema_field_axis()
    _arrange_stored_envelope(root)
    expected_chunk_records = _arrange_expected_chunk_records(root)
    expected_artifact_records = _arrange_expected_artifact_records(root)

    # setup invariant: the happy-path (unforced) role must not itself be
    # "discard", or this test could never distinguish the two branches (see
    # module docstring, seam decision 2).
    happy_role = expected_artifact_records[0]["artifact_role"]
    assert happy_role != DISCARD_ROLE, (
        f"test setup invariant broken: the stub's default (unforced) "
        f"artifact_role must not be {DISCARD_ROLE!r}, or this test cannot "
        f"distinguish the happy path from the discard path; got {happy_role!r}"
    )

    result = _run_vault_write("stub", str(PROSE_AND_TABLE_PDF), cwd=root)
    _assert_not_argparse_fallback(result, "vault write")
    assert result.returncode == 0, (
        f"expected exit code 0 for `axial vault write` on a fixture source "
        f"with artifacts and the stub LLM provider configured, got "
        f"{result.returncode}\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    assert artifacts_dir.exists(), (
        f"expected `axial vault write` to create {artifacts_dir} and write "
        f"artifact notes into it (Gherkin: 'one artifact note per artifact "
        f"appears under data/vault/artifacts/'), but it does not exist "
        f"after a successful run"
    )

    artifact_files = [p for p in artifacts_dir.iterdir() if p.is_file()]
    assert len(artifact_files) == len(expected_artifact_records), (
        f"expected exactly one artifact note per artifact under "
        f"{artifacts_dir}, got {len(artifact_files)} file(s) for "
        f"{len(expected_artifact_records)} artifact record(s). Files: "
        f"{sorted(p.name for p in artifact_files)}"
    )

    for expected in expected_artifact_records:
        note_path = _find_note_for_id(artifacts_dir, expected["artifact_id"], "artifact_id")
        frontmatter = _assert_artifact_note_matches_expected(note_path, expected, field_axis)

        assert frontmatter.get("retrievable") is True, (
            f"expected {note_path}'s frontmatter 'retrievable' to be the "
            f"real YAML boolean True for a non-discard role {expected['artifact_role']!r} "
            f"(PRD §8 P0-5 implies only discard is flagged non-retrievable), "
            f"got {frontmatter.get('retrievable')!r} ({type(frontmatter.get('retrievable')).__name__})"
        )

    # separation, both directions (PRD §8 P0-8) -- see module docstring,
    # seam decision 4.
    for expected in expected_artifact_records:
        prose_side_matches = (
            [p for p in prose_dir.iterdir() if p.is_file() and p.stem == expected["artifact_id"]]
            if prose_dir.exists()
            else []
        )
        assert prose_side_matches == [], (
            f"expected no artifact note for {expected['artifact_id']!r} to "
            f"be written under {prose_dir} -- the prose pool and artifact "
            f"pool must be separate surfaces (PRD §8 P0-8), got: "
            f"{prose_side_matches}"
        )

    # the prose notes must be unaffected by artifact routing.
    assert prose_dir.exists(), (
        f"expected `axial vault write` to still create {prose_dir} and "
        f"write prose notes into it (Gherkin: 'the prose notes are "
        f"unaffected'), but it does not exist after a successful run"
    )
    prose_files = [p for p in prose_dir.iterdir() if p.is_file()]
    assert len(prose_files) == len(expected_chunk_records), (
        f"expected the prose pool to be unaffected by artifact routing: "
        f"still exactly one prose note per chunk under {prose_dir}, got "
        f"{len(prose_files)} file(s) for {len(expected_chunk_records)} "
        f"chunk record(s)"
    )
    for expected_chunk in expected_chunk_records:
        _find_note_for_id(prose_dir, expected_chunk["chunk_id"], "chunk_id")
        artifact_side_matches = [
            p
            for p in artifacts_dir.iterdir()
            if p.is_file() and p.stem == expected_chunk["chunk_id"]
        ]
        assert artifact_side_matches == [], (
            f"expected no prose note for chunk {expected_chunk['chunk_id']!r} "
            f"to be written under {artifacts_dir} -- the prose pool and "
            f"artifact pool must be separate surfaces (PRD §8 P0-8), got: "
            f"{artifact_side_matches}"
        )


def test_vault_write_flags_discard_artifact_as_not_retrievable(isolated_vault_root):
    root = isolated_vault_root
    artifacts_dir = _artifacts_dir(root)

    field_axis = _in_schema_field_axis()
    _arrange_stored_envelope(root)
    forced_env = {STUB_ARTIFACT_ROLE_ENV_VAR: DISCARD_ROLE}
    expected_artifact_records = _arrange_expected_artifact_records(root, extra_env=forced_env)

    assert expected_artifact_records[0]["artifact_role"] == DISCARD_ROLE, (
        f"test setup invariant broken: forcing {STUB_ARTIFACT_ROLE_ENV_VAR}="
        f"{DISCARD_ROLE!r} on `axial artifacts` must yield an artifact_role "
        f"of {DISCARD_ROLE!r}, got {expected_artifact_records[0]['artifact_role']!r}"
    )

    result = _run_vault_write("stub", str(PROSE_AND_TABLE_PDF), cwd=root, extra_env=forced_env)
    _assert_not_argparse_fallback(result, "vault write")
    assert result.returncode == 0, (
        f"expected exit code 0 for `axial vault write` with a discard-roled "
        f"artifact and the stub LLM provider configured, got "
        f"{result.returncode}\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    expected = expected_artifact_records[0]
    note_path = _find_note_for_id(artifacts_dir, expected["artifact_id"], "artifact_id")
    frontmatter = _assert_artifact_note_matches_expected(note_path, expected, field_axis)

    assert frontmatter.get("retrievable") is False, (
        f"expected {note_path}'s frontmatter 'retrievable' to be the real "
        f"YAML boolean False for a discard-roled artifact (Gherkin: "
        f"'the discard-roled artifact note is present but flagged "
        f"retrievable: false'; PRD §8 P0-5), got "
        f"{frontmatter.get('retrievable')!r} "
        f"({type(frontmatter.get('retrievable')).__name__})"
    )

    # the discard-roled artifact must still be PRESENT in the pool, not
    # omitted (PRD §8 P0-5: "discard-tagged artifacts are RETAINED in the
    # pool but flagged non-retrievable").
    artifact_files = [p for p in artifacts_dir.iterdir() if p.is_file()]
    assert len(artifact_files) == 1, (
        f"expected the discard-roled artifact to be retained as exactly "
        f"one note under {artifacts_dir} (not omitted), got "
        f"{len(artifact_files)}: {sorted(p.name for p in artifact_files)}"
    )


def test_vault_write_artifact_pool_is_idempotent_on_repeat_runs(isolated_vault_root):
    root = isolated_vault_root
    artifacts_dir = _artifacts_dir(root)

    _arrange_stored_envelope(root)
    expected_artifact_records = _arrange_expected_artifact_records(root)

    first = _run_vault_write("stub", str(PROSE_AND_TABLE_PDF), cwd=root)
    _assert_not_argparse_fallback(first, "vault write")
    assert first.returncode == 0, (
        f"expected exit code 0 on the first `axial vault write` run, got "
        f"{first.returncode}\nstdout: {first.stdout!r}\nstderr: {first.stderr!r}"
    )

    assert artifacts_dir.exists(), (
        f"expected {artifacts_dir} to exist after the first `axial vault "
        f"write` run, but it does not"
    )
    first_files = sorted(p for p in artifacts_dir.iterdir() if p.is_file())
    assert len(first_files) == len(expected_artifact_records), (
        f"expected exactly one artifact note per artifact after the first "
        f"run, got {len(first_files)} for {len(expected_artifact_records)} "
        f"artifact record(s)"
    )
    first_contents = {p.name: p.read_bytes() for p in first_files}

    second = _run_vault_write("stub", str(PROSE_AND_TABLE_PDF), cwd=root)
    _assert_not_argparse_fallback(second, "vault write")
    assert second.returncode == 0, (
        f"expected exit code 0 on the repeat `axial vault write` run over "
        f"the same fixture, got {second.returncode}\n"
        f"stdout: {second.stdout!r}\nstderr: {second.stderr!r}"
    )

    second_files = sorted(p for p in artifacts_dir.iterdir() if p.is_file())
    assert [p.name for p in second_files] == [p.name for p in first_files], (
        f"expected re-running `axial vault write` to OVERWRITE the same "
        f"artifact note file(s), not create additional ones (Gherkin: "
        f"'re-running is idempotent'; plan inner-loop: 'overwrites an "
        f"artifact note idempotently rather than duplicating it'), got "
        f"first-run files {sorted(p.name for p in first_files)} vs. "
        f"second-run files {sorted(p.name for p in second_files)}"
    )

    second_contents = {p.name: p.read_bytes() for p in second_files}
    assert second_contents == first_contents, (
        "expected every artifact note's byte content to be identical "
        "across two consecutive `axial vault write` runs over the same "
        "fixture+env (idempotent overwrite, not drift), but at least one "
        "note's content differed"
    )
