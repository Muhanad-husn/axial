"""Outer acceptance test for issue #251, slice 02 of the vault-query
subproject (Phase B, sub:analysis-v0): `query_by_source` / `get_envelope`,
built on slice 01's reader (issue #249).

Locked behavioral contract -- do not edit once committed green without a
one-line justification in the PR body.

> **Three of this slice's four original scenarios were deleted with the tools
> they pinned** (issue #487, D1/D5): `query_by_polity` and the per-polity
> `coverage_count` read `polities_touched`, and `follow_backlinks` read
> `artifact_refs`/`cited_by` -- all retired facets, so each returned 0 or `[]`
> on every call. Their replacements are pinned at
> tests/analysis/test_name_query.py. `query_by_source`/`get_envelope` below
> are untouched by Phase A v1 and measured working.

Given a fixture vault and an envelope at
      data/envelopes/<source_id>.json
When  get_envelope(<source_id>) is called
Then  the result carries thesis, scope, stated_argument, and a nested toc
      whose entries are {title, children} objects
  And query_by_source(<source_id>) returns exactly that source's chunk_ids,
      sorted ascending

See specs/PHASE-B.md §7.5 (the vault query API, [FIRM]) and
plans/vault-query/02-facet-and-traversal-queries.md for this slice's own
acceptance criterion (identical Gherkin) and boundary
(`axial.query.query_by_source`, `axial.query.get_envelope`).

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

NORTH_SOURCE_ID = "vqf2-src-north"

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
