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


def _skeleton(record: dict) -> str:
    """`render_reader_answer`'s output with every quoted passage replaced by
    a one-line stand-in naming its source and length.

    The issue's third "done when" is about PLACEMENT -- the quote sits under
    the claim it grounds, not in an appendix -- and a count of resolved
    quotes cannot show placement. This can, and reproduces no book text, so
    it is safe to commit (DEC-23)."""
    lines: list[str] = []
    run: list[str] = []

    def flush() -> None:
        if run:
            words = sum(len(line.split()) for line in run)
            lines.append(f"  > [passage: {words} words, {len(run)} lines]")
            run.clear()

    for line in render_reader_answer(record).splitlines():
        stripped = line.strip()
        if stripped.startswith(">"):
            run.append(stripped[1:])
        else:
            flush()
            lines.append(line)
    flush()
    return "\n".join(lines)


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
    skeletons: list[str] = []
    with (LOG / "run.jsonl").open("w", encoding="utf-8") as handle:
        for path in sorted(ANALYSES.glob("*.json")):
            raw = json.loads(path.read_text(encoding="utf-8"))

            # The `rendered_word_count` BEFORE anything runs. Captured first,
            # because the whole question is whether the production path moves
            # it out from under the three consumers that read it.
            audit_before = len(render_markdown(raw).split())

            # Exactly what `persist_markdown` and `GET /asks/{id}/paper` do,
            # in each mode: resolve a copy, leave `raw` alone.
            locator = resolve_record_citations(
                copy.deepcopy(raw), citation_mode="locator", vault_dir=VAULT
            )
            passage = resolve_record_citations(
                copy.deepcopy(raw), citation_mode="passage", vault_dir=VAULT
            )

            # ... and the same count AFTER both resolutions have run. If a
            # resolution ever mutated the caller's record, this diverges.
            audit_after = len(render_markdown(raw).split())

            row = {
                "brief_id": raw.get("brief_id") or path.stem,
                "claims": len(raw.get("claims") or []),
                "quotes_locator": _quote_count(locator),
                "quotes_passage": _quote_count(passage),
                "reader_words_locator": len(render_reader_answer(locator).split()),
                "reader_words_passage": len(render_reader_answer(passage).split()),
                # The audit render -- the exact input the reviewer packet,
                # the dismissal judge and the reported `rendered_word_count`
                # all take. Two independent counts, not one printed twice.
                "audit_words_before": audit_before,
                "audit_words_after_both_resolutions": audit_after,
                "raw_record_gained_a_citation_key": _quote_count(raw) > 0
                or any(
                    isinstance(ground, dict) and "citation" in ground
                    for claim in (raw.get("claims") or [])
                    for ground in (claim.get("grounds") or [])
                ),
            }
            records.append(row)
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

            skeletons.append(_skeleton(passage))

    n = len(records)
    print(f"records: {n}")
    print(f"quotes resolved, locator mode: {sum(r['quotes_locator'] for r in records)}")
    print(f"quotes resolved, passage mode: {sum(r['quotes_passage'] for r in records)}")
    before = sum(r["reader_words_locator"] for r in records)
    after = sum(r["reader_words_passage"] for r in records)
    print(f"reader words, locator: {before}")
    print(f"reader words, passage: {after}  (+{after - before}, x{after / before:.2f})")
    audit_before = sum(r["audit_words_before"] for r in records)
    audit_after = sum(r["audit_words_after_both_resolutions"] for r in records)
    print(f"rendered_word_count, before either resolution: {audit_before}")
    print(f"rendered_word_count, after both resolutions:   {audit_after}")
    mutated = [r["brief_id"] for r in records if r["raw_record_gained_a_citation_key"]]
    print(f"records whose raw object gained a citation key: {len(mutated)} {mutated}")
    zero = [r["brief_id"] for r in records if r["quotes_passage"] == 0]
    print(f"records resolving no quote at all in passage mode: {len(zero)} {zero}")

    # Placement, not just presence: the reader render with every quote
    # replaced by its own word count. No book text, so this commits.
    (LOG / "placement-skeleton.txt").write_text(
        "\n\n---\n\n".join(skeletons), encoding="utf-8"
    )
    print(f"placement skeleton written: {LOG / 'placement-skeleton.txt'}")


if __name__ == "__main__":
    main()
