"""Outer acceptance test for issue #100 (model_json: repair invalid string
escapes before parsing).

Locked behavioral contract (DEC-1) -- do not edit once committed red.

Given a chunk-pass model response whose raw JSON text contains a Python-style
     `\\'` escape (an invalid JSON escape -- legal JSON escapes are only
     `" \\ / b f n r t u`) inside a chunk's "text" value, exactly the shape
     observed live on the ayubi-over-stating-the-arab-state gold source
When  the user runs `axial vault write <fixture>`
Then  the run still succeeds end-to-end (exit 0) and the written note's
      chunk text contains the literal, un-escaped word (e.g. "ra'is"), never
      the broken `ra\\'is` form and never a JSON parse failure
And   a response using only LEGAL JSON escapes (`\\"`, `\\\\`, `\\n`) plus a
      literal non-ASCII character round-trips byte-identically -- the repair
      must be a no-op on already-valid JSON, never mangling it
And   a response broken beyond escape repair (e.g. truncated mid-object)
      still fails loudly: non-zero exit, a ModelJsonError-derived message on
      stderr, after `complete_json`'s bounded re-asks -- the repair must
      never paper over a genuine parse failure or short-circuit the re-ask
      path

See `gh issue view 100` for the full report: deepseek-v4-flash, chunking a
book dense with Arabic transliterations, persistently emits Python-style
`\\'` escapes inside JSON strings. This is content-driven, not stochastic
(the model reproduces the same dialect on every re-ask), so it exhausted
`complete_json`'s bounded re-askS and looped the source forever under the
whole-file-atomic chunk checkpoint. Fix (implementer's job, in
`src/axial/model_json.py`'s `parse_model_json`): before `json.loads`, repair
a backslash followed by a character outside JSON's legal escape set by
dropping the backslash; `\\u` sequences are left untouched; already-valid
JSON must round-trip byte-identically.

Fixture reuse: tests/fixtures/envelope/thesis_paper.pdf plus its committed
tree fixture (tests/fixtures/envelope/thesis_paper_tree.json), exactly as
tests/test_vault_write.py and tests/test_vault_resume.py use them -- no new
fixture is needed. This test drives `axial vault write` end-to-end (not a
narrower unit call into `parse_model_json`/`axial chunk` directly) because
the locked contract is behavioral and end-to-end, mirroring the exact
production failure mode: an invalid escape inside a *chunk-pass* response
must not corrupt or abort a real vault-write run.

Seam decision 1 -- a new chunk-pass raw-response override seam
-----------------------------------------------------------------------
As of this commit, `src/axial/llm.py` has NO way to inject an arbitrary raw
string as the chunk-pass ("pass_name=CHUNK_PASS_NAME") canned response --
only the tag pass has this (`AXIAL_STUB_TAG_RESPONSE`,
`STUB_TAG_RESPONSE_ENV_VAR`). Driving an invalid-escape chunk response
through the CLI (the only way to exercise this end-to-end, per the module
docstring above) requires a chunk-pass equivalent. This test locks that seam
under the name `AXIAL_STUB_CHUNK_RESPONSE`, mirroring
`AXIAL_STUB_TAG_RESPONSE`'s existing contract exactly (a non-empty value
read fresh from the environment on every chunk-pass call, substituting a raw
string verbatim for `StubLLMClient._CANNED_CHUNK_RESPONSE`; unset/empty
means today's default canned chunk response, unaffected). Wiring this seam
into `axial.llm._canned_response_for` for `pass_name == CHUNK_PASS_NAME` is
therefore part of the implementer's job for issue #100 -- it is a test/CI-only
seam (no production behavior change), the same category of change as
`AXIAL_STUB_TAG_RESPONSE` itself, `AXIAL_STUB_ARTIFACT_ROLE`, and
`AXIAL_STUB_XREF_TARGET`. Until that seam exists, every test below is
red: the override is silently ignored, the stub's default (unrelated, valid)
canned chunk response is used instead, and the assertions on the actual
written chunk text/exit code fail.

Because the override is read fresh on every call (mirroring
`AXIAL_STUB_TAG_RESPONSE`), it applies identically to every chunk-pass call
`axial vault write` makes (one per prose section with chunkable text -- this
fixture has three: Introduction, Comparative Cases, Conclusion) AND to every
re-ask `complete_json` performs on a still-failing response -- exactly
matching the live bug's "content-driven, not stochastic" persistence
(module docstring above).

Seam decision 2 -- constructing the raw invalid-escape bytes without a second
escaping layer mangling them
-----------------------------------------------------------------------
The raw response text for the RED case must contain the literal two-byte
sequence backslash + apostrophe (`\\'`) inside a JSON string value -- NOT
`json.dumps`-produced text, since `json.dumps` would legally escape any
embedded backslash as `\\\\`, which decodes back to a single backslash and
is valid JSON (not the bug). So the JSON text is built by hand, string
concatenation only, with a single explicit `"\\\\"` Python literal (one
backslash character) spliced in -- never routed through `json.dumps` --
so the exact invalid byte sequence observed live is what the stub actually
returns as raw text.

Seam decision 3 -- scope: this locks the chunk-pass path only
-----------------------------------------------------------------------
The issue notes "All model-JSON passes benefit (chunk/envelope/tag/artifacts
route through parse_model_json)" -- but the live failure, the seam available
to construct a targeted end-to-end reproduction, and the CLAUDE.md brief for
this test all scope this outer contract to the chunk pass specifically (the
pass that actually broke in production, per the issue's Observed section).
Envelope/tag/artifacts sharing the same `parse_model_json` fix is a
consequence of the fix living in one shared module, not a separately locked
behavior here.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import yaml

from axial.envelope import compute_source_id

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "envelope"

THESIS_PAPER_PDF = FIXTURES_DIR / "thesis_paper.pdf"
THESIS_PAPER_TREE_FIXTURE = FIXTURES_DIR / "thesis_paper_tree.json"

PROVIDER_ENV_VAR = "AXIAL_LLM_PROVIDER"

# New test/CI-only fault-injection seam this outer test locks (seam decision
# 1 above): mirrors AXIAL_STUB_TAG_RESPONSE for the chunk pass instead of the
# tag pass. Does not exist in src/axial/llm.py as of this commit -- wiring it
# in is part of making this outer test green.
STUB_CHUNK_RESPONSE_ENV_VAR = "AXIAL_STUB_CHUNK_RESPONSE"

ARGPARSE_FALLBACK_MARKERS = (
    "invalid choice",
    "unrecognized arguments",
)

# --- seam decision 2: hand-built raw JSON text, never json.dumps'd --------

_BACKSLASH = "\\"  # exactly one backslash character

# The literal chunk text a real model emitted (issue #100 Observed section),
# reproduced with the exact invalid `\'` escape: the raw bytes are
# `ra\'is`, i.e. r, a, BACKSLASH, ', i, s -- not the valid-JSON-escaped form.
_WORD_WITH_INVALID_ESCAPE = f"ra{_BACKSLASH}'is"
_CHUNK_TEXT_WITH_INVALID_ESCAPE = f"The word {_WORD_WITH_INVALID_ESCAPE} connotes deference"

# The whole raw chunk-pass response text, built by string concatenation so
# the invalid escape survives untouched -- json.dumps() would never produce
# this (it would legally double the backslash instead).
RAW_RESPONSE_INVALID_ESCAPE = '{"chunks": [{"text": "' + _CHUNK_TEXT_WITH_INVALID_ESCAPE + '"}]}'

# What the chunk text must read AFTER repair: the backslash dropped, the
# apostrophe kept, nothing else changed.
EXPECTED_REPAIRED_CHUNK_TEXT = "The word ra'is connotes deference"

# The un-repaired, still-broken form that must never appear in output --
# proves the backslash was actually dropped, not just coincidentally never
# rendered.
_STILL_BROKEN_FORM = _BACKSLASH + "'is"

# --- valid-JSON no-op guard: legal escapes (", \, n) + a literal non-ASCII
# character (e), all via json.dumps with ensure_ascii=False so "e-acute"
# survives as a literal UTF-8 character rather than a \uXXXX escape. -------

LEGAL_CHUNK_TEXT = 'He wrote "the plan," then\\paused for a moment\nin the café downstairs.'

RAW_RESPONSE_LEGAL_ESCAPES = json.dumps(
    {"chunks": [{"text": LEGAL_CHUNK_TEXT}]}, ensure_ascii=False
)

# --- still-fatal guard: an invalid escape (so repair fires) PLUS the object
# is truncated mid-string, so repairing the escape alone can never rescue
# it -- genuinely, permanently broken JSON. -------------------------------

RAW_RESPONSE_BROKEN_BEYOND_REPAIR = (
    '{"chunks": [{"text": "The word ra' + _BACKSLASH + "'is starts here but the object never clos"
)


def _trees_dir(root: Path) -> Path:
    return root / "data" / "trees"


def _envelopes_dir(root: Path) -> Path:
    return root / "data" / "envelopes"


def _vault_dir(root: Path) -> Path:
    return root / "data" / "vault"


def _prose_dir(root: Path) -> Path:
    return _vault_dir(root) / "prose"


def _run_axial(
    args: list[str],
    provider: str,
    *,
    cwd: Path,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env[PROVIDER_ENV_VAR] = provider
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["uv", "run", "--project", str(REPO_ROOT), "axial", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        env=env,
    )


def _run_envelope(provider: str, *args: str, cwd: Path) -> subprocess.CompletedProcess:
    return _run_axial(["envelope", *args], provider, cwd=cwd)


def _run_vault_write(
    provider: str,
    *args: str,
    cwd: Path,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    return _run_axial(["vault", "write", *args], provider, cwd=cwd, extra_env=extra_env)


def _assert_not_argparse_fallback(result: subprocess.CompletedProcess, command: str) -> None:
    combined = result.stdout + result.stderr
    for marker in ARGPARSE_FALLBACK_MARKERS:
        assert marker not in combined, (
            f"expected a real `{command}` behavior path, not an argparse "
            f"fallback (found {marker!r}) -- this means the `{command}` "
            f"subcommand does not exist yet or was never reached:\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )


def _existing_envelope_files(root: Path) -> set[Path]:
    envelopes_dir = _envelopes_dir(root)
    if not envelopes_dir.exists():
        return set()
    return set(envelopes_dir.glob("*.json"))


def _place_tree_fixture(source_pdf: Path, tree_fixture_path: Path, root: Path) -> Path:
    """Pre-place the committed REAL tree fixture at
    <root>/data/trees/<source_id>.json so `axial.extract.extract` reuses it
    verbatim instead of running docling (mirrors tests/test_vault_write.py's
    helper of the same name)."""
    source_id = compute_source_id(source_pdf)
    tree_path = _trees_dir(root) / f"{source_id}.json"
    tree_path.parent.mkdir(parents=True, exist_ok=True)
    tree_path.write_bytes(tree_fixture_path.read_bytes())
    return tree_path


def _arrange_stored_envelope(root: Path) -> Path:
    """Pre-place the real tree fixture, then run `axial envelope` with the
    stub provider so a stored envelope exists on disk before vault write.
    Mirrors tests/test_vault_write.py's helper of the same name."""
    _place_tree_fixture(THESIS_PAPER_PDF, THESIS_PAPER_TREE_FIXTURE, root)
    before_files = _existing_envelope_files(root)

    result = _run_envelope("stub", str(THESIS_PAPER_PDF), cwd=root)
    _assert_not_argparse_fallback(result, "envelope")
    assert result.returncode == 0, (
        f"arrange step failed: expected exit code 0 for `axial envelope` on "
        f"the fixture with the stub LLM provider, got {result.returncode}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    new_files = _existing_envelope_files(root) - before_files
    assert len(new_files) == 1, (
        f"arrange step failed: expected exactly one new file under "
        f"{_envelopes_dir(root)} after `axial envelope`, got {len(new_files)}: "
        f"{sorted(new_files)}\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    return next(iter(new_files))


def _split_frontmatter(text: str, note_path: Path) -> tuple[dict, str]:
    """Split a note's text into its parsed YAML frontmatter mapping and its
    body string (mirrors tests/test_vault_write.py's helper)."""
    lines = text.splitlines()
    assert lines and lines[0].strip() == "---", (
        f"expected {note_path} to open with a YAML frontmatter block "
        f"delimited by a leading '---' line, got first line "
        f"{(lines[0] if lines else None)!r}. Full text (truncated): {text[:500]!r}"
    )

    closing_index = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            closing_index = index
            break
    assert closing_index is not None, (
        f"expected {note_path} to have a closing '---' line ending its "
        f"YAML frontmatter block, found none. Full text (truncated): {text[:1000]!r}"
    )

    frontmatter_text = "\n".join(lines[1:closing_index])
    body = "\n".join(lines[closing_index + 1 :])

    frontmatter = yaml.safe_load(frontmatter_text)
    assert isinstance(frontmatter, dict), (
        f"expected {note_path}'s YAML frontmatter block to parse to a "
        f"mapping/object, got {type(frontmatter).__name__}: {frontmatter!r}"
    )
    return frontmatter, body


def _all_prose_notes(root: Path) -> list[tuple[dict, str, Path]]:
    """Every prose note under `<root>/data/vault/prose/`, parsed into
    (frontmatter, body, path) triples."""
    prose_dir = _prose_dir(root)
    assert prose_dir.exists(), (
        f"expected {prose_dir} to exist after `axial vault write` ran, but it does not"
    )
    notes = []
    for path in prose_dir.iterdir():
        if not path.is_file():
            continue
        frontmatter, body = _split_frontmatter(path.read_text(encoding="utf-8"), path)
        notes.append((frontmatter, body, path))
    assert notes, f"expected at least one prose note under {prose_dir}, found none"
    return notes


def test_chunk_pass_invalid_python_style_escape_is_repaired_end_to_end(isolated_vault_root):
    """RED case (issue #100 core acceptance criterion): a chunk-pass response
    containing the literal invalid `\\'` escape observed live must not abort
    the run -- `axial vault write` exits 0 and the written chunk text carries
    the un-escaped word, never the broken backslash-apostrophe form."""
    root = isolated_vault_root
    _arrange_stored_envelope(root)

    result = _run_vault_write(
        "stub",
        str(THESIS_PAPER_PDF),
        cwd=root,
        extra_env={STUB_CHUNK_RESPONSE_ENV_VAR: RAW_RESPONSE_INVALID_ESCAPE},
    )
    _assert_not_argparse_fallback(result, "vault write")
    assert result.returncode == 0, (
        f"expected exit code 0 for `axial vault write` even when the "
        f"chunk-pass response contains an invalid Python-style `\\'` escape "
        f"(issue #100: this must be repaired before json.loads, not treated "
        f"as a fatal parse failure), got {result.returncode}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    notes = _all_prose_notes(root)

    repaired_seen = False
    for frontmatter, body, path in notes:
        chunk_text = frontmatter.get("chunk_text", "")
        assert _STILL_BROKEN_FORM not in chunk_text, (
            f"expected {path}'s frontmatter 'chunk_text' to have the "
            f"invalid backslash-apostrophe escape REPAIRED (backslash "
            f"dropped), but found the still-broken form {_STILL_BROKEN_FORM!r} "
            f"verbatim in {chunk_text!r} -- the repair did not fire"
        )
        assert _STILL_BROKEN_FORM not in body, (
            f"expected {path}'s body to have the invalid backslash-apostrophe "
            f"escape REPAIRED, but found {_STILL_BROKEN_FORM!r} verbatim in "
            f"the body (truncated): {body[:500]!r}"
        )
        if EXPECTED_REPAIRED_CHUNK_TEXT in chunk_text:
            repaired_seen = True
            assert EXPECTED_REPAIRED_CHUNK_TEXT in body, (
                f"expected {path}'s body to contain the repaired chunk text "
                f"{EXPECTED_REPAIRED_CHUNK_TEXT!r} (frontmatter 'chunk_text' "
                f"already carries it), but the body does not; body "
                f"(truncated): {body[:500]!r}"
            )

    assert repaired_seen, (
        f"expected at least one written prose note's chunk_text to equal "
        f"the repaired text {EXPECTED_REPAIRED_CHUNK_TEXT!r} (containing "
        f'the un-escaped word "ra\'is"), got none among: '
        f"{[fm.get('chunk_text') for fm, _, _ in notes]!r}"
    )


def test_chunk_pass_valid_json_with_legal_escapes_round_trips_byte_identically(
    isolated_vault_root,
):
    """No-op guard: a chunk-pass response using only LEGAL JSON escapes
    (`\\"`, `\\\\`, `\\n`) plus a literal non-ASCII character must round-trip
    through the repair completely unchanged -- proving the repair is a
    true no-op on already-valid JSON, never mangling a legal escape or a
    literal character."""
    root = isolated_vault_root
    _arrange_stored_envelope(root)

    result = _run_vault_write(
        "stub",
        str(THESIS_PAPER_PDF),
        cwd=root,
        extra_env={STUB_CHUNK_RESPONSE_ENV_VAR: RAW_RESPONSE_LEGAL_ESCAPES},
    )
    _assert_not_argparse_fallback(result, "vault write")
    assert result.returncode == 0, (
        f"expected exit code 0 for `axial vault write` on an already-valid "
        f"chunk-pass response using only legal JSON escapes, got "
        f"{result.returncode}\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    notes = _all_prose_notes(root)

    exact_match_seen = False
    for frontmatter, body, path in notes:
        chunk_text = frontmatter.get("chunk_text")
        if chunk_text == LEGAL_CHUNK_TEXT:
            exact_match_seen = True
            assert LEGAL_CHUNK_TEXT in body, (
                f"expected {path}'s body to contain the exact legal-escape "
                f"chunk text {LEGAL_CHUNK_TEXT!r} verbatim (quote, "
                f"backslash, newline, and 'e-acute' all preserved), but it "
                f"does not; body (truncated): {body[:500]!r}"
            )
        elif chunk_text is not None:
            # Any note whose chunk_text diverges from the exact input proves
            # the repair (or something upstream) mangled already-valid JSON
            # content -- a hard failure of the no-op guarantee.
            assert chunk_text == LEGAL_CHUNK_TEXT, (
                f"expected {path}'s frontmatter 'chunk_text' to equal the "
                f"legal-escape input {LEGAL_CHUNK_TEXT!r} byte-for-byte "
                f"(already-valid JSON must round-trip unchanged -- issue "
                f"#100's no-op guarantee), got {chunk_text!r}"
            )

    assert exact_match_seen, (
        f"expected at least one written prose note's chunk_text to equal "
        f"the legal-escape input {LEGAL_CHUNK_TEXT!r} exactly, got none "
        f"among: {[fm.get('chunk_text') for fm, _, _ in notes]!r}"
    )


def test_chunk_pass_json_broken_beyond_escape_repair_still_fails_with_model_json_error(
    isolated_vault_root,
):
    """Still-fatal guard: a chunk-pass response that is truncated mid-object
    (in addition to carrying an invalid escape) can never be rescued by
    escape repair alone. `axial vault write` must still fail loudly after
    `complete_json`'s bounded re-asks: non-zero exit, a ModelJsonError-
    derived message on stderr -- proving the repair never short-circuits or
    swallows a genuine parse failure."""
    root = isolated_vault_root
    _arrange_stored_envelope(root)

    result = _run_vault_write(
        "stub",
        str(THESIS_PAPER_PDF),
        cwd=root,
        extra_env={STUB_CHUNK_RESPONSE_ENV_VAR: RAW_RESPONSE_BROKEN_BEYOND_REPAIR},
    )
    _assert_not_argparse_fallback(result, "vault write")

    assert result.returncode != 0, (
        f"expected a non-zero exit code for `axial vault write` when the "
        f"chunk-pass response is truncated mid-object (unparseable even "
        f"after escape repair), got exit code 0 -- the repair must never "
        f"paper over a genuinely malformed response\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    assert "model response was not valid JSON" in result.stderr, (
        f"expected `axial vault write`'s stderr to carry the "
        f"ModelJsonError-derived 'model response was not valid JSON' "
        f"message (src/axial/chunk.py's parse_response/run_chunk wrapping, "
        f"propagated through axial.tag.ChunkingFailedError and "
        f"axial.vault.TaggingFailedError to the CLI's 'error: ...' line), "
        f"got stderr: {result.stderr!r}"
    )

    assert not _prose_dir(root).exists() or not list(_prose_dir(root).iterdir()), (
        f"expected no prose notes to be written when the chunk pass fails "
        f"outright (the failure happens before any note-write step), but "
        f"found files under {_prose_dir(root)}: "
        f"{sorted(_prose_dir(root).iterdir()) if _prose_dir(root).exists() else []}"
    )
