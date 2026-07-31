"""The validating dispatcher -- the hard gate between a model's requested
tool call and the deterministic §7.5 query API (specs/PHASE-B.md §4, issue
#253 slice 01, extended to the name layer by issue #488).

Checks the requested tool name against `TOOL_REGISTRY` and its args against
that tool's declared schema BEFORE calling: an unknown name, or missing/
extra/wrong-typed args, returns a structured `ToolResult` error instead of
ever reaching `axial.query.names`/`axial.query.reader` -- never raises for a
caller-supplied bad call. A real query-API failure (e.g. a well-formed but
nonexistent id or canonical) is caught the same way, so a bad tool call can
never crash the retrieval loop; only a bug in this module's own code would.

Arg types are validated against each tool's own declared `int_args`/
`str_list_args` (`axial.retrieve.tools.ToolSpec`): an arg named in the first
must be an `int` (never a `bool`, which Python's `isinstance(x, int)` would
otherwise let through), an arg named in the second may be a list of strings
or a bare string (issue #542, `get_chunk`'s batch), and every other allowed
arg must be a `str`.

`names_dir` is threaded through the call exactly like `vault_dir`/
`envelopes_dir`: an optional caller-supplied directory for the name-layer
tools (`find_names`, `get_name`, `name_neighbors`, `who_cites`,
`who_argues_against`, `where_names_meet`), defaulting to `None` so a caller
passing nothing resolves against the query API's own default (`axial.paths.
default_names_dir`), exactly as `vault_dir`/`envelopes_dir` already do.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from axial.query import reader
from axial.retrieve.tools import TOOL_REGISTRY, ToolSpec


@dataclass(frozen=True)
class ToolResult:
    """One dispatch outcome. `ids`/`count` are exactly the §7.6 trajectory
    entry's `result_ids`/`result_count` (empty/zero on any validation or
    query failure). `error`, when set, is the structured message meant for
    the model -- deliberately NOT one of the §7.6 trajectory fields, since
    that log's shape is fixed to exactly `{step, tool, args, result_ids,
    result_count}` ([FIRM]); the caller (the loop) is responsible for
    surfacing `error` to the model through its own conversation channel.

    `total`, when set (issue #505), is the true pre-cap count for a tool
    truncated at its `limit` -- `get_name`/`who_cites`/`who_argues_against`/
    `where_names_meet`, plus `get_chunk`, whose pre-cap count is the number
    of ids the call asked for (issue #542) -- and `None` for the rest. It
    rides beside the trajectory exactly the way `error` does, for the same
    reason: a capped result the model cannot see is a lie about the corpus
    (`get_name` on `Syria` returns 10 members out of 962), so the loop
    surfaces `total` through its own conversation channel rather than
    smuggling a sixth field into the [FIRM] trajectory shape.

    `detail`, when set (issue #517), is the same kind of beside-the-
    trajectory rider, populated by three tools: `find_names` states each
    hit's `kind`, `member_count` and `tier`, so a model can tell an
    exact/alias resolution apart from an embedding guess -- a bare canonical
    string cannot. `get_name` and `where_names_meet` state how many distinct
    sources the returned members span (`"<N> notes across <M> sources"`) --
    a live corpus run showed a model avoiding a large page or intersection
    entirely by resolving a narrow, one-book name instead, because it could
    not see that the "large" result it was told to avoid was actually the
    cross-book one. Every other tool leaves `detail` `None`."""

    ids: list[str]
    count: int
    error: str | None = None
    total: int | None = None
    detail: str | None = None


def _declared_type_ok(spec: ToolSpec, key: str, value: Any) -> bool:
    """Whether `value` matches `key`'s declared type on `spec`: `int` (never
    `bool`) when `key` is in `spec.int_args`; a list of strings OR a bare
    string when `key` is in `spec.str_list_args`; `str` otherwise.

    The bare string is accepted on a list arg deliberately (issue #542):
    `get_chunk` is advertised to the model as taking a list, but a model will
    keep emitting the single-id form it used before, and rejecting it would
    cost a full model turn to say something the tool can simply answer."""
    if key in spec.int_args:
        return isinstance(value, int) and not isinstance(value, bool)
    if key in spec.str_list_args:
        return isinstance(value, str) or (
            isinstance(value, list) and all(isinstance(item, str) for item in value)
        )
    return isinstance(value, str)


def _declared_type_name(spec: ToolSpec, key: str) -> str:
    """`key`'s declared type, named for the model in a validation error."""
    if key in spec.int_args:
        return "int"
    if key in spec.str_list_args:
        return "list of str"
    return "str"


def dispatch(
    tool: str,
    args: dict[str, Any],
    *,
    vault_dir: Path | None = None,
    envelopes_dir: Path | None = None,
    names_dir: Path | None = None,
) -> ToolResult:
    spec = TOOL_REGISTRY.get(tool)
    if spec is None:
        return ToolResult(
            ids=[],
            count=0,
            error=f"unknown tool {tool!r}; known tools: {sorted(TOOL_REGISTRY)}",
        )

    if not isinstance(args, dict):
        return ToolResult(
            ids=[],
            count=0,
            error=f"tool {tool!r} args must be an object, got {type(args).__name__}",
        )

    missing = spec.required_args - set(args)
    extra = set(args) - spec.allowed_args
    wrong_typed = {
        key
        for key, value in args.items()
        if key in spec.allowed_args and not _declared_type_ok(spec, key, value)
    }

    if missing or extra or wrong_typed:
        problems = []
        if missing:
            problems.append(f"missing required arg(s) {sorted(missing)!r}")
        if extra:
            problems.append(f"unexpected arg(s) {sorted(extra)!r}")
        if wrong_typed:
            expected = {key: _declared_type_name(spec, key) for key in wrong_typed}
            detail = ", ".join(f"{key!r} (expected {expected[key]})" for key in sorted(wrong_typed))
            problems.append(f"wrong-typed arg(s): {detail}")
        return ToolResult(
            ids=[], count=0, error=f"invalid args for tool {tool!r}: {'; '.join(problems)}"
        )

    try:
        ids, count, total, detail = spec.call(args, vault_dir, envelopes_dir, names_dir)
    except reader.QueryError as exc:
        return ToolResult(ids=[], count=0, error=f"tool {tool!r} query failed: {exc}")
    return ToolResult(ids=ids, count=count, total=total, detail=detail)
