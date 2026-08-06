"""Three hard glm-5.2 passes, re-run on openai/gpt-5.6-luna.

The three passes config routes to `z-ai/glm-5.2` today and that are
judgment calls rather than volume work:

  synthesize                  Phase B stage-4 (production_synthesis)
  counter_position_generate   Phase B section 7.8 (production_counter_position)
  paper_draft                 Phase C stage-3 (production_paper_draft)

(The fourth glm pass, `note_interrogate`, is the ~6,000-call per-note pass
with reasoning OFF -- volume, not judgment. Out of scope here.)

Each pass is isolated so the MODEL is the only variable:

  synthesize   the evidence set is rebuilt once from a persisted record's
               trajectory (LLM-free: assemble_evidence_ids -> assemble_evidence)
               and the same EvidenceSet object is handed to both arms. No
               retrieval runs, so retrieval's own run-to-run variance cannot
               leak into the comparison.
  counter      both arms are handed the SAME baseline claim graph (the
               persisted record's claims) and the same trajectory, so this
               measures the counter-position call alone rather than each
               arm's own upstream answer.
  paper_draft  intake and arc planning run ONCE per paper on deepseek-v4-pro,
               and both arms draft every section from that identical plan.

Both arms are warmed with one throwaway call under the synthesis pass name
before anything is timed: glm-5.2 always cold-starts, and a cold first call
would otherwise be charged to the first unit.
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

REPO = Path(r"D:\axial")
os.chdir(REPO)
sys.path.insert(0, str(REPO / "src"))

LOG_DIR = REPO / "data" / "logs" / "2026-08-05-luna-vs-glm"
JOURNAL = LOG_DIR / "run.jsonl"
OUT_DIR = LOG_DIR / "outputs"
LUNA_SECRETS = Path(
    r"C:\Users\mou97\AppData\Local\Temp\claude\D--axial\ae50754a-357a-4b32-9219-3a15ef4d390a"
    r"\scratchpad\secrets-luna.toml"
)

# $ per 1000 tokens, read from OpenRouter's /models endpoint 2026-08-05.
# glm-5.2 matches src/axial/llm.py's PRICE_TABLE_USD_PER_1K; luna is absent
# from that table (it would report null cost), which is why cost is computed
# here rather than read off a record.
PRICE = {
    "z-ai/glm-5.2": {"input": 0.00076, "output": 0.00242},
    "openai/gpt-5.6-luna": {"input": 0.0001, "output": 0.0006},
    "deepseek/deepseek-v4-pro": {"input": 0.000435, "output": 0.00087},
}

# Four persisted records, spanning the evidence-set sizes the vault produces
# (small to large), all four contested so the counter-position pass fires.
RECORD_IDS = [
    "124f7ba6ff8927c7",  # Syria, 2000-2011              (smallest, 24 notes)
    "080d9e472fc56a34",  # The Syrian civil war 2011-2021 (34)
    "fd0c2636d456d0fc",  # Syria 2011-2024, AANES/SDF     (largest, 83)
]

PAPER_BRIEFS = [
    "config/paper_briefs/dev/hollow-or-durable.yaml",
    "config/paper_briefs/dev/one-sovereign-or-several.yaml",
    "config/paper_briefs/dev/the-long-arc.yaml",
]

from axial.analyze.assembly import assemble_evidence  # noqa: E402
from axial.analyze.synthesis import (  # noqa: E402
    generate_counter_position,
    synthesize,
)
from axial.answer.record import _claim_to_dict  # noqa: E402
from axial.brief.intake import Brief  # noqa: E402
from axial.llm import (  # noqa: E402
    COUNTER_POSITION_GENERATE_PASS_NAME,
    PAPER_DRAFT_PASS_NAME,
    PAPER_PLAN_PASS_NAME,
    SECRETS_PATH_ENV_VAR,
    SYNTHESIZE_PASS_NAME,
    get_client,
)
from axial.paper.brief import load_paper_brief  # noqa: E402
from axial.paper.citations import markers_in  # noqa: E402
from axial.paper.claims import (  # noqa: E402
    MIN_DISTINCT_RECORDS,
    new_b_claim,
    new_c_claim,
)
from axial.paper.draft import (  # noqa: E402
    assign_claim_ids,
    draft_section,
    remap_local_ids,
)
from axial.paper.intake import run_intake  # noqa: E402
from axial.paper.lens import resolve_lens as resolve_paper_lens  # noqa: E402
from axial.paper.plan import run_plan  # noqa: E402
from axial.paper.record import build_claims  # noqa: E402
from axial.paper.shape import run_shape_check  # noqa: E402
from axial.retrieve.loop import assemble_evidence_ids  # noqa: E402


def journal(event: dict[str, Any]) -> None:
    """One record per unit of work, fsynced -- a killed run keeps what it
    bought (harness convention; #649 lost three paid runs to buffering)."""
    event = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **event}
    with JOURNAL.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    print(json.dumps(event, ensure_ascii=False)[:300], flush=True)


def done_units() -> set[str]:
    if not JOURNAL.is_file():
        return set()
    seen = set()
    for line in JOURNAL.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get("event") == "unit" and event.get("unit_key"):
            seen.add(event["unit_key"])
    return seen


def build_arm(secrets_path: Path | None):
    previous = os.environ.get(SECRETS_PATH_ENV_VAR)
    if secrets_path is None:
        os.environ.pop(SECRETS_PATH_ENV_VAR, None)
    else:
        os.environ[SECRETS_PATH_ENV_VAR] = str(secrets_path)
    try:
        return get_client()
    finally:
        if previous is None:
            os.environ.pop(SECRETS_PATH_ENV_VAR, None)
        else:
            os.environ[SECRETS_PATH_ENV_VAR] = previous


class Meter:
    """Wall clock and token usage for one call (or one section loop), read
    off the client's own per-pass accumulator."""

    def __init__(self, client: Any, pass_name: str) -> None:
        self.client = client
        self.pass_name = pass_name

    def __enter__(self) -> Meter:
        before = self.client.usage_for_pass(self.pass_name) or {}
        self._before = dict(before)
        self._start = time.perf_counter()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.seconds = time.perf_counter() - self._start
        after = self.client.usage_for_pass(self.pass_name) or {}
        self.prompt_tokens = after.get("prompt_tokens", 0) - self._before.get("prompt_tokens", 0)
        self.completion_tokens = after.get("completion_tokens", 0) - self._before.get(
            "completion_tokens", 0
        )

    def report(self, model: str) -> dict[str, Any]:
        price = PRICE.get(model)
        usd = None
        if price is not None:
            usd = (self.prompt_tokens / 1000) * price["input"] + (
                self.completion_tokens / 1000
            ) * price["output"]
        return {
            "model": model,
            "seconds": round(self.seconds, 2),
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "usd": usd,
        }


def write_output(name: str, payload: Any) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / name
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
    else:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Task 1 + 2: synthesize and counter_position_generate
# ---------------------------------------------------------------------------


def brief_of(record: dict[str, Any]) -> Brief:
    payload = record["brief"]
    return Brief(
        brief_id=payload["brief_id"],
        case=payload["case"],
        request=payload["request"],
        lens=payload.get("lens"),
        weights=payload.get("weights") or {},
        fork_answer=payload.get("fork_answer"),
    )


def run_brief_tasks(arms: dict[str, Any], skip: set[str]) -> None:
    for index, record_id in enumerate(RECORD_IDS):
        record = json.loads(
            (REPO / "data" / "analyses" / f"{record_id}.json").read_text(encoding="utf-8")
        )
        brief = brief_of(record)
        trajectory = record["trajectory"]
        question_scope = (record.get("interrogation") or {}).get("question_scope")

        evidence_ids = assemble_evidence_ids(trajectory, brief.weights)
        evidence = assemble_evidence(evidence_ids)
        journal(
            {
                "event": "evidence",
                "record_id": record_id,
                "case": brief.case,
                "assembled": len(evidence.chunk_ids),
                "baseline_assembled": (record.get("evidence") or {}).get("assembled_count"),
            }
        )

        # Alternate which arm goes first so provider load drift over the run
        # cannot systematically favour one of them.
        order = ["glm", "luna"] if index % 2 == 0 else ["luna", "glm"]

        for arm_name in order:
            client = arms[arm_name]
            key = f"synthesize:{record_id}:{arm_name}"
            if key in skip:
                continue
            model = client.model_for_pass(SYNTHESIZE_PASS_NAME)
            try:
                with Meter(client, SYNTHESIZE_PASS_NAME) as meter:
                    graph = synthesize(
                        evidence,
                        brief,
                        client=client,
                        question_scope=question_scope,
                    )
            except Exception as exc:  # noqa: BLE001 -- a failed arm is a result
                journal(
                    {
                        "event": "unit",
                        "unit_key": key,
                        "task": "synthesize",
                        "record_id": record_id,
                        "arm": arm_name,
                        "model": model,
                        "error": f"{type(exc).__name__}: {exc}"[:600],
                    }
                )
                continue
            claims = [_claim_to_dict(claim) for claim in graph.claims]
            write_output(
                f"synthesize-{record_id}-{arm_name}.json",
                {
                    "case": brief.case,
                    "request": brief.request,
                    "lens": graph.lens,
                    "model": model,
                    "claims": claims,
                },
            )
            journal(
                {
                    "event": "unit",
                    "unit_key": key,
                    "task": "synthesize",
                    "record_id": record_id,
                    "case": brief.case,
                    "arm": arm_name,
                    "claim_count": len(claims),
                    "kind_a": sum(1 for c in claims if c.get("kind") == "a"),
                    "kind_b": sum(1 for c in claims if c.get("kind") == "b"),
                    "grounds_total": sum(len(c.get("grounds") or []) for c in claims),
                    "composed_count": graph.evidence_composed_count,
                    "assembled_count": len(evidence.chunk_ids),
                    **meter.report(model),
                }
            )

        # Counter-position: BOTH arms get the persisted record's own claims,
        # so the two calls see identical input.
        baseline_claims = record["claims"]
        for arm_name in reversed(order):
            client = arms[arm_name]
            key = f"counter:{record_id}:{arm_name}"
            if key in skip:
                continue
            model = client.model_for_pass(COUNTER_POSITION_GENERATE_PASS_NAME)
            try:
                with Meter(client, COUNTER_POSITION_GENERATE_PASS_NAME) as meter:
                    result = generate_counter_position(
                        baseline_claims,
                        brief,
                        client=client,
                        trajectory=trajectory,
                    )
            except Exception as exc:  # noqa: BLE001
                journal(
                    {
                        "event": "unit",
                        "unit_key": key,
                        "task": "counter_position",
                        "record_id": record_id,
                        "arm": arm_name,
                        "model": model,
                        "error": f"{type(exc).__name__}: {exc}"[:600],
                    }
                )
                continue
            section = result.section
            write_output(
                f"counter-{record_id}-{arm_name}.json",
                {"case": brief.case, "model": model, "section": section},
            )
            journal(
                {
                    "event": "unit",
                    "unit_key": key,
                    "task": "counter_position",
                    "record_id": record_id,
                    "case": brief.case,
                    "arm": arm_name,
                    "model_called": result.model_called,
                    "present": section.get("present"),
                    "stance_chars": len(section.get("stance") or ""),
                    "grounds": len(section.get("grounds") or []),
                    **meter.report(model),
                }
            )


# ---------------------------------------------------------------------------
# Task 3: paper_draft
# ---------------------------------------------------------------------------


def run_paper_tasks(arms: dict[str, Any], plan_client: Any, skip: set[str]) -> None:
    for index, brief_path in enumerate(PAPER_BRIEFS):
        try:
            run_one_paper(arms, plan_client, skip, index, brief_path)
        except Exception as exc:  # noqa: BLE001 -- one bad paper never kills the run
            journal(
                {
                    "event": "paper_failed",
                    "paper": Path(brief_path).stem,
                    "error": f"{type(exc).__name__}: {exc}"[:600],
                }
            )


def run_one_paper(
    arms: dict[str, Any],
    plan_client: Any,
    skip: set[str],
    index: int,
    brief_path: str,
) -> None:
    if True:
        paper_brief = load_paper_brief(brief_path)
        stem = Path(brief_path).stem
        intake = run_intake(paper_brief.analysis_ids)
        lens = resolve_paper_lens(paper_brief.lens)

        # ONE plan, both arms. Planning is production_paper_plan
        # (deepseek-v4-pro) in both wirings and is not under test; running it
        # once removes its own run-to-run variance from the draft comparison.
        plan_path = OUT_DIR / f"plan-{stem}.json"
        with Meter(plan_client, PAPER_PLAN_PASS_NAME) as plan_meter:
            plan = run_plan(plan_client, paper_brief.thesis, lens, intake)
        journal(
            {
                "event": "plan",
                "paper": stem,
                "sections": len(plan.sections),
                "thesis": plan.thesis_statement[:200],
                **plan_meter.report(plan_client.model_for_pass(PAPER_PLAN_PASS_NAME)),
            }
        )
        write_output(
            plan_path.name,
            {
                "thesis_statement": plan.thesis_statement,
                "sections": [
                    {
                        "section_id": s.section_id,
                        "heading": s.heading,
                        "role": s.role,
                        "assigned_claims": [list(k) for k in s.assigned_claims],
                    }
                    for s in plan.sections
                ],
            },
        )

        claim_ids = assign_claim_ids(plan)
        order = ["luna", "glm"] if index % 2 == 0 else ["glm", "luna"]

        for arm_name in order:
            client = arms[arm_name]
            key = f"paper_draft:{stem}:{arm_name}"
            if key in skip:
                continue
            model = client.model_for_pass(PAPER_DRAFT_PASS_NAME)

            claims = build_claims(plan, intake)
            by_id = {claim["paper_claim_id"]: claim for claim in claims}
            drafts: list[Any] = []
            cited_so_far: list[dict[str, Any]] = []
            failed = None
            with Meter(client, PAPER_DRAFT_PASS_NAME) as meter:
                try:
                    for section in plan.sections:
                        draft = draft_section(
                            client,
                            plan.thesis_statement,
                            lens,
                            section,
                            claim_ids,
                            by_id,
                            cited_so_far,
                            cross_source_possible=(
                                len(intake.source_analyses) >= MIN_DISTINCT_RECORDS
                            ),
                        )
                        assigned = {
                            proposed.local_id: f"pc-{len(claims) + offset + 1:03d}"
                            for offset, proposed in enumerate(draft.new_claims)
                        }
                        draft = remap_local_ids(draft, assigned)
                        drafts.append(draft)
                        for proposed in draft.new_claims:
                            build = new_c_claim if proposed.kind == "c" else new_b_claim
                            claim = build(
                                proposed.local_id,
                                proposed.text,
                                list(proposed.derived_from),
                                by_id,
                            )
                            claim["section_id"] = draft.section_id
                            claims.append(claim)
                            by_id[claim["paper_claim_id"]] = claim
                        cited = {m for earlier in drafts for m in markers_in(earlier.prose)}
                        cited_so_far = [c for c in claims if c["paper_claim_id"] in cited]
                except Exception as exc:  # noqa: BLE001
                    failed = f"{type(exc).__name__}: {exc}"[:600]

            prose = "\n\n".join(
                f"## {section.heading}\n\n{draft.prose}"
                for section, draft in zip(plan.sections, drafts)
            )
            write_output(f"paper-{stem}-{arm_name}.md", prose)

            shape = None
            if not failed:
                prose_by_section = {d.section_id: d.prose for d in drafts}
                shape_result = run_shape_check(
                    plan_client,
                    plan.thesis_statement,
                    [
                        {
                            "section_id": s.section_id,
                            "heading": s.heading,
                            "role": s.role,
                            "prose": prose_by_section.get(s.section_id, ""),
                        }
                        for s in plan.sections
                    ],
                )
                shape = {
                    "model": shape_result.model,
                    "band": shape_result.band,
                    "defects": [
                        {"section_id": d.section_id, "note": d.note} for d in shape_result.defects
                    ],
                }
                write_output(f"shape-{stem}-{arm_name}.json", shape)

            journal(
                {
                    "event": "unit",
                    "unit_key": key,
                    "task": "paper_draft",
                    "paper": stem,
                    "arm": arm_name,
                    "sections_drafted": len(drafts),
                    "prose_chars": len(prose),
                    "new_claims": sum(len(d.new_claims) for d in drafts),
                    "new_b": sum(1 for d in drafts for n in d.new_claims if n.kind == "b"),
                    "new_c": sum(1 for d in drafts for n in d.new_claims if n.kind == "c"),
                    "retries": sum(d.retries for d in drafts),
                    "shape": shape,
                    "error": failed,
                    **meter.report(model),
                }
            )


def main() -> int:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    skip = done_units()

    arms = {"glm": build_arm(None), "luna": build_arm(LUNA_SECRETS)}
    plan_client = arms["glm"]  # paper_plan resolves to deepseek-v4-pro in both

    journal(
        {
            "event": "start",
            "skipped_units": sorted(skip),
            "wiring": {
                arm: {
                    "synthesize": client.model_for_pass(SYNTHESIZE_PASS_NAME),
                    "counter_position_generate": client.model_for_pass(
                        COUNTER_POSITION_GENERATE_PASS_NAME
                    ),
                    "paper_draft": client.model_for_pass(PAPER_DRAFT_PASS_NAME),
                    "paper_plan": client.model_for_pass(PAPER_PLAN_PASS_NAME),
                }
                for arm, client in arms.items()
            },
        }
    )

    # Warm both models before anything is timed (glm-5.2 always cold-starts).
    for arm_name, client in arms.items():
        start = time.perf_counter()
        try:
            client.complete("Reply with the single word: ready.", pass_name=SYNTHESIZE_PASS_NAME)
            error = None
        except Exception as exc:  # noqa: BLE001
            error = f"{type(exc).__name__}: {exc}"[:300]
        journal(
            {
                "event": "warmup",
                "arm": arm_name,
                "model": client.model_for_pass(SYNTHESIZE_PASS_NAME),
                "seconds": round(time.perf_counter() - start, 2),
                "error": error,
            }
        )

    run_brief_tasks(arms, skip)
    run_paper_tasks(arms, plan_client, skip)
    journal({"event": "end"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
