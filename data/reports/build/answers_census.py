"""Two censuses over the answer records, matching the per-kind name census.

  questions.csv        one row per §7.15 question: how many notes answer it,
                       abstain on it, return an empty list, or carry no key
                       at all (the mixed-frame third state, D7/#496).
  questions-by-source.csv   the same four states per question per source.
  name-substance.csv   one row per name page: of its member notes, how many
                       carry a claim, a position, an opponent, citations, and
                       so on. Joins the kind census to what the notes say.

Counts only -- no answer text is written out.
"""

from __future__ import annotations

import collections
import csv
import json
import re
from pathlib import Path

from axial.query.reader import is_abstention

REPO = Path(__file__).resolve().parents[3]
ANSWERS = REPO / "data" / "answers"
VAULT = REPO / "data" / "vault"
OUT = REPO / "data" / "reports" / "names-by-kind"

# §7.15's question set, in the order the spec lists it. `*_nearest` keys are
# the frame's example-fit annotations, not questions, and are skipped.
QUESTIONS = [
    "about",
    "claim",
    "move",
    "ranges_over",
    "stops_holding",
    "position_of",
    "position",
    "arguing_against",
    "names",
    "citations",
    "mechanism",
    "evidence",
    "comparison",
    "defines",
    "uses",
    "concedes",
    "assumes",
]

# The per-page substance columns: a member note "carries" one of these when
# the field is answered (not absent, not an abstention, not empty).
SUBSTANCE = ["claim", "position", "position_of", "arguing_against", "citations", "mechanism",
             "evidence", "comparison", "defines", "concedes", "assumes"]


def state(record: dict, field: str) -> str:
    """One of: missing (no key), abstained, empty, answered."""
    if field not in record:
        return "missing"
    value = record[field]
    if value is None:
        return "missing"
    if is_abstention(value):
        return "abstained"
    if isinstance(value, (list, dict, str)) and len(value) == 0:
        return "empty"
    return "answered"


def write_csv(path: Path, rows: list[dict], columns: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    per_question: dict[str, collections.Counter[str]] = collections.defaultdict(
        collections.Counter
    )
    per_source: dict[tuple[str, str], collections.Counter[str]] = collections.defaultdict(
        collections.Counter
    )
    substance_by_chunk: dict[str, frozenset[str]] = {}
    notes = 0

    for path in sorted(ANSWERS.glob("*.jsonl")):
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                record = json.loads(line)
                answers = record.get("answers") or {}
                source = record.get("source_id") or path.stem
                notes += 1
                for field in QUESTIONS:
                    value = state(answers, field)
                    per_question[field][value] += 1
                    per_source[(source, field)][value] += 1
                substance_by_chunk[record["chunk_id"]] = frozenset(
                    field for field in SUBSTANCE if state(answers, field) == "answered"
                )

    OUT.mkdir(parents=True, exist_ok=True)

    rows = []
    for field in QUESTIONS:
        counts = per_question[field]
        rows.append(
            {
                "question": field,
                "notes": notes,
                "answered": counts["answered"],
                "answered_pct": round(100 * counts["answered"] / notes, 1),
                "abstained": counts["abstained"],
                "abstained_pct": round(100 * counts["abstained"] / notes, 1),
                "empty": counts["empty"],
                "missing_key": counts["missing"],
                "missing_key_pct": round(100 * counts["missing"] / notes, 1),
            }
        )
    write_csv(OUT / "questions.csv", rows, list(rows[0].keys()))

    source_rows = []
    for (source, field), counts in sorted(per_source.items()):
        total = sum(counts.values())
        source_rows.append(
            {
                "source_id": source,
                "question": field,
                "notes": total,
                "answered": counts["answered"],
                "answered_pct": round(100 * counts["answered"] / total, 1),
                "abstained": counts["abstained"],
                "empty": counts["empty"],
                "missing_key": counts["missing"],
            }
        )
    write_csv(OUT / "questions-by-source.csv", source_rows, list(source_rows[0].keys()))

    # Per name page: how much substance its member notes carry. The page index
    # gives kind and counts; the page body gives the member chunk ids.
    member_link = re.compile(r"^- \[\[([^\]]+)\]\]", re.MULTILINE)
    page_rows = []
    for line in (VAULT / "names.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        page = json.loads(line)
        text = (VAULT / "names" / page["filename"]).read_text(encoding="utf-8")
        members = member_link.findall(text)
        tally: collections.Counter[str] = collections.Counter()
        known = 0
        for chunk_id in members:
            fields = substance_by_chunk.get(chunk_id)
            if fields is None:
                continue
            known += 1
            tally.update(fields)
        row = {
            "canonical": page["name"],
            "kind": page.get("kind") or "(unspecified)",
            "member_count": page.get("member_count", 0),
            "source_count": page.get("source_count", 0),
            "notes_resolved": known,
        }
        row.update({f"notes_with_{field}": tally[field] for field in SUBSTANCE})
        page_rows.append(row)

    page_rows.sort(key=lambda r: (r["kind"], -r["member_count"], r["canonical"].lower()))
    write_csv(OUT / "name-substance.csv", page_rows, list(page_rows[0].keys()))

    unresolved = sum(1 for r in page_rows if r["notes_resolved"] < r["member_count"])
    print(f"notes {notes}  pages {len(page_rows)}  pages with unresolved members {unresolved}")
    print(f"{'question':<18}{'answered':>10}{'%':>7}{'abstain':>9}{'empty':>8}{'no key':>8}")
    for row in rows:
        print(
            f"{row['question']:<18}{row['answered']:>10}{row['answered_pct']:>7}"
            f"{row['abstained']:>9}{row['empty']:>8}{row['missing_key']:>8}"
        )

    print()
    by_kind: dict[str, collections.Counter[str]] = collections.defaultdict(collections.Counter)
    for row in page_rows:
        counter = by_kind[row["kind"]]
        counter["pages"] += 1
        counter["notes"] += row["notes_resolved"]
        for field in ("claim", "position", "arguing_against", "citations"):
            counter[field] += row[f"notes_with_{field}"]
    print(f"{'kind':<24}{'notes':>8}{'claim':>8}{'position':>10}{'against':>9}{'cites':>8}")
    for kind, counter in sorted(by_kind.items(), key=lambda kv: -kv[1]["pages"]):
        print(
            f"{kind:<24}{counter['notes']:>8}{counter['claim']:>8}"
            f"{counter['position']:>10}{counter['arguing_against']:>9}{counter['citations']:>8}"
        )


if __name__ == "__main__":
    main()
