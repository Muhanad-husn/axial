"""Shared JSON parsing for raw model completions (issue #72).

Every LLM-backed pass parses its completion as JSON. deepseek-v4-flash
occasionally wraps an otherwise-valid answer in a markdown code fence despite
the prompts' "no fences" instruction; that is semantically a valid answer and
should not abort the pass. When parsing genuinely fails, the resulting error
must quote the raw response so the failure is diagnosable from worker logs
instead of just a bare `Expecting value: line 1 column 1 (char 0)`.
`json.loads` is called with `strict=False` because real model outputs carry
literal control characters (e.g. a raw newline or tab) inside JSON string
text fields, which strict-mode JSON rejects despite the intent being
unambiguous.
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


def complete_json(
    client: Any, prompt: str, pass_name: str | None = None, *, attempts: int = 3
) -> str:
    """Call `client.complete(prompt, pass_name=pass_name)` and validate the
    result parses as JSON via `parse_model_json`, re-asking -- a fresh
    completion of the same prompt, no sleep in between -- up to `attempts`
    total when the response is complete-but-unparseable (issue #76: a
    genuinely malformed completion, e.g. a missing comma mid-response, that
    no transport-level retry in llm.py catches, since it arrives as a
    well-formed HTTP 200 with `finish_reason == "stop"`). The failure is
    stochastic, not rate-related, so no backoff is needed between re-asks
    (unlike llm.py's transport retries).

    Returns the RAW response string, not the parsed value, once it verifies
    parseable -- deliberately: several call sites (e.g. tag.py) parse one
    raw response with multiple different per-axis parsers, so handing back
    only a parsed value would force them to either re-serialize it or
    duplicate this helper's parsing. Returning the validated raw string
    lets every call site keep its own exact parsing flow unchanged;
    `parse_model_json` is used here purely as the validity gate, and its
    parsed result is discarded once confirmed.

    On persistent failure, the final attempt's `ModelJsonError` (carrying
    the raw-response snippet) propagates unchanged, so callers keep
    wrapping it into their own typed parse error exactly as before.
    Transport-level errors from `client.complete()` itself (`LLMError`,
    `httpx.HTTPError`) are never caught here -- they propagate immediately
    on the first occurrence, exactly as today.

    `attempts < 1` is a caller bug, not a retry outcome: it raises
    `ValueError` immediately, before any completion is requested.
    """
    if attempts < 1:
        raise ValueError(f"attempts must be >= 1, got {attempts}")
    last_error: ModelJsonError | None = None
    for _ in range(attempts):
        raw = client.complete(prompt, pass_name=pass_name)
        try:
            parse_model_json(raw)
        except ModelJsonError as exc:
            last_error = exc
            continue
        return raw
    assert (
        last_error is not None
    )  # attempts >= 1, so the loop always sets this before falling through
    raise last_error


def parse_model_json(raw: str) -> Any:
    """Parse `raw` as JSON, first stripping a single markdown fence
    wrapping the whole response if present (opening ``` with an optional
    language tag, closing ```). Plain JSON (with or without surrounding
    whitespace) parses exactly as `json.loads` would. On failure, raises
    `ModelJsonError` whose message includes the decode error and a truncated
    snippet of the original raw text."""
    try:
        return json.loads(_strip_fence(raw), strict=False)
    except json.JSONDecodeError as exc:
        raise ModelJsonError(f"{exc}; raw response was: {_snippet(raw)}") from exc
