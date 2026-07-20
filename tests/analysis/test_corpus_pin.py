"""Outer acceptance test for issue #248, slice 02 (corpus-pin-manifest).

Locked behavioral contract (DEC-1) -- do not edit once committed red.

Given a fixture vault with two prose notes under data/vault/prose/ and one
      envelope under data/envelopes/
When  `axial pin write baseline` runs
Then  evals/corpus_pin/baseline.json is written, the command exits 0, and the
      file carries a `sources` list (one entry per envelope, each with
      `source_id` and `content_hash`), an `ingest_code_sha` equal to the
      repository's current git commit, and a `vault_snapshot_hash`
  And no value anywhere in the file contains any chunk_text from the fixture
      notes

Given the same unchanged fixture vault
When  `axial pin write baseline` runs a second time
Then  the written file is byte-identical to the first run's file

Given one fixture prose note whose `field.primary` tag value is then changed
When  `axial pin write baseline` runs again
Then  the `vault_snapshot_hash` differs from the previous run's hash and the
      `sources` list is unchanged

Given a fixture vault whose envelope's raw source file is absent from
      data/sources/ (e.g. it was never placed there, or was cleaned up
      since the envelope was written)
When  `axial pin write baseline` runs
Then  the command exits non-zero, no evals/corpus_pin/baseline.json is
      written at all, and stderr names both the missing source_id and the
      sources directory -- `content_hash` is never silently backfilled from
      the envelope hash, the source_id's own digest, or any other fallback
      (founder adjudication on issue #248, added to this locked contract
      when the fixture was updated to place its source file under
      data/sources/ -- see git history for that commit's message)

See specs/PHASE-B.md §7.12 (the corpus-pin manifest, [FIRM]: source list +
content hashes reusing `envelope.compute_source_id()`'s hashing path,
ingest-code SHA, vault snapshot hash over chunk_ids + tags never chunk_text
per DEC-23) and §8 P0-10, plus docs/eval/01-answer-quality.md's "Corpus pin"
section (the format this slice is the sole owner of). Plan:
plans/analysis-foundation/02-corpus-pin-manifest.md.

Isolation -- the isolated staging root (issue #68), same seam as
tests/eval/test_eval.py
-----------------------------------------------------------------------
`axial pin write` resolves `data/vault/`, `data/envelopes/`, and (by the
same established convention -- see tests/conftest.py's `isolated_vault_root`
docstring: no dir ever reads an env-var override, and the CLI exposes no
`--vault-dir`/`--envelopes-dir`/`--evals-dir` flag anywhere in this
codebase) `evals/` too, as plain paths relative to the process's current
working directory. This test never touches the real, shared `data/`
tree: it runs the CLI with `cwd` set to `isolated_vault_root`, a private
`tmp_path` staging root, exactly as `tests/eval/test_eval.py` does for
`axial eval`. `uv run --project <repo>` is required (not bare `uv run`)
because the subprocess's cwd is deliberately NOT the repo checkout.

Seam decision -- `ingest_code_sha` is the CODE's commit, not the caller's cwd
-----------------------------------------------------------------------
Per §7.12, `ingest_code_sha` is "the commit the Phase-A pipeline ran at" --
i.e. code provenance, not data location. Running the fixture from an
isolated non-repo `tmp_path` cwd is a deliberate stress of that reading: a
correct implementation resolves the axial checkout's own HEAD (e.g. via a
path relative to the installed package, mirroring how `tests/conftest.py`
itself derives `REPO_ROOT` from `Path(__file__)`), not the operator's
launch directory. This test computes its own expected SHA independently,
by shelling `git rev-parse HEAD` with `cwd` pinned to this repo checkout,
and compares it to what the manifest records.

Seam decision -- fixture notes/envelope are built directly, not through the
pipeline
-----------------------------------------------------------------------
Building the fixture via real `axial envelope`/`axial chunk`/`axial tag`
runs would require an LLM provider, defeating the point of an LLM-free
outer test. Instead this test writes one envelope JSON directly (the §7.3
shape) and two prose notes directly, using the already-shipped, stable
`axial.vault.render_note` helper (issue #31 slice 04's own frontmatter
renderer) so the notes are byte-for-byte the same format the real pipeline
writes, and `axial.envelope.compute_source_id` so the fixture's
`source_id` is genuinely content-derived exactly as a real envelope's
would be -- never a hand-typed id string. Neither helper belongs to this
slice's own implementation surface (`axial.eval.corpus_pin`, per the plan's
boundary line); reusing them here is the same "derive expectations from
the real tool, never hardcode" seam `tests/eval/test_eval.py` and
`tests/analysis/test_brief_intake.py` already establish.

DEC-23 leak check -- whole-file, not field-by-field
-----------------------------------------------------------------------
Each fixture note's `chunk_text` carries a unique sentinel string
(`SENTINEL_ALPHA`/`SENTINEL_BETA`) that appears nowhere else in the
fixture. Every scenario below asserts neither sentinel appears ANYWHERE in
the raw serialized pin file's text -- not merely absent from a `sources`
entry or some other field the implementer might expect it to be checked
against. This is the locked guarantee that a manifest committed to the
repo (`evals/corpus_pin/` is not gitignored, unlike `data/`) can never leak
source prose (DEC-23).

LLM-free by construction
-----------------------------------------------------------------------
Every CLI invocation below runs with `AXIAL_LLM_PROVIDER=explode` (the
poison-client env seam already established by
`tests/eval/test_eval.py`/`tests/ingestion/test_envelope.py`/etc. --
`ExplodingLLMClient.complete()` raises if a text-generating call is ever
attempted). A run that reaches the LLM at all is a bug: `axial pin write`
succeeding under this env var directly proves zero model calls. As of this
commit the codebase has no separate embedding-model call path at all
(issue #191 retired the embedding chunking mechanism; recursive/structural
is now the sole chunker) -- so there is no second poison client needed to
cover "zero embedding calls"; the explode-provider run covers the whole
LLM-free claim.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from axial.envelope import compute_source_id
from axial.vault import render_note

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

PROVIDER_ENV_VAR = "AXIAL_LLM_PROVIDER"

# Unique, unmistakable sentinels -- never appear anywhere else in the
# fixture, so any match anywhere in the written pin file is unambiguously a
# chunk_text leak (DEC-23).
SENTINEL_ALPHA = (
    "SENTINEL_CHUNK_TEXT_ALPHA_7f2c91 -- synthetic placeholder introduction "
    "prose, not a real source excerpt, written only for the corpus-pin "
    "acceptance fixture."
)
SENTINEL_BETA = (
    "SENTINEL_CHUNK_TEXT_BETA_3d8e05 -- synthetic placeholder conclusion "
    "prose, not a real source excerpt, written only for the corpus-pin "
    "acceptance fixture."
)


def _run_pin_write(root: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env[PROVIDER_ENV_VAR] = "explode"  # poison: any text-gen LLM call crashes the run
    return subprocess.run(
        ["uv", "run", "--project", str(REPO_ROOT), "axial", "pin", "write", *args],
        cwd=root,
        capture_output=True,
        text=True,
        env=env,
    )


def _pin_path(root: Path, name: str = "baseline") -> Path:
    return root / "evals" / "corpus_pin" / f"{name}.json"


def _expected_git_sha() -> str:
    """The real axial checkout's own current HEAD -- computed independently
    of the CLI subprocess under test, and independently of whatever cwd
    that subprocess happens to run from (see the module docstring's seam
    decision on `ingest_code_sha`)."""
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _build_fixture_vault(root: Path) -> dict[str, Any]:
    """Writes one synthetic envelope and two synthetic prose notes directly
    into `root`'s data/envelopes/ and data/vault/prose/ (no pipeline run, no
    LLM -- see module docstring). Returns the fixture's identifying details
    so scenario tests can assert against them and mutate note 1 in place."""
    # A placeholder "source" file, hashed exactly the way a real ingested
    # source would be (axial.envelope.compute_source_id), so this fixture's
    # source_id is genuinely content-derived rather than a hand-typed
    # string standing in for one. Its content is throwaway filler, never
    # real book text (repo copyright policy).
    #
    # Placed under data/sources/ with a SUPPORTED_EXTENSIONS-real extension
    # (.pdf) -- not merely at the isolated root -- because `axial pin
    # write`'s `content_hash` is (per the founder's #248 adjudication) a
    # full sha256 of the raw ingested source file read from data/sources/,
    # never a hash of the LLM-produced envelope JSON: envelopes are
    # regenerated routinely (#235, #241, the GLM trial), so hashing the
    # envelope would move every content_hash on every regen even though no
    # source changed. `write_pin` fails loudly (`MissingSourceFileError`)
    # rather than falling back if no matching file is found here.
    # `compute_source_id` is called on this exact file (not a separate
    # stand-in) so the source_id's own embedded content digest and the
    # pin's content_hash describe the identical bytes -- keeping the
    # fixture honest rather than merely shape-matching. The `.pdf` name is
    # nominal only: corpus_pin never parses the file, only reads its raw
    # bytes, so no real PDF structure is required.
    sources_dir = root / "data" / "sources"
    sources_dir.mkdir(parents=True, exist_ok=True)
    source_file = sources_dir / "synthetic_source_fixture.pdf"
    source_file.write_text(
        "Synthetic placeholder source file for the corpus-pin acceptance "
        "fixture. Not real source material.",
        encoding="utf-8",
    )
    source_id = compute_source_id(source_file)

    envelope = {
        "source_id": source_id,
        "author": "Synthetic Author",
        "title": "A Synthetic Source For The Corpus-Pin Fixture",
        "date": 2020,
        "thesis": "A synthetic placeholder thesis, for fixture purposes only.",
        "toc": [
            {"title": "Introduction", "children": []},
            {"title": "Conclusion", "children": []},
        ],
        "scope": "scope:general",
        "stated_argument": "A synthetic placeholder restated argument, for fixture purposes only.",
    }
    envelopes_dir = root / "data" / "envelopes"
    envelopes_dir.mkdir(parents=True, exist_ok=True)
    (envelopes_dir / f"{source_id}.json").write_text(
        json.dumps(envelope, indent=2), encoding="utf-8"
    )

    source_meta = {
        "author": envelope["author"],
        "title": envelope["title"],
        "date": envelope["date"],
        "thesis": envelope["thesis"],
        "scope": envelope["scope"],
    }

    note_1_chunk_id = f"{source_id}_000_introduction_001"
    note_1_frontmatter: dict[str, Any] = {
        "chunk_id": note_1_chunk_id,
        "section": "Introduction",
        "chunk_text": SENTINEL_ALPHA,
        "source_meta": source_meta,
        "schema_version": "0.1",
        "role_in_argument": "role:claim",
        "field": {"primary": "state", "secondary": []},
        "claim_type": {"primary": "state-formation", "secondary": None, "subtags": []},
        "theory_school": {
            "primary": "institutionalist-state-centered",
            "secondary": None,
            "status": "candidate",
        },
        "empirical_scope": {"value": "scope:country-case", "polity": "Syria"},
        "polities_touched": ["Syria"],
        "artifact_refs": [],
    }
    note_1_body = f"# Introduction\n\n{SENTINEL_ALPHA}\n"

    note_2_chunk_id = f"{source_id}_001_conclusion_001"
    note_2_frontmatter: dict[str, Any] = {
        "chunk_id": note_2_chunk_id,
        "section": "Conclusion",
        "chunk_text": SENTINEL_BETA,
        "source_meta": source_meta,
        "schema_version": "0.1",
        "role_in_argument": "role:claim",
        "field": {"primary": "violence", "secondary": []},
        "claim_type": {"primary": "war-and-state", "secondary": None, "subtags": []},
        "theory_school": {
            "primary": "institutionalist-state-centered",
            "secondary": None,
            "status": "candidate",
        },
        "empirical_scope": {"value": "scope:country-case", "polity": "Syria"},
        "polities_touched": ["Syria"],
        "artifact_refs": [],
    }
    note_2_body = f"# Conclusion\n\n{SENTINEL_BETA}\n"

    vault_prose_dir = root / "data" / "vault" / "prose"
    vault_prose_dir.mkdir(parents=True, exist_ok=True)
    note_1_path = vault_prose_dir / f"{note_1_chunk_id}.md"
    note_2_path = vault_prose_dir / f"{note_2_chunk_id}.md"
    note_1_path.write_text(render_note(note_1_frontmatter, note_1_body), encoding="utf-8")
    note_2_path.write_text(render_note(note_2_frontmatter, note_2_body), encoding="utf-8")

    return {
        "source_id": source_id,
        "source_file": source_file,
        "sources_dir": sources_dir,
        "note_1_path": note_1_path,
        "note_1_frontmatter": note_1_frontmatter,
        "note_1_body": note_1_body,
        "note_2_path": note_2_path,
        "note_2_frontmatter": note_2_frontmatter,
        "note_2_body": note_2_body,
    }


def _assert_ran_the_real_subcommand(result: subprocess.CompletedProcess) -> None:
    """Guard against a false pass: argparse's own "invalid choice"/
    "unrecognized arguments" error (raised while `axial pin write` isn't a
    real subcommand yet) is a distinct failure mode from a real,
    implemented-but-broken pin-write path. Surfacing it explicitly makes an
    early red run's cause obvious (mirrors tests/analysis/test_brief_intake.py
    and tests/eval/test_eval.py)."""
    combined_output = result.stdout + result.stderr
    assert (
        "invalid choice" not in combined_output and "unrecognized arguments" not in combined_output
    ), (
        "expected a real 'axial pin write' run, not an argparse fallback -- "
        "this means the `axial pin write` CLI subcommand does not exist "
        f"yet:\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )


def _assert_no_chunk_text_leak(raw_pin_text: str) -> None:
    """DEC-23: no value anywhere in the serialized pin file may contain any
    fixture note's chunk_text -- checked over the WHOLE raw file text, not
    scoped to any particular JSON field."""
    assert SENTINEL_ALPHA not in raw_pin_text, (
        "DEC-23 violation: the fixture's introduction-note chunk_text leaked "
        f"into the written pin file:\n{raw_pin_text}"
    )
    assert SENTINEL_BETA not in raw_pin_text, (
        "DEC-23 violation: the fixture's conclusion-note chunk_text leaked "
        f"into the written pin file:\n{raw_pin_text}"
    )


def test_pin_write_writes_manifest_with_sources_sha_and_snapshot_hash_leaking_no_chunk_text(
    isolated_vault_root,
):
    """Scenario 1 (issue #248): a fresh `axial pin write baseline` over the
    fixture vault writes evals/corpus_pin/baseline.json, exits 0, and the
    file carries a `sources` list (one entry per envelope, each with
    `source_id` + `content_hash`), an `ingest_code_sha` equal to the real
    repo's current git commit, and a `vault_snapshot_hash` -- with no
    fixture chunk_text leaking anywhere into the file (DEC-23)."""
    root = isolated_vault_root
    fixture = _build_fixture_vault(root)

    result = _run_pin_write(root, "baseline")
    _assert_ran_the_real_subcommand(result)
    assert result.returncode == 0, (
        "expected exit 0 for `axial pin write baseline` over a well-formed "
        f"fixture vault, got {result.returncode}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    pin_path = _pin_path(root)
    assert pin_path.is_file(), (
        f"expected evals/corpus_pin/baseline.json to be written under {root}, "
        f"found nothing at {pin_path}\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    raw_pin_text = pin_path.read_text(encoding="utf-8")
    _assert_no_chunk_text_leak(raw_pin_text)

    manifest = json.loads(raw_pin_text)

    assert "sources" in manifest, f"expected a top-level 'sources' key, got keys: {list(manifest)}"
    sources = manifest["sources"]
    assert len(sources) == 1, (
        f"expected exactly one 'sources' entry (one envelope was written), got {len(sources)}: "
        f"{sources}"
    )
    (entry,) = sources
    assert entry.get("source_id") == fixture["source_id"], (
        f"expected the source entry's source_id to equal the fixture envelope's own "
        f"source_id {fixture['source_id']!r}, got {entry.get('source_id')!r}"
    )
    assert isinstance(entry.get("content_hash"), str) and entry["content_hash"], (
        f"expected a non-empty string 'content_hash' on the source entry, got: {entry}"
    )

    expected_sha = _expected_git_sha()
    assert manifest.get("ingest_code_sha") == expected_sha, (
        "expected ingest_code_sha to equal the repository's current git commit "
        f"{expected_sha!r} (the CODE's commit -- computed independently of the "
        f"subprocess's own, deliberately non-repo, working directory), got "
        f"{manifest.get('ingest_code_sha')!r}"
    )

    assert (
        isinstance(manifest.get("vault_snapshot_hash"), str) and manifest["vault_snapshot_hash"]
    ), (
        f"expected a non-empty string 'vault_snapshot_hash', got: {manifest.get('vault_snapshot_hash')!r}"
    )


def test_pin_write_is_byte_identical_over_an_unchanged_vault(isolated_vault_root):
    """Scenario 2 (issue #248): re-running `axial pin write baseline` over
    the exact same, unchanged fixture vault produces a byte-identical
    file -- proving the manifest is diff-stable (sorted keys, deterministic
    hashing) rather than merely field-equal."""
    root = isolated_vault_root
    _build_fixture_vault(root)
    pin_path = _pin_path(root)

    first = _run_pin_write(root, "baseline")
    _assert_ran_the_real_subcommand(first)
    assert first.returncode == 0, (
        f"expected exit 0 on the first run, got {first.returncode}\n"
        f"stdout: {first.stdout!r}\nstderr: {first.stderr!r}"
    )
    first_bytes = pin_path.read_bytes()
    _assert_no_chunk_text_leak(first_bytes.decode("utf-8"))

    second = _run_pin_write(root, "baseline")
    assert second.returncode == 0, (
        f"expected exit 0 on the second, unchanged-vault run, got {second.returncode}\n"
        f"stdout: {second.stdout!r}\nstderr: {second.stderr!r}"
    )
    second_bytes = pin_path.read_bytes()

    assert first_bytes == second_bytes, (
        "expected a byte-identical evals/corpus_pin/baseline.json across two runs "
        "over the same unchanged fixture vault -- the manifest must be "
        "deterministic and diff-stable, not merely field-equivalent"
    )


def test_pin_write_snapshot_hash_moves_on_a_tag_change_but_sources_list_does_not(
    isolated_vault_root,
):
    """Scenario 3 (issue #248): changing one fixture note's `field.primary`
    tag and re-running moves `vault_snapshot_hash` while leaving `sources`
    completely unchanged -- the pin tracks tagging over the vault, not the
    envelope-derived source list, and the two are independent."""
    root = isolated_vault_root
    fixture = _build_fixture_vault(root)
    pin_path = _pin_path(root)

    baseline_run = _run_pin_write(root, "baseline")
    _assert_ran_the_real_subcommand(baseline_run)
    assert baseline_run.returncode == 0, (
        f"expected exit 0 on the baseline run, got {baseline_run.returncode}\n"
        f"stdout: {baseline_run.stdout!r}\nstderr: {baseline_run.stderr!r}"
    )
    baseline_manifest = json.loads(pin_path.read_text(encoding="utf-8"))

    # Mutate ONLY note 1's field.primary tag ("state" -> "violence", both
    # real schema values, config/domains/syria/schema.yaml's `field` axis)
    # and rewrite the same note file in place -- everything else about the
    # fixture (the envelope, note 2, note 1's chunk_text/chunk_id/section)
    # is untouched.
    mutated_frontmatter = dict(fixture["note_1_frontmatter"])
    mutated_frontmatter["field"] = {"primary": "violence", "secondary": []}
    fixture["note_1_path"].write_text(
        render_note(mutated_frontmatter, fixture["note_1_body"]), encoding="utf-8"
    )

    mutated_run = _run_pin_write(root, "baseline")
    assert mutated_run.returncode == 0, (
        f"expected exit 0 after mutating one note's field.primary tag, got "
        f"{mutated_run.returncode}\nstdout: {mutated_run.stdout!r}\nstderr: {mutated_run.stderr!r}"
    )
    mutated_raw_text = pin_path.read_text(encoding="utf-8")
    _assert_no_chunk_text_leak(mutated_raw_text)
    mutated_manifest = json.loads(mutated_raw_text)

    assert mutated_manifest.get("vault_snapshot_hash") != baseline_manifest.get(
        "vault_snapshot_hash"
    ), (
        "expected vault_snapshot_hash to differ after changing one note's "
        f"field.primary tag, but it stayed {baseline_manifest.get('vault_snapshot_hash')!r} "
        "on both runs"
    )
    assert mutated_manifest.get("sources") == baseline_manifest.get("sources"), (
        "expected the 'sources' list to be completely unchanged by a vault "
        f"tag edit (no envelope was touched), got baseline={baseline_manifest.get('sources')!r} "
        f"vs mutated={mutated_manifest.get('sources')!r}"
    )


def test_pin_write_fails_loudly_when_a_raw_source_file_is_missing(isolated_vault_root):
    """Scenario 4 (issue #248, founder adjudication on `content_hash`): if
    the envelope's raw source file cannot be found under data/sources/,
    `axial pin write` must fail loudly -- non-zero exit, no pin file written
    at all, stderr naming both the source_id and the sources directory --
    rather than silently backfilling content_hash from the envelope hash,
    the source_id's own digest, or any other fallback. This is the direct,
    previously-untested consequence of the adjudication: a provenance tool
    that degrades its own provenance silently is worse than one that stops."""
    root = isolated_vault_root
    fixture = _build_fixture_vault(root)

    # Simulate the exact condition the adjudication targets -- the
    # envelope exists (built from this file's own content, so its
    # source_id's embedded digest is real), but the raw file it names is no
    # longer present under data/sources/ at pin-write time.
    fixture["source_file"].unlink()

    result = _run_pin_write(root, "baseline")
    _assert_ran_the_real_subcommand(result)

    assert result.returncode != 0, (
        "expected a non-zero exit when the envelope's raw source file is "
        f"missing from data/sources/, got 0\nstdout: {result.stdout!r}\n"
        f"stderr: {result.stderr!r}"
    )

    pin_path = _pin_path(root)
    assert not pin_path.is_file(), (
        "expected NO evals/corpus_pin/baseline.json to be written at all when "
        f"the raw source file is missing (a degraded/partial manifest would "
        f"silently defeat the fail-loud guarantee) -- found one at {pin_path}"
    )

    assert fixture["source_id"] in result.stderr, (
        "expected the failure to name the specific source_id it could not "
        f"resolve a raw file for ({fixture['source_id']!r}), got stderr: "
        f"{result.stderr!r}"
    )
    assert "sources" in result.stderr, (
        "expected the failure to name the sources directory it looked under, "
        f"got stderr: {result.stderr!r}"
    )
