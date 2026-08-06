"""Assemble the v2 Axial dossier: prose body + generated appendices.

Reads the two hand-written prose files, splices in the library table (counted
from the live index) and the two paper appendices (read from the live paper
records), and writes data/reports/axial-report.md.

    uv run python data/reports/build_report_v2.py
    uv run python data/reports/md_to_docx.py axial-report
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent

BODY = OUT / "report_v2_body.md"
APPENDICES = OUT / "report_v2_appendices.md"
DEST = OUT / "axial-report.md"

NOTES_DB = ROOT / "data" / "vault" / "notes.db"
SOURCE_META = ROOT / "data" / "source_meta"
ANALYSES = ROOT / "data" / "analyses"
PAPERS = ROOT / "data" / "papers"

# The two papers, in the order they appear as appendices D and E.
PAPER_FILES = ["b02d747edc0bb416", "d5f983eafb05f8d6"]
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

    DEST.write_text(body + "\n" + appendices, encoding="utf-8")
    words = len(DEST.read_text(encoding="utf-8").split())
    print(f"wrote {DEST} — {words:,} words")


if __name__ == "__main__":
    main()
