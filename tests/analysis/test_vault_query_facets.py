"""Outer acceptance test for issue #251, slice 02 of the vault-query
subproject (Phase B, sub:analysis-v0): the remaining four §7.5 tools --
`query_by_polity`, `query_by_source` / `get_envelope`, `follow_backlinks`,
`coverage_count` -- built on slice 01's reader (issue #249).

Locked behavioral contract -- do not edit once committed green without a
one-line justification in the PR body.

Given a fixture vault where chunk A has polities_touched ["Syria", "Iraq"],
      chunk B has ["Iraq"], and chunk C has ["Lebanon"]
  And no LLM client configured or constructible in the test process
When  query_by_polity("Iraq") is called
Then  exactly chunk A and chunk B are returned, in ascending chunk_id order
  And an identical second call returns the identical id list in the
      identical order
  And zero model calls and zero embedding calls were made

Given the same fixture vault and an envelope at
      data/envelopes/<source_id>.json
When  get_envelope(<source_id>) is called
Then  the result carries thesis, scope, stated_argument, and a nested toc
      whose entries are {title, children} objects
  And query_by_source(<source_id>) returns exactly that source's chunk_ids,
      sorted ascending

Given chunk A whose artifact_refs is ["<artifact_id>"] and artifact
      <artifact_id> whose cited_by is ["<chunk A id>", "<chunk B id>"]
When  follow_backlinks(<chunk A id>) is called
Then  ["<artifact_id>"] is returned
When  follow_backlinks("<artifact_id>") is called
Then  ["<chunk A id>", "<chunk B id>"] is returned, sorted ascending

Given the same fixture vault
When  coverage_count() is called
Then  it returns {"Iraq": 2, "Syria": 1, "Lebanon": 1}

See specs/PHASE-B.md §7.5 (the vault query API, [FIRM]) and
plans/vault-query/02-facet-and-traversal-queries.md for this slice's own
acceptance criterion (identical Gherkin) and boundary
(`axial.query.query_by_polity`, `axial.query.query_by_source`,
`axial.query.get_envelope`, `axial.query.follow_backlinks`,
`axial.query.coverage_count`).

Seam decisions (mirroring tests/analysis/test_vault_query.py, slice 01):
library calls, not a CLI subprocess (no `axial query` subcommand is in
scope, §7.5's own out-of-scope list); an explicit `vault_dir` /
`envelopes_dir` kwarg pointed at a committed fixture directory under
`tests/fixtures/vault_query_facets/{prose,artifacts,envelopes}/`, never the
real `data/vault/` or `data/envelopes/`; `AXIAL_LLM_PROVIDER=explode` proves
"no LLM client configured or constructible" the same way every other
poison-provider test in this codebase does. Every fixture note is entirely
synthetic prose about invented polities (Freedonia-style, per DEC-23's
no-book-text-in-repo policy), never real source text.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

FIXTURE_VAULT_DIR = REPO_ROOT / "tests" / "fixtures" / "vault_query_facets"
FIXTURE_ENVELOPES_DIR = FIXTURE_VAULT_DIR / "envelopes"

CHUNK_A_ID = "vqf2-src-north_1_causes-of-conflict_001"
CHUNK_B_ID = "vqf2-src-north_1_causes-of-conflict_002"
CHUNK_C_ID = "vqf2-src-south_1_reform-effects_001"

NORTH_SOURCE_ID = "vqf2-src-north"
ARTIFACT_ID = "vqf2-art-001"

EXPECTED_THESIS = "Synthetic thesis: cross-border patronage structures conflict onset."
EXPECTED_SCOPE = "Synthetic scope: a comparative two-country study."
EXPECTED_STATED_ARGUMENT = (
    "Synthetic restated argument: weak patronage networks travel across "
    "borders and shape coalition change in both invented polities."
)


@pytest.fixture(autouse=True)
def _no_real_llm_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """Poison any LLM construction/call for every test in this module via
    the project's established `AXIAL_LLM_PROVIDER=explode` idiom -- proving
    the Gherkin's "no LLM client configured or constructible" clause and
    giving a hidden `.complete()` call nothing to pass silently through."""
    monkeypatch.setenv("AXIAL_LLM_PROVIDER", "explode")


def test_query_by_polity_returns_matching_chunks_ascending_deterministic_and_llm_free():
    """Scenario 1: `query_by_polity("Iraq")` returns exactly chunk A and
    chunk B (both touch Iraq; chunk C touches only Lebanon), in ascending
    chunk_id order, and a second identical call is byte-for-byte identical
    to the first."""
    from axial.query import query_by_polity

    first_result = query_by_polity("Iraq", vault_dir=FIXTURE_VAULT_DIR)

    assert first_result == [CHUNK_A_ID, CHUNK_B_ID], (
        f"expected exactly chunk A and chunk B (both touch Iraq), in "
        f"ascending chunk_id order, i.e. {[CHUNK_A_ID, CHUNK_B_ID]!r}; got "
        f"{first_result!r} -- chunk C (Lebanon-only) leaking in would be a "
        "membership bug, and a reversed/scrambled order would be a sort bug"
    )

    second_result = query_by_polity("Iraq", vault_dir=FIXTURE_VAULT_DIR)

    assert second_result == first_result, (
        "expected an identical second call over the same pinned fixture "
        f"vault to return the identical id list in the identical order -- "
        f"got {first_result!r} then {second_result!r} (§7.5's determinism "
        "contract)"
    )


def test_query_by_polity_excludes_a_chunk_that_only_touches_a_different_polity():
    """`query_by_polity("Lebanon")` returns only chunk C -- the single-item
    case, proving the filter is not accidentally matching every chunk."""
    from axial.query import query_by_polity

    result = query_by_polity("Lebanon", vault_dir=FIXTURE_VAULT_DIR)

    assert result == [CHUNK_C_ID]


def test_get_envelope_carries_thesis_scope_stated_argument_and_nested_toc():
    """Scenario 2 (first half): `get_envelope` on a known source_id returns
    thesis, scope, stated_argument, and a nested toc whose entries are
    `{title, children}` objects -- not the pre-#235 flat string list."""
    from axial.query import get_envelope

    result = get_envelope(NORTH_SOURCE_ID, envelopes_dir=FIXTURE_ENVELOPES_DIR)

    assert result.thesis == EXPECTED_THESIS
    assert result.scope == EXPECTED_SCOPE
    assert result.stated_argument == EXPECTED_STATED_ARGUMENT
    assert isinstance(result.toc, list) and len(result.toc) > 0, (
        f"expected a non-empty nested toc, got {result.toc!r}"
    )
    for entry in result.toc:
        assert isinstance(entry, dict) and "title" in entry and "children" in entry, (
            f"expected every toc entry to be a {{title, children}} object, "
            f"got {entry!r} -- a flat string entry would mean the pre-#235 "
            "flat toc shape leaked through instead of the nested one"
        )
        assert isinstance(entry["children"], list)


def test_get_envelope_on_an_unknown_source_id_raises_a_clear_not_found_error():
    from axial.query import get_envelope

    with pytest.raises(Exception) as exc_info:
        get_envelope("does-not-exist", envelopes_dir=FIXTURE_ENVELOPES_DIR)

    assert "does-not-exist" in str(exc_info.value)


def test_query_by_source_returns_exactly_that_sources_chunk_ids_sorted_ascending():
    """Scenario 2 (second half): `query_by_source(<source_id>)` returns
    exactly chunk A and chunk B (both `vqf2-src-north`), sorted ascending,
    excluding chunk C (a different source)."""
    from axial.query import query_by_source

    result = query_by_source(NORTH_SOURCE_ID, vault_dir=FIXTURE_VAULT_DIR)

    assert result == [CHUNK_A_ID, CHUNK_B_ID], (
        f"expected exactly {[CHUNK_A_ID, CHUNK_B_ID]!r} sorted ascending; "
        f"got {result!r} -- chunk C belongs to a different source_id and "
        "must not appear here"
    )


def test_follow_backlinks_chunk_to_artifact_and_artifact_to_chunks():
    """Scenario 3: bidirectional one-hop traversal. Chunk A's
    `artifact_refs` resolves to the one fixture artifact id; that
    artifact's `cited_by` resolves back to chunk A and chunk B, sorted
    ascending."""
    from axial.query import follow_backlinks

    forward = follow_backlinks(CHUNK_A_ID, vault_dir=FIXTURE_VAULT_DIR)
    assert forward == [ARTIFACT_ID]

    backward = follow_backlinks(ARTIFACT_ID, vault_dir=FIXTURE_VAULT_DIR)
    assert backward == [CHUNK_A_ID, CHUNK_B_ID]


def test_follow_backlinks_on_an_unresolvable_id_raises_a_clear_error():
    from axial.query import follow_backlinks

    with pytest.raises(Exception) as exc_info:
        follow_backlinks("does-not-exist", vault_dir=FIXTURE_VAULT_DIR)

    assert "does-not-exist" in str(exc_info.value)


def test_coverage_count_counts_substantive_chunks_per_polity_across_the_vault():
    """Scenario 4: `coverage_count()` sums each chunk once per distinct
    polity it touches: Iraq (chunk A + chunk B) = 2, Syria (chunk A) = 1,
    Lebanon (chunk C) = 1."""
    from axial.query import coverage_count

    result = coverage_count(vault_dir=FIXTURE_VAULT_DIR)

    assert result == {"Iraq": 2, "Syria": 1, "Lebanon": 1}
