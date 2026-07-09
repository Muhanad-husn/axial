"""Shared JSON parsing for raw model completions (issue #72).

Every LLM-backed pass parses its completion as JSON. deepseek-v4-flash
occasionally wraps an otherwise-valid answer in a markdown code fence despite
the prompts' "no fences" instruction; that is semantically a valid answer and
should not abort the pass. When parsing genuinely fails, the resulting error
must quote the raw response so the failure is diagnosable from worker logs
instead of just a bare `Expecting value: line 1 column 1 (char 0)`.
"""

from __future__ import annotations

import json
import re
from typing import Any

# A single fence wrapping the entire response: optional leading whitespace,
# an opening ``` optionally followed by a language tag (e.g. "json") to
# end-of-line, the body, a closing ```, optional trailing whitespace. Only
# matches when the fence wraps the WHOLE string -- a fence embedded after
# leading prose is left alone (that's a different failure, not a fence to
# strip).
_FENCE_RE = re.compile(r"\A\s*```[^\n]*\n(?P<body>.*)```\s*\Z", re.DOTALL)

_SNIPPET_LIMIT = 300


class ModelJsonError(ValueError):
    """Raised when a raw model completion cannot be parsed as JSON, even
    after stripping a single markdown fence. The message carries both the
    underlying `json.JSONDecodeError` text and a truncated snippet of the
    raw response, so callers' enriched error messages stay diagnosable from
    worker logs (issue #72)."""


def _strip_fence(raw: str) -> str:
    """Strip a single leading/trailing markdown fence wrapping `raw`,
    tolerating whitespace around and inside it. Returns `raw` unchanged when
    it isn't (wholly) fenced."""
    match = _FENCE_RE.match(raw)
    if match is None:
        return raw
    return match.group("body")


def _snippet(raw: str) -> str:
    """A truncated repr of `raw` (first ~300 chars), noting the total length
    when truncation happened, for diagnosable error messages."""
    if len(raw) <= _SNIPPET_LIMIT:
        return repr(raw)
    return f"{raw[:_SNIPPET_LIMIT]!r} (truncated, total length {len(raw)})"


def parse_model_json(raw: str) -> Any:
    """Parse `raw` as JSON, first stripping a single markdown fence
    wrapping the whole response if present (opening ``` with an optional
    language tag, closing ```). Plain JSON (with or without surrounding
    whitespace) parses exactly as `json.loads` would. On failure, raises
    `ModelJsonError` whose message includes the decode error and a truncated
    snippet of the original raw text."""
    try:
        return json.loads(_strip_fence(raw))
    except json.JSONDecodeError as exc:
        raise ModelJsonError(f"{exc}; raw response was: {_snippet(raw)}") from exc
