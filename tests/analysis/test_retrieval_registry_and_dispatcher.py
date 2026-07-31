"""Inner unit tests for issue #253 slice 01's tool registry and validating
dispatcher (specs/PHASE-B.md §7.5, §4's "hard gate"), extended by issue #488
to the name layer, seeded by plans/retrieval-loop/01-tool-loop-skeleton.md's
inner-loop checklist plus #488's own three mechanical facts:

- Registry: exactly the §7.5 tool set is exposed; each entry carries a name
  and an arg schema the dispatcher can validate against.
- Dispatcher accepts a known tool with well-formed args and calls through to
  the query API with exactly those args.
- Dispatcher rejects an unknown tool name and returns a structured error
  result rather than raising.
- Dispatcher rejects missing / extra / wrong-typed args before the call.
- Arg types are declared per-arg (`int` for `limit`, `str` otherwise) and
  the provider schema and dispatcher both honor the declaration.
- Each `ToolSpec` marks whether it yields chunk/artifact ids or not.

These are unit-level (no LLM client, no loop) -- the 4-scenario outer
acceptance contract for issue #253 lives in
`tests/analysis/test_retrieval_loop_skeleton.py`, and issue #488's own
4-observable outer acceptance contract lives in
`tests/analysis/test_retrieval_loop_name_tools.py`.

Issue #505: `get_name`, `who_cites` and `who_argues_against` gain the same
`limit` int arg `find_names`/`name_neighbors` already carried (all three
were previously unbounded and returned every matching row -- one `get_name`
on a hub name page returned 962 ids). `test_limit_is_the_one_declared_int_arg_
in_the_whole_tool_set` is updated to the new five-tool set (a locked-contract
edit, justified by the founder-approved #505 decision), and new tests below
prove the dispatcher's `int_args` wiring actually rejects/accepts `limit` on
all three.

Issue #505's own follow-up: `coverage_count` is REMOVED from the registry
entirely (a deliberate contract change, not an oversight -- on a paid corpus run a real
provider's model chose to call it unprompted and it returned all 49,674
canonicals in one result, holding the prompt over a million characters for 14 turns). The
function itself is untouched; only its tool-facing registration is gone.
`EXPECTED_TOOL_NAMES`/`NAME_VALUED_TOOLS` below and every assertion that
counted it are updated accordingly, and a new test proves it is absent from
both `TOOL_REGISTRY` and `tool_specs_for_provider()`.

Issue #517 adds `where_names_meet` (two required string args, `canonical`
and `other`, plus the same `limit`/`total` shape `get_name`/`who_cites`/
`who_argues_against` already carry) -- a one-line justification for editing
this locked-contract file, per the founder-approved #517 decision.
`EXPECTED_TOOL_NAMES`/`CHUNK_VALUED_TOOLS`/the `limit`-int-arg test below are
all updated, and new tests cover its two-required-arg schema through the
dispatcher.

Issue #542 makes `get_chunk` batch-valued: `chunk_id` takes a list of ids and
the call is bounded by the same `limit`/`DEFAULT_LIMIT` mechanism the name
tools already use. Two assertions here move as a result, both deliberate
contract changes rather than oversights -- `get_chunk` joins the
`limit`-taking set, and it now carries a real pre-cap `total` (the number of
ids asked for), so the "no pre-cap total" example moves to `query_by_source`.
The batch's own outer acceptance contract is
`tests/analysis/test_retrieval_batch_get_chunk.py`."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from axial.retrieve.dispatcher import ToolResult, dispatch
from axial.retrieve.tools import TOOL_REGISTRY, tool_specs_for_provider

# The callable tools the registry exposes. `query_by_tag`, `query_by_polity`
# and `follow_backlinks` were de-registered with the tools themselves (issue
# #487, D1/D5) for returning nothing useful; the name-layer tools that
# replace them are registered here (issue #488, which owns the loop's
# rewiring). `coverage_count` is the mirror case (issue #505's own
# follow-up): de-registered for returning far too much -- see
# `test_coverage_count_is_not_a_registered_tool` below. The function itself
# is untouched (`axial.query.names.coverage_count`, §7.7's real consumer).
EXPECTED_TOOL_NAMES = {
    "find_names",
    "get_name",
    "name_neighbors",
    "who_cites",
    "who_argues_against",
    "where_names_meet",
    "query_by_source",
    "get_envelope",
    "get_chunk",
    "get_artifact",
}

# The tools whose result_ids are canonical NAMES, never chunk/artifact ids
# (issue #488's "what is a chunk id and what is a name"). `get_envelope`
# yields a `source_id`, which is neither -- it belongs in this "not
# chunk-valued" bucket too, but is asserted separately below since it is not
# a name-layer tool.
NAME_VALUED_TOOLS = {"find_names", "name_neighbors"}
CHUNK_VALUED_TOOLS = {
    "get_name",
    "who_cites",
    "who_argues_against",
    "where_names_meet",
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
    """§7.5's own split, restated as a data assertion: `find_names` and
    `name_neighbors` yield names; `get_name`, `who_cites`,
    `who_argues_against`, `where_names_meet`, `query_by_source`, `get_chunk`
    and `get_artifact` yield chunk/artifact ids; `get_envelope` yields
    neither."""
    for name in NAME_VALUED_TOOLS:
        assert TOOL_REGISTRY[name].returns_chunk_ids is False, name
    for name in CHUNK_VALUED_TOOLS:
        assert TOOL_REGISTRY[name].returns_chunk_ids is True, name
    assert TOOL_REGISTRY["get_envelope"].returns_chunk_ids is False


def test_limit_is_the_one_declared_int_arg_in_the_whole_tool_set():
    """Issue #505: `get_name`/`who_cites`/`who_argues_against` join
    `find_names`/`name_neighbors` in declaring `limit` as an int arg -- the
    whole name-layer tool set is now uniform (bounded, `limit`-taking).
    Issue #517 adds `where_names_meet` to the same uniform set, and issue
    #542 adds `get_chunk`, whose id list is bounded by the same mechanism
    rather than by a second cap invented for it."""
    limit_taking = {
        "find_names",
        "name_neighbors",
        "get_name",
        "who_cites",
        "who_argues_against",
        "where_names_meet",
        "get_chunk",
    }
    for name, spec in TOOL_REGISTRY.items():
        if name in limit_taking:
            assert spec.int_args == frozenset({"limit"}), name
        else:
            assert spec.int_args == frozenset(), name


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
    """The registry's own declared `int_args` (issue #488) must reach the
    provider payload as an honest JSON type -- `find_names`'s `limit` is
    `"integer"`, its `query` and every other tool's string args are
    `"string"`."""
    specs = tool_specs_for_provider()
    by_name = {entry["function"]["name"]: entry for entry in specs}

    find_names_props = by_name["find_names"]["function"]["parameters"]["properties"]
    assert find_names_props["limit"]["type"] == "integer"
    assert find_names_props["query"]["type"] == "string"

    get_name_props = by_name["get_name"]["function"]["parameters"]["properties"]
    assert get_name_props["canonical"]["type"] == "string"


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


# --- issue #488: the name-layer tools through the dispatcher, names_dir ----


@pytest.fixture
def fixture_names_dir(tmp_path: Path) -> Path:
    """A minimal name layer: one canonical, `Charles Tilly`, with the alias
    `Tilly` -- just enough to prove `find_names`/`get_name` reach through
    the dispatcher with a caller-supplied `names_dir`, not the default."""
    names_dir = tmp_path / "names"
    names_dir.mkdir(parents=True, exist_ok=True)
    nodes = [{"canonical": "Charles Tilly", "kind": "person", "aliases": ["Tilly"]}]
    (names_dir / "index.json").write_text(
        '{"version": 1, "generated_at": "2026-07-29T00:00:00Z", "names": ["Charles Tilly"]}',
        encoding="utf-8",
    )
    import json

    (names_dir / "alias_map.json").write_text(
        json.dumps({"version": 1, "generated_at": "2026-07-29T00:00:00Z", "nodes": nodes}),
        encoding="utf-8",
    )
    return names_dir


def test_dispatch_accepts_find_names_with_a_caller_supplied_names_dir(
    fixture_names_dir: Path, tmp_path: Path
):
    """`find_names`, resolved through the fixture `names_dir`, not the
    default -- proving `names_dir` is threaded through `dispatch` rather
    than silently ignored."""
    result = dispatch(
        "find_names",
        {"query": "Tilly"},
        vault_dir=tmp_path / "empty-vault",
        names_dir=fixture_names_dir,
    )

    assert result.error is None
    assert result.ids == ["Charles Tilly"]
    assert result.count == 1


def test_dispatch_rejects_a_retired_tool_before_reaching_the_vault():
    """`query_by_tag`/`query_by_polity`/`follow_backlinks` no longer exist
    (D1/D5) -- the dispatcher rejects a call to one exactly like any other
    unknown tool name, structured and non-raising."""
    for retired in ("query_by_tag", "query_by_polity", "follow_backlinks"):
        result = dispatch(retired, {}, vault_dir=Path("/nonexistent"))
        assert result.ids == []
        assert result.count == 0
        assert result.error is not None
        assert retired in result.error


def test_dispatch_rejects_find_names_wrong_typed_limit_without_raising(
    fixture_names_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """`limit` is declared `int`; a string value is a well-named call with a
    wrong-typed arg, rejected before `axial.query.names.find_names` is ever
    called."""
    from axial.query import names as names_module

    def _explode(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("find_names must never be called on a wrong-typed arg")

    monkeypatch.setattr(names_module, "find_names", _explode)

    result = dispatch(
        "find_names",
        {"query": "Tilly", "limit": "five"},
        vault_dir=tmp_path / "empty-vault",
        names_dir=fixture_names_dir,
    )

    assert result.ids == []
    assert result.count == 0
    assert result.error is not None
    assert "limit" in result.error


def test_dispatch_rejects_find_names_with_an_undeclared_extra_arg_without_raising(
    fixture_names_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A well-named call (`find_names` exists) with an arg its schema does
    not declare is rejected before the vault/name layer is ever reached."""
    from axial.query import names as names_module

    def _explode(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("find_names must never be called on an undeclared arg")

    monkeypatch.setattr(names_module, "find_names", _explode)

    result = dispatch(
        "find_names",
        {"query": "Tilly", "polity": "Syria"},
        vault_dir=tmp_path / "empty-vault",
        names_dir=fixture_names_dir,
    )

    assert result.ids == []
    assert result.count == 0
    assert result.error is not None
    assert "polity" in result.error


# --- issue #505: get_name/who_cites/who_argues_against gain limit ----------


@pytest.fixture
def fixture_tilly_vault_dir(tmp_path: Path) -> Path:
    """A `Charles Tilly` name page with three members, plus a fourth note
    (not a page member) that cites and argues against Tilly -- enough to
    prove `limit` truncates through the dispatcher for all three tools and
    that `ToolResult.total` carries the true pre-cap count."""
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

    names_dir = vault_dir / "names"
    names_dir.mkdir(parents=True, exist_ok=True)
    member_lines = "\n".join(
        f"- [[{chunk_id}]] — Charles Tilly (1978): Claim of {chunk_id}." for chunk_id in member_ids
    )
    page_body = f"# Charles Tilly\n\n**Member notes:**\n{member_lines}\n"
    (names_dir / "charles-tilly.md").write_text(
        "---\n"
        + yaml.safe_dump(
            {"name": "Charles Tilly", "kind": "person", "aliases": [], "member_count": 3},
            sort_keys=False,
        )
        + "---\n"
        + page_body,
        encoding="utf-8",
    )
    return vault_dir


@pytest.mark.parametrize("tool", ["get_name", "who_cites", "who_argues_against"])
def test_dispatch_rejects_wrong_typed_limit_on_each_of_the_three_newly_bounded_tools(
    tool: str, fixture_tilly_vault_dir: Path
):
    result = dispatch(
        tool, {"canonical": "Charles Tilly", "limit": "five"}, vault_dir=fixture_tilly_vault_dir
    )

    assert result.ids == []
    assert result.count == 0
    assert result.error is not None
    assert "limit" in result.error


@pytest.mark.parametrize("tool", ["get_name", "who_cites", "who_argues_against"])
def test_dispatch_accepts_int_limit_on_each_of_the_three_newly_bounded_tools(
    tool: str, fixture_tilly_vault_dir: Path
):
    result = dispatch(
        tool, {"canonical": "Charles Tilly", "limit": 1}, vault_dir=fixture_tilly_vault_dir
    )

    assert result.error is None
    assert result.count == 1


def test_dispatch_carries_the_true_total_for_get_name_when_capped(fixture_tilly_vault_dir: Path):
    capped = dispatch(
        "get_name", {"canonical": "Charles Tilly", "limit": 1}, vault_dir=fixture_tilly_vault_dir
    )
    assert capped.count == 1
    assert capped.total == 3, "the page's own member_count, regardless of the cap"

    uncapped = dispatch(
        "get_name", {"canonical": "Charles Tilly"}, vault_dir=fixture_tilly_vault_dir
    )
    assert uncapped.count == 3
    assert uncapped.total == 3


def test_dispatch_carries_the_true_total_for_who_cites_and_who_argues_against_when_capped(
    fixture_tilly_vault_dir: Path,
):
    for tool in ("who_cites", "who_argues_against"):
        result = dispatch(
            tool, {"canonical": "Charles Tilly", "limit": 10}, vault_dir=fixture_tilly_vault_dir
        )
        assert result.count == 1
        assert result.total == 1, tool


def test_dispatch_total_is_none_for_a_tool_that_carries_no_pre_cap_total(
    fixture_tilly_vault_dir: Path,
):
    """`query_by_source` (and every tool but `get_name`/`who_cites`/
    `who_argues_against`/`where_names_meet`/`get_chunk`) never sets `total`
    -- it has no cap-relevant concept of one.

    `get_chunk` used to be this test's example and no longer is: issue #542
    gave it a batch bounded at `limit`, so it now has a real pre-cap count
    (the number of ids the call asked for) and reports it, asserted below."""
    result = dispatch(
        "query_by_source", {"source_id": "tillyfix-1978"}, vault_dir=fixture_tilly_vault_dir
    )

    assert result.error is None
    assert result.total is None


def test_dispatch_carries_the_ids_asked_for_as_get_chunks_pre_cap_total(
    fixture_tilly_vault_dir: Path,
):
    """Issue #542: a batch truncated at `limit` is never silent about being
    one -- `total` is the count of ids the call asked for, the same "N of M
    total" the model already reads for a capped name page."""
    member_ids = [f"tillyfix-1978_{index}_intro_001" for index in range(1, 4)]
    result = dispatch(
        "get_chunk", {"chunk_id": member_ids, "limit": 2}, vault_dir=fixture_tilly_vault_dir
    )

    assert result.error is None
    assert result.ids == member_ids[:2]
    assert result.count == 2
    assert result.total == 3


# --- issue #517: where_names_meet through the dispatcher -------------------


def test_dispatch_accepts_where_names_meet_and_returns_the_intersection(
    fixture_tilly_vault_dir: Path,
):
    names_dir = fixture_tilly_vault_dir / "names"
    shared_member = "tillyfix-1978_1_intro_001"
    other_body = (
        "# Iraq\n\n**Member notes:**\n"
        f"- [[{shared_member}]] — Charles Tilly (1978): Claim of {shared_member}.\n"
    )
    (names_dir / "iraq.md").write_text(
        "---\n"
        + yaml.safe_dump(
            {"name": "Iraq", "kind": "country/state/place", "aliases": [], "member_count": 1},
            sort_keys=False,
        )
        + "---\n"
        + other_body,
        encoding="utf-8",
    )

    result = dispatch(
        "where_names_meet",
        {"canonical": "Charles Tilly", "other": "Iraq"},
        vault_dir=fixture_tilly_vault_dir,
    )

    assert result.error is None
    assert result.ids == [shared_member]
    assert result.count == 1
    assert result.total == 1, "the true, uncapped intersection size"


def test_dispatch_rejects_where_names_meet_missing_the_other_required_arg(
    fixture_tilly_vault_dir: Path,
):
    result = dispatch(
        "where_names_meet", {"canonical": "Charles Tilly"}, vault_dir=fixture_tilly_vault_dir
    )

    assert result.ids == []
    assert result.count == 0
    assert result.error is not None
    assert "other" in result.error


def test_dispatch_rejects_where_names_meet_wrong_typed_limit(fixture_tilly_vault_dir: Path):
    result = dispatch(
        "where_names_meet",
        {"canonical": "Charles Tilly", "other": "Iraq", "limit": "five"},
        vault_dir=fixture_tilly_vault_dir,
    )

    assert result.ids == []
    assert result.count == 0
    assert result.error is not None
    assert "limit" in result.error


def test_dispatch_rejects_where_names_meet_with_an_undeclared_extra_arg(
    fixture_tilly_vault_dir: Path,
):
    result = dispatch(
        "where_names_meet",
        {"canonical": "Charles Tilly", "other": "Iraq", "polity": "Syria"},
        vault_dir=fixture_tilly_vault_dir,
    )

    assert result.ids == []
    assert result.count == 0
    assert result.error is not None
    assert "polity" in result.error


# --- issue #517: ToolResult.detail rides beside three tools' own results ---


def test_dispatch_carries_detail_for_find_names(fixture_names_dir: Path, tmp_path: Path):
    """`ToolResult.detail` carries each `find_names` hit's `kind`,
    `member_count` and `tier` -- planner-blindness feedback that rides beside
    the result, exactly like `total`."""
    result = dispatch(
        "find_names",
        {"query": "Tilly"},
        vault_dir=tmp_path / "empty-vault",
        names_dir=fixture_names_dir,
    )

    assert result.error is None
    assert result.detail is not None
    assert "Charles Tilly" in result.detail
    assert "tier=alias" in result.detail


def test_dispatch_carries_detail_for_get_name(fixture_tilly_vault_dir: Path):
    """issue #517's own follow-up: a live corpus run showed a model cannot
    tell a large page is one book from a bare chunk_id list -- `detail`
    states how many distinct sources the returned members span. All three
    of Tilly's fixture members share one `source_id`."""
    result = dispatch("get_name", {"canonical": "Charles Tilly"}, vault_dir=fixture_tilly_vault_dir)

    assert result.error is None
    assert result.detail == "3 notes across 1 sources"


def test_dispatch_carries_detail_for_where_names_meet(tmp_path: Path):
    """Same fix, for the intersection itself: two shared notes from two
    different sources report as spanning two sources, not just two notes."""
    vault_dir = tmp_path / "vault"
    names_dir = vault_dir / "names"
    names_dir.mkdir(parents=True, exist_ok=True)

    def _write_page(name: str, filename: str, chunk_ids: list[str]) -> None:
        member_lines = "\n".join(
            f"- [[{chunk_id}]] — Author (2020): A claim." for chunk_id in chunk_ids
        )
        body = f"# {name}\n\n**Member notes:**\n{member_lines}\n"
        (names_dir / filename).write_text(
            "---\n"
            + yaml.safe_dump(
                {"name": name, "kind": "concept", "aliases": [], "member_count": len(chunk_ids)},
                sort_keys=False,
            )
            + "---\n"
            + body,
            encoding="utf-8",
        )

    shared = ["srcA_1_a_001", "srcB_1_a_001"]
    _write_page("A", "a.md", shared)
    _write_page("B", "b.md", shared)

    result = dispatch("where_names_meet", {"canonical": "A", "other": "B"}, vault_dir=vault_dir)

    assert result.error is None
    assert result.count == 2
    assert result.detail == "2 notes across 2 sources"


@pytest.mark.parametrize(
    "tool,args",
    [
        ("name_neighbors", {"canonical": "Charles Tilly"}),
        ("who_cites", {"canonical": "Charles Tilly"}),
        ("who_argues_against", {"canonical": "Charles Tilly"}),
        ("get_chunk", {"chunk_id": "tillyfix-1978_1_intro_001"}),
        ("query_by_source", {"source_id": "tillyfix-1978"}),
    ],
)
def test_dispatch_leaves_detail_none_for_tools_with_no_source_span_concept(
    tool: str, args: dict[str, str], fixture_tilly_vault_dir: Path
):
    """Only `find_names`, `get_name` and `where_names_meet` populate
    `detail` (issue #517) -- every other tool leaves it `None`."""
    result = dispatch(tool, args, vault_dir=fixture_tilly_vault_dir)
    assert result.detail is None
