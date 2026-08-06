"""Mechanical corpus-shape counts, over any subset of sources.

Reproduces every figure in data/reports/axial-coverage.md from data/vault/notes.db,
so a 31-book baseline and a 35-book index can be counted the same way.

    uv run python scratchpad/coverage_counts.py --out scratchpad/shape-35.json
    uv run python scratchpad/coverage_counts.py --exclude gelvin-1998 gould-2003 \
        hinnebusch-1990 wedeen-2019 --out scratchpad/shape-31.json
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "vault" / "notes.db"

# Display names, and the aliases the index emitted for the same kind.
KIND_LABEL = {
    "person": "Person",
    "institution/group": "Institution or group",
    "work": "Work (a book or paper)",
    "concept": "Concept",
    "country/state/place": "Country or place",
    "event": "Event",
    "movement/religion": "Movement or religion",
    "period": "Historical period",
}
KIND_ALIAS = {
    "institution": "institution/group",
    "group": "institution/group",
    "movement": "movement/religion",
    "place": "country/state/place",
}
KIND_ORDER = list(KIND_LABEL)

BUCKETS = [(1, 1), (2, 4), (5, 9), (10, 29), (30, 99), (100, 10**9)]
BUCKET_LABELS = ["1", "2-4", "5-9", "10-29", "30-99", "100+"]

# The research bar from the report: enough notes to compare, enough books for the
# comparison to be between authors.
BAR_MIN_NOTES, BAR_MAX_NOTES, BAR_MIN_SOURCES = 30, 200, 5


def norm_kind(kind: str | None) -> str:
    if not kind:
        return "other"
    k = kind.strip().lower()
    k = KIND_ALIAS.get(k, k)
    return k if k in KIND_LABEL else "other"


def bucket_of(n: int) -> str:
    for label, (lo, hi) in zip(BUCKET_LABELS, BUCKETS):
        if lo <= n <= hi:
            return label
    return BUCKET_LABELS[-1]


def load(db: Path, exclude: set[str], back_matter: str):
    con = sqlite3.connect(db)
    stems = {sid: sid.rsplit("-", 1)[0] for (sid,) in con.execute("select source_id from sources")}
    keep = {sid for sid, stem in stems.items() if stem not in exclude}

    where = ""
    if back_matter == "exclude":
        where = "where n.back_matter = 0"
    elif back_matter == "only":
        where = "where n.back_matter = 1"

    rows = con.execute(
        f"""select nn.canonical, nn.source_id, nn.chunk_id
            from note_names nn join notes n using(chunk_id) {where}"""
    ).fetchall()
    notes = con.execute(f"select n.chunk_id, n.source_id from notes n {where}").fetchall()
    # The names table is the page's kind of record; note_names.kind is per-mention
    # and disagrees with it on a couple of hundred pages.
    page_kind = dict(con.execute("select canonical, kind from names"))
    con.close()

    rows = [r for r in rows if r[1] in keep]
    notes = [r for r in notes if r[1] in keep]
    return stems, keep, rows, notes, page_kind


def measure(db: Path, exclude: set[str], back_matter: str) -> dict:
    stems, keep, rows, notes, page_kind = load(db, exclude, back_matter)

    # canonical -> notes, sources, per-source note counts, kind
    members: dict[str, set] = defaultdict(set)
    srcs: dict[str, set] = defaultdict(set)
    by_src: dict[str, Counter] = defaultdict(Counter)
    kind_of: dict[str, str] = {}
    links = Counter()  # note_names rows per source
    touched = defaultdict(set)  # pages a source touches

    for canonical, source_id, chunk_id in rows:
        members[canonical].add(chunk_id)
        srcs[canonical].add(source_id)
        by_src[canonical][source_id] += 1
        kind_of.setdefault(canonical, norm_kind(page_kind.get(canonical)))
        links[source_id] += 1
        touched[source_id].add(canonical)

    pages = {
        c: {
            "kind": kind_of[c],
            "notes": len(members[c]),
            "sources": len(srcs[c]),
            "top_source": by_src[c].most_common(1)[0][0],
            "top_share": by_src[c].most_common(1)[0][1] / sum(by_src[c].values()),
        }
        for c in members
    }

    # --- per-kind shape ------------------------------------------------------
    shape = {}
    for k in KIND_ORDER + ["other"]:
        ps = [p for p in pages.values() if p["kind"] == k]
        if not ps:
            continue
        b = Counter(bucket_of(p["notes"]) for p in ps)
        shape[k] = {
            "pages": len(ps),
            "buckets": {lab: b.get(lab, 0) for lab in BUCKET_LABELS},
            "mentions": sum(p["notes"] for p in ps),
            "single_source": sum(1 for p in ps if p["sources"] == 1),
            "single_source_pct": 100 * sum(1 for p in ps if p["sources"] == 1) / len(ps),
            "meets_bar": sum(
                1
                for p in ps
                if BAR_MIN_NOTES <= p["notes"] <= BAR_MAX_NOTES and p["sources"] >= BAR_MIN_SOURCES
            ),
            # covered at length, but in one voice
            "well_covered": sum(1 for p in ps if p["notes"] >= 10),
            "single_voice": sum(1 for p in ps if p["notes"] >= 10 and p["top_share"] >= 0.70),
        }

    # --- concepts ------------------------------------------------------------
    concepts = {c: p for c, p in pages.items() if p["kind"] == "concept"}
    concept_stats = {
        "pages": len(concepts),
        "once": sum(1 for p in concepts.values() if p["notes"] == 1),
        "ge10": sum(1 for p in concepts.values() if p["notes"] >= 10),
        "ge30": sum(1 for p in concepts.values() if p["notes"] >= 30),
        "ge5_sources": sum(1 for p in concepts.values() if p["sources"] >= 5),
        "gt10_sources": sum(1 for p in concepts.values() if p["sources"] > 10),
    }

    def top(kind: str, n: int, key="notes"):
        ps = [(c, p) for c, p in pages.items() if p["kind"] == kind]
        ps.sort(key=lambda cp: (-cp[1][key], cp[0]))
        return [
            {
                "name": c,
                "notes": p["notes"],
                "sources": p["sources"],
                "top_source": stems[p["top_source"]],
                "top_share": round(100 * p["top_share"]),
            }
            for c, p in ps[:n]
        ]

    # --- per book ------------------------------------------------------------
    alone = Counter()
    for c, p in concepts.items():
        if p["sources"] == 1:
            alone[p["top_source"]] += 1
    concept_mentions = Counter()
    for canonical, source_id, _chunk_id in rows:
        if kind_of[canonical] == "concept":
            concept_mentions[source_id] += 1

    note_count = Counter(sid for _, sid in notes)
    books = sorted(
        (
            {
                "source": stems[sid],
                "notes": note_count.get(sid, 0),
                "links": links.get(sid, 0),
                "pages_touched": len(touched.get(sid, ())),
                "concept_mentions": concept_mentions.get(sid, 0),
                "concepts_alone": alone.get(sid, 0),
            }
            for sid in keep
        ),
        key=lambda b: -b["links"],
    )

    all_pages = list(pages.values())
    return {
        "sources": len(keep),
        "notes": len(notes),
        "pages": len(pages),
        "mentions": sum(p["notes"] for p in all_pages),
        "pages_once": sum(1 for p in all_pages if p["notes"] == 1),
        "pages_single_source": sum(1 for p in all_pages if p["sources"] == 1),
        "meets_bar": sum(
            1
            for p in all_pages
            if BAR_MIN_NOTES <= p["notes"] <= BAR_MAX_NOTES and p["sources"] >= BAR_MIN_SOURCES
        ),
        "shape": shape,
        "concepts": concept_stats,
        "top_concepts": top("concept", 40),
        "top_movements": top("movement/religion", 20),
        "top_places": top("country/state/place", 20),
        "top_persons": top("person", 20),
        "books": books,
        "bar_pages": sorted(
            (
                {"name": c, "kind": p["kind"], "notes": p["notes"], "sources": p["sources"]}
                for c, p in pages.items()
                if BAR_MIN_NOTES <= p["notes"] <= BAR_MAX_NOTES and p["sources"] >= BAR_MIN_SOURCES
            ),
            key=lambda p: -p["notes"],
        ),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exclude", nargs="*", default=[], help="source stems to leave out")
    ap.add_argument("--back-matter", choices=["include", "exclude", "only"], default="include")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    res = measure(DB, set(a.exclude), a.back_matter)
    res["excluded"] = sorted(a.exclude)
    res["back_matter"] = a.back_matter
    Path(a.out).write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
    print(
        f"{res['sources']} sources · {res['notes']:,} notes · {res['pages']:,} pages · "
        f"{res['mentions']:,} mentions · {res['meets_bar']} meet the bar  -> {a.out}"
    )


if __name__ == "__main__":
    main()
