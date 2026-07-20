"""Outer acceptance test for issue #249, slice 01 of the vault-query
subproject (Phase B, sub:analysis-v0): the vault reader and the tag-query
tool set.

Locked behavioral contract (DEC-1) -- do not edit once committed red.

Given a fixture vault under data/vault/prose/ with four prose notes whose
      frontmatter carries known values for field, claim_type (with subtags),
      empirical_scope (value + polity), role_in_argument, and theory_school
  And one artifact note under data/vault/artifacts/
  And no LLM client configured or constructible in the test process
When  query_by_tag(field="field:political-sociology", role_in_argument="role:claim")
      is called
Then  exactly the chunk_ids of the notes matching BOTH filters are returned,
      in ascending chunk_id order
  And an identical second call returns the identical id list in the
      identical order
  And zero model calls and zero embedding calls were made

Given the same fixture vault
When  get_chunk(<a known chunk_id>) is called
Then  the result carries that chunk_id, its chunk_text, its section, its
      source_meta, its polities_touched list, and its artifact_refs list

Given the same fixture vault
When  get_chunk("does-not-exist") is called
Then  a clear not-found error naming the id is raised, not a None result

See specs/PHASE-B.md §7.5 (the vault query API, [FIRM]: query_by_tag /
query_by_polity / query_by_source / get_envelope / get_chunk / get_artifact /
follow_backlinks / coverage_count, "no model and no embedding model" /
determinism) and §8 P0-2 (the foundation slice: "the acceptance test asserts
the full tool set is exercised in tests with no LLM client present") for the
source of truth. See plans/vault-query/01-vault-reader-and-tag-query.md for
this slice's own acceptance criterion (identical Gherkin) and boundary
(`axial.query.get_chunk(chunk_id)`, `axial.query.get_artifact(artifact_id)`,
`axial.query.query_by_tag(**filters)`).

Seam decision 1 -- library calls, not a CLI subprocess
-----------------------------------------------------------------------
Unlike tests/analysis/test_brief_intake.py (whose boundary is a CLI
subcommand), this slice's own plan names its boundary as three plain library
entry points under `axial.query`. There is no `axial query` CLI subcommand
in scope for this slice (out of scope: "the agentic loop that calls these
tools", P0-3) -- so this test imports and calls `axial.query.query_by_tag`
and `axial.query.get_chunk` directly, in-process. `axial.query` does not
exist yet (`src/axial/vault.py` is write-only today, per the issue), so
every test below is expected to fail on that import alone until the reader
is built -- that failure IS the right kind of red for an unbuilt module, not
an import typo or a broken fixture.

Seam decision 2 -- an explicit `vault_dir` kwarg, mirroring the write side
-----------------------------------------------------------------------
The plan's boundary line abbreviates the call shapes (`get_chunk(chunk_id)`,
`query_by_tag(**filters)`); it does not enumerate every keyword argument.
Every write-side function in `src/axial/vault.py` (`write_chunk_note`,
`write_artifact_note`, `run_vault_write`) already accepts an explicit,
optional `vault_dir` override so tests never have to touch the real
`data/vault/`; this test locks the read side to the same, already-established
convention, pointing it at a committed fixture vault under
`tests/fixtures/vault_query/{prose,artifacts}/` instead of copying fixtures
into a throwaway `data/vault/` at test time. This is a read-only surface (§3
non-goal 5), so there is no mutation risk in pointing it straight at a
committed fixture directory.

Seam decision 3 -- proving "zero model calls and zero embedding calls" by
reusing the project's own established poison-provider idiom
-----------------------------------------------------------------------
`AXIAL_LLM_PROVIDER=explode` -> `axial.llm.ExplodingLLMClient` is the
existing, project-wide mechanism this whole codebase already uses to prove
an LLM-free code path (tests/ingestion/test_envelope.py's "no recompute"
proof, tests/chunk/test_chunk_examine.py, every `tests/gold/test_gold_*.py`
poison-provider run, etc.): selecting/constructing the client never itself
raises, but its `.complete()` raises immediately and loudly if ever invoked
-- so a hidden LLM call does not pass silently, it crashes the test. An
autouse fixture below sets this env var for every test in this module,
proving the Gherkin's "no LLM client configured" (nothing here selects a
real provider) and giving the strongest available proof of "or constructible"
this test process can offer without dictating `axial.query`'s internal
import structure, which does not exist yet to pin down. There is no
embedding-model construction seam left anywhere in this codebase to poison
(the whole `Embedder` protocol / `get_embedder` apparatus was removed
outright by issue #191, retiring the embedding-based chunk mechanism), so
"zero embedding calls" holds trivially here -- there is nothing left to call.

Seam decision 4 -- fixture notes are committed, synthetic, and written to
disk in an order that defeats a naive "trust directory order" bug
-----------------------------------------------------------------------
Per repo copyright policy (no book text in the repo -- DEC-23), every
fixture note under tests/fixtures/vault_query/ is entirely synthetic prose
about invented polities ("Freedonia", "Ruritania"), never real source text.
The four prose fixtures were also committed to disk in the scrambled order
003, 001, 004, 002 -- neither alphabetical nor match-then-distractor order --
so an implementation that merely returns `Path.iterdir()`'s raw
(OS-dependent, not lexically sorted) enumeration order cannot coincidentally
satisfy the ascending-`chunk_id` sort assertion below; only an
implementation that actually sorts passes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# Gotcha (see CLAUDE.local.md / dispatch note): this file lives at
# tests/analysis/test_vault_query.py, so it takes THREE .parent hops to
# reach the repo root, not two.
REPO_ROOT = Path(__file__).resolve().parent.parent.parent

FIXTURE_VAULT_DIR = REPO_ROOT / "tests" / "fixtures" / "vault_query"

EXPECTED_FIELD_FILTER = "field:political-sociology"
EXPECTED_ROLE_FILTER = "role:claim"

# Ascending chunk_id order -- the two notes satisfying BOTH filters.
EXPECTED_MATCHING_CHUNK_IDS = ["vqfix_001_causes", "vqfix_004_uprising"]

# Distractors: satisfy exactly one of the two filters, never both.
DISTRACTOR_CHUNK_IDS = ["vqfix_002_reforms", "vqfix_003_markets"]

KNOWN_CHUNK_ID = "vqfix_001_causes"
EXPECTED_CHUNK_TEXT = (
    "SENTINEL_CHUNK_TEXT_VQFIX_001: a synthetic sentence stating that weak "
    "local patronage networks caused a shift in ruling-coalition composition."
)
EXPECTED_SECTION = "Synthetic Section One — Causal Claims"
EXPECTED_SOURCE_META = {
    "author": "A. Synthetic Author",
    "title": "A Synthetic Fixture Source on Political Sociology",
    "date": 2020,
    "thesis": "Synthetic thesis: patronage networks structure coalition change.",
    "scope": "Synthetic scope: a single-country case study.",
}
EXPECTED_POLITIES_TOUCHED = ["Freedonia"]
EXPECTED_ARTIFACT_REFS = ["vqfix_art_001"]

MISSING_CHUNK_ID = "does-not-exist"


@pytest.fixture(autouse=True)
def _no_real_llm_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """Seam decision 3 (module docstring): poison any LLM construction/call
    for every test in this module via the project's own established
    `AXIAL_LLM_PROVIDER=explode` idiom, read at call time by
    `axial.llm.get_client` -- so setting it here binds regardless of when in
    the test `axial.query` happens to call it."""
    monkeypatch.setenv("AXIAL_LLM_PROVIDER", "explode")


def _field(result: object, name: str):
    """Read a named field off `result` whether the reader returns a mapping
    or an attribute-bearing object -- the outer contract fixes the field
    surface (§7.5 / this issue's Gherkin), not the container shape, which
    `axial.query` does not exist yet to pin down."""
    if isinstance(result, dict):
        assert name in result, (
            f"expected key {name!r} in the get_chunk result, got keys {sorted(result)!r}"
        )
        return result[name]
    assert hasattr(result, name), (
        f"expected attribute {name!r} on the get_chunk result, got "
        f"{result!r} (type {type(result).__name__})"
    )
    return getattr(result, name)


def test_query_by_tag_conjunction_is_ascending_deterministic_and_llm_free():
    """Scenario 1 (issue #249): a `query_by_tag` call over two filters
    returns exactly the chunk_ids satisfying BOTH, sorted ascending by
    chunk_id -- never filesystem enumeration order -- and an identical
    second call is byte-for-byte identical to the first. The autouse
    `_no_real_llm_provider` fixture above makes any hidden LLM call crash
    this test loudly rather than pass silently, proving the "zero model
    calls and zero embedding calls" clause."""
    from axial.query import query_by_tag

    first_result = query_by_tag(
        field=EXPECTED_FIELD_FILTER,
        role_in_argument=EXPECTED_ROLE_FILTER,
        vault_dir=FIXTURE_VAULT_DIR,
    )

    assert list(first_result) == EXPECTED_MATCHING_CHUNK_IDS, (
        "expected exactly the chunk_ids satisfying BOTH "
        f"field={EXPECTED_FIELD_FILTER!r} and "
        f"role_in_argument={EXPECTED_ROLE_FILTER!r}, in ascending chunk_id "
        f"order, i.e. {EXPECTED_MATCHING_CHUNK_IDS!r}; got {list(first_result)!r} "
        "-- a conjunction bug (matching on only one axis) would leak one of "
        f"{DISTRACTOR_CHUNK_IDS!r} into this list"
    )

    second_result = query_by_tag(
        field=EXPECTED_FIELD_FILTER,
        role_in_argument=EXPECTED_ROLE_FILTER,
        vault_dir=FIXTURE_VAULT_DIR,
    )

    assert list(second_result) == list(first_result), (
        "expected an identical second call over the same pinned fixture "
        f"vault to return the identical id list in the identical order -- "
        f"got {list(first_result)!r} then {list(second_result)!r} "
        "(§7.5's determinism contract)"
    )


def test_get_chunk_returns_the_full_field_surface():
    """Scenario 2 (issue #249): `get_chunk` on a known chunk_id returns a
    result carrying that chunk_id, its chunk_text, its section, its
    source_meta, its polities_touched list, and its artifact_refs list --
    all six read straight off the fixture note's own frontmatter, so a
    reader that drops, mis-parses, or defaults any one of them fails here."""
    from axial.query import get_chunk

    result = get_chunk(KNOWN_CHUNK_ID, vault_dir=FIXTURE_VAULT_DIR)

    assert _field(result, "chunk_id") == KNOWN_CHUNK_ID
    assert _field(result, "chunk_text") == EXPECTED_CHUNK_TEXT
    assert _field(result, "section") == EXPECTED_SECTION
    assert _field(result, "source_meta") == EXPECTED_SOURCE_META
    assert _field(result, "polities_touched") == EXPECTED_POLITIES_TOUCHED
    assert _field(result, "artifact_refs") == EXPECTED_ARTIFACT_REFS


def test_get_chunk_raises_a_clear_not_found_error_naming_the_id():
    """Scenario 3 (issue #249): `get_chunk` on an id absent from the fixture
    vault raises rather than returning `None` -- `pytest.raises` itself
    fails with "DID NOT RAISE" if a buggy implementation returns `None`
    silently, so that failure mode is caught without this test needing to
    inspect the return value at all -- and the raised error names the
    missing id, so a caller reading the message (not just catching a type)
    can tell which id was missing."""
    from axial.query import get_chunk

    with pytest.raises(Exception) as exc_info:
        get_chunk(MISSING_CHUNK_ID, vault_dir=FIXTURE_VAULT_DIR)

    assert MISSING_CHUNK_ID in str(exc_info.value), (
        f"expected the not-found error to name the missing id "
        f"{MISSING_CHUNK_ID!r}, got: {exc_info.value!r}"
    )
