"""Emit a per-kind census of the name pages.

Sources, all already on disk -- nothing is re-asked and no model is called:
  data/vault/names.jsonl      one row per surviving page: name, filename, kind,
                              member_count, source_count (materialize, #634)
  data/names/alias_map.json   canonical -> aliases
  data/names/inventory.jsonl  per-surface occurrence counts
  data/names/disagreements.jsonl  which pages Gather found a disagreement on
  data/vault/names/*.md       the member links, read only for their source ids

Writes data/reports/names-by-kind/: `_index.csv` (one row per kind),
`all-names.csv` (every page), and one CSV per kind. Counts and source ids
only -- no claim text leaves the vault.
"""

from __future__ import annotations

import collections
import csv
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
VAULT = REPO / "data" / "vault"
NAMES = REPO / "data" / "names"
OUT = REPO / "data" / "reports" / "names-by-kind"

MEMBER_LINK = re.compile(r"^- \[\[([^\]]+)\]\]", re.MULTILINE)
NOTE_SOURCE = re.compile(r"^(.+?)-[0-9a-f]{12}_")

COLUMNS = [
    "canonical",
    "kind",
    "member_count",
    "source_count",
    "occurrences",
    "alias_count",
    "has_disagreement",
    "sources",
    "aliases",
    "page",
]


def slug(kind: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", kind.lower()).strip("-") or "unspecified"


def sources_of(path: Path) -> list[str]:
    """The source ids behind one page's member links."""
    if not path.exists():
        return []
    found = set()
    for note in MEMBER_LINK.findall(path.read_text(encoding="utf-8")):
        match = NOTE_SOURCE.match(note)
        if match:
            found.add(match.group(1))
    return sorted(found)


def write_csv(path: Path, records: list[dict], columns: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(records)


def main() -> None:
    pages = [
        json.loads(line)
        for line in (VAULT / "names.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    aliases_of = {
        node["canonical"]: node.get("aliases") or []
        for node in json.loads((NAMES / "alias_map.json").read_text(encoding="utf-8"))["nodes"]
    }

    surface_counts: collections.Counter[str] = collections.Counter()
    with (NAMES / "inventory.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            record = json.loads(line)
            surface_counts[record["surface"]] += record.get("count", 0)

    gathered = set()
    path = NAMES / "disagreements.jsonl"
    if path.exists():
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                record = json.loads(line)
                if record.get("disagreement"):
                    gathered.add(record["canonical"])

    rows = []
    missing = 0
    for page in pages:
        canonical = page["name"]
        page_path = VAULT / "names" / page["filename"]
        if not page_path.exists():
            missing += 1
        alias_list = aliases_of.get(canonical, [])
        rows.append(
            {
                "canonical": canonical,
                "kind": page.get("kind") or "(unspecified)",
                "member_count": page.get("member_count", 0),
                "source_count": page.get("source_count", 0),
                "occurrences": surface_counts.get(canonical, 0)
                + sum(surface_counts.get(alias, 0) for alias in alias_list),
                "alias_count": len(alias_list),
                "has_disagreement": int(canonical in gathered),
                "sources": "; ".join(sources_of(page_path)),
                "aliases": "; ".join(alias_list),
                "page": f"data/vault/names/{page['filename']}",
            }
        )

    rows.sort(key=lambda row: (row["kind"], -row["member_count"], row["canonical"].lower()))

    OUT.mkdir(parents=True, exist_ok=True)
    write_csv(OUT / "all-names.csv", rows, COLUMNS)

    by_kind: dict[str, list[dict]] = collections.defaultdict(list)
    for row in rows:
        by_kind[row["kind"]].append(row)

    index = []
    for kind, records in by_kind.items():
        filename = f"{slug(kind)}.csv"
        write_csv(OUT / filename, records, COLUMNS)
        biggest = max(records, key=lambda row: row["member_count"])
        index.append(
            {
                "kind": kind,
                "file": filename,
                "pages": len(records),
                "member_notes": sum(row["member_count"] for row in records),
                "pages_single_note": sum(1 for row in records if row["member_count"] <= 1),
                "pages_multi_source": sum(1 for row in records if row["source_count"] >= 2),
                # the usable band from the name-index study: 30-200 notes over 5+ sources
                "pages_in_usable_band": sum(
                    1
                    for row in records
                    if 30 <= row["member_count"] <= 200 and row["source_count"] >= 5
                ),
                "pages_with_aliases": sum(1 for row in records if row["alias_count"]),
                "pages_with_disagreement": sum(row["has_disagreement"] for row in records),
                "biggest_page": biggest["canonical"],
                "biggest_page_members": biggest["member_count"],
            }
        )

    index.sort(key=lambda row: -row["pages"])
    write_csv(OUT / "_index.csv", index, list(index[0].keys()))

    print(f"kinds {len(index)}  pages {sum(r['pages'] for r in index)}  missing files {missing}")
    for row in index:
        print(
            f"{row['pages']:>6}  {row['kind']:<24} notes={row['member_notes']:<7}"
            f" multi_source={row['pages_multi_source']:<6}"
            f" band={row['pages_in_usable_band']:<5}"
            f" gathered={row['pages_with_disagreement']:<5}"
            f" biggest={row['biggest_page_members']}"
        )


if __name__ == "__main__":
    main()
