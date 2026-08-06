"""Blind head-to-head judging of the Phase A arms.

Same instrument as the Phase B/C run: three judges from three labs, neither
model under test, the pair relabelled A/B with the assignment flipped per
sample, and the source material the pass was reading put in front of the judge
so faithfulness is checkable rather than assumed.
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

LOG_DIR = REPO / "data" / "logs" / "2026-08-05-luna-phase-a"
OUT_DIR = LOG_DIR / "outputs"
JOURNAL = LOG_DIR / "judgments.jsonl"

JUDGES = [
    ("deepseek/deepseek-v4-pro", 0.000435, 0.00087),
    ("google/gemini-3.5-flash", 0.0015, 0.009),
    ("anthropic/claude-sonnet-5", 0.002, 0.010),
]
MAX_TOKENS = 12000

API_KEY = tomllib.loads((REPO / "secrets" / "secrets.toml").read_text(encoding="utf-8"))[
    "openrouter"
]["api_key"]

VERDICT_SHAPE = """Reply with ONLY a JSON object, no prose around it. Keep every
"why" under 25 words -- a truncated object is a wasted call:

{
  "faithfulness": {"winner": "A"|"B"|"tie", "why": "one sentence"},
  "usefulness":   {"winner": "A"|"B"|"tie", "why": "one sentence"},
  "restraint":    {"winner": "A"|"B"|"tie", "why": "one sentence"},
  "overall":      {"winner": "A"|"B"|"tie", "margin": "clear"|"narrow",
                   "why": "two sentences at most"}
}"""


def journal(event: dict[str, Any]) -> None:
    event = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **event}
    with JOURNAL.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    print(json.dumps(event, ensure_ascii=False)[:300], flush=True)


def done_units() -> set[str]:
    if not JOURNAL.is_file():
        return set()
    return {
        json.loads(line)["unit_key"]
        for line in JOURNAL.read_text(encoding="utf-8").splitlines()
        if line.strip() and "unit_key" in json.loads(line)
    }


def ask(model: str, prompt: str, price_in: float, price_out: float) -> dict[str, Any]:
    started = time.perf_counter()
    with httpx.Client(timeout=900.0) as client:
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
        verdict = json.loads(match.group(0)) if match else {"parse_error": text[:300]}
    except ValueError:
        verdict = {"parse_error": text[:300]}
    return {
        "model": model,
        "seconds": round(time.perf_counter() - started, 2),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "usd": (prompt_tokens / 1000) * price_in + (completion_tokens / 1000) * price_out,
        "verdict": verdict,
    }


def judge_unit(unit_key: str, prompt: str, meta: dict[str, Any], skip: set[str]) -> None:
    if unit_key in skip:
        return
    results = []
    for model, price_in, price_out in JUDGES:
        try:
            results.append(ask(model, prompt, price_in, price_out))
        except Exception as exc:  # noqa: BLE001
            results.append({"model": model, "error": f"{type(exc).__name__}: {exc}"[:300]})
    journal({"unit_key": unit_key, **meta, "prompt_chars": len(prompt), "judges": results})


def pair(job: str, sample: str) -> tuple[str, str] | None:
    current = OUT_DIR / f"{job}-{sample}-current.txt"
    luna = OUT_DIR / f"{job}-{sample}-luna.txt"
    if not (current.is_file() and luna.is_file()):
        return None
    return current.read_text(encoding="utf-8"), luna.read_text(encoding="utf-8")


def samples_of(job: str) -> list[str]:
    """Sample keys read off the OUTPUT FILENAMES, not the run journal: the
    experiment truncates a gather name to 40 chars but leaves a chunk_id
    whole, so re-deriving the key from the journal missed every interrogate
    pair silently."""
    prefix, suffix = f"{job}-", "-current.txt"
    return sorted(
        path.name[len(prefix) : -len(suffix)] for path in OUT_DIR.glob(f"{job}-*-current.txt")
    )


def main() -> int:
    skip = done_units()

    # --- the Interrogator: the passage it was reading is the ground truth ---
    from axial.chunk import read_chunks

    chunks = {
        c["chunk_id"]: c
        for c in read_chunks("ayubi-1995-16fd6a2e503f", chunks_dir=REPO / "data" / "chunks")
    }
    for index, sample in enumerate(samples_of("interrogate")):
        got = pair("interrogate", sample)
        if not got:
            continue
        a_arm, b_arm = ("current", "luna") if index % 2 == 0 else ("luna", "current")
        a, b = got if a_arm == "current" else (got[1], got[0])
        text = (chunks.get(sample) or {}).get("text", "")
        prompt = f"""Two systems read the SAME passage from an academic book and answered the same
open questions about it -- what it claims, whose position it is, who it argues
against, who it cites, what it names. Judge only what is in front of you.

# The passage
{text}

# Answers A
{a}

# Answers B
{b}

Judge on three dimensions:
- faithfulness: is every answer actually supported by this passage, with nothing
  imported from outside it and nothing invented?
- usefulness: would these answers let someone find this passage later and know
  what it argues?
- restraint: the rule is to abstain on a question the passage does not support.
  Which one abstains honestly rather than filling every field?

More fields answered is NOT better. A confident answer the passage does not
support is worse than an abstention.

{VERDICT_SHAPE}"""
        judge_unit(
            f"interrogate:{sample}",
            prompt,
            {"job": "interrogate", "sample": sample, "A": a_arm, "B": b_arm},
            skip,
        )

    # --- Gather: the member notes are the ground truth ---
    from axial.gather import build_packets, load_gather_context, render_packet, split_into_batches

    records = {}
    for line in (
        (REPO / "data" / "names" / "disagreements.jsonl").read_text(encoding="utf-8").splitlines()
    ):
        if line.strip():
            record = json.loads(line)
            records[str(record["canonical"]).replace("/", "_")[:40]] = record
    answers_by_chunk_id, author_year = load_gather_context(
        REPO / "data" / "answers", REPO / "data" / "source_meta"
    )
    for index, sample in enumerate(samples_of("gather")):
        got = pair("gather", sample)
        if not got or sample not in records:
            continue
        a_arm, b_arm = ("luna", "current") if index % 2 == 0 else ("current", "luna")
        a, b = (got[1], got[0]) if a_arm == "luna" else got
        record = records[sample]
        batch = split_into_batches(
            build_packets(record["chunk_ids"], answers_by_chunk_id, author_year)
        )[0]
        rendered = "\n\n".join(render_packet(p) for p in batch)
        prompt = f"""Two systems read the SAME set of passages that all mention one name, and each
wrote one statement of what their authors disagree about. Judge only what is in
front of you.

# The name
{record["canonical"]}

# The passages
{rendered}

# Statement A
{a}

# Statement B
{b}

Judge on three dimensions:
- faithfulness: is the disagreement actually present in these passages, and are
  the positions attributed to the authors who hold them?
- usefulness: does it name a real disagreement two scholars could argue about,
  or a difference of emphasis dressed up as one?
- restraint: the correct answer is sometimes that there is NO disagreement here.
  Which one manufactures a dispute the passages do not carry?

Length is not quality.

{VERDICT_SHAPE}"""
        judge_unit(
            f"gather:{sample}",
            prompt,
            {"job": "gather", "sample": sample, "A": a_arm, "B": b_arm},
            skip,
        )

    # --- the envelope: the book's own structure is the ground truth ---
    from axial.envelope import compose_prompt as compose_envelope_prompt

    for index, sample in enumerate(samples_of("envelope")):
        got = pair("envelope", sample)
        if not got:
            continue
        a_arm, b_arm = ("current", "luna") if index % 2 == 0 else ("luna", "current")
        a, b = got if a_arm == "current" else (got[1], got[0])
        tree = json.loads((REPO / "data" / "trees" / f"{sample}.json").read_text(encoding="utf-8"))
        source = compose_envelope_prompt(tree)
        prompt = f"""Two systems were given the SAME book -- its headings, front matter and
selected pages -- and each wrote what the book argues: its thesis, its scope,
its stated argument, and a reconstructed table of contents. Judge only what is
in front of you.

# What both systems were given
{source}

# Reconstruction A
{a}

# Reconstruction B
{b}

Judge on three dimensions:
- faithfulness: is the thesis this book's actual argument, and does the
  reconstructed contents match the structure above rather than a plausible
  invention?
- usefulness: would this tell a reader what the book is for and how it is built?
- restraint: which one asserts less that the material does not support?

{VERDICT_SHAPE}"""
        judge_unit(
            f"envelope:{sample}",
            prompt,
            {"job": "envelope", "sample": sample, "A": a_arm, "B": b_arm},
            skip,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
