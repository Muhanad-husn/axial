"""The analysis record and `axial brief run` (Phase-B stage 6, specs/PHASE-B.md
§7.3, §8 P0-8/P0-9, issue #257).

`run_brief` is the whole-engine orchestrator: it drives stages 1 (brief
interrogation), 3 (retrieval) and 4 (synthesis) exactly as
`axial.analyze.examine.run_examine` already drives stages 1+3 for
`axial brief examine`, then assembles and persists the §7.3 analysis record
-- the deliverable this slice adds on top of the three already-merged
slices (#252 interrogation, #253/#254 retrieval loop, #255/#256 evidence
assembly + synthesis).

On a `refuse` disposition (§7.2), stages 3-4 never run: `claims` and
`trajectory` are both empty, `model_by_pass` names only the interrogation
pass, and the record is still written -- a refusal is a COMPLETE run, not
an error (§7.2, §8 P0-1). This mirrors `run_examine`'s own inherited
short-circuit (`run_planned_retrieval` itself returns an empty trajectory
on `refuse`) and extends it one stage further to skip synthesis too.

Out of this slice's scope (issue #257's own "do NOT build" list): computing
real `counter_position` / `coverage_map` / `confidence` CONTENT -- that is
the separate analysis-validators feature (issues #258-260). This module
writes each of those three fields as an honest, correctly-shaped
placeholder (`_placeholder_counter_position` / `_placeholder_confidence` /
the empty `{}` coverage map) rather than inventing partial content ahead of
the validators that own it.

`source_usage` (§7.13/P0-13, issue #265) IS computed here: `build_record`
assembles every other §7.3 field first, then calls
`axial.answer.source_usage.compute_source_usage` over the record-so-far
(its own `claims`/`trajectory`/`interrogation.disposition`) to fill it in --
zero model calls, pure vault reads plus arithmetic (see that module).

The rendered markdown answer (§7.10, issue #261) is written alongside the
JSON: `run_brief` calls `persist_markdown`, which renders the just-built
record through `axial.answer.render.render_markdown` (a pure function of
the record -- no model call, no vault read, no clock) and writes it to
`<analyses_dir>/<brief_id>.md`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from axial.analyze.assembly import assemble_evidence
from axial.analyze.synthesis import Claim, resolve_lens, synthesize
from axial.answer.render import render_markdown
from axial.answer.source_usage import compute_source_usage
from axial.brief.intake import Brief
from axial.brief.interrogate import InterrogationResult, interrogate
from axial.eval.corpus_pin import resolve_pin_id
from axial.llm import INTERROGATE_PASS_NAME, RETRIEVE_PASS_NAME, SYNTHESIZE_PASS_NAME, LLMClient
from axial.paths import DEFAULT_PIPELINE_CONFIG_PATH, default_analyses_dir, default_vault_dir
from axial.query.reader import get_chunk, query_by_tag
from axial.retrieve.loop import run_planned_retrieval


class AnswerError(Exception):
    """Base class for all stage-6 (analysis-record) errors."""


class MissingVaultSchemaVersionError(AnswerError):
    """Raised when the vault named by `vault_dir` holds no chunk at all --
    the record's `schema_version` field (§7.3) has nothing real to read."""

    def __init__(self, vault_dir: Path):
        self.vault_dir = vault_dir
        super().__init__(f"cannot determine schema_version: no chunks found under {vault_dir}")


def vault_schema_version(vault_dir: Path | None = None) -> str:
    """The domain schema version the vault was tagged under (§7.3): read
    off the first chunk in `chunk_id` order (`query_by_tag`'s own
    determinism contract), never off `config/domains/<domain>/schema.yaml`
    directly -- every prose note already carries its own `schema_version`
    (`axial.tag.build_tagged_record`'s field), so this works against any
    pinned/fixture vault without depending on the calling process's cwd
    holding a real domain-config checkout."""
    chunk_ids = query_by_tag(vault_dir=vault_dir)
    if not chunk_ids:
        raise MissingVaultSchemaVersionError(
            Path(vault_dir) if vault_dir is not None else default_vault_dir()
        )
    return get_chunk(chunk_ids[0], vault_dir=vault_dir).schema_version


def _brief_to_dict(brief: Brief) -> dict[str, Any]:
    """The brief, verbatim (§7.1, §7.3: "the brief (§7.1), verbatim")."""
    return {
        "brief_id": brief.brief_id,
        "case": brief.case,
        "request": brief.request,
        "lens": brief.lens,
    }


def _claim_to_dict(claim: Claim) -> dict[str, Any]:
    return {
        "claim_id": claim.claim_id,
        "text": claim.text,
        "kind": claim.kind,
        "grounds": [{"ref_type": g.ref_type, "ref_id": g.ref_id} for g in claim.grounds],
        "confidence": claim.confidence,
        "polities_touched": list(claim.polities_touched),
    }


def _placeholder_counter_position() -> dict[str, Any]:
    """The §7.8 shape (`{present, stance, grounds, corpus_one_sided,
    one_sided_reason}`), every field at its emptiest, most honest value:
    the contested-detection rule and the steelman check are the
    analysis-validators feature's job (issues #258-260), not this slice's --
    nothing here guesses at whether this brief is contested."""
    return {
        "present": False,
        "stance": None,
        "grounds": [],
        "corpus_one_sided": False,
        "one_sided_reason": None,
    }


def _placeholder_confidence() -> dict[str, Any]:
    """The §7.4 three-band vocabulary, pinned to its most conservative
    value (`low`) -- never a numeric score -- since no calibration has run
    yet (issues #258-260's job); the rationale says so plainly rather than
    inventing counts `coverage_map` (also a placeholder in this slice)
    cannot yet back."""
    return {
        "overall_band": "low",
        "rationale": (
            "placeholder: confidence has not yet been computed by the "
            "analysis-validators (issues #258-260), and coverage_map is "
            "likewise a placeholder in this slice, so no real counts back "
            "this band"
        ),
    }


@dataclass(frozen=True)
class BriefRunResult:
    """`run_brief`'s own return shape: the persisted §7.3 record, the path
    it was written to, and the path of the rendered markdown answer written
    alongside it (§7.10)."""

    record: dict[str, Any]
    path: Path
    markdown_path: Path


def build_record(
    brief: Brief,
    interrogation_result: InterrogationResult,
    *,
    corpus_pin: str,
    schema_version: str,
    lens: str,
    claims: list[Claim],
    trajectory: list[dict[str, Any]],
    model_by_pass: dict[str, str],
    vault_dir: Path | None = None,
) -> dict[str, Any]:
    """Assemble the §7.3 analysis record. `claims`/`trajectory` are the
    caller's already-computed stage-4/stage-3 output (empty on a `refuse`
    disposition); `counter_position`/`coverage_map`/`confidence` are always
    this slice's placeholders (see module docstring). `source_usage`
    (§7.13) is computed over the record's own `claims`/`trajectory`/
    `interrogation` -- assembled last here, once every field it reads is
    already in the dict."""
    record = {
        "brief_id": brief.brief_id,
        "brief": _brief_to_dict(brief),
        "corpus_pin": corpus_pin,
        "schema_version": schema_version,
        "lens": lens,
        "interrogation": interrogation_result.to_dict(),
        "claims": [_claim_to_dict(claim) for claim in claims],
        "counter_position": _placeholder_counter_position(),
        "coverage_map": {},
        "confidence": _placeholder_confidence(),
        "trajectory": list(trajectory),
        "model_by_pass": dict(model_by_pass),
    }
    record["source_usage"] = compute_source_usage(record, vault_dir=vault_dir)
    return record


def persist_record(
    brief_id: str,
    record: dict[str, Any],
    *,
    analyses_dir: Path | None = None,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
) -> Path:
    """Write `record` to `<analyses_dir>/<brief_id>.json` (§7.3), keyed
    deterministically on `brief_id` exactly like
    `axial.brief.interrogate.persist_interrogation` -- re-running the same
    brief overwrites the same file rather than accumulating one per run."""
    if analyses_dir is None:
        analyses_dir = default_analyses_dir(config_path)
    analyses_dir = Path(analyses_dir)
    analyses_dir.mkdir(parents=True, exist_ok=True)
    path = analyses_dir / f"{brief_id}.json"
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def persist_markdown(
    brief_id: str,
    record: dict[str, Any],
    *,
    analyses_dir: Path | None = None,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
) -> Path:
    """Render `record` to markdown (§7.10, `axial.answer.render.render_markdown`)
    and write it to `<analyses_dir>/<brief_id>.md`, alongside the JSON record
    written by `persist_record` -- keyed on `brief_id` the same way, so
    re-running the same brief overwrites the same file rather than
    accumulating one per run."""
    if analyses_dir is None:
        analyses_dir = default_analyses_dir(config_path)
    analyses_dir = Path(analyses_dir)
    analyses_dir.mkdir(parents=True, exist_ok=True)
    path = analyses_dir / f"{brief_id}.md"
    path.write_text(render_markdown(record), encoding="utf-8")
    return path


def run_brief(
    brief: Brief,
    *,
    client: LLMClient,
    vault_dir: Path | None = None,
    envelopes_dir: Path | None = None,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
    analyses_dir: Path | None = None,
    evals_dir: Path | None = None,
    lenses_dir: Path | None = None,
    step_budget: int | None = None,
    thin_result_floor: int | None = None,
) -> BriefRunResult:
    """Run the full engine (stages 1-6) over `brief` and persist the §7.3
    analysis record to `<analyses_dir>/<brief_id>.json`, returning both.

    The corpus pin (§7.12) and the vault's `schema_version` are resolved
    FIRST, before any model call -- both are configuration-level
    preconditions of the run (a missing pin, an empty vault), not something
    the brief's own content affects, so a misconfigured install fails fast
    rather than after spending an interrogation call.

    On a `refuse` disposition (§7.2), stages 3 (retrieval) and 4
    (synthesis) never run: `claims` and `trajectory` are both empty and
    `model_by_pass` names only the interrogation pass. This is a COMPLETE
    run -- the record is still written and this function still returns
    normally; translating that into exit 0 is the CLI's job."""
    corpus_pin = resolve_pin_id(evals_dir)
    schema_version = vault_schema_version(vault_dir)

    interrogation_result = interrogate(brief, client=client, vault_dir=vault_dir)
    model_by_pass: dict[str, str] = {
        INTERROGATE_PASS_NAME: client.model_for_pass(INTERROGATE_PASS_NAME)
    }

    if interrogation_result.disposition == "refuse":
        lens = resolve_lens(brief.lens, lenses_dir=lenses_dir)
        claims: list[Claim] = []
        trajectory: list[dict[str, Any]] = []
    else:
        retrieval_result = run_planned_retrieval(
            client,
            brief,
            interrogation_result,
            vault_dir=vault_dir,
            envelopes_dir=envelopes_dir,
            config_path=config_path,
            step_budget=step_budget,
            thin_result_floor=thin_result_floor,
        )
        model_by_pass[RETRIEVE_PASS_NAME] = client.model_for_pass(RETRIEVE_PASS_NAME)

        evidence = assemble_evidence(retrieval_result.evidence_ids, vault_dir=vault_dir)
        claim_graph = synthesize(
            evidence, brief, client=client, vault_dir=vault_dir, lenses_dir=lenses_dir
        )
        model_by_pass[SYNTHESIZE_PASS_NAME] = client.model_for_pass(SYNTHESIZE_PASS_NAME)

        lens = claim_graph.lens
        claims = claim_graph.claims
        trajectory = retrieval_result.trajectory

    record = build_record(
        brief,
        interrogation_result,
        corpus_pin=corpus_pin,
        schema_version=schema_version,
        lens=lens,
        claims=claims,
        trajectory=trajectory,
        model_by_pass=model_by_pass,
        vault_dir=vault_dir,
    )
    path = persist_record(
        brief.brief_id, record, analyses_dir=analyses_dir, config_path=config_path
    )
    markdown_path = persist_markdown(
        brief.brief_id, record, analyses_dir=analyses_dir, config_path=config_path
    )
    return BriefRunResult(record=record, path=path, markdown_path=markdown_path)
