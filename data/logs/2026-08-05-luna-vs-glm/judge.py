"""Blind head-to-head judging of the two arms' outputs.

Three judges from three labs, none of them either model under test
(vendor distinctness is the whole point of the panel instrument, DEC-40):

  deepseek/deepseek-v4-pro   deepseek
  google/gemini-3.5-flash    google
  anthropic/claude-sonnet-5  anthropic

Each judge sees the same submission pair with the arms relabelled A/B, and
the A/B assignment FLIPS per unit, so a judge with a position bias cannot
systematically favour one arm. No judge is told which model wrote which
answer, and grounds are resolved to real passage text so grounding is
checkable rather than assumed.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import tomllib
from pathlib import Path
from typing import Any

import httpx

REPO = Path(r"D:\axial")
os.chdir(REPO)
sys.path.insert(0, str(REPO / "src"))

LOG_DIR = REPO / "data" / "logs" / "2026-08-05-luna-vs-glm"
OUT_DIR = LOG_DIR / "outputs"
JOURNAL = LOG_DIR / "judgments.jsonl"

JUDGES = [
    ("deepseek/deepseek-v4-pro", 0.000435, 0.00087),
    ("google/gemini-3.5-flash", 0.0015, 0.009),
    ("anthropic/claude-sonnet-5", 0.002, 0.010),
]

from axial.panel.packet import _resolve_reference  # noqa: E402

API_KEY = tomllib.loads((REPO / "secrets" / "secrets.toml").read_text(encoding="utf-8"))[
    "openrouter"
]["api_key"]

# A first pass at 4000 truncated three verdicts mid-JSON: these judges spend
# the budget on reasoning tokens before the object starts.
MAX_TOKENS = 12000

# When set to a list, `judge_unit` collects (unit_key, prompt, meta) instead of
# calling anything -- how `repair.py` rebuilds a prompt for a re-ask without
# re-running the judges that already answered.
COLLECT: list[Any] | None = None

VERDICT_SHAPE = """Reply with ONLY a JSON object, no prose around it. Keep every
"why" under 25 words -- a truncated object is a wasted call:

{
  "grounding":    {"winner": "A"|"B"|"tie", "why": "one sentence"},
  "completeness": {"winner": "A"|"B"|"tie", "why": "one sentence"},
  "argument":     {"winner": "A"|"B"|"tie", "why": "one sentence"},
  "attribution":  {"winner": "A"|"B"|"tie", "why": "one sentence"},
  "overall":      {"winner": "A"|"B"|"tie", "margin": "clear"|"narrow",
                   "why": "two sentences at most"}
}"""


def journal(event: dict[str, Any]) -> None:
    event = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **event}
    with JOURNAL.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    print(json.dumps(event, ensure_ascii=False)[:400], flush=True)


def done_units() -> set[str]:
    if not JOURNAL.is_file():
        return set()
    seen = set()
    for line in JOURNAL.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get("unit_key"):
            seen.add(event["unit_key"])
    return seen


def ask(model: str, prompt: str, price_in: float, price_out: float) -> dict[str, Any]:
    started = time.perf_counter()
    with httpx.Client(timeout=600.0) as client:
        response = client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {API_KEY}"},
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": MAX_TOKENS,
            },
        )
    response.raise_for_status()
    body = response.json()
    text = body["choices"][0]["message"]["content"] or ""
    usage = body.get("usage") or {}
    prompt_tokens = usage.get("prompt_tokens", 0)
    completion_tokens = usage.get("completion_tokens", 0)
    match = re.search(r"\{.*\}", text, re.S)
    try:
        verdict = json.loads(match.group(0)) if match else {"parse_error": text[:400]}
    except ValueError:
        verdict = {"parse_error": text[:400]}
    return {
        "model": model,
        "seconds": round(time.perf_counter() - started, 2),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "usd": (prompt_tokens / 1000) * price_in + (completion_tokens / 1000) * price_out,
        "verdict": verdict,
    }


def render_claims(claims: list[dict[str, Any]]) -> str:
    lines = []
    for claim in claims:
        grounds = ", ".join(str(g.get("ref_id")) for g in (claim.get("grounds") or [])) or "none"
        lines.append(
            f"- ({claim.get('kind')}, {claim.get('confidence')}) {claim.get('text')}\n"
            f"  grounds: {grounds}"
        )
    return "\n".join(lines)


def cited_ref_ids(*claim_lists: list[dict[str, Any]]) -> list[str]:
    seen: list[str] = []
    for claims in claim_lists:
        for claim in claims:
            for ground in claim.get("grounds") or []:
                ref_id = ground.get("ref_id")
                if ref_id and ref_id not in seen:
                    seen.append(str(ref_id))
    return seen


def render_evidence(ref_ids: list[str]) -> str:
    blocks = []
    for ref_id in ref_ids:
        try:
            text = _resolve_reference("chunk", ref_id, "-", None)
        except Exception:  # noqa: BLE001 -- an unresolvable ground is itself a finding
            text = "(this passage could not be resolved in the vault)"
        blocks.append(f"### {ref_id}\n{text}")
    return "\n\n".join(blocks)


def judge_unit(
    unit_key: str,
    prompt: str,
    meta: dict[str, Any],
    skip: set[str],
) -> None:
    if COLLECT is not None:
        COLLECT.append((unit_key, prompt, meta))
        return
    if unit_key in skip:
        return
    results = []
    for model, price_in, price_out in JUDGES:
        try:
            results.append(ask(model, prompt, price_in, price_out))
        except Exception as exc:  # noqa: BLE001
            results.append({"model": model, "error": f"{type(exc).__name__}: {exc}"[:400]})
    journal({"unit_key": unit_key, **meta, "prompt_chars": len(prompt), "judges": results})


# ---------------------------------------------------------------------------


def synthesis_units(skip: set[str]) -> None:
    paths = sorted(OUT_DIR.glob("synthesize-*-glm.json"))
    for index, glm_path in enumerate(paths):
        record_id = glm_path.stem.split("-")[1]
        luna_path = OUT_DIR / f"synthesize-{record_id}-luna.json"
        if not luna_path.is_file():
            continue
        glm = json.loads(glm_path.read_text(encoding="utf-8"))
        luna = json.loads(luna_path.read_text(encoding="utf-8"))
        # Flip which arm is A on alternate units.
        a_arm, b_arm = ("glm", "luna") if index % 2 == 0 else ("luna", "glm")
        a, b = (glm, luna) if a_arm == "glm" else (luna, glm)

        evidence = render_evidence(cited_ref_ids(a["claims"], b["claims"]))
        prompt = f"""You are refereeing two anonymised answers to the same research request. Both
were written from the SAME evidence set by different systems. Judge only what is
in front of you.

# The case
{a["case"]}

# The request
{a["request"]}

# The passages both answers could cite
{evidence}

# Answer A
{render_claims(a["claims"])}

# Answer B
{render_claims(b["claims"])}

Judge on four dimensions:
- grounding: does each cited passage actually support the claim it is attached to?
- completeness: does the answer address the whole request, including the part
  that asks it to test its choice?
- argument: does it commit to a position and defend it, or does it list findings?
- attribution: claims marked (a) are single-source assertions and claims marked
  (b) are the system's own cross-source inference. Are they marked honestly --
  is anything the system inferred passed off as something a source said?

More claims is not better. A longer answer is not better.

{VERDICT_SHAPE}"""
        judge_unit(
            f"synthesize:{record_id}",
            prompt,
            {
                "task": "synthesize",
                "record_id": record_id,
                "case": a["case"],
                "A": a_arm,
                "B": b_arm,
            },
            skip,
        )


def counter_units(skip: set[str]) -> None:
    paths = sorted(OUT_DIR.glob("counter-*-glm.json"))
    for index, glm_path in enumerate(paths):
        record_id = glm_path.stem.split("-")[1]
        luna_path = OUT_DIR / f"counter-{record_id}-luna.json"
        if not luna_path.is_file():
            continue
        glm = json.loads(glm_path.read_text(encoding="utf-8"))
        luna = json.loads(luna_path.read_text(encoding="utf-8"))
        a_arm, b_arm = ("luna", "glm") if index % 2 == 0 else ("glm", "luna")
        a, b = (luna, glm) if a_arm == "luna" else (glm, luna)
        if not (a["section"].get("present") and b["section"].get("present")):
            journal(
                {
                    "unit_key": f"counter:{record_id}",
                    "task": "counter_position",
                    "record_id": record_id,
                    "skipped": "one or both arms produced no counter-position section",
                    "present": {
                        a_arm: a["section"].get("present"),
                        b_arm: b["section"].get("present"),
                    },
                }
            )
            continue

        record = json.loads(
            (REPO / "data" / "analyses" / f"{record_id}.json").read_text(encoding="utf-8")
        )
        ref_ids = cited_ref_ids(
            [{"grounds": a["section"].get("grounds") or []}],
            [{"grounds": b["section"].get("grounds") or []}],
        )
        prompt = f"""Two anonymised counter-position sections were written for the SAME answer,
from the same pool of opposing evidence. A counter-position section states the
strongest version of the position the answer rejects. Judge only what is in
front of you.

# The case
{record["brief"]["case"]}

# The request
{record["brief"]["request"]}

# The answer both sections are attached to
{render_claims(record["claims"])}

# The opposing passages both sections could cite
{render_evidence(ref_ids)}

# Section A
{a["section"].get("stance")}

# Section B
{b["section"].get("stance")}

Judge on four dimensions:
- grounding: does each cited passage actually support what the section says?
- completeness: does the section state a real opposing position, or a caveat?
- argument: is the opposing position given its STRONGEST form (a steelman), or
  is it set up weakly so the answer wins (a strawman)?
- attribution: is the opposing position attributed to whoever actually holds it?

Length is not quality.

{VERDICT_SHAPE}"""
        judge_unit(
            f"counter:{record_id}",
            prompt,
            {
                "task": "counter_position",
                "record_id": record_id,
                "case": record["brief"]["case"],
                "A": a_arm,
                "B": b_arm,
            },
            skip,
        )


def paper_units(skip: set[str]) -> None:
    paths = sorted(OUT_DIR.glob("paper-*-glm.md"))
    for index, glm_path in enumerate(paths):
        stem = glm_path.stem[len("paper-") : -len("-glm")]
        luna_path = OUT_DIR / f"paper-{stem}-luna.md"
        if not luna_path.is_file():
            continue
        glm = glm_path.read_text(encoding="utf-8")
        luna = luna_path.read_text(encoding="utf-8")
        a_arm, b_arm = ("glm", "luna") if index % 2 == 0 else ("luna", "glm")
        a, b = (glm, luna) if a_arm == "glm" else (luna, glm)
        plan = json.loads((OUT_DIR / f"plan-{stem}.json").read_text(encoding="utf-8"))

        prompt = f"""Two anonymised drafts of the same paper. Both were written to the SAME plan,
from the same claims, by different systems. Judge only what is in front of you.

# The thesis both drafts were told to argue
{plan["thesis_statement"]}

# The plan both drafts followed
{json.dumps([{k: s[k] for k in ("section_id", "heading", "role")} for s in plan["sections"]], indent=2)}

# Draft A
{a}

# Draft B
{b}

A marker like [pc-004] is a citation to a numbered claim carried in from the
underlying analyses; a draft may also propose new claims of its own.

Judge on four dimensions:
- grounding: are the cited claim markers used for what they actually say, or
  decoratively?
- completeness: does each section do the job its role in the plan assigns it?
- argument: does the paper ARGUE the thesis -- sections that earn each other,
  a position defended against its alternative -- or does it summarise?
- attribution: does it keep clear what the sources said versus what the paper
  is concluding for itself?

Length is not quality. Fluency is not argument.

{VERDICT_SHAPE}"""
        judge_unit(
            f"paper:{stem}",
            prompt,
            {"task": "paper_draft", "paper": stem, "A": a_arm, "B": b_arm},
            skip,
        )


def main() -> int:
    skip = done_units()
    synthesis_units(skip)
    counter_units(skip)
    paper_units(skip)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
