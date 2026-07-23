"""The validating dispatcher -- the hard gate between a model's requested
tool call and the deterministic §7.5 query API (specs/PHASE-B.md §4, issue
#253 slice 01).

Checks the requested tool name against `TOOL_REGISTRY` and its args against
that tool's signature BEFORE calling: an unknown name, or missing/extra/
wrong-typed args, returns a structured `ToolResult` error instead of ever
reaching `axial.query.reader` -- never raises for a caller-supplied bad
call. A real query-API failure (e.g. a well-formed but nonexistent id) is
caught the same way, so a bad tool call can never crash the retrieval loop;
only a bug in this module's own code would.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from axial.query import reader
from axial.retrieve.tools import TOOL_REGISTRY


@dataclass(frozen=True)
class ToolResult:
    """One dispatch outcome. `ids`/`count` are exactly the §7.6 trajectory
    entry's `result_ids`/`result_count` (empty/zero on any validation or
    query failure). `error`, when set, is the structured message meant for
    the model -- deliberately NOT one of the §7.6 trajectory fields, since
    that log's shape is fixed to exactly `{step, tool, args, result_ids,
    result_count}` ([FIRM]); the caller (the loop) is responsible for
    surfacing `error` to the model through its own conversation channel."""

    ids: list[str]
    count: int
    error: str | None = None


def dispatch(
    tool: str,
    args: dict[str, Any],
    *,
    vault_dir: Path | None = None,
    envelopes_dir: Path | None = None,
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
        if key in spec.allowed_args and not isinstance(value, str)
    }

    if missing or extra or wrong_typed:
        problems = []
        if missing:
            problems.append(f"missing required arg(s) {sorted(missing)!r}")
        if extra:
            problems.append(f"unexpected arg(s) {sorted(extra)!r}")
        if wrong_typed:
            problems.append(f"wrong-typed arg(s) {sorted(wrong_typed)!r} (expected str)")
        return ToolResult(
            ids=[], count=0, error=f"invalid args for tool {tool!r}: {'; '.join(problems)}"
        )

    try:
        ids, count = spec.call(args, vault_dir, envelopes_dir)
    except reader.QueryError as exc:
        return ToolResult(ids=[], count=0, error=f"tool {tool!r} query failed: {exc}")
    return ToolResult(ids=ids, count=count)
