"""#785: what flipping the unconfigured citation mode from `locator` to
`passage` actually moves, over the 19 records in `data/analyses/`.

No model calls. Pure resolution against `data/vault/`.

Three questions, one per column of the run record:

1. Does the reader-facing answer gain quotes? (`render_reader_answer` over a
   record resolved in each mode.)
2. Does `rendered_word_count` move? It is reported by
   `run_report.py:681` as `len(render_markdown(record).split())`, on the
   RAW record -- the hazard comment on #785 says the flip moves it.
3. Does the sealed reviewer packet gain text? Its `analysis_markdown` is
   `render_markdown(record)` on the same raw record.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

from axial.answer.reader import render_reader_answer
from axial.answer.render import render_markdown
from axial.query.citations import resolve_record_citations

ANALYSES = Path("data/analyses")
VAULT = Path("data/vault")
LOG = Path("data/logs/2026-08-17-785-citation-default-flip")


def _quote_count(record: dict) -> int:
    total = 0
    groups = [claim.get("grounds") for claim in (record.get("claims") or [])]
    counter = record.get("counter_position")
    if isinstance(counter, dict):
        groups.append(counter.get("grounds"))
    for grounds in groups:
        if not isinstance(grounds, list):
            continue
        for ground in grounds:
            if isinstance(ground, dict) and isinstance(ground.get("citation"), dict):
                if ground["citation"].get("quote"):
                    total += 1
    return total


def main() -> None:
    LOG.mkdir(parents=True, exist_ok=True)
    records = []
    with (LOG / "run.jsonl").open("w", encoding="utf-8") as handle:
        for path in sorted(ANALYSES.glob("*.json")):
            raw = json.loads(path.read_text(encoding="utf-8"))

            locator = resolve_record_citations(
                copy.deepcopy(raw), citation_mode="locator", vault_dir=VAULT
            )
            passage = resolve_record_citations(
                copy.deepcopy(raw), citation_mode="passage", vault_dir=VAULT
            )

            row = {
                "brief_id": raw.get("brief_id") or path.stem,
                "claims": len(raw.get("claims") or []),
                "quotes_locator": _quote_count(locator),
                "quotes_passage": _quote_count(passage),
                "reader_words_locator": len(render_reader_answer(locator).split()),
                "reader_words_passage": len(render_reader_answer(passage).split()),
                # The audit render, on the RAW record -- the exact input the
                # reviewer packet, the dismissal judge and the reported
                # `rendered_word_count` all take.
                "rendered_word_count_raw": len(render_markdown(raw).split()),
            }
            records.append(row)
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    n = len(records)
    print(f"records: {n}")
    print(f"quotes resolved, locator mode: {sum(r['quotes_locator'] for r in records)}")
    print(f"quotes resolved, passage mode: {sum(r['quotes_passage'] for r in records)}")
    before = sum(r["reader_words_locator"] for r in records)
    after = sum(r["reader_words_passage"] for r in records)
    print(f"reader words, locator: {before}")
    print(f"reader words, passage: {after}  (+{after - before}, x{after / before:.2f})")
    print(f"rendered_word_count (audit, raw record): {sum(r['rendered_word_count_raw'] for r in records)}")
    zero = [r["brief_id"] for r in records if r["quotes_passage"] == 0]
    print(f"records resolving no quote at all in passage mode: {len(zero)} {zero}")


if __name__ == "__main__":
    main()
