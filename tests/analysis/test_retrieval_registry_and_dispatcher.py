"""Inner unit tests for issue #253 slice 01's tool registry and validating
dispatcher (specs/PHASE-B.md §7.5, §4's "hard gate"), seeded by
plans/retrieval-loop/01-tool-loop-skeleton.md's inner-loop checklist:

- Registry: exactly the §7.5 tool set is exposed; each entry carries a name
  and an arg schema the dispatcher can validate against.
- Dispatcher accepts a known tool with well-formed args and calls through to
  the query API with exactly those args.
- Dispatcher rejects an unknown tool name and returns a structured error
  result rather than raising.
- Dispatcher rejects missing / extra / wrong-typed args before the call.

These are unit-level (no LLM client, no loop) -- the 4-scenario outer
acceptance contract lives in
`tests/analysis/test_retrieval_loop_skeleton.py`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from axial.retrieve.dispatcher import ToolResult, dispatch
from axial.retrieve.tools import TOOL_REGISTRY, tool_specs_for_provider

# The eight callable tools the six §7.5 bullets expose (two bullets --
# "query_by_source / get_envelope" and "get_chunk / get_artifact" -- each
# bundle two distinct reader.py functions, so each becomes its own tool
# name here; see tools.py's module docstring).
EXPECTED_TOOL_NAMES = {
    "query_by_tag",
    "query_by_polity",
    "query_by_source",
    "get_envelope",
    "get_chunk",
    "get_artifact",
    "follow_backlinks",
    "coverage_count",
}


def test_registry_exposes_exactly_the_expected_tool_set():
    assert set(TOOL_REGISTRY) == EXPECTED_TOOL_NAMES, (
        f"expected exactly {sorted(EXPECTED_TOOL_NAMES)}, got {sorted(TOOL_REGISTRY)}"
    )


def test_every_registry_entry_carries_a_name_and_a_validatable_arg_schema():
    for name, spec in TOOL_REGISTRY.items():
        assert spec.name == name
        assert isinstance(spec.required_args, frozenset)
        assert isinstance(spec.optional_args, frozenset)
        assert spec.required_args.isdisjoint(spec.optional_args)
        assert callable(spec.call)


def test_tool_specs_for_provider_carries_every_tool_with_required_args_marked():
    specs = tool_specs_for_provider()
    names = {entry["function"]["name"] for entry in specs}
    assert names == EXPECTED_TOOL_NAMES

    by_name = {entry["function"]["name"]: entry for entry in specs}
    polity_spec = by_name["query_by_polity"]
    assert polity_spec["function"]["parameters"]["required"] == ["polity"]
    assert "polity" in polity_spec["function"]["parameters"]["properties"]


@pytest.fixture
def fixture_vault_dir(tmp_path: Path) -> Path:
    prose_dir = tmp_path / "prose"
    prose_dir.mkdir(parents=True, exist_ok=True)
    frontmatter: dict[str, Any] = {
        "chunk_id": "rtd_001_intro",
        "section": "Synthetic Section",
        "chunk_text": "SENTINEL: synthetic prose.",
        "source_meta": {
            "author": "A. Synthetic Author",
            "title": "A Synthetic Fixture Source",
            "date": 2021,
            "thesis": "Synthetic thesis.",
            "scope": "Synthetic scope.",
        },
        "schema_version": "0.1",
        "role_in_argument": "role:claim",
        "field": {"primary": "state-formation", "secondary": []},
        "claim_type": {"primary": "claim:causal", "secondary": None, "subtags": []},
        "theory_school": {
            "primary": "school:synthetic-institutionalist",
            "secondary": None,
            "status": "candidate",
        },
        "empirical_scope": {"value": "scope:country-case", "polity": "Syria"},
        "polities_touched": ["Syria"],
        "artifact_refs": [],
    }
    text = "---\n" + yaml.safe_dump(frontmatter, sort_keys=False) + "---\nBody.\n"
    (prose_dir / "rtd_001_intro.md").write_text(text, encoding="utf-8")
    return tmp_path


def test_dispatch_accepts_a_known_tool_and_calls_through_with_exactly_those_args(
    fixture_vault_dir: Path,
):
    """`query_by_tag` with two filter args (`field` + `polity`) is passed
    through to `reader.query_by_tag` as exactly those two kwargs -- proving
    the dispatcher does not drop, rename, or add args on a well-formed
    call."""
    result = dispatch(
        "query_by_tag",
        {"field": "state-formation", "polity": "Syria"},
        vault_dir=fixture_vault_dir,
    )

    assert isinstance(result, ToolResult)
    assert result.error is None
    assert result.ids == ["rtd_001_intro"]
    assert result.count == 1


def test_dispatch_rejects_an_unknown_tool_without_raising():
    result = dispatch("query_by_vibes", {"q": "x"}, vault_dir=Path("/nonexistent"))

    assert result.ids == []
    assert result.count == 0
    assert result.error is not None
    assert "query_by_vibes" in result.error


def test_dispatch_rejects_missing_required_arg_without_raising():
    result = dispatch("get_chunk", {}, vault_dir=Path("/nonexistent"))

    assert result.ids == []
    assert result.count == 0
    assert result.error is not None
    assert "chunk_id" in result.error


def test_dispatch_rejects_extra_arg_without_raising():
    result = dispatch(
        "get_chunk",
        {"chunk_id": "any", "unexpected_extra_arg": "x"},
        vault_dir=Path("/nonexistent"),
    )

    assert result.ids == []
    assert result.count == 0
    assert result.error is not None
    assert "unexpected_extra_arg" in result.error


def test_dispatch_rejects_wrong_typed_arg_without_raising():
    result = dispatch(
        "get_chunk",
        {"chunk_id": 12345},  # must be a string
        vault_dir=Path("/nonexistent"),
    )

    assert result.ids == []
    assert result.count == 0
    assert result.error is not None
    assert "chunk_id" in result.error


def test_dispatch_never_raises_for_any_malformed_args_shape():
    """`args` itself is not even a mapping -- still a structured error, not
    a crash."""
    result = dispatch("get_chunk", "not-a-dict", vault_dir=Path("/nonexistent"))  # type: ignore[arg-type]

    assert result.ids == []
    assert result.count == 0
    assert result.error is not None
