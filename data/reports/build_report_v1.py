"""Assemble the Axial general-reader report: markdown + docx."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
SCRATCH = OUT

# --------------------------------------------------------------------------
# source short cites and overviews
# --------------------------------------------------------------------------

SHORT = {
    "agamben-2005": "Agamben 2005",
    "ayubi-1995": "Ayubi 1995",
    "batatu-1999": "Batatu 1999",
    "bayat-2017": "Bayat 2017",
    "beshara-2011": "Beshara 2011",
    "caspersen-2012": "Caspersen 2012",
    "chouliaraki-2024": "Chouliaraki 2024",
    "elcheroth-2017": "Elcheroth & Reicher 2017",
    "gellner-1981": "Gellner 1981",
    "hall-2006": "Hall & Schroeder 2006",
    "heydemann-2000": "Heydemann 2000",
    "heydemann-2004": "Heydemann 2004",
    "jackson-1990": "Jackson 1990",
    "kalyvas-2006": "Kalyvas 2006",
    "kandiah-2018": "Kandiah 2018",
    "kao-2025": "Kao 2025",
    "malesevic-2007": "Malesevic & Haugaard 2007",
    "malesevic-2010": "Malesevic 2010",
    "malesevic-2013": "Malesevic 2013",
    "malesevic-2026": "Malesevic 2026",
    "mann-v1-2012": "Mann vol. I",
    "mann-v2-1993": "Mann vol. II",
    "mann-v3-2012": "Mann vol. III",
    "mann-v4-2013": "Mann vol. IV",
    "smith-2009": "Smith 2009",
    "tilly-1978": "Tilly 1978",
    "ungor-2020": "Ungor 2020",
    "vignal-2021": "Vignal 2021",
    "white-2011": "White 2011",
    "wimmer-2013": "Wimmer 2013",
    "zaum-2007": "Zaum 2007",
}
SHORT = {k: v.replace("Malesevic", "Malešević").replace("Ungor", "Üngör") for k, v in SHORT.items()}

OVERVIEW = {
    "agamben-2005": "How governments suspend the law in the name of emergency, and how the exception became an ordinary technique of rule.",
    "ayubi-1995": "Argues the Arab state is fierce rather than strong: heavy on coercion, thin on the capacity to organise society.",
    "batatu-1999": "Syria's rural classes and their route into political power; the social foundations of the Ba'athist state.",
    "bayat-2017": "Why the Arab Spring produced mass mobilisation without the organisation and ideas that turn an uprising into a revolution.",
    "beshara-2011": "When and how a distinctly Syrian national identity first appeared, and what it had to compete with.",
    "caspersen-2012": "How territories no state recognises manage to survive and build working institutions anyway.",
    "chouliaraki-2024": "How the language of victimhood is claimed, contested and weaponised in Western public debate.",
    "elcheroth-2017": "Argues leaders choose violence because violence freezes fluid populations into hardened identities.",
    "gellner-1981": "Islam as a blueprint for social order, used to re-examine classic questions about religion and the fate of civilisations.",
    "hall-2006": "Leading scholars assess Michael Mann's theory of power, sympathetically and critically. An edited collection.",
    "heydemann-2000": "Tests European theories of war-driven state formation against Middle Eastern cases, and finds where they break. An edited collection.",
    "heydemann-2004": "How economic networks shape, and are shaped by, attempts at fiscal reform. An edited collection.",
    "jackson-1990": "States that hold legal sovereignty without the capacity of a state, and the international rules that keep them alive.",
    "kalyvas-2006": "Argues violence against civilians follows a logic of territorial control and information, not opaque hatred.",
    "kandiah-2018": "A research paper on how outside powers make domestic legitimacy conditional in Syria, and what that does to stability.",
    "kao-2025": "How decentralisation is actually lived locally across Lebanon, Morocco, Syria and Tunisia. An edited collection.",
    "malesevic-2007": "Ernest Gellner's legacy reassessed by leading social theorists. An edited collection.",
    "malesevic-2010": "Argues organisation and ideology, not human nature, are what make mass violence possible.",
    "malesevic-2013": "Treats the nation-state as a product of organisation, ideology and small-group loyalty rather than a natural identity.",
    "malesevic-2026": "A journal article on when civil war builds a state and when it destroys one.",
    "mann-v1-2012": "From prehistory to the eve of industrialisation: the four-sources-of-power model and its first application.",
    "mann-v2-1993": "Classes and nation-states, 1760-1914, across the five Western powers at the leading edge of power.",
    "mann-v3-2012": "Global empires, ideologies and revolution up to 1945.",
    "mann-v4-2013": "Globalisations since 1945: capitalism, the nation-state system, and the American empire.",
    "smith-2009": "The case that modern nations are built from older ethnic memories and symbols rather than invented from nothing.",
    "tilly-1978": "How groups organise, make claims, and occasionally convert conflict into revolution.",
    "ungor-2020": "Why states outsource mass violence to militias, and what those militias then become.",
    "vignal-2021": "The Syrian war as it changed everyday economic life and the country's human geography.",
    "white-2011": "Argues 'minority' and 'majority' were produced by the mandate state, not inherited from before it.",
    "wimmer-2013": "A statistical history arguing nation-state formation and ethnic politics drive two centuries of war.",
    "zaum-2007": "International administrations that build states while promising self-government, and the contradiction inside that.",
}


def stem(source_id: str) -> str:
    return source_id.rsplit("-", 1)[0]


def short(source_id: str) -> str:
    return SHORT.get(stem(source_id), stem(source_id))


# --------------------------------------------------------------------------
# sources table
# --------------------------------------------------------------------------


def val(x):
    return x.get("value") if isinstance(x, dict) else x


def clean_author(raw: str) -> str:
    raw = (raw or "").strip().strip(";").strip()
    if "," in raw and " and " not in raw and "&" not in raw:
        parts = [p.strip() for p in raw.split(",")]
        if len(parts) == 2 and parts[1]:
            raw = f"{parts[1]} {parts[0]}"
    return re.sub(r"\s+", " ", raw).strip(" .;")


def title_case_fix(t: str) -> str:
    if t.isupper():
        t = t.title()
    return t


# Display-only corrections. Nothing here changes a fact: it fixes casing,
# stray punctuation and spacing that the file metadata carries verbatim.
AUTHOR_FIX = {
    "kalyvas-2006": "Stathis N. Kalyvas",
    "kao-2025": "Kristen Kao et al. (eds)",
    "malesevic-2013": "Siniša Malešević",
    "white-2011": "Benjamin Thomas White",
    "zaum-2007": "Dominik Zaum",
    "hall-2006": "John A. Hall and Ralph Schroeder (eds)",
    "heydemann-2000": "Steven Heydemann (ed.)",
    "heydemann-2004": "Steven Heydemann (ed.)",
    "malesevic-2007": "Siniša Malešević and Mark Haugaard (eds)",
}
TITLE_FIX = {
    "gellner-1981": "Muslim Society",
    "malesevic-2010": "The Sociology of War and Violence",
    "hall-2006": "An Anatomy of Power: The Social Theory of Michael Mann",
    "jackson-1990": "Quasi-States: Sovereignty, International Relations, and the Third World",
    "white-2011": "The Emergence of Minorities in the Middle East",
    "zaum-2007": "The Sovereignty Paradox: The Norms and Politics of International Statebuilding",
    "malesevic-2013": "Nation-States and Nationalisms: Organization, Ideology and Solidarity",
    "mann-v4-2013": "The Sources of Social Power, Volume 4",
    "mann-v2-1993": "The Sources of Social Power, Volume 2",
    "kandiah-2018": "Examining the Centrality of State Legitimacy and Capacity to Stable Governance in the Syrian Conflict",
    "batatu-1999": "Syria's Peasantry, the Descendants of Its Lesser Rural Notables, and Their Politics",
}
PUBLISHER_FIX = {
    "agamben-2005": "University of Chicago Press",
    "zaum-2007": "Oxford University Press",
    "vignal-2021": "Hurst",
    "malesevic-2026": "Springer",
    "malesevic-2013": "Polity",
}


def build_sources():
    rows = []
    total_pages = 0
    for p in sorted((ROOT / "data" / "source_meta").glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        sid = d["source_id"]
        key = stem(sid)
        pub = val(d.get("publisher")) or ""
        if pub == "unavailable":
            pub = "not recorded"
        pub = PUBLISHER_FIX.get(key, pub.split(",")[0].strip())
        pages = d.get("physical_page_count") or 0
        total_pages += pages
        rows.append(
            {
                "key": key,
                "author": AUTHOR_FIX.get(key, clean_author(val(d.get("author")) or "")),
                "title": TITLE_FIX.get(key, title_case_fix(val(d.get("title")) or "")),
                "year": val(d.get("date")) or "",
                "publisher": pub,
                "pages": pages,
                "overview": OVERVIEW.get(key, ""),
            }
        )
    rows.sort(key=lambda r: r["key"])
    lines = [
        "| Author | Title | Publisher | Year | Pages | What it is about |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['author']} | *{r['title']}* | {r['publisher']} | {r['year']} | {r['pages']} | {r['overview']} |"
        )
    return "\n".join(lines), total_pages, len(rows)


# --------------------------------------------------------------------------
# answer rendering
# --------------------------------------------------------------------------

CHUNK_RE = re.compile(r"chunk:([a-z0-9\-]+-[0-9a-f]{12})_(\d+)_([a-z0-9\-]+)_(\d+)")


def pretty_section(slug: str) -> str:
    s = slug.replace("-", " ").strip()
    for _ in range(3):
        s = re.sub(r"(\d) (\d)", r"\1.\2", s)
    s = re.sub(r"\s+", " ", s)
    return s[:1].upper() + s[1:]


def render_grounds(line: str) -> str:
    counts: dict[str, int] = {}
    seen: set[str] = set()
    for m in CHUNK_RE.finditer(line):
        if m.group(0) in seen:
            continue
        seen.add(m.group(0))
        label = short(m.group(1))
        counts[label] = counts.get(label, 0) + 1
    return "; ".join(f"{k} ({v} passages)" if v > 1 else k for k, v in counts.items())


def render_answer(md_path: Path) -> str:
    text = md_path.read_text(encoding="utf-8")
    out = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("# Analysis answer"):
            i += 1
            continue
        if line.startswith("**Case:**") or line.startswith("**Request:**"):
            i += 1
            continue
        if line.startswith("**Lens:**"):
            lens = line.split("**Lens:**", 1)[1].strip().replace("-", " ")
            disp = ""
            if i + 1 < len(lines) and lines[i + 1].startswith("**Disposition:**"):
                disp = lines[i + 1].split("**Disposition:**", 1)[1].strip()
                i += 1
            disp = {
                "proceed_bounded": "proceed, with stated bounds",
                "proceed": "proceed",
                "halt": "halt",
            }.get(disp, disp)
            out.append(
                f"*Reading lens: {lens}. Decision after interrogating the question: {disp}.*"
            )
            out.append("")
            i += 1
            continue
        if line.startswith("## Claims"):
            out.append("**Claims**")
            out.append("")
            i += 1
            continue
        if line.startswith("## Counter-position"):
            out.append(
                "**Counter-position** — the strongest case against this answer's own conclusion"
            )
            out.append("")
            i += 1
            continue
        if line.startswith("## Coverage map"):
            out.append(
                "**Coverage map** — how much of the library stands behind each name the answer rests on"
            )
            out.append("")
            i += 1
            continue
        if line.startswith("## Confidence"):
            out.append("**Confidence**")
            out.append("")
            i += 1
            continue
        if line.startswith("## Source usage"):
            out.append(
                "**Source usage** — share of the answer's cited evidence taken from each book"
            )
            out.append("")
            i += 1
            # rewrite the usage lines
            shares = []
            while i < len(lines):
                ln = lines[i]
                if not ln.strip():
                    i += 1
                    continue
                m = re.match(r"- ([a-z0-9\-]+-[0-9a-f]{12}): evidence_share=([0-9.]+)", ln)
                if not m:
                    break
                shares.append((short(m.group(1)), float(m.group(2))))
                i += 1
            for name, sh in sorted(shares, key=lambda t: -t[1]):
                out.append(f"- {name}: {round(sh * 100)}%")
            continue
        if line.strip().startswith("grounds:"):
            g = render_grounds(line)
            out.append(f"    - Sources: {g}")
            i += 1
            continue
        m = re.match(r"- \((a|b|c)\) (.*)$", line)
        if m:
            kind = {"a": "(a) source says", "b": "(b) Axial infers", "c": "(c) speculative"}[
                m.group(1)
            ]
            body = m.group(2)
            conf = ""
            cm = re.search(r"\[confidence: (.*?)\]\s*$", body)
            if cm:
                conf = cm.group(1)
                body = body[: cm.start()].strip()
                capped = re.match(r"(\w+) \(model emitted '(\w+)', capped by .*\)$", conf)
                if capped:
                    conf = (
                        f"**{capped.group(1)}** — the writing model asked for "
                        f"'{capped.group(2)}'; capped by how much of the library "
                        "stands behind this claim"
                    )
                else:
                    conf = f"**{conf}**"
            out.append(f"- **{kind}.** {body}")
            if conf:
                out.append(f"    - Confidence: {conf}")
            i += 1
            continue
        m = re.match(r"- (.+?): corpus=(\d+) evidence=(\d+) band=(\w+)$", line)
        if m:
            out.append(
                f"- **{m.group(1)}** — {m.group(2)} passages in the library, {m.group(3)} used here; coverage judged *{m.group(4)}*"
            )
            i += 1
            continue
        if line.startswith("**Stance:**"):
            out.append(line.replace("**Stance:**", "").strip())
            i += 1
            continue
        if line.startswith("**Band:**"):
            out.append(f"Overall band: **{line.split('**Band:**')[1].strip()}**")
            i += 1
            continue
        if line.startswith("**Rationale:**"):
            why = line.replace("**Rationale:**", "Why:").strip()
            why = why.replace("corpus notes", "passages in the library").replace(
                "evidence notes", "used here"
            )
            why = why.replace(
                "the least-covered name touched", "the thinnest-covered name it touches"
            )
            out.append(why)
            i += 1
            continue
        out.append(line)
        i += 1
    text = "\n".join(out)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# --------------------------------------------------------------------------
# metrics
# --------------------------------------------------------------------------

METRICS = {
    r["sweep"] + "/" + r["case"]: r
    for r in json.loads((SCRATCH / "metrics.json").read_text(encoding="utf-8"))
}

ROLE = {
    "interrogate": "Reading the question",
    "retrieve": "Searching the library",
    "synthesize": "Writing the answer",
    "counter_position_generate": "Writing the counter-position",
}


def model_table(rec) -> str:
    lines = ["| Task | Model |", "|---|---|"]
    for key in ["interrogate", "retrieve", "synthesize", "counter_position_generate"]:
        lines.append(f"| {ROLE[key]} | `{rec['models'][key]}` |")
    return "\n".join(lines)


def metrics_block(rec, extra_note: str = "") -> str:
    hit_n, hit_d = rec["hit"].split("/")
    missed = ", ".join(short(s) for s in rec["missed"]) or "none"
    cross = rec["other"]["cross_source_rate"]
    mins = int(rec["lat"] // 60)
    secs = int(rec["lat"] % 60)
    rows = [
        "| Measure | Value |",
        "|---|---|",
        f"| Time to answer | {mins} min {secs} s{extra_note} |",
        f"| Cost | ${rec['usd']:.4f} |",
        f"| Books cited in the answer | {rec['other']['sources_cited']} |",
        f"| Books the question demands, reached | {hit_n} of {hit_d}"
        + (f" (missed: {missed})" if rec["missed"] else "")
        + " |",
        f"| Inferences resting on two or more books | {cross['numerator']} of {cross['denominator']} |",
        f"| Answer size | {rec['claims']} claims, {rec['words']:,} words |",
    ]
    return "\n".join(rows)


# --------------------------------------------------------------------------
# authored per-brief content
# --------------------------------------------------------------------------

ANSWER_PATHS = {
    "smoke-v5/P3-04": "data/runs/smoke-v5/analyses/P3-04/draw0/92d2d85745ecaa2d.md",
    "smoke-v5/S-01": "data/runs/smoke-v5/analyses/S-01/draw0/ec94042430910584.md",
    "smoke-v5/S-02": "data/runs/smoke-v5/analyses/S-02/draw0/e7d6a2646523cb1d.md",
    "smoke-v5/S-03": "data/runs/smoke-v5/analyses/S-03/draw0/fa44475aaaa90a48.md",
    "smoke-v5/S-04": "data/runs/smoke-v5/analyses/S-04/draw0/be50533708e44f33.md",
    "smoke-v5/S-05": "data/runs/smoke-v5/analyses/S-05/draw0/c2afb6d42f713e1c.md",
    "eval-A-C-14/A": "data/runs/eval-A-C-14/analyses/A/draw0/dae632c369c18ffc.md",
    "eval-A-C-14/C": "data/runs/eval-A-C-14/analyses/C/draw0/6678f15a71f15ac0.md",
    "eval-B-open/B": "data/runs/eval-B-open/analyses/B/draw0/080d9e472fc56a34.md",
    "eval-B-closed/B": "data/runs/eval-B-closed/analyses/B/draw0/080d9e472fc56a34.md",
}


def brief_question(path: str) -> tuple[str, str]:
    text = (ROOT / path).read_text(encoding="utf-8")
    case = re.search(r'^case:\s*"(.*)"\s*$', text, re.M).group(1)
    req = re.search(r'^request:\s*"(.*)"\s*$', text, re.M | re.S).group(1)
    req = re.sub(r"\s+", " ", req).strip()
    return case, req


SHORT_BRIEFS = [
    {
        "id": "P3-04",
        "key": "smoke-v5/P3-04",
        "yaml": "config/briefs/smoke/P3-04.yaml",
        "domain": "Syrian civil war; sectarianism",
        "note": "¹",
        "review": (
            "**Strong** on factual correctness, **strong** on citation grounding, **adequate** on completeness. "
            "The reviewer found two defects, both of the mild kind: one inference reaching slightly past the passage "
            "it cites, and one claim carrying a shade more emphasis than its source. Reviewed before this round's "
            "fixes, the same question drew ten defects and a 'weak' on completeness. It is the largest single "
            "improvement in the set. Note also what the engine did to itself here: three of the six names this answer "
            "rests on are thinly covered, and 17 of its 18 claims were capped below the confidence the writing model "
            "asked for."
        ),
    },
    {
        "id": "S-01",
        "key": "smoke-v5/S-01",
        "yaml": "config/briefs/smoke/S-01.yaml",
        "domain": "European state formation theory",
        "note": "",
        "review": (
            "**Strong** on factual correctness, **adequate** on citation grounding, **strong** on completeness. "
            "Three defects, all soft: two inferences reaching past their cited passages, one claim stated more firmly "
            "than the passage supports. The answer commits to a verdict rather than surveying the field — that Mann "
            "specifies Tilly's mechanisms rather than overturning them — and then states the opposing case, that the "
            "distinction breaks the bellicist claim outright, in its strongest form."
        ),
    },
    {
        "id": "S-02",
        "key": "smoke-v5/S-02",
        "yaml": "config/briefs/smoke/S-02.yaml",
        "domain": "Theories of nationalism",
        "note": "",
        "review": (
            "**Strong** on all three dimensions, with only two defects — the cleanest result in the set alongside S-04. "
            "The reviewer singled out the counter-position for rendering Smith's ethno-symbolism 'at full strength' "
            "rather than as a caricature, and credited the answer for a careful judgement call: recognising that a "
            "passage inside a book edited by someone else was Mann's own voice, and crediting it to Mann. Reviewed "
            "before the fixes, this same question scored 'weak' on completeness with eight defects."
        ),
    },
    {
        "id": "S-03",
        "key": "smoke-v5/S-03",
        "yaml": "config/briefs/smoke/S-03.yaml",
        "domain": "Sovereignty and international statebuilding",
        "note": "",
        "review": (
            "**Adequate** on factual correctness and on citation grounding, **strong** on completeness. Three defects. "
            "This is the only answer in the set that did not move up to 'strong' on the first two dimensions, and it is "
            "also the narrowest question: the founding book on the concept is on the shelf, but only five books in the "
            "library discuss it at all. The answer reached all three books the question demands, and 15 of its 16 "
            "claims were capped below the confidence the writing model asked for."
        ),
    },
    {
        "id": "S-04",
        "key": "smoke-v5/S-04",
        "yaml": "config/briefs/smoke/S-04.yaml",
        "domain": "Post-Soviet unrecognised states",
        "note": "",
        "review": (
            "**Strong** on all three dimensions; two defects, both about wording rather than substance. This is the "
            "answer that changed most between the two review rounds. In the first round it printed "
            "'Counter-position: (none disclosed)' while fourteen of its own cited passages named an opponent, and the "
            "reviewer called that evasive. After the fix, the reviewer described its counter-position as 'a genuinely "
            "strong counter-position drawn from the same author's own concessions — directly answering the question's "
            "harder half'. One number below reads badly at first glance and should not: none of this answer's own "
            "inferences span two books, because the library holds this subject in one book. Thin coverage is what this "
            "brief was built to probe, and 24 of its 25 claims were capped below the confidence the writing model "
            "asked for."
        ),
    },
    {
        "id": "S-05",
        "key": "smoke-v5/S-05",
        "yaml": "config/briefs/smoke/S-05.yaml",
        "domain": "Somaliland, recognition and statehood",
        "note": "",
        "review": (
            "**Strong** on all three dimensions, three defects. The reviewer described its counter-position as 'a "
            "genuine steelman built from the book's own dissenting voices rather than a strawman'. That matters here "
            "more than anywhere else in the set, because every passage in this answer comes from one book — the "
            "condition under which a system is most tempted to sound more certain than it should. The engine was never "
            "told the coverage was thin. It disclosed the single-book concentration itself and capped 22 of its 26 "
            "claims below the confidence the writing model asked for."
        ),
    },
]

HARD_BRIEFS = [
    {
        "id": "A",
        "label": "Question A — did war make the state everywhere?",
        "key": "eval-A-C-14/A",
        "yaml": "config/briefs/eval/A.yaml",
        "domain": "Comparative state formation and war",
        "arm": "Open-source stack, 14 search steps (the retained setting)",
        "review": (
            "**Not peer-reviewed.** Only question B was put to the sealed reviewer. A was measured mechanically: every "
            "claim carried a kind and sources that resolve (a perfect 1.000), and an independent grounding check "
            "supported 87.5% of its source-attributed claims. Its clear failure is mechanical and worth stating: it "
            "decomposed the claim that war made the modern state, over five separate mechanisms, without ever citing "
            "Tilly — the originating text the question's own premise names. Run again at 20 search steps it cost 65% "
            "more, gathered six more passages, put one more in front of the writing model, and still never reached "
            "Tilly."
        ),
    },
    {
        "id": "C",
        "label": "Question C — why nationalism and mass war arrived together",
        "key": "eval-A-C-14/C",
        "yaml": "config/briefs/eval/C.yaml",
        "domain": "Nationalism, war and empire",
        "arm": "Open-source stack, 14 search steps (the retained setting)",
        "review": (
            "**Not peer-reviewed.** Measured mechanically: every claim carried a kind and resolvable sources, and the "
            "grounding check supported 93.8% of its source-attributed claims. It reached only two of the six books the "
            "question demands — the weakest retrieval result anywhere in this evaluation. Raising the search budget to "
            "20 steps gathered 181 passages across 15 books instead of 107 across 8, lifted the reach to three of six, "
            "and put one fewer passage in front of the writing model."
        ),
    },
    {
        "id": "B-open",
        "label": "Question B — which account explains violence against Syrian civilians? (open-source arm)",
        "key": "eval-B-open/B",
        "yaml": "config/briefs/eval/B.yaml",
        "domain": "Syrian civil war; civilian violence",
        "arm": "Open-source stack",
        "review": (
            "**The sealed reviewer, reading both answers blind, chose this one.** **Strong** on factual correctness, "
            "**strong** on citation grounding, **strong** on completeness. It was credited for three things "
            "specifically: reading Üngör's passage on paramilitary violence as written — as a structural argument, "
            "and one aimed against culture-first explanations — and then using it to test its own conclusion rather "
            "than to decorate it; anchoring its judgement in the Daraa case, the most granular ground-level evidence "
            "available to it; and stating the account it rejects in that account's canonical strongest form. The "
            "reviewer called the margin over the proprietary answer narrow."
        ),
    },
    {
        "id": "B-closed",
        "label": "Question B — the same question, proprietary arm",
        "key": "eval-B-closed/B",
        "yaml": "config/briefs/eval/B.yaml",
        "domain": "Syrian civil war; civilian violence",
        "arm": "Proprietary stack",
        "review": (
            "**Strong** on factual correctness, **strong** on citation grounding, **adequate** on completeness. The "
            "reviewer's specific objection is the one worth understanding, because it is the kind of error that reads "
            "as competent: this answer cites the same Üngör passage as the open-source answer, and marshals it "
            "against its own thrust. The passage locates paramilitary violence in incomplete state monopolies of "
            "violence and covert outside support, explicitly 'rather than in cultural divisions alone'. This answer "
            "uses it to support an account built on the deliberate production of sectarian identity. It also cost 2.3 "
            "times as much and reached two fewer books."
        ),
    },
]


def build_short():
    out = []
    for b in SHORT_BRIEFS:
        rec = METRICS[b["key"]]
        case, req = brief_question(b["yaml"])
        out.append(f"### {b['id']} — {case}")
        out.append("")
        out.append(f"**Category / domain.** {b['domain']}")
        out.append("")
        out.append("**Question.**")
        out.append("")
        out.append(f"> {req}")
        out.append("")
        out.append("**Response.**")
        out.append("")
        out.append(render_answer(ROOT / ANSWER_PATHS[b["key"]]))
        out.append("")
        out.append("**Peer reviewer.**")
        out.append("")
        out.append(b["review"])
        out.append("")
        out.append("**Metrics.**")
        out.append("")
        note = (
            " — of which about 10 minutes is one-time startup paid by whichever brief runs first"
            if b["id"] == "P3-04"
            else ""
        )
        out.append(metrics_block(rec, note))
        out.append("")
        out.append(model_table(rec))
        out.append("")
    return "\n".join(out)


def build_hard():
    out = []
    for b in HARD_BRIEFS:
        rec = METRICS[b["key"]]
        case, req = brief_question(b["yaml"])
        out.append(f"### {b['label']}")
        out.append("")
        out.append(f"**Category / domain.** {b['domain']}  ")
        out.append(f"**Setting.** {case} — {b['arm']}")
        out.append("")
        out.append("**Question.**")
        out.append("")
        out.append(f"> {req}")
        out.append("")
        out.append("**Response.**")
        out.append("")
        out.append(render_answer(ROOT / ANSWER_PATHS[b["key"]]))
        out.append("")
        out.append("**Peer reviewer.**")
        out.append("")
        out.append(b["review"])
        out.append("")
        out.append("**Model combination, and what it produced.**")
        out.append("")
        out.append(model_table(rec))
        out.append("")
        out.append(metrics_block(rec))
        out.append("")
    return "\n".join(out)


def main():
    template = (SCRATCH / "report_template_v1.md").read_text(encoding="utf-8")
    sources_md, total_pages, n = build_sources()
    template = template.replace("{{SOURCES_TABLE}}", sources_md)
    template = template.replace("{{SHORT_BRIEFS}}", build_short())
    template = template.replace("{{HARD_BRIEFS}}", build_hard())
    template = template.replace("10,314 printed pages", f"{total_pages:,} printed pages")
    (OUT / "axial-report-v1.md").write_text(template, encoding="utf-8")
    print("sources:", n, "pages:", total_pages)
    print("wrote", OUT / "axial-report-v1.md")


if __name__ == "__main__":
    main()
