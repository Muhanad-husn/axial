"""Assemble the v2 Axial dossier: prose body + generated appendices.

Reads the two hand-written prose files under `source/`, splices in the library
table (counted from the live index) and the two paper appendices (read from the
live paper records), and writes `data/reports/axial-report.md`.

    uv run python data/reports/build/build_report_v2.py
    uv run python data/reports/build/md_to_docx.py axial-report
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
REPORTS = Path(__file__).resolve().parents[1]
SOURCE = REPORTS / "source"

BODY = SOURCE / "report_v2_body.md"
APPENDICES = SOURCE / "report_v2_appendices.md"
DEST = REPORTS / "axial-report.md"

NOTES_DB = ROOT / "data" / "vault" / "notes.db"
SOURCE_META = ROOT / "data" / "source_meta"
ANALYSES = ROOT / "data" / "analyses"
PAPERS = ROOT / "data" / "papers"

# The two papers reproduced in full, in the order they appear as appendices D and E.
PAPER_FILES = ["b02d747edc0bb416", "d5f983eafb05f8d6"]
# The papers listed in appendix F rather than reproduced. Order is the report's.
FURTHER_PAPERS = [
    "9f449f41b88e5c70",  # S-02, nationalism and the fiscal-military nexus
    "a1039fad4da31320",  # S-01, Mann against Tilly
    "f5ae5ff2f09766af",  # S-03, what later work did to quasi-states
    "408378f2e286fff2",  # S-04, Transnistria
    "273aea05df54e2df",  # S-05, Somaliland
    "5d866ef2ce4971ae",  # P3-04, sectarian exclusion in Syria
]
# Short cites for the library table, in the report's own house style.
SHORT = {
    "agamben-2005": "Agamben, *State of Exception* (2005)",
    "ayubi-1995": "Ayubi, *Over-stating the Arab State* (1995)",
    "batatu-1999": "Batatu, *Syria's Peasantry* (1999)",
    "bayat-2017": "Bayat, *Revolution without Revolutionaries* (2017)",
    "beshara-2011": "Beshara, ed., *The Origins of Syrian Nationhood* (2011)",
    "caspersen-2012": "Caspersen, *Unrecognized States* (2012)",
    "chouliaraki-2024": "Chouliaraki, *Wronged* (2024)",
    "elcheroth-2017": "Elcheroth & Reicher, *Identity, Violence and Power* (2017)",
    "gellner-1981": "Gellner, *Muslim Society* (1981)",
    "gelvin-1998": "Gelvin, *Divided Loyalties* (1998)",
    "gould-2003": "Gould, *Collision of Wills* (2003)",
    "hall-2006": "Hall & Schroeder, eds., *An Anatomy of Power* (2006)",
    "heydemann-2000": "Heydemann, ed., *War, Institutions, and Social Change* (2000)",
    "heydemann-2004": "Heydemann, ed., *Networks of Privilege* (2004)",
    "hinnebusch-1990": "Hinnebusch, *Authoritarian Power and State Formation* (1990)",
    "jackson-1990": "Jackson, *Quasi-States* (1990)",
    "kalyvas-2006": "Kalyvas, *The Logic of Violence in Civil War* (2006)",
    "kandiah-2018": "Kandiah, *State Legitimacy and Capacity in the Syrian Conflict* (2018)",
    "kao-2025": "Kao & Lust, eds., *Decentralization, Local Governance, and Inequality* (2025)",
    "malesevic-2007": "Malešević & Haugaard, eds., *Ernest Gellner and Contemporary Social Thought* (2007)",
    "malesevic-2010": "Malešević, *The Sociology of War and Violence* (2010)",
    "malesevic-2013": "Malešević, *Nation-States and Nationalisms* (2013)",
    "malesevic-2026": "Malešević, 'Do Civil Wars Make or Break States?' (2026)",
    "mann-v1-2012": "Mann, *The Sources of Social Power*, vol. I",
    "mann-v2-1993": "Mann, *The Sources of Social Power*, vol. II",
    "mann-v3-2012": "Mann, *The Sources of Social Power*, vol. III",
    "mann-v4-2013": "Mann, *The Sources of Social Power*, vol. IV",
    "smith-2009": "Smith, *Ethno-symbolism and Nationalism* (2009)",
    "tilly-1978": "Tilly, *From Mobilization to Revolution* (1978)",
    "ungor-2020": "Üngör, *Paramilitarism* (2020)",
    "vignal-2021": "Vignal, *War-Torn* (2021)",
    "wedeen-2019": "Wedeen, *Authoritarian Apprehensions* (2019)",
    "white-2011": "White, *The Emergence of Minorities in the Middle East* (2011)",
    "wimmer-2013": "Wimmer, *Waves of War* (2013)",
    "zaum-2007": "Zaum, *The Sovereignty Paradox* (2007)",
}

NOT_A_BOOK = {
    "kandiah-2018": "master's research paper",
    "malesevic-2026": "journal article",
}


def stem(source_id: str) -> str:
    """Strip the content-hash suffix off a source id."""
    return source_id.rsplit("-", 1)[0]


def library_table() -> str:
    con = sqlite3.connect(NOTES_DB)
    passages = dict(con.execute("SELECT source_id, COUNT(*) FROM notes GROUP BY source_id"))
    touched = dict(
        con.execute(
            "SELECT source_id, COUNT(DISTINCT canonical) FROM note_names GROUP BY source_id"
        )
    )
    # Concepts no other source mentions. The kind of record is the `names` table,
    # never note_names.kind, which is per-mention and disagrees on a few hundred pages.
    alone = dict(
        con.execute(
            """
            SELECT source_id, COUNT(*) FROM (
                SELECT nn.canonical, MIN(nn.source_id) AS source_id
                FROM note_names nn JOIN names n ON n.canonical = nn.canonical
                WHERE n.kind = 'concept'
                GROUP BY nn.canonical HAVING COUNT(DISTINCT nn.source_id) = 1
            ) GROUP BY source_id
            """
        )
    )
    con.close()

    rows = []
    for source_id, n in passages.items():
        key = stem(source_id)
        rows.append(
            (
                SHORT.get(key, key),
                n,
                touched.get(source_id, 0),
                alone.get(source_id, 0),
                NOT_A_BOOK.get(key),
            )
        )
    rows.sort(key=lambda r: -r[1])

    out = [
        "| Source | Passages | Name pages touched | Concepts it alone holds |",
        "|---|---:|---:|---:|",
    ]
    for title, n, t, a, note in rows:
        label = f"{title}<br/>*{note}*" if note else title
        out.append(f"| {label} | {n:,} | {t:,} | {a:,} |")
    out.append(f"| **{len(rows)} sources** | **{sum(r[1] for r in rows):,}** | | |")
    return "\n".join(out)


def demote(markdown: str, levels: int = 2) -> str:
    """Push every heading down so a whole paper nests under an appendix."""
    lines = []
    for line in markdown.splitlines():
        m = re.match(r"^(#{1,6}) (.*)$", line)
        if m:
            lines.append("#" * min(6, len(m.group(1)) + levels) + " " + m.group(2))
        else:
            lines.append(line)
    return "\n".join(lines)


def paper_appendix(letter: str, paper_id: str, ordinal: str) -> str:
    record = json.loads((PAPERS / f"{paper_id}.json").read_text(encoding="utf-8"))
    rendered = (PAPERS / f"{paper_id}.md").read_text(encoding="utf-8")
    brief = record["paper_brief"]
    questions = []
    for analysis_id in brief["analysis_ids"]:
        rec = json.loads((ANALYSES / f"{analysis_id}.json").read_text(encoding="utf-8"))
        q = rec.get("brief", {}) or {}
        questions.append((analysis_id, q.get("case", ""), q.get("request", "")))

    claims = record.get("claims", [])
    kinds = {}
    for c in claims:
        kinds[c.get("kind")] = kinds.get(c.get("kind"), 0) + 1
    new_claims = [c for c in claims if not c.get("origin")]
    bib = record.get("bibliography", []) or []
    shape = record.get("shape", {}) or {}

    parts = [f"## Appendix {letter} — {ordinal} paper, and the questions behind it", ""]
    parts.append("### The paper brief")
    parts.append("")
    parts.append(f"**Title.** {brief['title']}")
    parts.append("")
    parts.append(f"**Organising question (the `thesis` field).** {brief['thesis'].strip()}")
    parts.append("")
    parts.append(f"**Lens.** {brief.get('lens', '—')}")
    parts.append("")
    parts.append(
        f"**Built from {len(questions)} prior analysis "
        f"{'record' if len(questions) == 1 else 'records'}.** "
        "The drafter never sees the library. It sees only the claims those records "
        "produced, and it cannot fetch anything else."
    )
    parts.append("")
    parts.append("### The research questions those records answered")
    parts.append("")
    parts.append(
        "These are the questions put to Axial, verbatim. Each was answered on its own, "
        "with its own retrieval, its own counter-position and its own checks, before the "
        "paper was planned."
    )
    parts.append("")
    for i, (analysis_id, case, request) in enumerate(questions, start=1):
        parts.append(f"**Question {i}** — `{analysis_id}`")
        parts.append("")
        parts.append(f"> **Case.** {case}")
        parts.append(">")
        parts.append(f"> **Request.** {request}")
        parts.append("")

    parts.append("### What the paper came out as")
    parts.append("")
    parts.append("| What was counted | The count |")
    parts.append("|---|---|")
    parts.append(f"| Claims | {len(claims)} |")
    parts.append(
        "| By kind | " + ", ".join(f"({k}) {v}" for k, v in sorted(kinds.items()) if k) + " |"
    )
    parts.append(f"| Made by the paper itself, not carried from a record | {len(new_claims)} |")
    parts.append(f"| Books cited | {len(bib)} |")
    parts.append(f"| Confidence band | {record.get('confidence', {}).get('overall_band', '—')} |")
    if shape.get("band"):
        parts.append(f"| Shape check | {shape['band']} |")
    cost = record.get("cost", {}) or {}
    if isinstance(cost, dict) and cost.get("total_usd") is not None:
        parts.append(f"| Cost to draft | ${cost['total_usd']:.3f} |")
    parts.append("")
    parts.append("### The paper, as rendered")
    parts.append("")
    parts.append(
        "*Reproduced exactly as Axial produced it, including the confidence and coverage "
        "disclosure, the shape check, the citation index and the bibliography. Nothing has "
        "been edited, tidied or shortened.*"
    )
    parts.append("")
    parts.append("---")
    parts.append("")
    parts.append(demote(rendered, levels=2))
    parts.append("")
    parts.append("---")
    parts.append("")
    return "\n".join(parts)


def paper_title(record: dict) -> str:
    """What the paper is called: the brief's override, else the shape check's own."""
    brief_title = (record.get("paper_brief", {}) or {}).get("title")
    if brief_title:
        return brief_title
    return (record.get("shape", {}) or {}).get("title") or "Untitled paper"


def paper_index() -> str:
    """Appendix F: the papers that are listed rather than reproduced."""
    rows = []
    for paper_id in FURTHER_PAPERS:
        record = json.loads((PAPERS / f"{paper_id}.json").read_text(encoding="utf-8"))
        brief = record["paper_brief"]
        analyses = []
        for analysis_id in brief["analysis_ids"]:
            rec = json.loads((ANALYSES / f"{analysis_id}.json").read_text(encoding="utf-8"))
            q = rec.get("brief", {}) or {}
            analyses.append((analysis_id, q.get("case", ""), q.get("request", "")))
        rows.append(
            {
                "id": paper_id,
                "title": paper_title(record),
                "thesis": brief["thesis"].strip(),
                "lens": brief.get("lens", "—"),
                "analyses": analyses,
                "claims": len(record.get("claims", [])),
                "new_claims": len([c for c in record.get("claims", []) if not c.get("origin")]),
                "books": len(record.get("bibliography", []) or []),
                "confidence": (record.get("confidence", {}) or {}).get("overall_band", "—"),
                "shape": (record.get("shape", {}) or {}).get("band", "—"),
                "usd": (record.get("cost", {}) or {}).get("total_usd"),
                "pin": record.get("corpus_pin", "—"),
            }
        )

    single_source = [r for r in rows if r["books"] == 1]
    total = sum(r["usd"] or 0.0 for r in rows)

    parts = [
        "## Appendix F — The other papers, listed rather than reproduced",
        "",
        "Appendices D and E carry two papers in full because a reader has to see at least "
        "one end to end. Reproducing every paper would treble this document, so the rest "
        "are indexed here: what each was asked, what it argued, and what it cost. Each "
        "renders to `data/papers/<id>.md`, with the record that produced it beside it.",
        "",
        f"All {len(rows)} were drafted on corpus pin `{rows[0]['pin']}`, the same pin as the "
        "two papers above, so the whole set is comparable. Each stands on one prior analysis "
        "record, where the papers in D and E stand on two and three.",
        "",
        "| Paper | The case it was asked about | Lens | Claims | Books cited | Confidence | Shape | Cost |",
        "|---|---|---|---:|---:|---|---|---:|",
    ]
    for r in rows:
        case = r["analyses"][0][1] if r["analyses"] else "—"
        usd = f"${r['usd']:.4f}" if r["usd"] is not None else "—"
        parts.append(
            f"| {r['title']} | {case} | {r['lens']} | {r['claims']} | {r['books']} | "
            f"{r['confidence']} | {r['shape']} | {usd} |"
        )
    parts.append("")
    parts.append(
        f"**The whole set cost ${total:.2f} to draft.** A paper standing on one analysis "
        "record is roughly a tenth the price of the multi-record papers in D and E, because "
        "cost tracks the size of the claim inventory the drafter is handed and nothing else."
    )
    parts.append("")

    if single_source:
        named = ", ".join(f"*{r['title']}*" for r in single_source)
        parts.append(
            f"**Read the books-cited column before anything else.** "
            f"{len(single_source)} of these papers — {named} — cite exactly **one book**. "
            "That is not a drafting failure; it is the library reporting its own shape. The "
            "shelf holds one comparative study of unrecognised states and no monograph on "
            "either territory, so a question about one of them has one source to stand on and "
            "the paper says so in its own coverage disclosure. It is the same corpus gap the "
            "sealed panel found in section 7.4, showing up before any reviewer was asked. A "
            "paper carried by a single book should be read as a well-formed argument over a "
            "thin shelf, never as a finding."
        )
        parts.append("")

    parts.append(
        "**None of these were put to the sealed panel.** The panel figures in section 7.4 "
        "cover the two papers in D and E and their planted-defect control, and adding papers "
        "to the shelf does not extend them. The four mechanical gates ran on every paper here, "
        "as they run on every paper by construction."
    )
    parts.append("")

    for r in rows:
        parts.append(f"### {r['title']}")
        parts.append("")
        parts.append(
            f"*`data/papers/{r['id']}.md` · lens: {r['lens']} · {r['claims']} claims, "
            f"{r['new_claims']} of them the paper's own · {r['books']} "
            f"{'book' if r['books'] == 1 else 'books'} cited*"
        )
        parts.append("")
        parts.append(f"**The thesis put to it.** {r['thesis']}")
        parts.append("")
        for analysis_id, case, request in r["analyses"]:
            parts.append(f"**The question behind it** — `{analysis_id}`")
            parts.append("")
            parts.append(f"> **Case.** {case}")
            parts.append(">")
            parts.append(f"> **Request.** {request}")
            parts.append("")
    return "\n".join(parts)


def main() -> None:
    body = BODY.read_text(encoding="utf-8")
    appendices = APPENDICES.read_text(encoding="utf-8")

    appendices = appendices.replace("<!--LIBRARY_TABLE-->", library_table())

    papers = "\n".join(
        [
            paper_appendix("D", PAPER_FILES[0], "The first"),
            paper_appendix("E", PAPER_FILES[1], "The second"),
        ]
    )
    appendices = appendices.replace("<!--PAPERS-->", papers)
    appendices = appendices.replace("<!--PAPER_INDEX-->", paper_index())

    DEST.write_text(body + "\n" + appendices, encoding="utf-8")
    words = len(DEST.read_text(encoding="utf-8").split())
    print(f"wrote {DEST} — {words:,} words")


if __name__ == "__main__":
    main()
