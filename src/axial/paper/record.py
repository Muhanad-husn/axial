"""The paper record and `axial paper draft` (specs/PHASE-C.md §7.3, §8 P0-7).

`run_paper` is the whole-pipeline orchestrator: it drives stages 1 through 5
and assembles the §7.3 record, the audit surface every gate later reads. It is
the Phase-C analogue of `axial.answer.record.run_brief`, and deliberately not
an import of it -- nothing here reaches the Phase-B run path (§3 non-goal 1).

**The order is not arbitrary and two steps in it are load-bearing.**

`claims` is assembled AFTER drafting and then reduced to exactly what the
prose cited (§7.5). A claim the planner assigned and the drafter passed over
is dropped rather than carried as an orphan: a record whose claim list
overstates what the paper rests on cannot be audited by counting.

`coverage_map` is computed from the REDUCED claims, so it discloses the
coverage of what the paper actually cites rather than of what it was offered.
It is unioned from the source records, never recomputed (§7.11): Phase C
performs no retrieval of its own, so it has nothing to recompute a map over.

**Costs and model_by_pass are recorded per pass**, so a paper's spend is
attributable to planning versus drafting, and so §7.7's vendor guard has
something to read when the panel later scores this paper.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from axial.paper.biblio import build_bibliography, source_ids_for_claims
from axial.paper.brief import PaperBrief
from axial.paper.citations import build_citation_index, markers_in, reduce_to_cited
from axial.paper.claims import assert_ceilings, carried_claim, new_b_claim, new_c_claim
from axial.paper.coverage import build_coverage_map, overall_confidence
from axial.paper.draft import assign_claim_ids, draft_section, remap_local_ids
from axial.paper.intake import PaperIntake, run_intake
from axial.paper.lens import resolve_lens
from axial.paper.plan import Plan, run_plan
from axial.paper.render import render_paper
from axial.paths import ANALYSES_DIR

# Where a paper record and its rendered markdown land (§6, §7.3).
PAPERS_DIR = Path("data/papers")

# New (b)/(c) claim ids continue the same `pc-NNN` sequence as carried
# claims, so one namespace covers all three and a marker never has to say
# which it is.
_NEW_CLAIM_PREFIX = "pc"


class PaperRunError(Exception):
    """Base class for paper-run failures."""


def _source_lenses(intake: PaperIntake) -> dict[str, Any]:
    """What each NAMED source record was read through (§7.3).

    A paper drawn from records analysed under different lenses is normal and
    is not an intake rejection, but it is a fact about the paper's foundations
    a reader is owed, so it is recorded rather than flattened."""
    return {brief_id: intake.records[brief_id].get("lens") for brief_id in intake.source_analyses}


def _counter_position(
    plan: Plan, intake: PaperIntake, claims_by_id: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """The §7.3 counter-position, in the PHASE-B §7.8 shape.

    Present when the plan carried a counter-position section: its stance is
    that section's heading and its grounds are the union of its claims'
    grounds, so the field points at the same real vault ids the section cites.
    Otherwise the source records' own one-sidedness disclosure is carried
    forward, naming which records reported it.

    A source record whose own section is `failed` never contributes a
    disclosure: that state is a run that died, not a corpus with one side
    (PR #558)."""
    for section in plan.sections:
        if section.role != "counter-position":
            continue
        grounds: list[dict[str, Any]] = []
        seen: set[tuple[Any, Any]] = set()
        for claim in claims_by_id.values():
            if claim.get("section_id") != section.section_id:
                continue
            for ground in claim.get("grounds") or []:
                key = (ground.get("ref_type"), ground.get("ref_id"))
                if key not in seen:
                    seen.add(key)
                    grounds.append(dict(ground))
        return {
            "present": True,
            "stance": section.heading,
            "grounds": grounds,
            "corpus_one_sided": False,
            "one_sided_reason": None,
        }

    disclosing = [
        brief_id
        for brief_id, record in intake.records.items()
        if isinstance(cp := record.get("counter_position"), dict)
        and not cp.get("failed")
        and cp.get("corpus_one_sided") is True
    ]
    return {
        "present": False,
        "stance": None,
        "grounds": [],
        "corpus_one_sided": True,
        "one_sided_reason": (
            "every source analysis reported the corpus one-sided on this question: "
            f"{sorted(disclosing)!r}"
        ),
    }


def build_claims(
    plan: Plan,
    intake: PaperIntake,
) -> list[dict[str, Any]]:
    """Every CARRIED claim the plan assigns, in plan order (§7.4).

    New (b) and (c) claims are not built here: they do not exist until a
    section has been drafted, and they are appended one section at a time by
    `run_paper` so that each drafting call can reason across what earlier
    ones produced."""
    claim_ids = assign_claim_ids(plan)
    inventory = intake.by_key()
    section_of = {
        key: section.section_id for section in plan.sections for key in section.assigned_claims
    }

    claims: list[dict[str, Any]] = []
    for key, paper_claim_id in claim_ids.items():
        entry = inventory[key]
        source_map = intake.records[entry.brief_id].get("coverage_map") or {}
        claim = carried_claim(paper_claim_id, str(entry.claim.get("text") or ""), entry, source_map)
        claim["section_id"] = section_of.get(key)
        claims.append(claim)
    return claims


def run_paper(
    client: Any,
    paper_brief: PaperBrief,
    *,
    analyses_dir: Path | None = None,
    lenses_dir: Path | None = None,
    source_meta_dir: Path | None = None,
    vault_dir: Path | None = None,
    papers_dir: Path | None = None,
) -> dict[str, Any]:
    """Stages 1-5, end to end, returning the persisted §7.3 record."""
    papers_dir = Path(papers_dir) if papers_dir is not None else PAPERS_DIR

    intake = run_intake(paper_brief.analysis_ids, analyses_dir=analyses_dir or ANALYSES_DIR)

    lens = resolve_lens(paper_brief.lens, lenses_dir=lenses_dir)
    plan = run_plan(client, paper_brief.thesis, lens, intake)

    claim_ids = assign_claim_ids(plan)
    claims = build_claims(plan, intake)
    by_id = {claim["paper_claim_id"]: claim for claim in claims}

    drafts = []
    cited_so_far: list[dict[str, Any]] = []
    for section in plan.sections:
        draft = draft_section(
            client, plan.thesis_statement, lens, section, claim_ids, by_id, cited_so_far
        )

        # Allocate a stable id per new claim BEFORE remapping, so the prose's
        # markers and the claim list agree. Numbering continues the carried
        # sequence, so one namespace covers both kinds.
        assigned = {
            proposed.local_id: f"{_NEW_CLAIM_PREFIX}-{len(claims) + index + 1:03d}"
            for index, proposed in enumerate(draft.new_claims)
        }
        draft = remap_local_ids(draft, assigned)
        drafts.append(draft)

        for proposed in draft.new_claims:
            build = new_c_claim if proposed.kind == "c" else new_b_claim
            claim = build(proposed.local_id, proposed.text, list(proposed.derived_from), by_id)
            claim["section_id"] = draft.section_id
            claims.append(claim)
            by_id[claim["paper_claim_id"]] = claim

        # What the NEXT section may reason across is what earlier sections
        # actually cited, not everything that exists: a claim the drafter was
        # offered and passed over is not part of the argument so far.
        cited = {marker for earlier in drafts for marker in markers_in(earlier.prose)}
        cited_so_far = [claim for claim in claims if claim["paper_claim_id"] in cited]

    citations = build_citation_index(
        [{"section_id": draft.section_id, "prose": draft.prose} for draft in drafts],
        set(by_id),
    )
    claims = reduce_to_cited(claims, citations)

    source_maps = {
        brief_id: (record.get("coverage_map") or {}) for brief_id, record in intake.records.items()
    }
    assert_ceilings(claims, intake.by_key(), source_maps)

    for claim in claims:
        claim["source_ids"] = sorted(source_ids_for_claims([claim], vault_dir=vault_dir))

    # Unioned from the named source records, never recomputed (§7.11): Phase C
    # performs no retrieval of its own, so there is nothing to recompute a map
    # over.
    coverage_map = build_coverage_map(claims, intake.records)
    confidence = overall_confidence(coverage_map, intake.records)
    bibliography = build_bibliography(claims, source_meta_dir=source_meta_dir, vault_dir=vault_dir)

    markdown_path = papers_dir / f"{paper_brief.paper_brief_id}.md"
    record: dict[str, Any] = {
        "paper_brief_id": paper_brief.paper_brief_id,
        "paper_brief": {
            "thesis": paper_brief.thesis,
            "analysis_ids": list(paper_brief.analysis_ids),
            "lens": paper_brief.lens,
            "title": paper_brief.title,
        },
        "corpus_pin": intake.corpus_pin,
        "lens": lens.name,
        "source_lenses": _source_lenses(intake),
        "source_analyses": list(intake.source_analyses),
        "plan": plan.to_json(),
        "drafts": [{"section_id": draft.section_id, "prose": draft.prose} for draft in drafts],
        "claims": claims,
        "citations": [citation.to_json() for citation in citations],
        "counter_position": _counter_position(plan, intake, by_id),
        "coverage_map": coverage_map,
        "confidence": confidence,
        "bibliography": bibliography,
        "paper_markdown_path": str(markdown_path),
        "model_by_pass": dict(getattr(client, "model_by_pass", {}) or {}),
        "cost": getattr(client, "cost_report", lambda: {})(),
    }

    persist_paper(record, papers_dir=papers_dir)
    return record


def persist_paper(record: dict[str, Any], *, papers_dir: Path | None = None) -> Path:
    """Write the record and its rendered markdown side by side (§7.3, §7.10)."""
    papers_dir = Path(papers_dir) if papers_dir is not None else PAPERS_DIR
    papers_dir.mkdir(parents=True, exist_ok=True)

    paper_brief_id = record["paper_brief_id"]
    markdown_path = papers_dir / f"{paper_brief_id}.md"
    markdown_path.write_text(render_paper(record), encoding="utf-8")

    record_path = papers_dir / f"{paper_brief_id}.json"
    record_path.write_text(
        json.dumps(record, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8"
    )
    return record_path
