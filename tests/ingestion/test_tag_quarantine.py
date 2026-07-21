"""Outer acceptance test for issue #120, quarantine slice (checkpoint already
shipped via #81; cleanup-on-success dropped by founder decision -- this test
covers quarantine ONLY).

Locked behavioral contract (DEC-1) -- do not edit without founder-adjudicated
authorization. REVISED per a founder ruling: `out_of_vocab` (an out-of-
vocabulary tag value persisting after the #102 correction re-ask,
`TagNotInSchemaError`) is DESCOPED from quarantine -- it remains a hard
error per P0-6 (#96/#102): a schema-coverage signal that must halt the
source, not be silently skipped. Quarantine now covers exactly two classes:
`content_filter` (`ContentRefusedError`) and `malformed_json`
(`ModelJsonError` persisting after `complete_json`'s bounded retries).

Today, one content-caused failure on any chunk in the tag pass aborts the
WHOLE source (mann-v4 died at tag ~858/1010 to a single refused chunk,
losing 5.5h -- 69% of the 2026-07 run's hours went to failed attempts for
this class of reason, see docs/postmortem/gold-run-2026-07/README.md). This
test locks the fix: a chunk whose failure is CONTENT-CAUSED (content_filter
or malformed_json) is skipped, logged, and recorded, and the source
CONTINUES; a TRANSIENT failure keeps today's retry/backoff path completely
unchanged (never quarantined); an out-of-vocabulary tag value (P0-6) keeps
its existing hard-error contract unchanged too (never quarantined).

Scenario 1 -- content-caused failure -> quarantined, source completes
-----------------------------------------------------------------------
Given  a source with several chunks, one of which (neither first nor last)
       is "poisoned": every LLM call `axial.tag.run_tag` makes for it fails
       with a content-caused failure class -- `ContentRefusedError`
       (content_filter surviving the #116 fallback reroute), or malformed
       JSON that persists after `complete_json`'s bounded retry budget
       (`ModelJsonError`)
When   `run_tag` is called once, with `tags_dir` supplied (checkpoint
       active)
Then   `run_tag` COMPLETES (does not raise) -- the source is not aborted
And    the poisoned chunk produces NO tagged record in the returned result
And    a stderr line `tag: quarantining chunk <chunk_id>: <reason>` is
       logged, `<reason>` being exactly one of `content_filter`,
       `malformed_json`
And    the tag checkpoint (`<tags_dir>/<source_id>.jsonl`) carries a
       `{"chunk_id": ..., "quarantine_reason": ...}` record for the
       poisoned chunk
And    every OTHER chunk -- both before and after the poisoned one in
       chunking order -- is tagged normally (present in the returned
       result, checkpointed as an ordinary, non-quarantine record)
And    `run_tag`'s result surfaces a `quarantine_count` of 1

Scenario 2 -- transient failure -> NOT quarantined, propagates unchanged
-----------------------------------------------------------------------
Given  the same shape of source, with one chunk failing with a TRANSIENT,
       non-content class (a plain `axial.llm.OpenRouterError` -- transport/
       rate/truncation, never a moderation refusal)
When   `run_tag` is called once
Then   the failure propagates exactly as today (`axial.tag.LLMFailedError`,
       run_tag's existing `except (LLMError, httpx.HTTPError)` wrapping) --
       the source is NOT completed and the chunk is NOT silently skipped
And    no `tag: quarantining chunk ...` log line is emitted for it
And    no quarantine checkpoint record is written for it
This is the critical guard: quarantine must never swallow a transient fault.

Scenario 3 -- resume skips an already-quarantined chunk
-----------------------------------------------------------------------
Given  a tag checkpoint that ALREADY carries a quarantine record (as
       scenario 1 would have written on an earlier run) for one chunk
When   `run_tag` is called again for the same source, same `tags_dir`, with
       a fresh LLM client
Then   NO LLM call is made for that chunk (it is skipped, not re-attempted)
And    a stderr line `tag: skipping quarantined chunk <chunk_id> (reason:
       <reason>)` is logged
And    that chunk is absent from the returned tagged records; every other
       chunk is processed (and tagged) normally

See GitHub issue #120 for the source of truth, and the founder ruling above
for the `out_of_vocab` descope. `axial.tag.run_tag`'s per-chunk loop
(~line 1094, the loop body starting just after the #132 non-prose guard)
already quarantines `ContentRefusedError` and a persisting `ModelJsonError`
(shipped implementation, this commit); a persisting `TagNotInSchemaError`
(out-of-vocab) is intentionally left OUT of scope here and continues to
propagate straight out of `run_tag` as the P0-6 hard error, unchanged --
that is covered by the existing P0-6 tests (test_tag_axis_prefix.py /
test_tag_vocab_reask.py), not this file.

Seam decision 1 -- bypassing docling/network via a monkeypatched upstream
pass, exactly mirroring tests/test_xref_checkpoint.py's Seam decision 1
-----------------------------------------------------------------------
`run_tag` normally builds its chunk records via its own internal call to
`axial.chunk.read_chunks` (imported directly into `axial.tag`'s module
namespace: `from axial.chunk import ChunkError, read_chunks`). This test
never drives a real PDF through docling; it monkeypatches
`axial.tag.read_chunks` in place with a fake returning a fixed, synthetic
chunk-record set regardless of what `run_tag` passes it. `run_tag`'s own
per-chunk loop -- the actual subject of this issue -- is never bypassed;
only its upstream chunk data source is.

Migration note (issue #154, slice 04): `axial.chunk.run_chunk` (the
retired LLM-echo chunker) is deleted; `axial.tag.run_tag` now reads chunk
records via `axial.chunk.read_chunks` instead. This test repoints its
monkeypatch from `tag_module.run_chunk` to `tag_module.read_chunks`
(signature `read_chunks(source_id, **kwargs)`) accordingly -- every
assertion below is unchanged.

Seam decision 2 -- identifying "which chunk is this LLM call for" through
the chunk's own text embedded in the prompt, exactly mirroring
tests/test_xref_checkpoint.py's Seam decision 2
-----------------------------------------------------------------------
`compose_multi_axis_tag_prompt` embeds the chunk's own `text` verbatim into
the prompt body. Each synthetic chunk here is given distinct, greppable body
text, and the fake LLM client below identifies which chunk a given prompt is
for by scanning it for exactly one of these markers -- so it can fail a
SPECIFIC chunk (and only that chunk) on demand, on every call including the
#102 correction re-ask (whose prompt is the same base prompt plus an
appended notice, so the marker still matches).

Seam decision 3 -- the real domain schema/codebook, not a synthetic fixture
-----------------------------------------------------------------------
`run_tag` calls `axial.schema.load_schema` / `axial.codebook.load_codebook`
on a `domain_dir` -- this test points them at the REAL, committed
`config/domains/syria` (exactly as tests/test_tag.py already does), so every
tag value used here is drawn from that schema's real controlled vocabulary
(`role_in_argument`, `empirical_scope`, `field`, `claim_type`,
`theory_school`) rather than inventing a parallel fixture domain that could
drift from the real one.

Seam decision 4 -- each content-caused failure class is injected at the
layer it actually occurs
-----------------------------------------------------------------------
`content_filter` and `transient` are injected as real `axial.llm.LLMError`
subclasses raised directly from the fake client's `.complete()` -- mirroring
`tests/test_xref_checkpoint.py`'s `_StallInjectedError` pattern exactly (a
typed `LLMError` subclass, never a bare `Exception`), since that is
precisely how a real `OpenRouterClient` surfaces both a surviving
content_filter refusal (`ContentRefusedError`, after its own internal #116
fallback reroute already failed) and a transient transport failure
(`OpenRouterError`) to any caller. `malformed_json`, by contrast, is a
content-shaped failure -- non-JSON text -- so it is injected as the RAW
COMPLETION TEXT the fake client returns (`run_tag`'s own parsing is what
turns that text into `ModelJsonError` today), never as a raised exception,
since a real model failing this way does not raise from the transport layer
at all.

Test hygiene: every path this test touches (`tags_dir`, the synthetic
source file) lives under pytest's own `tmp_path`, outside this repo
entirely -- nothing here reads or writes any real `data/` directory, and no
real LLM/network/docling call is ever made (the fake client below is the
only "LLM" involved). The real `config/domains/syria` schema/codebook files
ARE read (read-only), exactly as tests/test_tag.py already does.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import axial.tag as tag_module
from axial.envelope import compute_source_id
from axial.llm import TAG_PASS_NAME, ContentRefusedError, OpenRouterError

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DOMAIN_DIR = REPO_ROOT / "config" / "domains" / "syria"

CHUNK_COUNT = 4
# Neither first nor last, so a single test proves BOTH "before" and "after"
# chunks are tagged normally around the poisoned one.
POISONED_INDEX = 1


def _chunk_text(index: int) -> str:
    """Distinct, greppable body text for synthetic chunk `index` -- no
    chunk's text is ever a substring of another's (zero-padded index), so
    the fake client below can unambiguously identify which chunk a given
    prompt is for (see module docstring, seam decision 2)."""
    return (
        f"This is the body text of synthetic tag-quarantine test chunk "
        f"number {index:03d} of {CHUNK_COUNT}, discussing state formation "
        f"and legitimacy in a way that is ordinary, unremarkable prose."
    )


CHUNK_TEXTS = [_chunk_text(i) for i in range(CHUNK_COUNT)]


def _chunk_records() -> list[dict[str, str]]:
    return [
        {
            "chunk_id": f"tag-quarantine-chunk-{i:03d}",
            "section": f"Section {i}",
            "text": CHUNK_TEXTS[i],
        }
        for i in range(CHUNK_COUNT)
    ]


def _valid_tag_response_json() -> str:
    """A raw completion string, valid against the REAL syria schema for
    every axis `run_tag` tags (role_in_argument, empirical_scope, field,
    claim_type, theory_school) -- see config/domains/syria/schema.yaml."""
    payload = {
        "role_in_argument": "role:setup",
        "empirical_scope": "scope:general",
        "field": {"primary": "state", "secondary": []},
        "claim_type": {"primary": "state-formation", "secondary": None},
        "theory_school": {"primary": "colonial-postcolonial", "secondary": None},
    }
    return json.dumps(payload)


_MALFORMED_JSON_RESPONSE = "this is not JSON at all, sorry {"


class _QuarantineTestClient:
    """A fake `LLMClient` (duck-typed: only `.complete(prompt, pass_name)`
    is required) that answers every chunk validly EXCEPT one designated
    `poison_text`, for which it fails on every call according to
    `failure_mode` (see module docstring, seam decision 4):

      - "content_filter": raises `ContentRefusedError` (an `LLMError`
        subclass) on every call for the poisoned chunk -- the fallback
        reroute a real client would attempt internally is out of scope
        here; this fake IS the point at which that reroute has already
        failed (mirroring `ContentRefusedError`'s own docstring).
      - "transient": raises `OpenRouterError` (a plain, non-content
        `LLMError`) on every call for the poisoned chunk.
      - "malformed_json": returns non-JSON text on every call, so
        `complete_json`'s bounded retry budget is exhausted.

    Counts calls per synthetic chunk, identified by which chunk's own text
    (see `CHUNK_TEXTS`) appears in the prompt it is given."""

    def __init__(self, poison_text: str | None, failure_mode: str | None):
        self.poison_text = poison_text
        self.failure_mode = failure_mode
        self.calls_by_chunk_text: dict[str, int] = {}

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        assert pass_name == TAG_PASS_NAME, (
            f"expected every call this fake client receives from run_tag's "
            f"per-chunk loop to use pass_name={TAG_PASS_NAME!r}, got {pass_name!r}"
        )
        matched = [text for text in CHUNK_TEXTS if text in prompt]
        assert len(matched) == 1, (
            f"expected the prompt to contain exactly one known synthetic "
            f"chunk's text, got {len(matched)} match(es); prompt: {prompt!r}"
        )
        chunk_text = matched[0]
        self.calls_by_chunk_text[chunk_text] = self.calls_by_chunk_text.get(chunk_text, 0) + 1

        if self.poison_text is not None and chunk_text == self.poison_text:
            if self.failure_mode == "content_filter":
                raise ContentRefusedError(
                    "simulated finish_reason='content_filter' refusal surviving "
                    "the #116 fallback reroute (issue #120 quarantine test)"
                )
            if self.failure_mode == "transient":
                raise OpenRouterError(
                    "simulated transient transport error, e.g. rate limit "
                    "(issue #120 quarantine test) -- NOT content-caused"
                )
            if self.failure_mode == "malformed_json":
                return _MALFORMED_JSON_RESPONSE
            raise AssertionError(f"unknown failure_mode {self.failure_mode!r}")

        return _valid_tag_response_json()


def _read_checkpoint_records(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        records.append(json.loads(line))
    return records


def _make_source(tmp_path: Path, name: str) -> Path:
    source_path = tmp_path / name
    source_path.write_text(
        f"synthetic source file for issue #120 quarantine test ({name})",
        encoding="utf-8",
    )
    return source_path


# --------------------------------------------------------------------------
# Scenario 1: content-caused failure -> quarantined, source completes.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "failure_mode, expected_reason, expected_calls_for_poisoned_chunk",
    [
        ("content_filter", "content_filter", 1),
        ("malformed_json", "malformed_json", 3),  # complete_json's default retry budget
    ],
)
def test_content_caused_failure_is_quarantined_and_source_completes(
    tmp_path, monkeypatch, capsys, failure_mode, expected_reason, expected_calls_for_poisoned_chunk
):
    chunk_records = _chunk_records()
    poisoned_chunk = chunk_records[POISONED_INDEX]
    poisoned_text = poisoned_chunk["text"]
    survivors = [c for i, c in enumerate(chunk_records) if i != POISONED_INDEX]

    monkeypatch.setattr(tag_module, "read_chunks", lambda source_id, **kwargs: chunk_records)

    source_path = _make_source(tmp_path, f"poisoned_source_{failure_mode}.txt")
    source_id = compute_source_id(source_path)
    tags_dir = tmp_path / "data" / "tags"
    checkpoint_path = tag_module.tags_checkpoint_path(source_id, tags_dir)

    client = _QuarantineTestClient(poison_text=poisoned_text, failure_mode=failure_mode)

    # --- The core acceptance: run_tag must COMPLETE, not raise. ---
    try:
        result = tag_module.run_tag(
            source_path,
            client=client,
            domain_dir=DOMAIN_DIR,
            tags_dir=tags_dir,
            votes=1,
        )
    except Exception as exc:  # noqa: BLE001 -- the acceptance itself is "no exception"
        raise AssertionError(
            f"expected run_tag to COMPLETE the source with the poisoned chunk "
            f"quarantined (failure_mode={failure_mode!r}), but it raised "
            f"{type(exc).__name__}: {exc} -- as of this commit, run_tag has no "
            f"quarantine handling at all, so a content-caused failure still "
            f"aborts the whole source (issue #120)."
        ) from exc

    records = list(result)
    tagged_ids = [r["chunk_id"] for r in records]

    assert poisoned_chunk["chunk_id"] not in tagged_ids, (
        f"expected the quarantined chunk {poisoned_chunk['chunk_id']!r} to "
        f"produce NO tagged record, but it appears in the returned records: "
        f"{tagged_ids}"
    )
    assert tagged_ids == [c["chunk_id"] for c in survivors], (
        f"expected every chunk OTHER than the quarantined one -- both before "
        f"and after it -- to be tagged normally, in order, got {tagged_ids} "
        f"vs expected {[c['chunk_id'] for c in survivors]}"
    )

    # --- the model was actually attempted (and, for malformed_json, retried
    # through its full existing bounded budget) before quarantining --
    # quarantine must never short-circuit today's retry/re-ask behavior. ---
    assert client.calls_by_chunk_text.get(poisoned_text, 0) == expected_calls_for_poisoned_chunk, (
        f"expected the poisoned chunk to receive exactly "
        f"{expected_calls_for_poisoned_chunk} LLM call(s) for failure_mode="
        f"{failure_mode!r} (today's existing retry/re-ask budget must still "
        f"run to exhaustion before quarantining), got "
        f"{client.calls_by_chunk_text.get(poisoned_text, 0)}"
    )

    # --- stderr quarantine log. ---
    captured = capsys.readouterr()
    expected_log = f"tag: quarantining chunk {poisoned_chunk['chunk_id']}: {expected_reason}"
    assert expected_log in captured.err, (
        f"expected stderr to contain {expected_log!r} (issue #120's required "
        f"quarantine log line), got stderr: {captured.err!r}"
    )

    # --- checkpoint quarantine record. ---
    assert checkpoint_path.exists(), (
        f"expected a tag checkpoint at {checkpoint_path} after a quarantined "
        f"chunk, got no file at all"
    )
    checkpoint_records = _read_checkpoint_records(checkpoint_path)
    quarantine_lines = [
        r for r in checkpoint_records if r.get("chunk_id") == poisoned_chunk["chunk_id"]
    ]
    assert len(quarantine_lines) == 1, (
        f"expected exactly one checkpoint line for the quarantined chunk "
        f"{poisoned_chunk['chunk_id']!r}, got {len(quarantine_lines)}: "
        f"{quarantine_lines}"
    )
    assert quarantine_lines[0].get("quarantine_reason") == expected_reason, (
        f"expected the checkpoint's quarantine record to carry "
        f"'quarantine_reason': {expected_reason!r}, got {quarantine_lines[0]!r}"
    )

    # --- every other chunk is checkpointed as an ORDINARY (non-quarantine)
    # tagged record. ---
    for chunk in survivors:
        matches = [r for r in checkpoint_records if r.get("chunk_id") == chunk["chunk_id"]]
        assert len(matches) == 1, (
            f"expected exactly one checkpoint line for chunk "
            f"{chunk['chunk_id']!r}, got {len(matches)}"
        )
        assert "quarantine_reason" not in matches[0], (
            f"expected chunk {chunk['chunk_id']!r} (tagged normally, not "
            f"quarantined) to carry NO 'quarantine_reason' in its checkpoint "
            f"record, got {matches[0]!r}"
        )

    # --- run_tag surfaces a quarantine_count. ---
    quarantine_count = getattr(result, "quarantine_count", None)
    assert quarantine_count == 1, (
        f"expected run_tag's result to surface quarantine_count == 1 (issue "
        f"#120: 'run_tag surfaces a quarantine_count'), got {quarantine_count!r} "
        f"-- as of this commit, run_tag's return value has no such attribute "
        f"at all"
    )


# --------------------------------------------------------------------------
# Scenario 2: transient failure -> NOT quarantined, propagates unchanged.
# --------------------------------------------------------------------------


def test_transient_failure_is_not_quarantined_and_still_propagates(tmp_path, monkeypatch, capsys):
    """The critical guard: a non-content, transient LLM failure must keep
    today's exact contract (propagate/retry as before) -- quarantine must
    never swallow it."""
    chunk_records = _chunk_records()
    poisoned_chunk = chunk_records[POISONED_INDEX]
    poisoned_text = poisoned_chunk["text"]

    monkeypatch.setattr(tag_module, "read_chunks", lambda source_id, **kwargs: chunk_records)

    source_path = _make_source(tmp_path, "transient_source.txt")
    source_id = compute_source_id(source_path)
    tags_dir = tmp_path / "data" / "tags"
    checkpoint_path = tag_module.tags_checkpoint_path(source_id, tags_dir)

    client = _QuarantineTestClient(poison_text=poisoned_text, failure_mode="transient")

    with pytest.raises(Exception) as excinfo:
        tag_module.run_tag(
            source_path,
            client=client,
            domain_dir=DOMAIN_DIR,
            tags_dir=tags_dir,
            votes=1,
        )

    assert isinstance(excinfo.value, tag_module.LLMFailedError), (
        f"expected a transient, non-content LLM failure to still raise "
        f"axial.tag.LLMFailedError exactly as today's contract (run_tag's "
        f"existing 'except (LLMError, httpx.HTTPError)' wrapping) -- a "
        f"transient failure must NEVER be quarantined, got "
        f"{type(excinfo.value).__name__}: {excinfo.value}"
    )

    captured = capsys.readouterr()
    assert f"tag: quarantining chunk {poisoned_chunk['chunk_id']}" not in captured.err, (
        f"a transient failure must NEVER be logged as a quarantine, got stderr: {captured.err!r}"
    )

    checkpoint_records = _read_checkpoint_records(checkpoint_path)
    for record in checkpoint_records:
        assert record.get("chunk_id") != poisoned_chunk["chunk_id"], (
            f"a transient failure must NEVER be checkpointed as a quarantine "
            f"record, got {record!r} at {checkpoint_path}"
        )


# --------------------------------------------------------------------------
# Scenario 3: resume skips an already-quarantined chunk.
# --------------------------------------------------------------------------


def test_resume_skips_already_quarantined_chunk(tmp_path, monkeypatch, capsys):
    chunk_records = _chunk_records()
    quarantined_chunk = chunk_records[POISONED_INDEX]
    quarantined_text = quarantined_chunk["text"]
    others = [c for i, c in enumerate(chunk_records) if i != POISONED_INDEX]

    monkeypatch.setattr(tag_module, "read_chunks", lambda source_id, **kwargs: chunk_records)

    source_path = _make_source(tmp_path, "resume_source.txt")
    source_id = compute_source_id(source_path)
    tags_dir = tmp_path / "data" / "tags"
    checkpoint_path = tag_module.tags_checkpoint_path(source_id, tags_dir)

    # Pre-seed a checkpoint carrying a quarantine record for one chunk, as an
    # earlier run (scenario 1) would have already written.
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    with checkpoint_path.open("w", encoding="utf-8") as fh:
        fh.write(
            json.dumps(
                {"chunk_id": quarantined_chunk["chunk_id"], "quarantine_reason": "content_filter"}
            )
            + "\n"
        )

    # A fresh client with NO failure armed at all: if run_tag ever calls it
    # for the already-quarantined chunk, that is itself a contract violation
    # (it should never be re-attempted), never mind what it would answer.
    client = _QuarantineTestClient(poison_text=None, failure_mode=None)

    result = tag_module.run_tag(
        source_path,
        client=client,
        domain_dir=DOMAIN_DIR,
        tags_dir=tags_dir,
        votes=1,
    )

    assert quarantined_text not in client.calls_by_chunk_text, (
        f"expected ZERO LLM calls for the already-quarantined chunk "
        f"{quarantined_chunk['chunk_id']!r} on resume (issue #120: 'a chunk "
        f"whose checkpoint record carries quarantine_reason is skipped, not "
        f"re-attempted'), got {client.calls_by_chunk_text.get(quarantined_text, 0)}"
    )

    for chunk in others:
        assert client.calls_by_chunk_text.get(chunk["text"]) == 1, (
            f"expected chunk {chunk['chunk_id']!r} (not previously "
            f"quarantined or checkpointed) to be tagged normally on this "
            f"resume run, got "
            f"{client.calls_by_chunk_text.get(chunk['text'], 0)} call(s)"
        )

    captured = capsys.readouterr()
    expected_log = (
        f"tag: skipping quarantined chunk {quarantined_chunk['chunk_id']} (reason: content_filter)"
    )
    assert expected_log in captured.err, (
        f"expected stderr to contain {expected_log!r} (issue #120's required "
        f"resume-skip log line), got stderr: {captured.err!r}"
    )

    records = list(result)
    tagged_ids = [r["chunk_id"] for r in records]
    assert quarantined_chunk["chunk_id"] not in tagged_ids, (
        f"expected the already-quarantined chunk "
        f"{quarantined_chunk['chunk_id']!r} to be ABSENT from run_tag's "
        f"returned tagged records (it must never be treated as an ordinary "
        f"cached tagged record), got it present in: {tagged_ids}"
    )
    assert tagged_ids == [c["chunk_id"] for c in others], (
        f"expected every non-quarantined chunk to be tagged and returned, in "
        f"order, got {tagged_ids} vs expected {[c['chunk_id'] for c in others]}"
    )
