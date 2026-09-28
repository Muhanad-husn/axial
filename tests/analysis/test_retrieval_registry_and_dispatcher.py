"""Inner unit tests for issue #253 slice 01's tool registry and validating
dispatcher (specs/PHASE-B.md §7.5, §4's "hard gate"), seeded by
plans/retrieval-loop/01-tool-loop-skeleton.md's inner-loop checklist plus
#488's own three mechanical facts:

- Registry: exactly the surviving tool set is exposed; each entry carries a
  name and an arg schema the dispatcher can validate against.
- Dispatcher accepts a known tool with well-formed args and calls through to
  the query API with exactly those args.
- Dispatcher rejects an unknown tool name and returns a structured error
  result rather than raising.
- Dispatcher rejects missing / extra / wrong-typed args before the call.
- Arg types are declared per-arg (`int` for `limit`/the two publication-year
  filters, `str` otherwise, `list[str]` for `get_chunk`'s `chunk_id`) and the
  provider schema and dispatcher both honor the declaration.
- Each `ToolSpec` marks whether it yields chunk/artifact ids or not.

These are unit-level (no LLM client, no loop) -- the 4-scenario outer
acceptance contract for issue #253 lives in
`tests/analysis/test_retrieval_loop_skeleton.py`.

**DEC-75 (issue #853): the eight name-layer walk tools are retired.**
`find_names`, `get_name`, `name_neighbors`, `who_cites`, `who_argues_against`,
`where_names_meet`, `names_arguing_against` and `opposition_pairs` are no
longer registered here at all -- the name pages they walked (or, for the
last two, the free-text-to-name resolution they existed to serve as an
example of) are gone. `find_names`/`get_name` survive as plain functions
(`axial.query.names`), answered from the store, but are not tool-callable.
Every test in this file that pinned one of those eight as a registered tool,
or built a vault fixture as a name-page markdown file to exercise one, is
deleted rather than adapted -- the behavior itself, not just its test, is
gone. What remains: `find_notes`, `positions_on`, `query_by_source`,
`get_envelope`, `get_chunk`, `get_artifact`.

`coverage_count` was already de-registered before this issue (#505's own
follow-up): a deliberate contract change, not an oversight -- on a paid
corpus run a real provider's model chose to call it unprompted and it
returned all 49,674 canonicals in one result, holding the prompt over a
million characters for 14 turns. The function itself is untouched; only its
tool-facing registration is gone, and it stays gone here.

Issue #542 makes `get_chunk` batch-valued: `chunk_id` takes a list of ids and
the call is bounded by the same `limit`/`DEFAULT_LIMIT` mechanism. It now
carries a real pre-cap `total` (the number of ids asked for). The batch's own
outer acceptance contract is `tests/analysis/test_retrieval_batch_get_chunk.py`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from axial.retrieve.dispatcher import ToolResult, dispatch
from axial.retrieve.tools import TOOL_REGISTRY, tool_specs_for_provider

# The callable tools the registry exposes, post-DEC-75. `query_by_tag`,
# `query_by_polity` and `follow_backlinks` were de-registered with the tools
# themselves (issue #487, D1/D5) for returning nothing useful; the name-layer
# tools that briefly replaced them (issue #488) are themselves retired now
# (DEC-75, issue #853). `coverage_count` is the mirror case (issue #505's own
# follow-up): de-registered for returning far too much -- see
# `test_coverage_count_is_not_a_registered_tool` below. The function itself
# is untouched (`axial.query.names.coverage_count`, §7.7's real consumer).
# Issue #650 (DEC-62) added the store- and map-backed tools that take a name,
# a year and a source as FILTERS rather than as the way in -- `find_notes`
# and `positions_on` are what survive of that set once `opposition_pairs`/
# `names_arguing_against` also retired alongside the name-layer tools.
EXPECTED_TOOL_NAMES = {
    "find_notes",
    "positions_on",
    "query_by_source",
    "get_envelope",
    "get_chunk",
    "get_artifact",
}

# The tool whose result is a `source_id`, never a chunk/artifact id.
CHUNK_VALUED_TOOLS = {
    "find_notes",
    "positions_on",
    "query_by_source",
    "get_chunk",
    "get_artifact",
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
        assert isinstance(spec.int_args, frozenset)
        assert spec.int_args <= spec.allowed_args, "a declared int arg must be an allowed arg"
        assert isinstance(spec.returns_chunk_ids, bool)
        assert callable(spec.call)


def test_returns_chunk_ids_matches_the_issues_own_two_groups():
    """§7.5's own split, restated as a data assertion: `find_notes`,
    `positions_on`, `query_by_source`, `get_chunk` and `get_artifact` yield
    chunk/artifact ids; `get_envelope` yields a `source_id`, neither."""
    for name in CHUNK_VALUED_TOOLS:
        assert TOOL_REGISTRY[name].returns_chunk_ids is True, name
    assert TOOL_REGISTRY["get_envelope"].returns_chunk_ids is False


def test_every_bounded_tool_declares_limit_as_its_int_arg():
    """`find_notes`/`positions_on`/`get_chunk` declare `limit` as an int arg
    -- `find_notes` additionally declares the two publication-year filters as
    ints, since a year is a number and must reach the provider schema as one,
    which is the whole reason `int_args` exists. `query_by_source`,
    `get_envelope` and `get_artifact` take no bound at all."""
    unbounded = {"query_by_source", "get_envelope", "get_artifact"}
    for name, spec in TOOL_REGISTRY.items():
        if name in unbounded:
            assert spec.int_args == frozenset(), name
        elif name == "find_notes":
            assert spec.int_args == frozenset({"limit", "published_after", "published_before"})
        else:
            assert spec.int_args == frozenset({"limit"}), name


def test_chunk_id_is_the_one_declared_list_arg_in_the_whole_tool_set():
    """Issue #542: `get_chunk` reads a batch, so its `chunk_id` is a list of
    strings. It is the only list-typed arg in the tool set; every other tool
    stays string- and int-typed."""
    for name, spec in TOOL_REGISTRY.items():
        expected = frozenset({"chunk_id"}) if name == "get_chunk" else frozenset()
        assert spec.str_list_args == expected, name
        assert spec.str_list_args <= spec.allowed_args, name
        assert spec.str_list_args.isdisjoint(spec.int_args), name


def test_coverage_count_is_not_a_registered_tool():
    """Issue #505's own follow-up: `coverage_count` is de-registered, the
    mirror of D1/D5 (struck for returning nothing useful) -- this one is
    struck for returning far too much. On a paid corpus run a real provider's model
    chose to call it unprompted and it returned all 49,674 canonicals, holding
    the prompt over a million characters for 14 turns. Absent from both the
    registry the dispatcher validates against and the schema a real
    provider's model would see."""
    assert "coverage_count" not in TOOL_REGISTRY

    provider_names = {entry["function"]["name"] for entry in tool_specs_for_provider()}
    assert "coverage_count" not in provider_names

    result = dispatch("coverage_count", {}, vault_dir=Path("/nonexistent"))
    assert result.error is not None
    assert "coverage_count" in result.error, (
        "an unregistered tool is rejected exactly like any other unknown name, "
        "structured and non-raising -- never reaches axial.query.names"
    )


def test_tool_specs_for_provider_carries_every_tool_with_required_args_marked():
    specs = tool_specs_for_provider()
    names = {entry["function"]["name"] for entry in specs}
    assert names == EXPECTED_TOOL_NAMES

    by_name = {entry["function"]["name"]: entry for entry in specs}
    source_spec = by_name["query_by_source"]
    assert source_spec["function"]["parameters"]["required"] == ["source_id"]
    assert "source_id" in source_spec["function"]["parameters"]["properties"]


def test_tool_specs_for_provider_emits_integer_type_for_limit_and_string_otherwise():
    """The registry's own declared `int_args` must reach the provider payload
    as an honest JSON type -- `find_notes`'s `limit` is `"integer"`, its
    `about` and every other tool's string args are `"string"`."""
    specs = tool_specs_for_provider()
    by_name = {entry["function"]["name"]: entry for entry in specs}

    find_notes_props = by_name["find_notes"]["function"]["parameters"]["properties"]
    assert find_notes_props["limit"]["type"] == "integer"
    assert find_notes_props["about"]["type"] == "string"

    query_by_source_props = by_name["query_by_source"]["function"]["parameters"]["properties"]
    assert query_by_source_props["source_id"]["type"] == "string"


@pytest.fixture
def fixture_vault_dir(tmp_path: Path) -> Path:
    prose_dir = tmp_path / "prose"
    prose_dir.mkdir(parents=True, exist_ok=True)
    frontmatter: dict[str, Any] = {
        "chunk_id": "rtd-src_1_intro_001",
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
    (prose_dir / "rtd-src_1_intro_001.md").write_text(text, encoding="utf-8")
    return tmp_path


def test_dispatch_accepts_a_known_tool_and_calls_through_with_exactly_those_args(
    fixture_vault_dir: Path,
):
    """`query_by_source` with its one arg is passed through to
    `reader.query_by_source` as exactly that kwarg -- proving the dispatcher
    does not drop, rename, or add args on a well-formed call."""
    result = dispatch(
        "query_by_source",
        {"source_id": "rtd-src"},
        vault_dir=fixture_vault_dir,
    )

    assert isinstance(result, ToolResult)
    assert result.error is None
    assert result.ids == ["rtd-src_1_intro_001"]
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


def test_dispatch_rejects_a_retired_tool_before_reaching_the_vault():
    """`query_by_tag`/`query_by_polity`/`follow_backlinks` (D1/D5) and the
    eight name-layer walk tools (DEC-75, issue #853: `find_names`, `get_name`,
    `name_neighbors`, `who_cites`, `who_argues_against`, `where_names_meet`,
    `names_arguing_against`, `opposition_pairs`) no longer exist -- the
    dispatcher rejects a call to any of them exactly like any other unknown
    tool name, structured and non-raising."""
    retired = (
        "query_by_tag",
        "query_by_polity",
        "follow_backlinks",
        "find_names",
        "get_name",
        "name_neighbors",
        "who_cites",
        "who_argues_against",
        "where_names_meet",
        "names_arguing_against",
        "opposition_pairs",
    )
    for name in retired:
        result = dispatch(name, {}, vault_dir=Path("/nonexistent"))
        assert result.ids == []
        assert result.count == 0
        assert result.error is not None
        assert name in result.error


@pytest.fixture
def fixture_batch_vault_dir(tmp_path: Path) -> Path:
    """Three notes from one source, plus a fourth from a different one --
    enough to prove `limit` truncates `get_chunk`'s batch through the
    dispatcher and that `ToolResult.total` carries the true pre-cap count.
    DEC-75 (issue #853): this used to also carry a `Charles Tilly` name page
    to exercise the retired `get_name`/`who_cites`/`who_argues_against`; that
    part is gone along with the tools it served."""
    vault_dir = tmp_path / "dispatch-vault"
    prose_dir = vault_dir / "prose"
    prose_dir.mkdir(parents=True, exist_ok=True)
    member_ids = [f"tillyfix-1978_{i}_intro_001" for i in range(1, 4)]
    for chunk_id in member_ids:
        frontmatter = {
            "chunk_id": chunk_id,
            "section": "Synthetic Section",
            "chunk_text": "SENTINEL: synthetic prose.",
            "source_meta": {"author": "Charles Tilly", "title": "T", "date": 1978},
            "answers": {"claim": f"Claim of {chunk_id}.", "position_of": "the author"},
        }
        text = "---\n" + yaml.safe_dump(frontmatter, sort_keys=False) + "---\nBody.\n"
        (prose_dir / f"{chunk_id}.md").write_text(text, encoding="utf-8")

    traversal_id = "batatufix-1978_1_iraq_001"
    traversal_frontmatter = {
        "chunk_id": traversal_id,
        "section": "Synthetic Section",
        "chunk_text": "SENTINEL: synthetic prose.",
        "source_meta": {"author": "Hanna Batatu", "title": "T", "date": 1978},
        "answers": {
            "claim": "A claim.",
            "position_of": "the author",
            "arguing_against": ["Charles Tilly"],
            "citations": [{"cited": "Charles Tilly", "stance": "support", "about": "x"}],
        },
    }
    text = "---\n" + yaml.safe_dump(traversal_frontmatter, sort_keys=False) + "---\nBody.\n"
    (prose_dir / f"{traversal_id}.md").write_text(text, encoding="utf-8")
    return vault_dir


def test_dispatch_total_is_none_for_a_tool_that_carries_no_pre_cap_total(
    fixture_batch_vault_dir: Path,
):
    """`query_by_source` (and every tool but `get_chunk`) never sets `total`
    -- it has no cap-relevant concept of one."""
    result = dispatch(
        "query_by_source", {"source_id": "tillyfix-1978"}, vault_dir=fixture_batch_vault_dir
    )

    assert result.error is None
    assert result.total is None


def test_dispatch_carries_the_ids_asked_for_as_get_chunks_pre_cap_total(
    fixture_batch_vault_dir: Path,
):
    """Issue #542: a batch truncated at `limit` is never silent about being
    one -- `total` is the count of ids the call asked for."""
    member_ids = [f"tillyfix-1978_{index}_intro_001" for index in range(1, 4)]
    result = dispatch(
        "get_chunk", {"chunk_id": member_ids, "limit": 2}, vault_dir=fixture_batch_vault_dir
    )

    assert result.error is None
    assert result.ids == member_ids[:2]
    assert result.count == 2
    assert result.total == 3


@pytest.mark.parametrize(
    "tool,args",
    [
        ("get_chunk", {"chunk_id": "tillyfix-1978_1_intro_001"}),
        ("query_by_source", {"source_id": "tillyfix-1978"}),
    ],
)
def test_dispatch_leaves_detail_none_for_tools_with_no_source_span_concept(
    tool: str, args: dict[str, str], fixture_batch_vault_dir: Path
):
    """`find_notes`/`positions_on` populate `detail` with their own
    resolution/span information (issue #650) -- `get_chunk`/`query_by_source`
    leave it `None`. The name-layer tools that used to also populate `detail`
    (`find_names`, `get_name`, `name_neighbors`, `where_names_meet`) are
    retired (DEC-75, issue #853)."""
    result = dispatch(tool, args, vault_dir=fixture_batch_vault_dir)
    assert result.detail is None
