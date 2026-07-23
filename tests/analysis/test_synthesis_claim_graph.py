"""Outer acceptance test for issue #256, slice 02 of the analysis-synthesis
subproject (Phase B, sub:analysis-v0): the stage-4 synthesis pass emits the
marked, grounded claim graph.

Given a fixture vault, a brief naming lens "political-economy", and an
      assembled evidence set of known chunk ids
  And AXIAL_LLM_PROVIDER=record with AXIAL_LLM_RECORD_PATH set, the canned
      synthesis response carrying one (a) claim, one (b) claim, and one (c)
      claim
When  the synthesis pass runs over that evidence set
Then  every emitted claim carries a `kind` in {a, b, c}
  And the (a) claim and the (b) claim each carry at least one `grounds` entry
  And every grounds entry is {ref_type, ref_id} with ref_type in
      {chunk, artifact} and ref_id resolving to a real id in the fixture vault
  And each claim's `polities_touched` equals the union of its grounds chunks'
      polities_touched facets
  And `lens` is recorded as "political-economy"

Given the recorded prompt at AXIAL_LLM_RECORD_PATH from that run
Then  the prompt instructs the model to reason only over the supplied grounds
  And the prompt forbids asserting from parametric memory or the open web
  And the prompt states that a cross-source inference is marked (b) and never
      voiced as a source assertion

Given the canned response carries an (a) claim with empty grounds
When  the synthesis pass runs
Then  the pass fails loudly with the offending claim named, and no claim graph
      with an ungrounded (a) claim is returned

Given a brief with no `lens` field
When  the synthesis pass runs
Then  a lens is selected from config/lenses/ and recorded on the result,
      never left null

Given the same evidence set and the same canned response
When  the synthesis pass runs twice
Then  the two claim graphs carry identical claim_ids

See specs/PHASE-B.md §7.4 (the claim graph), §7.11 (per-pass model tiering),
§8 P0-4 (evidence assembly & analysis), and
plans/analysis-synthesis/02-synthesis-claim-graph.md for this slice's own
acceptance criterion (identical Gherkin).

Seam decisions
--------------
This is a library-level test (`axial.analyze.synthesis.synthesize`), not a
CLI-subprocess test: the plan's own "Boundary / endpoint" states the library
entry point directly, and no CLI subcommand exists for this slice (persisting
a record and rendering an answer are later slices). `RecordLLMClient` is
built in-process (mirroring `tests/analysis/test_brief_examine.py` scenario
2's in-process seam) with `AXIAL_STUB_SYNTHESIZE_RESPONSE` driving the canned
claim-graph response end-to-end -- the same seam
`AXIAL_STUB_INTERROGATE_RESPONSE` already established for the interrogate
pass (issue #252).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from axial.analyze.assembly import assemble_evidence
from axial.analyze.synthesis import UngroundedClaimError, synthesize
from axial.brief.intake import Brief
from axial.llm import STUB_SYNTHESIZE_RESPONSE_ENV_VAR, RecordLLMClient

SYRIA_A = "acfix_001_syria_a"
IRAQ_A = "acfix_002_iraq_a"
LEBANON_A = "acfix_003_lebanon_a"
ARTIFACT_A = "acfix_004_artifact"


def _chunk_frontmatter(*, chunk_id: str, polities_touched: list[str]) -> dict[str, Any]:
    return {
        "chunk_id": chunk_id,
        "section": "Synthetic Section",
        "chunk_text": f"SENTINEL_{chunk_id}: synthetic prose.",
        "source_meta": {
            "author": "A. Synthetic Author",
            "title": "A Synthetic Fixture Source",
            "date": 2021,
            "thesis": "Synthetic thesis.",
            "scope": "Synthetic scope.",
        },
        "schema_version": "0.1",
        "role_in_argument": "role:claim",
        "field": {"primary": "field:political-sociology", "secondary": []},
        "claim_type": {"primary": "claim:causal", "secondary": None, "subtags": []},
        "theory_school": {
            "primary": "school:synthetic-institutionalist",
            "secondary": None,
            "status": "candidate",
        },
        "empirical_scope": {
            "value": "scope:country-case",
            "polity": polities_touched[0] if polities_touched else None,
        },
        "polities_touched": polities_touched,
        "artifact_refs": [],
    }


def _artifact_frontmatter() -> dict[str, Any]:
    return {
        "artifact_id": ARTIFACT_A,
        "artifact_role": "case-study",
        "field": {"primary": "field:political-sociology", "secondary": []},
        "source_id": "acfix",
        "section": "Synthetic Section",
        "retrievable": True,
        "cited_by": [],
    }


def _write_fixture_vault(root: Path) -> Path:
    prose_dir = root / "data" / "vault" / "prose"
    prose_dir.mkdir(parents=True, exist_ok=True)
    notes = [
        _chunk_frontmatter(chunk_id=SYRIA_A, polities_touched=["Syria"]),
        _chunk_frontmatter(chunk_id=IRAQ_A, polities_touched=["Iraq"]),
        _chunk_frontmatter(chunk_id=LEBANON_A, polities_touched=["Lebanon"]),
    ]
    for frontmatter in notes:
        text = "---\n" + yaml.safe_dump(frontmatter, sort_keys=False) + "---\nBody.\n"
        (prose_dir / f"{frontmatter['chunk_id']}.md").write_text(text, encoding="utf-8")

    artifacts_dir = root / "data" / "vault" / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    artifact_fm = _artifact_frontmatter()
    artifact_text = "---\n" + yaml.safe_dump(artifact_fm, sort_keys=False) + "---\nBody.\n"
    (artifacts_dir / f"{artifact_fm['artifact_id']}.md").write_text(artifact_text, encoding="utf-8")
    return root


@pytest.fixture
def fixture_root(tmp_path: Path) -> Path:
    return _write_fixture_vault(tmp_path)


@pytest.fixture
def vault_dir(fixture_root: Path) -> Path:
    return fixture_root / "data" / "vault"


def _three_kind_response() -> str:
    """One (a), one (b), one (c) claim -- the acceptance criterion's own
    canned response. The (b) claim draws on two chunks across two
    polities (Syria, Iraq) so `polities_touched` union/dedup is exercised
    on a real multi-source claim, not just a single-source one."""
    return json.dumps(
        {
            "claims": [
                {
                    "text": "The corpus states that displacement reshaped local authority in Syria.",
                    "kind": "a",
                    "grounds": [{"ref_type": "chunk", "ref_id": SYRIA_A}],
                    "confidence": "medium",
                },
                {
                    "text": "A cross-source inference linking Syrian and Iraqi displacement dynamics.",
                    "kind": "b",
                    "grounds": [
                        {"ref_type": "chunk", "ref_id": SYRIA_A},
                        {"ref_type": "chunk", "ref_id": IRAQ_A},
                        {"ref_type": "artifact", "ref_id": ARTIFACT_A},
                    ],
                    "confidence": "low",
                },
                {
                    "text": "A speculative extrapolation beyond the corpus.",
                    "kind": "c",
                    "grounds": [],
                    "confidence": "low",
                },
            ]
        }
    )


def _build_client(record_path: Path) -> RecordLLMClient:
    return RecordLLMClient(record_path)


def _read_recorded_prompts(record_path: Path) -> list[str]:
    if not record_path.exists():
        return []
    return [json.loads(line) for line in record_path.read_text(encoding="utf-8").splitlines()]


def test_synthesis_emits_marked_grounded_claims_with_recorded_lens(
    fixture_root: Path, vault_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    """Scenario 1+2 (issue #256): every claim's kind/grounds/polities_touched
    round-trip correctly, and the prompt carries the grounded-by-construction
    instructions."""
    monkeypatch.setenv(STUB_SYNTHESIZE_RESPONSE_ENV_VAR, _three_kind_response())
    record_path = fixture_root / "record.jsonl"
    client = _build_client(record_path)

    brief = Brief(
        brief_id="synfix-brief",
        case="Syria",
        request="How did displacement reshape local authority?",
        lens="political-economy",
    )
    evidence = assemble_evidence([SYRIA_A, IRAQ_A], vault_dir=vault_dir)

    graph = synthesize(evidence, brief, client=client, vault_dir=vault_dir)

    assert graph.lens == "political-economy"
    assert len(graph.claims) == 3

    by_kind = {claim.kind: claim for claim in graph.claims}
    assert set(by_kind) == {"a", "b", "c"}

    for kind in ("a", "b"):
        claim = by_kind[kind]
        assert len(claim.grounds) >= 1, f"kind {kind} claim must carry grounds"
        for ground in claim.grounds:
            assert ground.ref_type in {"chunk", "artifact"}
            assert ground.ref_id  # resolved already (synthesize would have raised otherwise)

    # (a): grounded in Syria only -> polities_touched == ["Syria"].
    assert by_kind["a"].polities_touched == ["Syria"]
    # (b): grounded in Syria + Iraq chunks + one artifact (no facet of its
    # own) -> union, first-seen order, deduped.
    assert by_kind["b"].polities_touched == ["Syria", "Iraq"]
    # (c): empty grounds -> empty polities_touched.
    assert by_kind["c"].grounds == []
    assert by_kind["c"].polities_touched == []

    prompts = _read_recorded_prompts(record_path)
    assert len(prompts) == 1
    prompt = prompts[0].lower()
    assert "reason only over" in prompt
    assert "parametric memory" in prompt
    assert "open web" in prompt
    assert "never" in prompt and "(b)" in prompts[0]


def test_synthesis_fails_loudly_on_an_ungrounded_a_claim(
    fixture_root: Path, vault_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    """Scenario 3 (issue #256): an (a) claim with empty grounds must fail
    loudly, naming the offending claim -- never a silently-dropped claim or
    an ungrounded claim graph."""
    bad_response = json.dumps(
        {
            "claims": [
                {
                    "text": "An ungrounded source-says claim.",
                    "kind": "a",
                    "grounds": [],
                    "confidence": "medium",
                }
            ]
        }
    )
    monkeypatch.setenv(STUB_SYNTHESIZE_RESPONSE_ENV_VAR, bad_response)
    record_path = fixture_root / "record.jsonl"
    client = _build_client(record_path)

    brief = Brief(
        brief_id="synfix-brief-bad",
        case="Syria",
        request="How did displacement reshape local authority?",
        lens="political-economy",
    )
    evidence = assemble_evidence([SYRIA_A], vault_dir=vault_dir)

    with pytest.raises(UngroundedClaimError) as exc_info:
        synthesize(evidence, brief, client=client, vault_dir=vault_dir)

    assert "An ungrounded source-says claim." in str(exc_info.value)


def test_synthesis_auto_selects_and_records_a_lens_when_brief_omits_it(
    fixture_root: Path, vault_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    """Scenario 4 (issue #256): a brief with no `lens` gets one selected
    from config/lenses/ and recorded on the result -- never left null."""
    monkeypatch.setenv(STUB_SYNTHESIZE_RESPONSE_ENV_VAR, json.dumps({"claims": []}))
    record_path = fixture_root / "record.jsonl"
    client = _build_client(record_path)

    brief = Brief(
        brief_id="synfix-brief-nolens",
        case="Syria",
        request="How did displacement reshape local authority?",
        lens=None,
    )
    evidence = assemble_evidence([SYRIA_A], vault_dir=vault_dir)

    graph = synthesize(evidence, brief, client=client, vault_dir=vault_dir)

    assert graph.lens is not None
    assert isinstance(graph.lens, str) and graph.lens.strip()


def test_synthesis_claim_ids_are_identical_across_two_runs(
    fixture_root: Path, vault_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    """Scenario 5 (issue #256): the same evidence set and the same canned
    response run twice must carry identical claim_ids."""
    monkeypatch.setenv(STUB_SYNTHESIZE_RESPONSE_ENV_VAR, _three_kind_response())

    brief = Brief(
        brief_id="synfix-brief-det",
        case="Syria",
        request="How did displacement reshape local authority?",
        lens="political-economy",
    )
    evidence = assemble_evidence([SYRIA_A, IRAQ_A], vault_dir=vault_dir)

    client_1 = _build_client(fixture_root / "record_1.jsonl")
    client_2 = _build_client(fixture_root / "record_2.jsonl")

    graph_1 = synthesize(evidence, brief, client=client_1, vault_dir=vault_dir)
    graph_2 = synthesize(evidence, brief, client=client_2, vault_dir=vault_dir)

    assert [c.claim_id for c in graph_1.claims] == [c.claim_id for c in graph_2.claims]
