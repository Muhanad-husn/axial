"""Inner unit tests for per-chunk checkpoint/resume (issue #81).

Covers the seams the outer acceptance test (tests/test_vault_resume.py) pins
from the outside:

  1. `AXIAL_STUB_TAG_FAIL_AT` -- the per-process, 1-indexed tag-pass
     fault-injection counter in `axial.llm`.
  2. The tag-pass checkpoint (`data/tags/<source_id>.jsonl`): appended as
     each chunk is tagged, its already-present chunk_ids skipped on resume,
     records recombined in stable chunk order.

There is no chunk-pass checkpoint/resume to cover here: the chunk stage
(`run_chunk_recursive`) overwrites its on-disk artifact fresh on every call
(see its own docstring) and has no per-section resume, so the tag-pass
fixtures below stub `axial.tag.read_chunks` in its place.
"""

from __future__ import annotations

import json

import pytest

from axial.llm import CHUNK_PASS_NAME, TAG_PASS_NAME, StubLLMClient


# --- seam 1: AXIAL_STUB_TAG_FAIL_AT -----------------------------------------


@pytest.fixture(autouse=True)
def _reset_tag_call_counter():
    """The fail-at counter is a per-process module global; reset it before
    every test so counts don't bleed across tests in one pytest process."""
    import axial.llm as llm_mod

    llm_mod._tag_pass_call_count = 0
    yield
    llm_mod._tag_pass_call_count = 0


def test_tag_fail_at_raises_on_the_nth_tag_call_only(monkeypatch):
    from axial.llm import LLMError, StubLLMClient

    monkeypatch.setenv("AXIAL_STUB_TAG_FAIL_AT", "2")
    client = StubLLMClient()

    # First tag call succeeds.
    client.complete("p1", pass_name=TAG_PASS_NAME)
    # Second tag call raises an LLMError subclass.
    with pytest.raises(LLMError):
        client.complete("p2", pass_name=TAG_PASS_NAME)
    # Third and later still succeed (only the Nth fails).
    assert client.complete("p3", pass_name=TAG_PASS_NAME)


def test_tag_fail_at_counts_only_tag_pass_calls(monkeypatch):
    from axial.llm import LLMError

    monkeypatch.setenv("AXIAL_STUB_TAG_FAIL_AT", "2")
    client = StubLLMClient()

    # Chunk-pass calls never advance the tag counter.
    client.complete("c1", pass_name=CHUNK_PASS_NAME)
    client.complete("c2", pass_name=CHUNK_PASS_NAME)

    # So the first tag call is call #1 (succeeds), the second is #2 (fails).
    client.complete("t1", pass_name=TAG_PASS_NAME)
    with pytest.raises(LLMError):
        client.complete("t2", pass_name=TAG_PASS_NAME)


@pytest.mark.parametrize("value", ["", "0", "-3", "notanumber"])
def test_tag_fail_at_never_fails_for_unset_or_nonpositive(monkeypatch, value):
    monkeypatch.setenv("AXIAL_STUB_TAG_FAIL_AT", value)
    client = StubLLMClient()
    for _ in range(5):
        assert client.complete("p", pass_name=TAG_PASS_NAME)


def test_tag_fail_at_is_honored_by_record_client(monkeypatch, tmp_path):
    from axial.llm import LLMError, RecordLLMClient

    monkeypatch.setenv("AXIAL_STUB_TAG_FAIL_AT", "1")
    client = RecordLLMClient(tmp_path / "rec.jsonl")
    with pytest.raises(LLMError):
        client.complete("p", pass_name=TAG_PASS_NAME)


# --- seam 2: tag-pass checkpoint --------------------------------------------


def _write_minimal_domain(tmp_path):
    domain_dir = tmp_path / "domain"
    domain_dir.mkdir()
    (domain_dir / "schema.yaml").write_text(
        "version: 0.1\naxes:\n  role_in_argument:\n"
        "    applies_to: [prose]\n    cardinality: single\n"
        "    values: [role:claim, role:evidence]\n",
        encoding="utf-8",
    )
    (domain_dir / "codebook.yaml").write_text(
        "axes:\n  role_in_argument:\n"
        "    role:claim: {definition: d, positive_example: p, negative_example: n}\n"
        "    role:evidence: {definition: d, positive_example: p, negative_example: n}\n",
        encoding="utf-8",
    )
    return domain_dir


_CHUNK_RECORDS = [
    {"chunk_id": "paper-xyz_1_intro_001", "section": "Introduction", "text": "one"},
    {"chunk_id": "paper-xyz_1_intro_002", "section": "Introduction", "text": "two"},
    {"chunk_id": "paper-xyz_2_concl_001", "section": "Conclusion", "text": "three"},
]


def _arrange_tag_source(tmp_path, monkeypatch):
    import axial.tag as tag_mod

    source = tmp_path / "paper.pdf"
    source.write_bytes(b"tag checkpoint bytes")
    domain_dir = _write_minimal_domain(tmp_path)
    monkeypatch.setattr(tag_mod, "read_chunks", lambda *a, **k: list(_CHUNK_RECORDS))
    source_id = tag_mod.compute_source_id(source)
    return source, domain_dir, source_id


def test_run_tag_appends_a_tag_checkpoint_line_per_chunk(monkeypatch, tmp_path):
    import axial.tag as tag_mod

    source, domain_dir, source_id = _arrange_tag_source(tmp_path, monkeypatch)
    tags_dir = tmp_path / "tags"

    records = tag_mod.run_tag(
        source, client=StubLLMClient(), domain_dir=domain_dir, tags_dir=tags_dir
    )

    checkpoint = tags_dir / f"{source_id}.jsonl"
    assert checkpoint.is_file()
    persisted = [
        json.loads(line) for line in checkpoint.read_text(encoding="utf-8").splitlines() if line
    ]
    assert [r["chunk_id"] for r in persisted] == [r["chunk_id"] for r in _CHUNK_RECORDS]
    assert [r["chunk_id"] for r in records] == [r["chunk_id"] for r in _CHUNK_RECORDS]


def test_run_tag_resume_skips_already_checkpointed_chunks(monkeypatch, tmp_path):
    import axial.tag as tag_mod

    source, domain_dir, source_id = _arrange_tag_source(tmp_path, monkeypatch)
    tags_dir = tmp_path / "tags"

    # First run tags everything.
    tag_mod.run_tag(source, client=StubLLMClient(), domain_dir=domain_dir, tags_dir=tags_dir)

    # Second run must not re-send any chunk to the model.
    class _CountingClient(StubLLMClient):
        pass

    counting = _CountingClient()
    records = tag_mod.run_tag(source, client=counting, domain_dir=domain_dir, tags_dir=tags_dir)

    assert counting.call_count == 0
    assert [r["chunk_id"] for r in records] == [r["chunk_id"] for r in _CHUNK_RECORDS]

    checkpoint = tags_dir / f"{source_id}.jsonl"
    persisted = [
        json.loads(line) for line in checkpoint.read_text(encoding="utf-8").splitlines() if line
    ]
    # No duplicates: exactly one line per chunk after the resume run.
    assert len(persisted) == len(_CHUNK_RECORDS)


def test_run_tag_resume_tags_only_missing_chunks_in_stable_order(monkeypatch, tmp_path):
    import axial.tag as tag_mod
    from axial.tag import append_tag_checkpoint, build_tagged_record, tags_checkpoint_path

    source, domain_dir, source_id = _arrange_tag_source(tmp_path, monkeypatch)
    tags_dir = tmp_path / "tags"

    # Pre-seed the checkpoint with the first chunk only.
    checkpoint = tags_checkpoint_path(source_id, tags_dir)
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    seeded = build_tagged_record(_CHUNK_RECORDS[0], "role:claim", "0.1")
    append_tag_checkpoint(checkpoint, seeded)

    counting = StubLLMClient()
    records = tag_mod.run_tag(source, client=counting, domain_dir=domain_dir, tags_dir=tags_dir)

    # Only the two missing chunks were tagged.
    assert counting.call_count == len(_CHUNK_RECORDS) - 1
    # Records recombine in stable chunk order (seeded first, then fresh).
    assert [r["chunk_id"] for r in records] == [r["chunk_id"] for r in _CHUNK_RECORDS]


# --- hardening: torn checkpoint lines survive a hard process kill ----------
#
# A hard kill (OOM kill, Stop-Process) mid-`append_tag_checkpoint`/
# `append_chunk_checkpoint` can leave the file's last line partially flushed
# -- a torn final line. Bare `json.loads` on that line would raise on every
# subsequent load, permanently poisoning that source's resume (strictly
# worse than no checkpoint at all). Both checkpoints share the same
# append/heal machinery (`axial.checkpoint`), so both tolerate it the same
# way: the torn tail is dropped and the record simply reappears in the
# "not yet checkpointed" gap on the next run.


def test_load_tag_checkpoint_drops_torn_final_line_and_resume_retags_it(monkeypatch, tmp_path):
    import axial.tag as tag_mod

    source, domain_dir, source_id = _arrange_tag_source(tmp_path, monkeypatch)
    tags_dir = tmp_path / "tags"
    checkpoint = tag_mod.tags_checkpoint_path(source_id, tags_dir)
    checkpoint.parent.mkdir(parents=True, exist_ok=True)

    # Two intact lines, plus a third line torn mid-JSON with no trailing
    # newline -- simulating a hard kill mid-append of the third chunk.
    intact = [
        tag_mod.build_tagged_record(_CHUNK_RECORDS[0], "role:claim", "0.1"),
        tag_mod.build_tagged_record(_CHUNK_RECORDS[1], "role:claim", "0.1"),
    ]
    full_third = json.dumps(tag_mod.build_tagged_record(_CHUNK_RECORDS[2], "role:claim", "0.1"))
    torn_tail = full_third[:20]
    assert not torn_tail.endswith("}")
    checkpoint.write_text(
        "".join(json.dumps(r) + "\n" for r in intact) + torn_tail, encoding="utf-8"
    )

    loaded = tag_mod.load_tag_checkpoint(checkpoint)
    assert [r["chunk_id"] for r in loaded] == [r["chunk_id"] for r in intact]

    # Resume: only the torn (third) chunk is re-tagged.
    counting = StubLLMClient()
    records = tag_mod.run_tag(source, client=counting, domain_dir=domain_dir, tags_dir=tags_dir)

    assert counting.call_count == 1
    assert [r["chunk_id"] for r in records] == [r["chunk_id"] for r in _CHUNK_RECORDS]

    # The checkpoint healed: the torn tail was truncated before the new
    # record was appended, so every line is valid JSON, one per chunk, with
    # no leftover fragment glued onto the freshly appended line.
    healed_lines = [
        line for line in checkpoint.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    assert len(healed_lines) == len(_CHUNK_RECORDS)
    for line in healed_lines:
        json.loads(line)  # must not raise


def test_load_tag_checkpoint_raises_naming_path_and_line_for_a_non_final_torn_line(tmp_path):
    import axial.tag as tag_mod

    checkpoint = tmp_path / "tags" / "src.jsonl"
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    intact_first = json.dumps({"chunk_id": "a"})
    torn_middle = '{"chunk_id": "b", "broken'
    intact_last = json.dumps({"chunk_id": "c"})
    checkpoint.write_text(f"{intact_first}\n{torn_middle}\n{intact_last}\n", encoding="utf-8")

    with pytest.raises(tag_mod.TagCheckpointCorruptError) as exc_info:
        tag_mod.load_tag_checkpoint(checkpoint)

    message = str(exc_info.value)
    assert str(checkpoint) in message
    assert "2" in message  # 1-indexed line number of the torn (non-final) line
