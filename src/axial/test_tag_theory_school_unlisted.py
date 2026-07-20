"""Regression coverage for the theory_school soft-land (founder-approved,
2026-07-20): out-of-vocabulary `theory_school` no longer aborts the whole
source once the #102 bounded correction re-ask has also failed -- it lands
as the `unlisted` sentinel and the model's real proposal is logged as a
candidate addition for operator review, mirroring `log_polity_not_in_list`'s
accept-and-log philosophy (spec-drift #77) for this one closed-vocabulary
axis. Every OTHER closed axis (field, claim_type, role_in_argument,
empirical_scope) is untouched and still raises `TagNotInSchemaError`
fatally, exactly as before.

See `config/domains/syria/schema.yaml` (`theory_school.groups.open:
[unlisted]`) and `codebook.yaml` (the `unlisted` vs `not-applicable`
definitions) for the schema/codebook half of this change, and
`specs/PRODUCT.md` Appendix E for the spec.

Mirrors `src/axial/test_tag.py`'s own in-process `run_tag` unit-test style
(a small synthetic domain written under `tmp_path`, `read_chunks` stubbed to
a fixed chunk list, a scripted client returning one response per call) --
never the CLI-subprocess style `tests/ingestion/` uses, since this is an
inner-loop regression guard, not an outer acceptance contract.
"""

from __future__ import annotations

import json

import pytest

from axial.llm import TAG_PASS_NAME

# A real school the schema's mind-map-derived vocabulary does not cover
# (module docstring's own live-failure example) -- deliberately never added
# to the fixture domain's vocabulary below, so it stays genuinely
# out-of-vocab in every scenario that uses it.
OUT_OF_VOCAB_SCHOOL = "pluralist"
IN_VOCAB_SCHOOL = "bellicist"
UNLISTED_SENTINEL = "unlisted"


def _write_theory_school_domain(tmp_path):
    """A minimal schema.yaml + codebook.yaml covering role_in_argument
    (single), field (primary_plus_secondary, closed), and theory_school
    (primary_plus_optional_secondary, grouped -- mirrors the real syria
    domain's shape, including the `not-applicable`/`unlisted` sentinel
    group), for `run_tag` unit tests."""
    domain_dir = tmp_path / "domain"
    domain_dir.mkdir()
    (domain_dir / "schema.yaml").write_text(
        "version: 0.1\n"
        "axes:\n"
        "  role_in_argument:\n"
        "    applies_to: [prose]\n"
        "    cardinality: single\n"
        "    values: [role:claim, role:evidence]\n"
        "  field:\n"
        "    applies_to: [prose]\n"
        "    cardinality: primary_plus_secondary\n"
        "    values: [state, violence]\n"
        "  theory_school:\n"
        "    applies_to: [prose]\n"
        "    cardinality: primary_plus_optional_secondary\n"
        "    status: candidate\n"
        "    groups:\n"
        "      state:\n"
        "        - bellicist\n"
        "        - marxist-political-economy\n"
        "      none:\n"
        "        - not-applicable\n"
        "      open:\n"
        "        - unlisted\n",
        encoding="utf-8",
    )
    (domain_dir / "codebook.yaml").write_text(
        "axes:\n"
        "  role_in_argument:\n"
        "    role:claim: {definition: d, positive_example: p, negative_example: n}\n"
        "    role:evidence: {definition: d, positive_example: p, negative_example: n}\n"
        "  field:\n"
        "    state: {definition: d, positive_example: p, negative_example: n}\n"
        "    violence: {definition: d, positive_example: p, negative_example: n}\n"
        "  theory_school:\n"
        "    bellicist: {definition: d, positive_example: p, negative_example: n}\n"
        "    marxist-political-economy: {definition: d, positive_example: p, negative_example: n}\n"
        "    not-applicable: {definition: d, positive_example: p, negative_example: n}\n"
        "    unlisted: {definition: d, positive_example: p, negative_example: n}\n",
        encoding="utf-8",
    )
    return domain_dir


_CHUNK = {"chunk_id": "src_1_intro_001", "section": "Introduction", "text": "chunk one"}


def _one_chunk_read_chunks(monkeypatch, tag_mod):
    monkeypatch.setattr(tag_mod, "read_chunks", lambda *args, **kwargs: [dict(_CHUNK)])


def _payload(*, theory_school_primary, field_secondary):
    return json.dumps(
        {
            "role_in_argument": "role:claim",
            "field": {"primary": "state", "secondary": field_secondary},
            "theory_school": {"primary": theory_school_primary},
        }
    )


class _ScriptedClient:
    """Returns one scripted raw response per call, in order (mirrors
    `test_tag.py`'s own `_ScriptedClient`)."""

    def __init__(self, responses: list[str]):
        self._responses = responses
        self.call_count = 0

    def complete(self, prompt, pass_name=None):
        assert pass_name == TAG_PASS_NAME
        response = self._responses[self.call_count]
        self.call_count += 1
        return response


def test_theory_school_out_of_vocab_survives_reask_lands_unlisted_preserving_other_axes(
    monkeypatch, tmp_path
):
    """An out-of-vocab theory_school primary that is STILL out-of-vocab on
    the #102 bounded correction re-ask's own answer lands as `unlisted`
    instead of raising -- and every other axis on the chunk (here proven via
    field.secondary, deliberately varied between the two responses) comes
    through as the model's own final, corrected answer, not lost or stale."""
    import axial.tag as tag_mod

    domain_dir = _write_theory_school_domain(tmp_path)
    _one_chunk_read_chunks(monkeypatch, tag_mod)

    first = _payload(theory_school_primary=OUT_OF_VOCAB_SCHOOL, field_secondary=[])
    # The bounded correction re-ask's own answer: theory_school is STILL
    # out-of-vocab (the model never self-corrects it), but field.secondary
    # now carries "violence" -- proving the final record reflects THIS
    # (second, actually-used) response, not a stale/lost first attempt.
    still_bad = _payload(theory_school_primary=OUT_OF_VOCAB_SCHOOL, field_secondary=["violence"])

    client = _ScriptedClient([first, still_bad])
    (tmp_path / "paper.pdf").write_bytes(b"fake pdf bytes")
    records = tag_mod.run_tag(tmp_path / "paper.pdf", client=client, domain_dir=domain_dir)

    assert len(records) == 1
    record = records[0]

    # theory_school soft-landed to the sentinel, never raised.
    assert record["theory_school"]["primary"] == UNLISTED_SENTINEL

    # Every other axis on the chunk is preserved, from the model's own final
    # (corrected) response.
    assert record["role_in_argument"] == "role:claim"
    assert record["field"]["primary"] == "state"
    assert record["field"]["secondary"] == ["violence"]

    # The #102 bounded re-ask genuinely fired exactly once for this chunk --
    # never skipped, never looped further.
    assert client.call_count == 2


def test_theory_school_softland_writes_a_candidates_log_record(monkeypatch, tmp_path, capsys):
    """The soft-land appends a JSONL candidate record (proposed value +
    source/chunk/section/position provenance) to the theory_school
    candidates log, and prints a non-fatal stderr diagnostic naming the
    offending value -- mirroring `log_polity_not_in_list`'s convention."""
    import axial.tag as tag_mod

    domain_dir = _write_theory_school_domain(tmp_path)
    _one_chunk_read_chunks(monkeypatch, tag_mod)
    tags_dir = tmp_path / "tags"

    payload = _payload(theory_school_primary=OUT_OF_VOCAB_SCHOOL, field_secondary=[])
    client = _ScriptedClient([payload, payload])
    (tmp_path / "paper.pdf").write_bytes(b"fake pdf bytes")
    tag_mod.run_tag(tmp_path / "paper.pdf", client=client, domain_dir=domain_dir, tags_dir=tags_dir)

    candidates_path = tags_dir / "theory_school_candidates.jsonl"
    assert candidates_path.is_file(), (
        f"expected a theory_school candidates log at {candidates_path}, found none"
    )
    lines = [line for line in candidates_path.read_text(encoding="utf-8").splitlines() if line]
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["proposed_value"] == OUT_OF_VOCAB_SCHOOL
    assert record["position"] == "primary"
    assert record["chunk_id"] == _CHUNK["chunk_id"]
    assert record["section"] == _CHUNK["section"]
    assert "source_id" in record and record["source_id"]

    captured = capsys.readouterr()
    assert OUT_OF_VOCAB_SCHOOL in captured.err
    assert "unlisted" in captured.err


def test_not_applicable_and_unlisted_are_both_legal_theory_school_values(tmp_path):
    """The schema loader flattens BOTH sentinel groups (`none.not-applicable`
    and `open.unlisted`) into the axis's tag_ids -- proven against the real
    domain, not the fixture, since this is the actual shipped schema
    change."""
    from axial.schema import load_schema

    schema = load_schema("config/domains/syria")
    tag_ids = schema.axes["theory_school"].tag_ids
    assert "not-applicable" in tag_ids
    assert "unlisted" in tag_ids


def test_theory_school_codebook_teaches_both_sentinel_definitions():
    """`_tag_descriptions('theory_school', codebook)` renders BOTH
    sentinels' definitions -- the model must be taught the distinction
    between "no theory applies" (`not-applicable`) and "a real theory
    applies but isn't listed" (`unlisted`), against the real domain's
    codebook."""
    from axial.codebook import load_codebook
    from axial.tag import _tag_descriptions

    codebook = load_codebook("config/domains/syria")
    rendered = _tag_descriptions("theory_school", codebook)
    assert "not-applicable:" in rendered
    assert "unlisted:" in rendered


def test_out_of_vocab_field_still_raises_fatally(monkeypatch, tmp_path):
    """Guard against over-broadening: an out-of-vocab value on a DIFFERENT
    closed axis (field) is untouched by the theory_school soft-land and
    still raises `TagNotInSchemaError` fatally after the bounded re-ask,
    exactly as before this change."""
    import axial.tag as tag_mod

    domain_dir = _write_theory_school_domain(tmp_path)
    _one_chunk_read_chunks(monkeypatch, tag_mod)

    bad_field_payload = json.dumps(
        {
            "role_in_argument": "role:claim",
            "field": {"primary": "not-a-real-field", "secondary": []},
            "theory_school": {"primary": IN_VOCAB_SCHOOL},
        }
    )
    client = _ScriptedClient([bad_field_payload, bad_field_payload])
    (tmp_path / "paper.pdf").write_bytes(b"fake pdf bytes")

    with pytest.raises(tag_mod.TagNotInSchemaError) as exc_info:
        tag_mod.run_tag(tmp_path / "paper.pdf", client=client, domain_dir=domain_dir)

    assert exc_info.value.axis_name == "field"
    # Both the original ask and the single bounded re-ask fired before the
    # hard error -- the soft-land never intercepts a non-theory_school axis.
    assert client.call_count == 2


def test_theory_school_in_vocab_on_first_answer_never_softlands_or_logs(monkeypatch, tmp_path):
    """Happy path: an in-vocab theory_school primary on the first answer
    tags normally, makes exactly one LLM call (the correction path never
    fires), and writes no candidates-log record at all."""
    import axial.tag as tag_mod

    domain_dir = _write_theory_school_domain(tmp_path)
    _one_chunk_read_chunks(monkeypatch, tag_mod)
    tags_dir = tmp_path / "tags"

    payload = _payload(theory_school_primary=IN_VOCAB_SCHOOL, field_secondary=[])
    client = _ScriptedClient([payload])
    (tmp_path / "paper.pdf").write_bytes(b"fake pdf bytes")
    records = tag_mod.run_tag(
        tmp_path / "paper.pdf", client=client, domain_dir=domain_dir, tags_dir=tags_dir
    )

    assert records[0]["theory_school"]["primary"] == IN_VOCAB_SCHOOL
    assert client.call_count == 1

    candidates_path = tags_dir / "theory_school_candidates.jsonl"
    assert not candidates_path.exists()
