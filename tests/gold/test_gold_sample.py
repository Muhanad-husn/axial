"""Outer acceptance test for issue #53, slice 01 (gold: stratified sampling
of tagged chunks).

Locked behavioral contract (DEC-1) -- do not edit once committed red.

Given a populated prose vault whose tagged notes span >=2 field values, >=2
      empirical_scope values and >=2 role_in_argument values, AND at least
      one non-substantive back-matter note (a "Bibliography" and an
      "Endnotes" section), AND a data/gold/sources.yaml declaring each
      source's type (book/paper)
When  the user runs `axial gold sample`
Then  a set of chunk records is written under data/gold/chunks/
And   the selection covers every represented field / empirical_scope /
      role_in_argument value (stratification, PR #124's ratified axes)
And   no selected chunk comes from a non-substantive back-matter section
And   each declared source-type present in the corpus contributes >=1 chunk
And   the selection size sits within the configured band (default 100-120),
      clamped to the number of available chunks
And   each record carries chunk_id, source, section, chunk_text, field,
      empirical_scope, role_in_argument, claim_type and theory_school
And   re-running reproduces the same selection and does not accumulate stale
      records

See specs/PRODUCT.md §9 (gold corpus & labeling), §8 (P0-9), and the
founder-ratified stratification retarget (spec PR #124: strata are field ×
empirical_scope × role_in_argument; source-type/claim_type/theory_school are
descriptive, not balancing; non-substantive back-matter is excluded from the
sampling frame). Plan: plans/gold/01-gold-sample.md.

Arrange mechanism -- seed the vault directly, no LLM
-----------------------------------------------------------------------
This feature is offline by construction: it reads tagged prose notes the
`tag`/`vault` passes already wrote. Per plans/gold/README.md (notes: two
documented arrangements), this test takes the lighter one -- it seeds a
handful of tagged note `.md` files directly into `<root>/data/vault/prose/`
with the exact frontmatter shape `axial vault write` produces (Appendix H
nesting: `field.primary`, `empirical_scope.value`, flat `role_in_argument`,
nested `claim_type`/`theory_school`), rather than running the real
tag->vault thread under the stub provider. No LLM, no network, no docling.

Isolation -- run from an isolated staging root (issue #68)
-----------------------------------------------------------------------
`axial gold sample` resolves `data/vault/prose/`, `data/gold/sources.yaml`
and its `data/gold/chunks/` output as plain cwd-relative paths (mirroring
every other pass -- see src/axial/vault.py's `_default_vault_dir`). The real
`data/vault/prose/` already holds a large real corpus, so a count-based
assertion against it would be meaningless. So every `axial` subprocess here
runs with `cwd` set to `isolated_vault_root` (tests/conftest.py's opt-in
fixture): a fresh per-test staging directory outside this repo entirely. The
real `data/` tree is never read or written.

Source identity -- derived from chunk_id, matched to sources.yaml
-----------------------------------------------------------------------
The vault frontmatter carries no top-level `source` key; source identity
lives in the `chunk_id` prefix (`<source_id>_<order>_<slug>_<NNN>`, per
src/axial/chunk.py) and `data/gold/sources.yaml` is keyed by that same
`source_id` (`<stem>-<sha256[:12]>`, no underscores). This test builds its
seeded chunk_ids in that exact shape and its sources.yaml keyed by the same
source_ids, then derives each record's expected source-type by stripping the
trailing `_<order>_<slug>_<NNN>` off chunk_id -- never hardcoding a mapping
the sampler doesn't also compute.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

PROVIDER_ENV_VAR = "AXIAL_LLM_PROVIDER"

ARGPARSE_FALLBACK_MARKERS = (
    "invalid choice",
    "unrecognized arguments",
)

REQUIRED_RECORD_KEYS = (
    "chunk_id",
    "source",
    "section",
    "chunk_text",
    "field",
    "empirical_scope",
    "role_in_argument",
    "claim_type",
    "theory_school",
)

# Two seeded sources, one of each declared type, so "each source-type present
# contributes >=1 chunk" is a real, checkable clause.
SOURCE_BOOK = "alpha-history-000000000001"
SOURCE_PAPER = "beta-analysis-000000000002"

# Each spec: (source_id, order, slug, field, scope, role). The substantive
# frame spans 3 fields, 4 scopes and 4 roles -- comfortably >= the AC's ">=2
# of each" precondition.
SUBSTANTIVE_SPECS = [
    (SOURCE_BOOK, "1", "introduction", "state", "scope:general", "role:setup"),
    (SOURCE_BOOK, "2", "chapter-one", "violence", "scope:country-case", "role:claim"),
    (SOURCE_BOOK, "3", "chapter-two", "ideology", "scope:comparative", "role:evidence"),
    (SOURCE_PAPER, "1", "analysis", "state", "scope:regional", "role:synthesis"),
    (SOURCE_PAPER, "2", "findings", "violence", "scope:general", "role:claim"),
]

# Non-substantive back-matter notes that MUST be excluded from the sampling
# frame. "Endnotes" deliberately exercises the BROADER gold-frame exclusion:
# the chunk-pass filter (#113) keeps endnotes/appendix, but the gold frame
# (#53) excludes them too.
BACK_MATTER_SPECS = [
    (SOURCE_BOOK, "9", "bibliography", "Bibliography", "state", "scope:general", "role:claim"),
    (SOURCE_PAPER, "9", "endnotes", "Endnotes", "violence", "scope:country-case", "role:evidence"),
]

SOURCE_TYPES = {SOURCE_BOOK: "book", SOURCE_PAPER: "paper"}


def _prose_dir(root: Path) -> Path:
    return root / "data" / "vault" / "prose"


def _gold_dir(root: Path) -> Path:
    return root / "data" / "gold"


def _chunks_dir(root: Path) -> Path:
    return _gold_dir(root) / "chunks"


def _source_id_of(chunk_id: str) -> str:
    """Strip the trailing `_<order>_<slug>_<NNN>` off a chunk_id to recover
    its source_id -- the same derivation the sampler must perform to key each
    record's source against sources.yaml (mirrors src/axial/chunk.py's
    `<source_id>_<order>_<slug>_<NNN>` construction; source_id itself carries
    no underscores)."""
    return "_".join(chunk_id.split("_")[:-3])


def _render_note(frontmatter: dict, section: str, chunk_text: str) -> str:
    """Render a prose note exactly as src/axial/vault.py's `render_note`
    does structurally: a `---`-delimited YAML frontmatter block then a
    readable body."""
    block = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True)
    return f"---\n{block}---\n# {section}\n\n{chunk_text}\n"


def _write_note(
    prose_dir: Path,
    *,
    source_id: str,
    order: str,
    slug: str,
    section: str,
    field: str,
    scope: str,
    role: str,
    index: int = 1,
) -> str:
    """Seed one tagged prose note with the Appendix-H frontmatter shape and
    return its chunk_id."""
    chunk_id = f"{source_id}_{order}_{slug}_{index:03d}"
    frontmatter = {
        "chunk_id": chunk_id,
        "section": section,
        "chunk_text": f"Substantive prose body for {chunk_id}.",
        "source_meta": {
            "author": "Seeded Author",
            "title": source_id,
            "date": "2020",
            "thesis": "A seeded thesis.",
            "scope": "A seeded scope.",
        },
        "schema_version": "0.1",
        "role_in_argument": role,
        "field": {"primary": field, "secondary": []},
        "claim_type": {"primary": "state-formation", "secondary": None, "subtags": []},
        "theory_school": {"primary": "bellicist", "secondary": None, "status": "candidate"},
        "empirical_scope": {"value": scope},
        "artifact_refs": [],
    }
    prose_dir.mkdir(parents=True, exist_ok=True)
    (prose_dir / f"{chunk_id}.md").write_text(
        _render_note(frontmatter, section, frontmatter["chunk_text"]), encoding="utf-8"
    )
    return chunk_id


def _seed_vault(root: Path) -> dict[str, list[str]]:
    """Seed the substantive + back-matter notes and the sources manifest.
    Returns the expected substantive chunk_ids and the back-matter chunk_ids
    (which must NOT appear in the selection)."""
    prose_dir = _prose_dir(root)
    substantive = [
        _write_note(
            prose_dir,
            source_id=source_id,
            order=order,
            slug=slug,
            section=slug.replace("-", " ").title(),
            field=field,
            scope=scope,
            role=role,
        )
        for source_id, order, slug, field, scope, role in SUBSTANTIVE_SPECS
    ]
    back_matter = [
        _write_note(
            prose_dir,
            source_id=source_id,
            order=order,
            slug=slug,
            section=section,
            field=field,
            scope=scope,
            role=role,
        )
        for source_id, order, slug, section, field, scope, role in BACK_MATTER_SPECS
    ]

    gold_dir = _gold_dir(root)
    gold_dir.mkdir(parents=True, exist_ok=True)
    (gold_dir / "sources.yaml").write_text(yaml.safe_dump(SOURCE_TYPES), encoding="utf-8")

    return {"substantive": substantive, "back_matter": back_matter}


def _run_gold_sample(root: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env[PROVIDER_ENV_VAR] = "explode"  # any run that reaches an LLM is a bug
    return subprocess.run(
        ["uv", "run", "--project", str(REPO_ROOT), "axial", "gold", "sample", *args],
        cwd=root,
        capture_output=True,
        text=True,
        env=env,
    )


def _assert_not_argparse_fallback(result: subprocess.CompletedProcess) -> None:
    combined = result.stdout + result.stderr
    for marker in ARGPARSE_FALLBACK_MARKERS:
        assert marker not in combined, (
            f"expected a real `gold sample` behavior path, not an argparse "
            f"fallback (found {marker!r}) -- the subcommand does not exist "
            f"yet or was never reached:\nstdout: {result.stdout!r}\n"
            f"stderr: {result.stderr!r}"
        )


def _load_records(root: Path) -> list[dict]:
    chunks_dir = _chunks_dir(root)
    assert chunks_dir.exists(), (
        f"expected `axial gold sample` to create {chunks_dir} and write chunk "
        f"records into it, but it does not exist after a successful run"
    )
    records = []
    for path in sorted(chunks_dir.glob("*.json")):
        records.append(json.loads(path.read_text(encoding="utf-8")))
    return records


def _expected_axis_values() -> dict[str, set[str]]:
    return {
        "field": {field for _s, _o, _sl, field, _sc, _r in SUBSTANTIVE_SPECS},
        "empirical_scope": {scope for _s, _o, _sl, _f, scope, _r in SUBSTANTIVE_SPECS},
        "role_in_argument": {role for _s, _o, _sl, _f, _sc, role in SUBSTANTIVE_SPECS},
    }


def test_gold_sample_selects_stratified_records(isolated_vault_root):
    root = isolated_vault_root
    seeded = _seed_vault(root)

    result = _run_gold_sample(root)
    _assert_not_argparse_fallback(result)
    assert result.returncode == 0, (
        f"expected exit code 0 for `axial gold sample` on a seeded vault with "
        f"a sources.yaml, got {result.returncode}\nstdout: {result.stdout!r}\n"
        f"stderr: {result.stderr!r}"
    )

    records = _load_records(root)
    assert records, (
        f"expected `axial gold sample` to write at least one chunk record "
        f"under {_chunks_dir(root)}, got none. stdout: {result.stdout!r}"
    )

    # Every record carries the full field set (PR #124 record shape).
    for record in records:
        missing = [key for key in REQUIRED_RECORD_KEYS if key not in record]
        assert not missing, (
            f"expected every gold record to carry {list(REQUIRED_RECORD_KEYS)}, "
            f"record is missing {missing}: {record!r}"
        )

    selected_ids = {record["chunk_id"] for record in records}

    # No back-matter note is ever selected (sampling-frame exclusion).
    back_matter_selected = selected_ids & set(seeded["back_matter"])
    assert not back_matter_selected, (
        f"expected no non-substantive back-matter chunk to be selected "
        f"(#53 excludes bibliography/endnotes/... from the frame), but these "
        f"were selected: {sorted(back_matter_selected)}"
    )
    for record in records:
        assert record["section"].strip().lower() not in {"bibliography", "endnotes"}, (
            f"expected no selected record to carry a back-matter section "
            f"heading, got section {record['section']!r} (chunk "
            f"{record['chunk_id']!r})"
        )

    # Stratification: every represented value of each of the three ratified
    # axes appears in the selection.
    expected = _expected_axis_values()
    for axis, values in expected.items():
        present = {record[axis] for record in records}
        assert values <= present, (
            f"expected the selection to cover every represented {axis!r} value "
            f"{sorted(values)} (stratified sampling, PR #124), but only "
            f"{sorted(present)} are present -- missing {sorted(values - present)}"
        )

    # Source-type coverage: each declared type present in the corpus
    # contributes >=1 selected chunk.
    selected_types = {SOURCE_TYPES[_source_id_of(cid)] for cid in selected_ids}
    assert selected_types == set(SOURCE_TYPES.values()), (
        f"expected every declared source-type present in the corpus "
        f"{sorted(set(SOURCE_TYPES.values()))} to contribute at least one "
        f"selected chunk, got {sorted(selected_types)}"
    )

    # Each record's derived source matches the sources.yaml key.
    for record in records:
        assert record["source"] == _source_id_of(record["chunk_id"]), (
            f"expected record 'source' to be the source_id derived from "
            f"chunk_id {record['chunk_id']!r} (the sources.yaml key), got "
            f"{record['source']!r}"
        )

    # Band: default 100-120 clamped to available. Only the 5 substantive
    # chunks are available, so all 5 are selected (available < band floor).
    assert selected_ids == set(seeded["substantive"]), (
        f"expected the selection to be exactly the {len(seeded['substantive'])} "
        f"substantive chunks (available < the default 100-120 band, so the "
        f"band clamps to all available substantive chunks), got a different "
        f"set. selected: {sorted(selected_ids)}; substantive: "
        f"{sorted(seeded['substantive'])}"
    )
    assert len(records) <= 120, (
        f"expected the selection never to exceed the default band ceiling of "
        f"120, got {len(records)}"
    )


def test_gold_sample_is_deterministic_and_clears_stale(isolated_vault_root):
    root = isolated_vault_root
    _seed_vault(root)

    # Pre-plant a stale record file the sampler must clear (no accumulation).
    chunks_dir = _chunks_dir(root)
    chunks_dir.mkdir(parents=True, exist_ok=True)
    stale = chunks_dir / "stale-leftover.json"
    stale.write_text(json.dumps({"chunk_id": "stale"}), encoding="utf-8")

    first = _run_gold_sample(root)
    _assert_not_argparse_fallback(first)
    assert first.returncode == 0, (
        f"expected exit code 0 for the first `axial gold sample` run, got "
        f"{first.returncode}\nstdout: {first.stdout!r}\nstderr: {first.stderr!r}"
    )

    assert not stale.exists(), (
        "expected `axial gold sample` to clear any prior sample under "
        "data/gold/chunks/ before writing (Gherkin: 'does not accumulate "
        "stale records'), but the pre-planted stale file survived"
    )

    first_records = {r["chunk_id"]: r for r in _load_records(root)}

    second = _run_gold_sample(root)
    _assert_not_argparse_fallback(second)
    assert second.returncode == 0, (
        f"expected exit code 0 for the second (re-run) `axial gold sample`, "
        f"got {second.returncode}\nstdout: {second.stdout!r}\n"
        f"stderr: {second.stderr!r}"
    )

    second_records = {r["chunk_id"]: r for r in _load_records(root)}
    assert second_records == first_records, (
        "expected re-running `axial gold sample` to reproduce the exact same "
        "selection (Gherkin: deterministic re-run), but the record set "
        "changed between runs.\n"
        f"first:  {sorted(first_records)}\nsecond: {sorted(second_records)}"
    )
