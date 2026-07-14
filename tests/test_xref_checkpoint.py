"""Outer acceptance test for issue #110 (xref per-chunk checkpoint/resume).

Locked behavioral contract (DEC-1) -- do not edit once committed red.

Given  a source with many chunks (this test uses 15 -- enough to prove the
       property without needing a literal 822), and a per-chunk-loop stall
       forced on the LAST chunk (i.e. every earlier chunk was already
       processed when the stall hits)
When   `run_xref` is called once with `xref_dir=<some dir>` and fails
       partway through
Then   `data/xref/<source_id>.jsonl` exists and carries exactly one JSON
       line per chunk processed BEFORE the failure (issue #110's checkpoint,
       mirroring `axial.tag`/`axial.artifacts`'s existing per-record
       checkpoint pattern -- append+flush as each record lands)
And    a second call to `run_xref`, with a FRESH LLM client but the SAME
       `xref_dir`, makes ZERO LLM calls for the chunks already checkpointed
       by the first call, and only (re)attempts the previously-failed chunk
       -- no LLM call is remade for an already-checkpointed chunk (issue
       #110's whole point: "every re-run restarts from chunk 0 and re-burns
       all prior LLM calls" is exactly the bug this closes)
And    after that second, resumed call, the checkpoint carries all 15
       chunk_ids, with no duplicate lines

See GitHub issue #110 ("xref: per-chunk checkpoint") for the source of
truth: `run_xref`'s per-chunk loop (`src/axial/xref.py`, ~lines 226-237, as
of this commit) has NO checkpoint at all today -- every re-run restarts from
chunk 0. The fix under this contract is an OPT-IN `xref_dir: Path | None`
parameter on `run_xref` (opt-in, mirroring `axial.tag.run_tag`'s `tags_dir`
and `axial.artifacts.run_artifacts`'s `artifacts_dir` -- standalone `axial
xref` passes none and is unaffected): when supplied, each processed chunk is
appended as one JSON line to `<xref_dir>/<source_id>.jsonl` as it is
produced, and on a later call for the same source, a chunk whose `chunk_id`
already appears there is skipped -- reused without ever calling the LLM
again for it.

As of this commit `run_xref` has no `xref_dir` parameter at all, so this
test is expected to fail red for exactly that reason: calling it with
`xref_dir=...` either raises `TypeError` immediately (no such parameter) or,
once merely accepted-and-ignored, produces zero checkpoint output and zero
resume-skip behavior -- never an import error, never a fixture/collection
failure.
Seam decision 1 -- bypassing docling/network entirely via monkeypatched
upstream passes, not real chunking/artifact-classification
-----------------------------------------------------------------------
`run_xref` normally builds its chunk/artifact records via its own internal
calls to `axial.chunk.read_chunks` / `axial.artifacts.run_artifacts` (both
imported directly into `axial.xref`'s module namespace: `from axial.chunk
import ChunkError, read_chunks` / `from axial.artifacts import ... ,
run_artifacts`). This test never drives a real PDF through docling (too slow,
and out of bounds for an isolated single-file test run per this issue's
constraints); instead it monkeypatches `axial.xref.read_chunks` and
`axial.xref.run_artifacts` directly, in place, with fakes that return a
fixed, synthetic 15-chunk / zero-artifact record set regardless of what
`run_xref` passes them. Because Python looks up `read_chunks`/`run_artifacts`
as plain module-global names at call time, monkeypatching the module
attribute redirects every call `run_xref` makes internally -- proven prior
art for this exact technique lives in
tests/test_llm_wallclock_timeout.py's `monkeypatch.setattr(llm_module,
"_sleep", ...)`. `run_xref`'s own per-chunk LOOP -- the actual subject of
issue #110 -- is never bypassed; only its two upstream data sources are.

Migration note (issue #154, slice 04): `axial.chunk.run_chunk` (the
retired LLM-echo chunker) is deleted; `axial.xref.run_xref` now reads
chunk records via `axial.chunk.read_chunks` instead. This test repoints
its monkeypatch from `xref_module.run_chunk` to `xref_module.read_chunks`
(signature `read_chunks(source_id, **kwargs)`) accordingly -- every
assertion below is unchanged.

Seam decision 2 -- identifying "which chunk is this LLM call for" through an
already-real observable: the chunk's own text embedded in the prompt
-----------------------------------------------------------------------
`compose_xref_prompt(chunk_text, artifact_ids)` (src/axial/xref.py) embeds
the chunk's own `text` verbatim into the prompt body -- the ONLY way
`run_xref`'s loop identifies which chunk a given LLM call is for, since
`pass_name` alone does not vary per-chunk. Each of the 15 synthetic chunks
in this test is given distinct, greppable body text
("...synthetic test chunk number NNN...", zero-padded so no chunk's text is
a substring of a different chunk's text), and the fake LLM client counts/
fails calls by scanning the prompt for exactly one of these markers. This
never depends on any raw wire-format detail of the prompt template beyond
"the chunk's own text appears in the prompt it is given" -- an invariant
`compose_xref_prompt`'s own docstring already locks by construction.

Seam decision 3 -- the injected mid-pass failure is a real `axial.llm.LLMError`
subclass, not a bare `Exception`
-----------------------------------------------------------------------
Mirroring `axial.llm.StubInjectedTagFailureError` /
`StubInjectedArtifactFailureError`'s existing pattern for injected test
failures, the fake client raises a small `LLMError` subclass
(`_StallInjectedError`) from `.complete()` on the chosen chunk. This
propagates through `axial.model_json.complete_json` (which never catches a
transport-level `client.complete()` exception, per its own docstring) into
`run_xref`'s existing `except (LLMError, httpx.HTTPError) as exc: raise
LLMFailedError(exc)` -- i.e. the SAME typed-error path a real transient LLM
failure already takes today, never a new exception class this test invents
out of thin air. This test asserts through the outcome (checkpoint file
contents, call counts) rather than pinning the exact exception class
`run_xref` re-raises as, since that is an implementation, not behavioral,
detail.

Test hygiene: every path this test touches (`xref_dir`, the synthetic
source file) lives under pytest's own `tmp_path`, outside this repo
entirely -- nothing here reads or writes any real `data/` directory, and no
real LLM/network/docling call is ever made (the fake client above is the
only "LLM" involved).
"""

from __future__ import annotations

import json

import pytest

import axial.xref as xref_module
from axial.envelope import compute_source_id
from axial.llm import LLMError, XREF_PASS_NAME

CHUNK_COUNT = 15


def _chunk_text(index: int) -> str:
    """Distinct, greppable body text for synthetic chunk `index` -- no
    chunk's text is ever a substring of another's (zero-padded index), so
    the fake client below can unambiguously identify which chunk a given
    prompt is for (see module docstring, seam decision 2)."""
    return f"This is the body text of synthetic test chunk number {index:03d} of {CHUNK_COUNT}."


CHUNK_TEXTS = [_chunk_text(i) for i in range(CHUNK_COUNT)]


class _StallInjectedError(LLMError):
    """A typed `LLMError` subclass this test raises to simulate a mid-pass
    stall on one chosen chunk -- mirrors `axial.llm.StubInjectedTagFailureError`
    / `StubInjectedArtifactFailureError`'s own pattern of a dedicated
    `LLMError` subclass for injected test failures (see module docstring,
    seam decision 3)."""


class _CountingXrefClient:
    """A fake `LLMClient` (duck-typed: only `.complete(prompt, pass_name)`
    is required) that counts calls per synthetic chunk, identified by which
    chunk's own text (see `CHUNK_TEXTS`) appears in the prompt it is given
    (see module docstring, seam decision 2). Optionally raises
    `_StallInjectedError` on the one call whose prompt contains
    `fail_on_chunk_text`, simulating a mid-pass stall on that chunk."""

    def __init__(self, fail_on_chunk_text: str | None = None):
        self.fail_on_chunk_text = fail_on_chunk_text
        self.calls_by_chunk_text: dict[str, int] = {}

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        assert pass_name == XREF_PASS_NAME, (
            f"expected every call this fake client receives from run_xref's "
            f"per-chunk loop to use pass_name={XREF_PASS_NAME!r}, got {pass_name!r}"
        )
        matched = [text for text in CHUNK_TEXTS if text in prompt]
        assert len(matched) == 1, (
            f"expected the prompt to contain exactly one known synthetic "
            f"chunk's text, got {len(matched)} match(es); prompt: {prompt!r}"
        )
        chunk_text = matched[0]
        self.calls_by_chunk_text[chunk_text] = self.calls_by_chunk_text.get(chunk_text, 0) + 1
        if self.fail_on_chunk_text is not None and chunk_text == self.fail_on_chunk_text:
            raise _StallInjectedError(
                f"simulated mid-pass stall on chunk text {chunk_text!r} (issue #110 test)"
            )
        return json.dumps({"referenced_artifact_ids": []})

    @property
    def total_calls(self) -> int:
        return sum(self.calls_by_chunk_text.values())


def _read_checkpoint_chunk_ids(path) -> list[str]:
    if not path.exists():
        return []
    ids = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        record = json.loads(line)
        assert isinstance(record, dict) and isinstance(record.get("chunk_id"), str), (
            f"expected every checkpoint line in {path} to be a JSON object "
            f"carrying a string 'chunk_id' (issue #110, mirroring "
            f"axial.tag/axial.artifacts's existing checkpoint record shape), "
            f"got {record!r}"
        )
        ids.append(record["chunk_id"])
    return ids


def test_xref_checkpoints_each_chunk_and_resume_skips_llm_calls_for_completed_chunks(
    tmp_path, monkeypatch
):
    """Core contract (issue #110, acceptance #7): a stalled xref pass leaves
    every already-processed chunk durably checkpointed; a resumed call with
    a fresh LLM client makes ZERO calls for those chunks and only
    (re)attempts the one that failed."""
    chunk_records = [
        {"chunk_id": f"xref-ckpt-chunk-{i:03d}", "text": CHUNK_TEXTS[i]} for i in range(CHUNK_COUNT)
    ]
    all_chunk_ids = {record["chunk_id"] for record in chunk_records}

    def fake_read_chunks(source_id, **kwargs):
        return chunk_records

    def fake_run_artifacts(path, **kwargs):
        # No real artifacts needed to exercise per-chunk checkpointing --
        # the xref-detect loop runs once per chunk regardless of the known
        # artifact set's size.
        return []

    monkeypatch.setattr(xref_module, "read_chunks", fake_read_chunks)
    monkeypatch.setattr(xref_module, "run_artifacts", fake_run_artifacts)

    source_path = tmp_path / "many_chunks_source.txt"
    source_path.write_text(
        "synthetic multi-chunk source for issue #110's checkpoint test", encoding="utf-8"
    )
    source_id = compute_source_id(source_path)

    xref_dir = tmp_path / "data" / "xref"
    checkpoint_path = xref_dir / f"{source_id}.jsonl"

    last_chunk_text = CHUNK_TEXTS[-1]
    last_chunk_id = chunk_records[-1]["chunk_id"]
    expected_checkpointed_before_failure = {r["chunk_id"] for r in chunk_records[:-1]}

    # --- Run 1: process the source; force a raise on the LAST chunk, so
    # every earlier chunk was already processed (and must be checkpointed)
    # when the stall hits. ---
    client_1 = _CountingXrefClient(fail_on_chunk_text=last_chunk_text)

    with pytest.raises(Exception):
        xref_module.run_xref(
            source_path,
            client=client_1,
            xref_dir=xref_dir,
        )

    for record in chunk_records[:-1]:
        text = record["text"]
        assert client_1.calls_by_chunk_text.get(text) == 1, (
            f"expected chunk {record['chunk_id']!r} (processed before the "
            f"forced failure) to receive exactly one LLM call in run 1, got "
            f"{client_1.calls_by_chunk_text.get(text, 0)}. If this is 0, "
            f"run_xref never even reached its per-chunk loop -- most likely "
            f"because it does not yet accept an `xref_dir` parameter at all "
            f"(issue #110)."
        )
    assert client_1.calls_by_chunk_text.get(last_chunk_text) == 1, (
        "expected the forced-failure chunk to be attempted exactly once in run 1"
    )
    assert client_1.total_calls == CHUNK_COUNT, (
        f"expected run 1 to attempt all {CHUNK_COUNT} chunk(s) (succeeding "
        f"on the first {CHUNK_COUNT - 1}, failing on the last), got "
        f"{client_1.total_calls} total call(s)"
    )

    # --- The core checkpoint contract: every chunk processed before the
    # failure must be durably persisted, one JSON line each, at
    # <xref_dir>/<source_id>.jsonl (issue #110, mirroring axial.tag's/
    # axial.artifacts's existing "append+flush as each record lands"
    # checkpoint). ---
    assert checkpoint_path.exists(), (
        f"expected {checkpoint_path} to exist after a partial xref-pass "
        f"failure (issue #110: 'append one JSON line per processed chunk, "
        f"as it is produced') -- got no file at all. As of this commit, "
        f"run_xref has no per-chunk checkpoint mechanism at all, which is "
        f"precisely the bug issue #110 fixes."
    )
    checkpointed_ids_after_failure = set(_read_checkpoint_chunk_ids(checkpoint_path))
    assert checkpointed_ids_after_failure == expected_checkpointed_before_failure, (
        f"expected {checkpoint_path} to carry exactly the "
        f"{CHUNK_COUNT - 1} chunk_id(s) processed before the forced "
        f"failure on the last chunk, got "
        f"{sorted(checkpointed_ids_after_failure)} vs expected "
        f"{sorted(expected_checkpointed_before_failure)}"
    )
    assert len(_read_checkpoint_chunk_ids(checkpoint_path)) == CHUNK_COUNT - 1, (
        f"expected exactly {CHUNK_COUNT - 1} checkpoint line(s) after run "
        f"1's partial failure (no duplicate/extra lines), got "
        f"{len(_read_checkpoint_chunk_ids(checkpoint_path))}"
    )
    assert last_chunk_id not in checkpointed_ids_after_failure, (
        f"the chunk that failed ({last_chunk_id!r}) must NOT be "
        f"checkpointed -- only successfully processed chunks are persisted"
    )

    # --- Run 2: a FRESH LLM client, the SAME xref_dir. Already-checkpointed
    # chunks must make ZERO fresh LLM calls; only the previously-failed
    # chunk should be (re)attempted -- issue #110's whole point. ---
    client_2 = _CountingXrefClient(fail_on_chunk_text=None)

    result = xref_module.run_xref(
        source_path,
        client=client_2,
        xref_dir=xref_dir,
    )

    for record in chunk_records[:-1]:
        text = record["text"]
        assert text not in client_2.calls_by_chunk_text, (
            f"expected chunk {record['chunk_id']!r} (already checkpointed "
            f"by run 1) to make ZERO LLM calls on the resumed run 2 (issue "
            f"#110: 'no LLM call is remade for them'), but a FRESH client "
            f"was called {client_2.calls_by_chunk_text.get(text, 0)} "
            f"time(s) for it -- run_xref is not skipping already-"
            f"checkpointed chunks on resume."
        )
    assert client_2.calls_by_chunk_text.get(last_chunk_text) == 1, (
        f"expected ONLY the previously-failed chunk "
        f"({last_chunk_id!r}) to be (re)attempted on the resumed run 2, got "
        f"{client_2.calls_by_chunk_text.get(last_chunk_text, 0)} call(s) for it"
    )
    assert client_2.total_calls == 1, (
        f"expected exactly 1 fresh LLM call on the resumed run 2 (only the "
        f"one previously-failed, not-yet-checkpointed chunk), got "
        f"{client_2.total_calls} total call(s) -- a fresh client making "
        f"more than 1 call means run_xref re-processed some already-"
        f"checkpointed chunk(s) instead of skipping them"
    )

    # --- After the resumed run completes, the checkpoint must carry every
    # chunk_id, with no duplicate lines. ---
    final_ids = _read_checkpoint_chunk_ids(checkpoint_path)
    assert set(final_ids) == all_chunk_ids, (
        f"expected {checkpoint_path} to carry all {CHUNK_COUNT} chunk_id(s) "
        f"after the resumed run completes, got {sorted(set(final_ids))}"
    )
    assert len(final_ids) == CHUNK_COUNT, (
        f"expected exactly {CHUNK_COUNT} checkpoint line(s) after the "
        f"resumed run (no duplicate re-append of an already-checkpointed "
        f"chunk), got {len(final_ids)}"
    )

    assert isinstance(result, list), (
        f"expected run_xref to still return a list of xref pairs (its "
        f"existing contract, unchanged by the checkpoint feature), got "
        f"{type(result).__name__}: {result!r}"
    )
