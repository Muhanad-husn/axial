"""Outer acceptance test for issue #34, slice 02 (xref-backlinks).

Locked behavioral contract (DEC-1) -- do not edit once committed red.

Given a fixture source whose chunk references an artifact, and
      AXIAL_LLM_PROVIDER=stub
When  the user runs `axial vault write <fixture>`
Then  the referencing prose note's frontmatter carries `artifact_refs`
      including the artifact_id
And   the referenced artifact note's frontmatter carries `cited_by`
      including the chunk_id
And   a note with no references carries an empty or absent backlink field
      (never a dangling one)
And   re-running is idempotent -- no duplicate backlink entries

See specs/PRODUCT.md §5 stage 7 ("Cross-reference pass. Detect prose->
artifact references ('as Table 3 shows') and write bidirectional links into
both sides' frontmatter... Output: vault notes ... with backlinks."), §7.2
("Chunk-level: ... `artifact_refs`" / "Artifact notes carry: ... `cited_by`
back-references to prose chunks."), and §8 P0-7 ("Prose->artifact references
produce bidirectional links in both notes' frontmatter.") and P0-8
("Prose pool and artifact pool are separate, independently queryable
surfaces sharing metadata conventions.") for the source of truth.
Plan: plans/xref/02-xref-backlinks.md.

Fixture reuse: tests/fixtures/extract/prose_and_table.pdf (+ its committed
prose_and_table_tree.json), the exact fixture tests/test_xref.py (slice 01)
and tests/test_vault_artifacts.py (artifacts slice 02) already lock
contracts against. It carries a stored-envelope-eligible structure (two
top-level sections, "Introduction" and "Discussion") and exactly one
artifact node (a table, nested under "Introduction"), so `axial vault
write` on it exercises prose notes, one artifact note, and (once this
slice lands) the backlink pass over both, in a single fixture. No new
fixture is needed.

Seam decision 1 -- reusing slice 01's already-implemented
AXIAL_STUB_XREF_TARGET seam, never inventing a new one
-----------------------------------------------------------------------
tests/test_xref.py (slice 01, already green) locked and
src/axial/llm.py's `_canned_xref_response` already implements
`AXIAL_STUB_XREF_TARGET`: unset/"" makes the stub's `pass_name="xref"`
response reference NO artifact for EVERY chunk-level xref call in the run
(the empty/no-references case, the default); set to a string `S` makes it
reference exactly `S` for EVERY chunk-level call in the run (uniformly --
the stub dispatches by pass_name only, never by which chunk is asking).
This test drives all three Gherkin backlink clauses with that existing,
already-implemented seam alone -- it invents nothing new in src/, and it
never asserts anything about xref's own detection/dangling-filter logic
(that is slice 01's already-locked contract in tests/test_xref.py); this
test's whole concern is what `axial vault write` does with the pairs xref
already detects: does it materialize them as bidirectional frontmatter.

Seam decision 2 -- sequential runs, not a single mixed-reference run
-----------------------------------------------------------------------
Because `AXIAL_STUB_XREF_TARGET` (per seam decision 1) applies uniformly to
every chunk-level xref call within one process run, a single `axial vault
write` invocation cannot produce a MIX of some chunks referencing the
artifact and others not -- it is all-chunks-reference or no-chunks-reference
for that one run. tests/test_xref.py's own outer test resolved the
analogous problem (proving the happy path and the empty path from the same
fixture) the same way: separate CLI invocations, each driving one branch
deterministically. This test does the same, in sequence over the SAME
fixture+notes:
  1. First run, target unset (default): proves the "note with no
     references carries an empty or absent backlink field, never a
     dangling one" clause -- for every prose note AND the one artifact
     note, since nothing references anything in this run.
  2. Second run (same fixture), target set to the one real artifact_id:
     proves the "referencing prose note carries artifact_refs including
     the artifact_id" and "referenced artifact note carries cited_by
     including the chunk_id" clauses, plus full bidirectional consistency
     (every artifact_refs entry has a matching cited_by entry and vice
     versa) -- checked both ways explicitly, not just by construction.
  3. Third run (same fixture, same target unchanged): proves "re-running
     is idempotent -- no duplicate backlink entries" by asserting neither
     list-valued field's content or length changed from run 2.
This sequence is not merely convenient plumbing: run 1 -> run 2 proves the
backlink pass actually ADDS the fields when a reference newly appears
(not merely a static default baked in once), and run 2 -> run 3 proves it
does not re-add/duplicate on a stable rerun -- both real, observable
production behaviors this slice must deliver, not shape-only checks.

Seam decision 3 -- computing expected chunk_id/artifact_id sets, never
hardcoding them
-----------------------------------------------------------------------
Mirroring tests/test_xref.py's seam decision 3 and
tests/test_vault_artifacts.py's seam decision 1, this test never hardcodes
chunk_id/artifact_id values. It independently runs `axial chunk` and
`axial artifacts` (both already-green, stub provider, same fixture) to
discover the fixture's real chunk_id set and its one real artifact_id, and
uses those as the sets `axial vault write`'s backlink pass must reference
by name.

Seam decision 4 -- frontmatter field names and shape locked by this test
-----------------------------------------------------------------------
The Gherkin and the plan both name the two fields literally:
`artifact_refs` (a list of artifact_id strings) on a prose note, and
`cited_by` (a list of chunk_id strings) on an artifact note. This test
locks exactly those two names and that list-of-strings shape, and treats a
YAML-absent key or an explicit null as equivalent to an empty list (the
Gherkin's "empty or absent"). It does NOT accept a bare scalar (e.g. a lone
string, not wrapped in a list) as a valid "reference" -- that would be
exactly the "dangling" shape the Gherkin's third clause rules out.

This test does not lock how/when within `run_vault_write` the backlink
pass runs (a final patch step over already-written notes vs. folding the
xref pairs into the frontmatter before the first write -- both satisfy the
observable contract this test checks), only its observable, black-box
effect on the two note pools' frontmatter.

Test hygiene: this test relies on tests/conftest.py's autouse
`_isolate_persisted_tree_and_envelope_state` fixture for data/trees/ and
data/envelopes/ isolation (not re-implemented here); `data/vault/` is not
one of that fixture's protected directories, so this test defines its own
`clean_vault` fixture (mirroring tests/test_vault_write.py's and
tests/test_vault_artifacts.py's fixture of the same name) to remove any
file/directory it newly creates there.

Arrange-mechanism change (issue #68, vault isolation) -- no behavioral
assertion changed
-----------------------------------------------------------------------
Exactly as tests/test_vault_write.py, tests/test_vault_tag_frontmatter.py,
and tests/test_vault_artifacts.py now document: once real gold-corpus notes
started landing in the real `data/vault/prose/`, this test's own local
`clean_vault` fixture (described above) became actively dangerous, not just
insufficient -- it set-differenced the ENTIRE real `data/vault/` tree via
`.rglob("*")` and deleted anything "newly appeared" at teardown, which is
exactly the shape that destroys a concurrently-written real note (a live
ingestion worker's note, created during this test's run, looks identical to
this test's own output to a blind before/after diff). No CLI flag or env
var exists to redirect `vault_dir`/`envelopes_dir`/the domain directory,
and editing the real `config/pipeline.yaml` is out of bounds. So every
`axial` subprocess this test spawns now runs with `cwd` set to
`isolated_vault_root` (tests/conftest.py's opt-in fixture, issue #68): a
fresh per-test staging directory outside this repo entirely.
`TREES_DIR`/`VAULT_DIR`/`PROSE_DIR`/`ARTIFACTS_DIR` are now computed from
that root instead of hardcoded at `REPO_ROOT`; the former `clean_vault`
fixture (and its `_vault_files`/`_vault_dirs` diff-and-delete helpers)
above is superseded by `isolated_vault_root` and removed entirely -- the
real `data/vault/` is never read, moved, or written by this test. Every
behavioral assertion below is unchanged -- only where the CLI runs and
where this test looks for its own output moved.
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
from pathlib import Path

import yaml

from axial.chunk import run_chunk
from axial.envelope import compute_source_id
from axial.llm import StubLLMClient

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "extract"

PROSE_AND_TABLE_PDF = FIXTURES_DIR / "prose_and_table.pdf"
PROSE_AND_TABLE_TREE_FIXTURE = FIXTURES_DIR / "prose_and_table_tree.json"

PROVIDER_ENV_VAR = "AXIAL_LLM_PROVIDER"
# The existing fault-injection seam this test reuses -- see module
# docstring, seam decision 1. Already implemented by slice 01
# (src/axial/llm.py's `_canned_xref_response`); this test does not add it.
STUB_XREF_TARGET_ENV_VAR = "AXIAL_STUB_XREF_TARGET"

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


@contextlib.contextmanager
def _chdir(path: Path):
    """Temporarily change the process cwd to `path` (issue #151 slice 01
    migration -- see `_arrange_known_chunk_ids` below): the OLD
    `axial.chunk.run_chunk` mechanism calls `axial.extract.extract`
    internally, which resolves its persisted-tree cache directory
    (`axial.extract.TREES_DIR`) as a plain, cwd-relative path with no
    override parameter. Calling `run_chunk` in-process instead of shelling
    out to `axial chunk` (whose CLI verb now runs the NEW embedding-based
    mechanism as of issue #151) needs this to reproduce the exact
    resolution the old subprocess's own `cwd=` argument achieved."""
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def _run_envelope(provider: str, *args: str, cwd: Path) -> subprocess.CompletedProcess:
    return _run_axial(["envelope", *args], provider, cwd=cwd)


def _run_artifacts(provider: str, *args: str, cwd: Path) -> subprocess.CompletedProcess:
    return _run_axial(["artifacts", *args], provider, cwd=cwd)


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


def _place_tree_fixture(source_pdf: Path, tree_fixture_path: Path, root: Path) -> Path:
    """Pre-place the committed REAL tree fixture at
    <root>/data/trees/<source_id>.json so `axial.extract.extract` reuses it
    verbatim instead of running docling (PRD §7.4)."""
    source_id = compute_source_id(source_pdf)
    tree_path = _trees_dir(root) / f"{source_id}.json"
    tree_path.parent.mkdir(parents=True, exist_ok=True)
    tree_path.write_bytes(tree_fixture_path.read_bytes())
    return tree_path


def _arrange_stored_envelope(root: Path) -> None:
    """Pre-place the real tree fixture, then run `axial envelope` with the
    stub provider so a stored envelope exists on disk before vault write --
    `vault write` never recomputes one (PRD §10 "no recompute")."""
    _place_tree_fixture(PROSE_AND_TABLE_PDF, PROSE_AND_TABLE_TREE_FIXTURE, root)
    result = _run_envelope("stub", str(PROSE_AND_TABLE_PDF), cwd=root)
    _assert_not_argparse_fallback(result, "envelope")
    assert result.returncode == 0, (
        f"arrange step failed: expected exit code 0 for `axial envelope` on "
        f"the fixture with the stub LLM provider, got {result.returncode}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )


def _parse_json_records(stdout: str, *, array_key: str, kind: str) -> list[dict]:
    """Parse records from stdout, tolerating any of: a bare JSON array, a
    JSON object with a top-level `array_key` array, or newline-delimited
    JSON (one record per line) -- mirrors this suite's shared parsing
    leniency convention (tests/test_xref.py, tests/test_vault_artifacts.py)."""
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


def _arrange_known_chunk_ids(root: Path) -> set[str]:
    """Independently call the OLD `axial.chunk.run_chunk` mechanism
    IN-PROCESS (stub client) to discover the exact set of real chunk_ids
    this fixture yields -- see module docstring, seam decision 3.

    Migrated off a subprocess call to the standalone `axial chunk` CLI
    (issue #151 slice 01): that CLI verb now runs the NEW embedding-based
    chunk mechanism and no longer emits chunk records on stdout at all. The
    OLD mechanism `axial vault write` itself still calls in-process
    (`axial.chunk.run_chunk`) ships unchanged until issue #154 retires it,
    so calling it here in-process too keeps this ground truth identical to
    what that unchanged call site actually produces."""
    with _chdir(root):
        records = run_chunk(PROSE_AND_TABLE_PDF, client=StubLLMClient())
    chunk_ids = {r.get("chunk_id") for r in records}
    assert chunk_ids and all(isinstance(cid, str) and cid for cid in chunk_ids), (
        f"arrange step failed: expected run_chunk to yield at least one "
        f"chunk record with a non-empty chunk_id, got records: {records!r}"
    )
    return chunk_ids


def _arrange_known_artifact_id(root: Path) -> str:
    """Run `axial artifacts` (already green) to discover this fixture's one
    real artifact_id -- see module docstring, seam decision 3."""
    result = _run_artifacts("stub", str(PROSE_AND_TABLE_PDF), cwd=root)
    _assert_not_argparse_fallback(result, "artifacts")
    assert result.returncode == 0, (
        f"arrange step failed: expected exit code 0 for `axial artifacts` "
        f"on the fixture with the stub LLM provider, got {result.returncode}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    records = _parse_json_records(result.stdout, array_key="artifacts", kind="artifacts")
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


def _split_frontmatter(text: str, note_path: Path) -> tuple[dict, str]:
    """Split a note's text into its parsed YAML frontmatter mapping and its
    body string, per the standard `---`-delimited convention this suite
    already locks (tests/test_vault_write.py's seam decision 4). Splits on
    a bare `---` line, which src/axial/vault.py's `render_note` guarantees
    cannot appear inside the frontmatter body itself (its own
    `default_style='"'` docstring explains why)."""
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


def _read_frontmatter(note_path: Path) -> dict:
    return _split_frontmatter(note_path.read_text(encoding="utf-8"), note_path)[0]


def _normalized_backlink_list(value, field_name: str, note_path: Path) -> list:
    """Normalize a possibly-absent/null list-valued backlink field: a
    missing key or explicit YAML null is treated as the empty list (the
    Gherkin's "empty or absent"). A bare scalar (e.g. a lone id string, not
    wrapped in a list) is rejected outright -- that is exactly the
    "dangling" shape the Gherkin's third clause rules out, never a valid
    stand-in for "no references"."""
    if value is None:
        return []
    assert isinstance(value, list), (
        f"expected {note_path}'s frontmatter {field_name!r} to be a YAML "
        f"list (or absent/null for 'no references') -- never a bare scalar "
        f"(a dangling single value, not a real list), got "
        f"{type(value).__name__}: {value!r}"
    )
    for entry in value:
        assert isinstance(entry, str) and entry, (
            f"expected every entry of {note_path}'s frontmatter "
            f"{field_name!r} to be a non-empty string id, got {entry!r} "
            f"(full list: {value!r})"
        )
    return value


def test_vault_write_backlinks_are_bidirectional_and_idempotent(isolated_vault_root):
    root = isolated_vault_root
    prose_dir = _prose_dir(root)
    artifacts_dir = _artifacts_dir(root)

    _arrange_stored_envelope(root)
    known_chunk_ids = _arrange_known_chunk_ids(root)
    known_artifact_id = _arrange_known_artifact_id(root)

    # --- Run 1 (target unset -- the default): a note with no references
    # carries an empty or absent backlink field, never a dangling one. ---
    no_ref_result = _run_vault_write("stub", str(PROSE_AND_TABLE_PDF), cwd=root)
    _assert_not_argparse_fallback(no_ref_result, "vault write")
    assert no_ref_result.returncode == 0, (
        f"expected exit code 0 for `axial vault write` when the underlying "
        f"xref pass detects no references, got {no_ref_result.returncode}\n"
        f"stdout: {no_ref_result.stdout!r}\nstderr: {no_ref_result.stderr!r}"
    )

    for chunk_id in known_chunk_ids:
        note_path = _find_note_for_id(prose_dir, chunk_id, "chunk_id")
        frontmatter = _read_frontmatter(note_path)
        refs = _normalized_backlink_list(
            frontmatter.get("artifact_refs"), "artifact_refs", note_path
        )
        assert refs == [], (
            f"expected {note_path}'s frontmatter 'artifact_refs' to be "
            f"empty or absent when no reference was detected for this "
            f"chunk (Gherkin: 'a note with no references carries an empty "
            f"or absent backlink field'), got {refs!r}"
        )

    artifact_note_path = _find_note_for_id(artifacts_dir, known_artifact_id, "artifact_id")
    artifact_frontmatter = _read_frontmatter(artifact_note_path)
    cited_by = _normalized_backlink_list(
        artifact_frontmatter.get("cited_by"), "cited_by", artifact_note_path
    )
    assert cited_by == [], (
        f"expected {artifact_note_path}'s frontmatter 'cited_by' to be "
        f"empty or absent when no chunk references this artifact (Gherkin: "
        f"'a note with no references carries an empty or absent backlink "
        f"field'), got {cited_by!r}"
    )

    # --- Run 2 (target = the one real artifact_id, applied to every
    # chunk-level xref call -- see module docstring, seam decision 1): the
    # referencing prose notes carry artifact_refs including the
    # artifact_id, the referenced artifact note carries cited_by including
    # every referencing chunk_id, and the two sides agree bidirectionally. ---
    happy_result = _run_vault_write(
        "stub",
        str(PROSE_AND_TABLE_PDF),
        cwd=root,
        extra_env={STUB_XREF_TARGET_ENV_VAR: known_artifact_id},
    )
    _assert_not_argparse_fallback(happy_result, "vault write")
    assert happy_result.returncode == 0, (
        f"expected exit code 0 for `axial vault write` with the stub "
        f"canned to reference a real artifact from every chunk, got "
        f"{happy_result.returncode}\nstdout: {happy_result.stdout!r}\n"
        f"stderr: {happy_result.stderr!r}"
    )

    prose_refs_after_happy_run: dict[str, list[str]] = {}
    for chunk_id in known_chunk_ids:
        note_path = _find_note_for_id(prose_dir, chunk_id, "chunk_id")
        frontmatter = _read_frontmatter(note_path)
        refs = _normalized_backlink_list(
            frontmatter.get("artifact_refs"), "artifact_refs", note_path
        )
        assert known_artifact_id in refs, (
            f"expected {note_path}'s frontmatter 'artifact_refs' to "
            f"include the referenced artifact_id {known_artifact_id!r} "
            f"(Gherkin: 'the referencing prose note's frontmatter carries "
            f"artifact_refs including the artifact_id'), got {refs!r}"
        )
        prose_refs_after_happy_run[chunk_id] = refs

    artifact_frontmatter = _read_frontmatter(artifact_note_path)
    cited_by_after_happy_run = _normalized_backlink_list(
        artifact_frontmatter.get("cited_by"), "cited_by", artifact_note_path
    )
    assert set(cited_by_after_happy_run) == known_chunk_ids, (
        f"expected {artifact_note_path}'s frontmatter 'cited_by' to name "
        f"exactly the chunk_ids that reference it (Gherkin: 'the referenced "
        f"artifact note's frontmatter carries cited_by including the "
        f"chunk_id'), got {sorted(cited_by_after_happy_run)} vs. expected "
        f"{sorted(known_chunk_ids)}"
    )

    # Bidirectional consistency, checked explicitly both ways (plan Goal:
    # "Every artifact_refs entry has a matching cited_by and vice versa").
    for chunk_id, refs in prose_refs_after_happy_run.items():
        assert chunk_id in cited_by_after_happy_run, (
            f"bidirectional consistency broken: chunk {chunk_id!r} carries "
            f"artifact_refs {refs!r} naming {known_artifact_id!r}, but "
            f"{artifact_note_path}'s cited_by {cited_by_after_happy_run!r} "
            f"does not name this chunk back"
        )
    for chunk_id in cited_by_after_happy_run:
        assert known_artifact_id in prose_refs_after_happy_run.get(chunk_id, []), (
            f"bidirectional consistency broken: {artifact_note_path}'s "
            f"cited_by names chunk {chunk_id!r}, but that chunk's own "
            f"prose note does not carry a matching artifact_refs entry for "
            f"{known_artifact_id!r} (got {prose_refs_after_happy_run.get(chunk_id)!r})"
        )

    # --- Run 3 (same fixture, same target unchanged): re-running is
    # idempotent -- no duplicate backlink entries. ---
    repeat_result = _run_vault_write(
        "stub",
        str(PROSE_AND_TABLE_PDF),
        cwd=root,
        extra_env={STUB_XREF_TARGET_ENV_VAR: known_artifact_id},
    )
    _assert_not_argparse_fallback(repeat_result, "vault write")
    assert repeat_result.returncode == 0, (
        f"expected exit code 0 on a repeat `axial vault write` run over "
        f"the same fixture+target, got {repeat_result.returncode}\n"
        f"stdout: {repeat_result.stdout!r}\nstderr: {repeat_result.stderr!r}"
    )

    for chunk_id in known_chunk_ids:
        note_path = _find_note_for_id(prose_dir, chunk_id, "chunk_id")
        frontmatter = _read_frontmatter(note_path)
        refs_after_repeat = _normalized_backlink_list(
            frontmatter.get("artifact_refs"), "artifact_refs", note_path
        )
        assert len(refs_after_repeat) == len(set(refs_after_repeat)), (
            f"expected {note_path}'s frontmatter 'artifact_refs' to carry "
            f"no duplicate entries after a repeat `axial vault write` run "
            f"(Gherkin: 're-running is idempotent -- no duplicate backlink "
            f"entries'), got {refs_after_repeat!r}"
        )
        assert refs_after_repeat == prose_refs_after_happy_run[chunk_id], (
            f"expected {note_path}'s frontmatter 'artifact_refs' to be "
            f"unchanged by a repeat run with the same target (idempotent, "
            f"not merely non-duplicated), got {refs_after_repeat!r} vs. "
            f"the first happy run's {prose_refs_after_happy_run[chunk_id]!r}"
        )

    artifact_frontmatter = _read_frontmatter(artifact_note_path)
    cited_by_after_repeat = _normalized_backlink_list(
        artifact_frontmatter.get("cited_by"), "cited_by", artifact_note_path
    )
    assert len(cited_by_after_repeat) == len(set(cited_by_after_repeat)), (
        f"expected {artifact_note_path}'s frontmatter 'cited_by' to carry "
        f"no duplicate entries after a repeat `axial vault write` run "
        f"(Gherkin: 're-running is idempotent -- no duplicate backlink "
        f"entries'), got {cited_by_after_repeat!r}"
    )
    assert set(cited_by_after_repeat) == set(cited_by_after_happy_run), (
        f"expected {artifact_note_path}'s frontmatter 'cited_by' to be "
        f"unchanged by a repeat run with the same target, got "
        f"{sorted(cited_by_after_repeat)} vs. the first happy run's "
        f"{sorted(cited_by_after_happy_run)}"
    )
