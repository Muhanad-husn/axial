"""Three Phase A jobs, re-run on openai/gpt-5.6-luna.

The Phase B/C measurement (data/logs/2026-08-05-luna-vs-glm/) covered the three
judgment-heavy passes glm-5.2 ran. This covers the layer underneath it, where
the corpus money actually goes.

  note_interrogate   glm-5.2         ~6,000 calls per full pass, reasoning OFF
  gather             deepseek-flash  once per name page, reasoning high
  envelope           deepseek-pro    once per source, reasoning high

Isolation is total on all three: the prompt is composed ONCE per sample by the
product's own composer and the identical string is sent to both models. No
upstream stage runs, so nothing but the model can differ.

Three samples per job. Both models are warmed before anything is timed.
"""

from __future__ import annotations

import json
import os
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
JOURNAL = LOG_DIR / "run.jsonl"
OUT_DIR = LOG_DIR / "outputs"

# $ per 1000 tokens, OpenRouter published rates read 2026-08-05.
ARMS = {
    "current": None,  # filled per job -- each job has its own incumbent
    "luna": ("openai/gpt-5.6-luna", 0.0001, 0.0006),
}
PRICE = {
    "z-ai/glm-5.2": (0.00076, 0.00242),
    "deepseek/deepseek-v4-flash": (0.00014, 0.00028),
    "deepseek/deepseek-v4-pro": (0.000435, 0.00087),
    "openai/gpt-5.6-luna": (0.0001, 0.0006),
}

API_KEY = tomllib.loads((REPO / "secrets" / "secrets.toml").read_text(encoding="utf-8"))[
    "openrouter"
]["api_key"]

from axial.chunk import read_chunks  # noqa: E402
from axial.envelope import compose_prompt as compose_envelope_prompt  # noqa: E402
from axial.envelope import parse_response as parse_envelope_response  # noqa: E402
from axial.gather import (  # noqa: E402
    build_packets,
    compose_gather_prompt,
    load_gather_context,
    parse_gather_response,
    split_into_batches,
)
from axial.interrogate import (  # noqa: E402
    compose_interrogation_prompt,
    frame_examples,
    parse_answer_response,
)


def journal(event: dict[str, Any]) -> None:
    event = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **event}
    with JOURNAL.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    print(json.dumps(event, ensure_ascii=False)[:280], flush=True)


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


def call(model: str, prompt: str, reasoning: str | None) -> dict[str, Any]:
    """One completion, timed. `reasoning` mirrors what config/pipeline.yaml
    sets for the pass, so each arm is asked the way the product asks it."""
    payload: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 32000,
    }
    if reasoning:
        payload["reasoning"] = {"effort": reasoning}
    started = time.perf_counter()
    with httpx.Client(timeout=900.0) as client:
        response = client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {API_KEY}"},
            json=payload,
        )
    response.raise_for_status()
    body = response.json()
    text = body["choices"][0]["message"]["content"] or ""
    usage = body.get("usage") or {}
    prompt_tokens = usage.get("prompt_tokens", 0)
    completion_tokens = usage.get("completion_tokens", 0)
    price_in, price_out = PRICE[model]
    return {
        "model": model,
        "seconds": round(time.perf_counter() - started, 2),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "usd": (prompt_tokens / 1000) * price_in + (completion_tokens / 1000) * price_out,
        "finish_reason": body["choices"][0].get("finish_reason"),
        "text": text,
    }


def run_sample(
    job: str,
    sample_id: str,
    prompt: str,
    incumbent: tuple[str, str | None],
    parse: Any,
    index: int,
    skip: set[str],
) -> None:
    """Both arms on one prompt, arm order alternating by sample."""
    incumbent_model, reasoning = incumbent
    arms = [("current", incumbent_model), ("luna", "openai/gpt-5.6-luna")]
    if index % 2:
        arms.reverse()
    for arm, model in arms:
        key = f"{job}:{sample_id}:{arm}"
        if key in skip:
            continue
        try:
            result = call(model, prompt, reasoning)
        except Exception as exc:  # noqa: BLE001
            journal(
                {
                    "event": "unit",
                    "unit_key": key,
                    "job": job,
                    "sample": sample_id,
                    "arm": arm,
                    "model": model,
                    "error": f"{type(exc).__name__}: {exc}"[:400],
                }
            )
            continue
        text = result.pop("text")
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        (OUT_DIR / f"{job}-{sample_id}-{arm}.txt").write_text(text, encoding="utf-8")
        parsed, parse_error = None, None
        try:
            parsed = parse(text)
        except Exception as exc:  # noqa: BLE001 -- a parse failure IS the finding
            parse_error = f"{type(exc).__name__}: {exc}"[:300]
        journal(
            {
                "event": "unit",
                "unit_key": key,
                "job": job,
                "sample": sample_id,
                "arm": arm,
                "prompt_chars": len(prompt),
                "response_chars": len(text),
                "parse_error": parse_error,
                "parsed": parsed if isinstance(parsed, (dict, list, str, int)) else str(parsed),
                **result,
            }
        )


# ---------------------------------------------------------------------------
# Job 1 -- the Interrogator (note_interrogate): glm-5.2, reasoning OFF
# ---------------------------------------------------------------------------


def job_interrogate(skip: set[str]) -> None:
    from axial.codebook import load_codebook
    from axial.envelope import envelope_path
    from axial.intake import source_meta_path
    from axial.schema import load_schema

    domain = REPO / "config" / "domains" / "syria"
    examples = frame_examples(load_schema(domain), load_codebook(domain))
    source_id = "ayubi-1995-16fd6a2e503f"
    envelope = json.loads(
        (REPO / "data" / "envelopes" / f"{source_id}.json").read_text(encoding="utf-8")
    )
    source_meta = json.loads(
        source_meta_path(source_id, REPO / "data" / "source_meta").read_text(encoding="utf-8")
    )
    chunks = read_chunks(source_id, chunks_dir=REPO / "data" / "chunks")

    # Three notes spanning the length distribution -- a short one, the median,
    # and a long one -- rather than three from the same part of the book.
    ordered = sorted(chunks, key=lambda c: len(c.get("text") or ""))
    picks = [ordered[len(ordered) // 10], ordered[len(ordered) // 2], ordered[-3]]

    def parse(text: str) -> Any:
        answers = parse_answer_response(text, examples)
        return {
            "fields_answered": sorted(k for k, v in answers.items() if v not in (None, "", [])),
            "answers": answers,
        }

    for index, chunk in enumerate(picks):
        prompt = compose_interrogation_prompt(chunk, source_meta, envelope, examples)
        journal(
            {
                "event": "sample",
                "job": "interrogate",
                "sample": chunk["chunk_id"],
                "chunk_chars": len(chunk.get("text") or ""),
                "prompt_chars": len(prompt),
            }
        )
        run_sample(
            "interrogate",
            chunk["chunk_id"],
            prompt,
            ("z-ai/glm-5.2", None),  # reasoning_by_pass.note_interrogate: false
            parse,
            index,
            skip,
        )


# ---------------------------------------------------------------------------
# Job 2 -- Gather: deepseek-v4-flash (llm_tier default), reasoning high
# ---------------------------------------------------------------------------


def job_gather(skip: set[str]) -> None:
    records = [
        json.loads(line)
        for line in (REPO / "data" / "names" / "disagreements.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    # Names that actually produced a disagreement, biggest first -- the band
    # config/pipeline.yaml's min_members: 10 keeps.
    landed = [r for r in records if r.get("disagreement") and r.get("chunk_ids")]
    landed.sort(key=lambda r: len(r["chunk_ids"]), reverse=True)
    picks = [landed[0], landed[len(landed) // 2], landed[-1]]

    answers_by_chunk_id, author_year = load_gather_context(
        REPO / "data" / "answers", REPO / "data" / "source_meta"
    )

    for index, record in enumerate(picks):
        canonical = record["canonical"]
        packets = build_packets(record["chunk_ids"], answers_by_chunk_id, author_year)
        batches = split_into_batches(packets)
        if not batches:
            continue
        prompt = compose_gather_prompt(canonical, batches[0])
        journal(
            {
                "event": "sample",
                "job": "gather",
                "sample": canonical,
                "members": len(record["chunk_ids"]),
                "packets": len(packets),
                "batches": len(batches),
                "prompt_chars": len(prompt),
                "baseline_disagreement": (record.get("disagreement") or "")[:300],
            }
        )
        run_sample(
            "gather",
            canonical.replace("/", "_")[:40],
            prompt,
            ("deepseek/deepseek-v4-flash", "high"),
            lambda text: {
                "disagreement": parse_gather_response(text)[0],
                "links": parse_gather_response(text)[1],
            },
            index,
            skip,
        )


# ---------------------------------------------------------------------------
# Job 3 -- the envelope: deepseek-v4-pro, reasoning high
# ---------------------------------------------------------------------------


def job_envelope(skip: set[str]) -> None:
    trees = sorted((REPO / "data" / "trees").glob("*.json"))
    picks = [trees[0], trees[len(trees) // 2], trees[-1]]
    for index, tree_path in enumerate(picks):
        tree = json.loads(tree_path.read_text(encoding="utf-8"))
        prompt = compose_envelope_prompt(tree)
        journal(
            {
                "event": "sample",
                "job": "envelope",
                "sample": tree_path.stem,
                "prompt_chars": len(prompt),
            }
        )

        def parse(text: str) -> Any:
            parsed = parse_envelope_response(text)
            return {
                "thesis_chars": len(str(parsed.get("thesis") or "")),
                "toc_entries": len(parsed.get("toc") or []),
                "scope_chars": len(str(parsed.get("scope") or "")),
                "stated_argument_chars": len(str(parsed.get("stated_argument") or "")),
                "thesis": str(parsed.get("thesis") or "")[:600],
            }

        run_sample(
            "envelope",
            tree_path.stem,
            prompt,
            ("deepseek/deepseek-v4-pro", "high"),
            parse,
            index,
            skip,
        )


def main() -> int:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    skip = done_units()
    journal({"event": "start", "skipped_units": sorted(skip)})

    for model in (
        "z-ai/glm-5.2",
        "deepseek/deepseek-v4-flash",
        "deepseek/deepseek-v4-pro",
        "openai/gpt-5.6-luna",
    ):
        started = time.perf_counter()
        try:
            call(model, "Reply with the single word: ready.", None)
            error = None
        except Exception as exc:  # noqa: BLE001
            error = f"{type(exc).__name__}: {exc}"[:200]
        journal(
            {
                "event": "warmup",
                "model": model,
                "seconds": round(time.perf_counter() - started, 2),
                "error": error,
            }
        )

    for job in (job_interrogate, job_gather, job_envelope):
        try:
            job(skip)
        except Exception as exc:  # noqa: BLE001 -- one bad job never kills the run
            journal(
                {
                    "event": "job_failed",
                    "job": job.__name__,
                    "error": f"{type(exc).__name__}: {exc}"[:500],
                }
            )
    journal({"event": "end"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
