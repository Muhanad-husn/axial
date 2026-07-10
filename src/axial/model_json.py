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

Issue #100: deepseek-v4-flash, chunking a book dense with Arabic
transliterations, persistently emits Python-style invalid escapes (e.g.
`\\'`) inside JSON string values -- content-driven, not stochastic, so it
survives every one of `complete_json`'s bounded re-asks. `_repair_invalid_escapes`
drops the backslash from any `\\X` pair whose `X` is outside JSON's legal
escape set (`" \\ / b f n r t u`) before `json.loads` ever sees the text.

Why a single linear left-to-right pass over the whole raw text is safe and a
true no-op on already-valid JSON, with no need to track whether the scanner
is "inside a string": a valid JSON document can only contain a bare
backslash inside a string (a backslash anywhere else is a syntax error
`json.loads` would reject regardless of this repair), and *inside* a string
every backslash must already begin one of the legal escape pairs above --
otherwise the document was already invalid before repair ran. So repairing
"a backslash followed by an illegal escape char, anywhere in the text" can
only ever fire on text that would otherwise fail to parse; it can never
touch a backslash that is part of a legal escape in valid JSON, because
every backslash in valid JSON already starts a legal pair. The scanner
still must walk left-to-right and consume matched escape pairs two
characters at a time (never a regex lookbehind/lookahead over already-
consumed backslashes), so a legal `\\\\` (escaped backslash) immediately
followed by a literal `'` is read as TWO independent tokens -- the escaped
backslash, THEN a bare apostrophe -- and the apostrophe is left alone rather
than misread as part of a `\\'` pair.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable

# A single fence wrapping the entire response: optional leading whitespace,
# an opening ``` optionally followed by a language tag (e.g. "json") to
# end-of-line, the body, a closing ```, optional trailing whitespace. Only
# matches when the fence wraps the WHOLE string -- a fence embedded after
# leading prose is left alone (that's a different failure, not a fence to
# strip).
_FENCE_RE = re.compile(r"\A\s*```[^\n]*\n(?P<body>.*)```\s*\Z", re.DOTALL)

_SNIPPET_LIMIT = 300

# JSON's legal single-character escapes (RFC 8259 §7): the char immediately
# following a backslash inside a string. `u` is included here even though a
# real `\uXXXX` escape needs 4 following hex digits too -- this repair only
# decides whether to drop the backslash, never touches what comes after, so
# `\u` sequences are always left completely untouched (module docstring).
_LEGAL_ESCAPE_CHARS = frozenset('"\\/bfnrtu')


def _repair_invalid_escapes(raw: str) -> str:
    """Drop the backslash from any `\\X` pair in `raw` whose `X` is outside
    JSON's legal escape set, left to right, consuming matched pairs two
    characters at a time so a legal `\\\\` is never misread as starting a
    pair with whatever character follows it (see module docstring for the
    full reasoning and the `\\\\'` vs `\\'` distinction). A true no-op on
    already-valid JSON."""
    if "\\" not in raw:
        return raw
    out: list[str] = []
    i = 0
    n = len(raw)
    while i < n:
        char = raw[i]
        if char == "\\" and i + 1 < n:
            next_char = raw[i + 1]
            if next_char in _LEGAL_ESCAPE_CHARS:
                out.append(char)
                out.append(next_char)
            else:
                # Illegal escape: drop the backslash, keep the char.
                out.append(next_char)
            i += 2
            continue
        out.append(char)
        i += 1
    return "".join(out)


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
    client: Any,
    prompt: str,
    pass_name: str | None = None,
    *,
    attempts: int = 3,
    validate: Callable[[str], None] | None = None,
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

    `validate`, when given, is called with the raw response string AFTER
    `parse_model_json` has already confirmed it parses -- it never runs on a
    response that fails JSON parsing, that case is already re-asked on its
    own. It exists for cheap, caller-defined degeneracy checks on otherwise
    valid JSON whose *content* is response noise, not a real answer -- e.g.
    an empty-string tag value or an empty `toc` list (issue #80): valid
    JSON, degenerate content, the same species as broken JSON (#76) or
    `secondary: []` (#58), and deserving the same bounded re-ask rather than
    an instant abort. If `validate` RAISES (any exception), that attempt
    counts as failed exactly like an unparseable response, and the loop
    re-asks within the same bounded budget. `validate` must NEVER be used
    for a genuine schema-vocabulary miss (e.g. an out-of-list tag) -- that
    is the P0-6 schema-gap signal and must stay immediately fatal, not
    smoothed over by a re-ask; callers keep that check in their own
    post-`complete_json` parse/validate flow, entirely outside `validate`.

    Returns the RAW response string, not the parsed value, once it verifies
    parseable (and, when `validate` is given, non-degenerate) -- deliberately:
    several call sites (e.g. tag.py) parse one raw response with multiple
    different per-axis parsers, so handing back only a parsed value would
    force them to either re-serialize it or duplicate this helper's parsing.
    Returning the validated raw string lets every call site keep its own
    exact parsing flow unchanged; `parse_model_json` is used here purely as
    the validity gate, and its parsed result is discarded once confirmed.

    On persistent failure, the final attempt's exception -- `ModelJsonError`
    (carrying the raw-response snippet) when the JSON itself never parsed,
    or `validate`'s own exception, UNCHANGED, when JSON parsed but
    `validate` kept rejecting it -- propagates exactly as raised, so callers
    keep wrapping/handling it into their own typed error exactly as before.
    Transport-level errors from `client.complete()` itself (`LLMError`,
    `httpx.HTTPError`) are never caught here -- they propagate immediately
    on the first occurrence, exactly as today.

    `attempts < 1` is a caller bug, not a retry outcome: it raises
    `ValueError` immediately, before any completion is requested.
    """
    if attempts < 1:
        raise ValueError(f"attempts must be >= 1, got {attempts}")
    last_error: Exception | None = None
    for _ in range(attempts):
        raw = client.complete(prompt, pass_name=pass_name)
        try:
            parse_model_json(raw)
        except ModelJsonError as exc:
            last_error = exc
            continue
        if validate is not None:
            try:
                validate(raw)
            except Exception as exc:  # noqa: BLE001 -- caller's own check, any exception re-asks
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
    snippet of the original raw text. Before parsing, any invalid string
    escape (a backslash followed by a character outside JSON's legal escape
    set) is repaired by dropping the backslash (issue #100) -- a no-op on
    already-valid JSON; text broken beyond that repair still raises
    `ModelJsonError` exactly as before."""
    try:
        return json.loads(_repair_invalid_escapes(_strip_fence(raw)), strict=False)
    except json.JSONDecodeError as exc:
        raise ModelJsonError(f"{exc}; raw response was: {_snippet(raw)}") from exc
