"""Back-matter section classification (issue #508 class B, §7.16).

A surface form seen only inside a bibliography, an index, front matter or an
appendix is not a name page. Deciding that a heading means "bibliography" is
not a string-shape fact, so it is not a regex here: the corpus's DISTINCT
section headings are classified once by one flash call and cached to disk,
the same classify-once shape the source router uses (#164) and the same
lesson #268 paid for -- six hand-tuned constants read 4 of 30 real cases and
one model call replaced them. A ten-alternative English back-matter
vocabulary living in `src/` would also break the domain-frame rule: no
corpus- or language-specific content belongs in code.

The answer record carries its own verbatim `section` (§7.15), so nothing
here reads a chunk or a tree.

**Endnotes are deliberately NOT back matter.** In this genre the
historiographical quarrel happens in the notes. Measured on the corpus of
record, cutting endnotes costs 6.9% of head-page evidence for 5,132 mostly
worthless pages; bibliography plus index plus front matter costs 5.2% for
3,987 -- so the notes stay and the other four go. The prompt says so.

**It fails open.** A heading the classification never reached, an answer
naming a class outside the four, an index the batch never carried: all read
as body, so the surfaces in that section keep their pages. Cutting a real
name costs more than keeping a worthless one, and this mirrors the router's
own "an unknown label fails open to prose" rule (§7.8).

The cache (`data/names/section_classes.json`) maps every heading ever asked
about to its class, so a re-run makes no call at all and a newly ingested
source only ever pays for the headings it actually introduced.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from axial.llm import NAME_SECTIONS_PASS_NAME, LLMClient, get_client
from axial.model_json import complete_json, parse_model_json
from axial.paths import DEFAULT_PIPELINE_CONFIG_PATH

# Alongside `inventory.jsonl`, `alias_map.json`, `index.json` and
# `disagreements.jsonl` -- §6's `data/names/` layout.
DEFAULT_SECTION_CLASSES_PATH = Path("data/names/section_classes.json")

SECTION_CLASSES_VERSION = 1

# The four classes that take a section's surfaces out of the name space, and
# the one that keeps them. Written as the model is asked to write them.
BIBLIOGRAPHY_CLASS = "bibliography"
INDEX_CLASS = "index"
FRONT_MATTER_CLASS = "front matter"
APPENDIX_CLASS = "appendix"
BODY_CLASS = "body"
BACK_MATTER_CLASSES = frozenset(
    {BIBLIOGRAPHY_CLASS, INDEX_CLASS, FRONT_MATTER_CLASS, APPENDIX_CLASS}
)

# The largest block of headings one call may carry, in characters. A
# construction limit on request size, exactly as
# `axial.merge_names.DEFAULT_MEMBER_CHAR_BUDGET` is for a merge call -- not a
# quality knob and not tuned. The corpus of record's 2,813 distinct headings
# are a few calls at this budget.
SECTION_CHAR_BUDGET = 20_000

_PROMPT_TEMPLATE = """\
Below is a numbered list of section headings taken from academic books. Say \
which of them are BACK MATTER OR FRONT MATTER rather than the book's own \
argument.

A heading is one of exactly four classes if it names:
- "bibliography" -- a reference list, works cited, sources consulted;
- "index" -- an index of names, subjects or places;
- "front matter" -- a title page, copyright page, dedication, table of \
contents, list of figures, acknowledgements, preface or foreword;
- "appendix" -- an appendix, annex or supplementary table section.

ENDNOTES AND FOOTNOTES ARE NOT IN ANY OF THESE FOUR CLASSES. A heading like \
"Notes", "Notes to Chapter 3" or "Endnotes" is ordinary argument for this \
purpose -- do not list it. Neither is a chapter, an introduction, a \
conclusion, an epilogue or any other part of the book's own text.

Some headings come out of the scanner with a space between every letter \
("N O T E S", "B I B L I O G R A P H Y"). Read those as the word they spell.

If you are not sure what a heading names, leave it out.

HEADINGS.
{headings}

RESPONSE. Reply with ONLY a JSON object (no prose, no markdown fences), \
carrying one key "back_matter": a list of objects, one per heading that IS \
one of the four classes above, each {{"n": <the heading's number>, "class": \
"<one of bibliography, index, front matter, appendix>"}}. A heading you do \
not list is treated as ordinary argument. An empty list is a valid answer.
"""


def load_section_classes(path: Path) -> dict[str, str]:
    """Every heading this corpus has already been classified on, mapped to
    its class. An absent or damaged cache reads as empty -- a re-ask costs
    one cheap call, and refusing to run over a corrupted cache would be a
    worse failure than paying for it again."""
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    sections = document.get("sections") if isinstance(document, dict) else None
    if not isinstance(sections, dict):
        return {}
    return {key: value for key, value in sections.items() if isinstance(value, str)}


def write_section_classes(path: Path, classes: dict[str, str]) -> None:
    """Persist the classification, sorted by heading so a diff between two
    runs reads as what actually changed."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "version": SECTION_CLASSES_VERSION,
        "sections": {heading: classes[heading] for heading in sorted(classes)},
    }
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")


def _batches(headings: list[str]) -> list[list[str]]:
    """`headings` split into as few blocks as fit under
    `SECTION_CHAR_BUDGET`, so no single request grows with the corpus."""
    batches: list[list[str]] = []
    current: list[str] = []
    size = 0
    for heading in headings:
        cost = len(heading) + 8  # the rendered "  <n>. " prefix and newline
        if current and size + cost > SECTION_CHAR_BUDGET:
            batches.append(current)
            current, size = [], 0
        current.append(heading)
        size += cost
    if current:
        batches.append(current)
    return batches


def build_prompt(headings: list[str]) -> str:
    """One batch's prompt: the headings, numbered from 1, verbatim."""
    rendered = "\n".join(f"{n}. {heading}" for n, heading in enumerate(headings, start=1))
    return _PROMPT_TEMPLATE.format(headings=rendered)


def parse_response(raw: str, headings: list[str]) -> dict[str, str]:
    """One batch's classification. Every heading in the batch is in the
    result: the ones the response named as one of the four classes carry
    that class, everything else carries `BODY_CLASS`. An entry whose `n` is
    not one of this batch's own numbers, or whose `class` is not one of the
    four, is dropped -- the model can only ever cut a heading it was asked
    about, and only for one of the four stated reasons."""
    classes = {heading: BODY_CLASS for heading in headings}
    document: Any = parse_model_json(raw)
    entries = document.get("back_matter") if isinstance(document, dict) else None
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        number = entry.get("n")
        label = entry.get("class")
        if not isinstance(number, int) or not 1 <= number <= len(headings):
            continue
        if not isinstance(label, str) or label.strip().casefold() not in BACK_MATTER_CLASSES:
            continue
        classes[headings[number - 1]] = label.strip().casefold()
    return classes


def classify_sections(
    headings: Iterable[str],
    *,
    client: LLMClient | None = None,
    classes_path: Path | None = None,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
) -> dict[str, str]:
    """Every heading in `headings`, mapped to its class. Cache-first: a
    heading already in `classes_path` is never re-asked, and a run whose
    headings are all cached makes no model call and builds no client."""
    classes_path = Path(classes_path) if classes_path is not None else DEFAULT_SECTION_CLASSES_PATH
    cached = load_section_classes(classes_path)

    wanted = sorted({heading for heading in headings if heading})
    pending = [heading for heading in wanted if heading not in cached]
    if not pending:
        return {heading: cached[heading] for heading in wanted}

    if client is None:
        client = get_client(config_path=config_path)

    for batch in _batches(pending):
        raw = complete_json(client, build_prompt(batch), NAME_SECTIONS_PASS_NAME)
        cached.update(parse_response(raw, batch))

    write_section_classes(classes_path, cached)
    return {heading: cached[heading] for heading in wanted}


def back_matter_sections(
    headings: Iterable[str],
    *,
    client: LLMClient | None = None,
    classes_path: Path | None = None,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
) -> frozenset[str]:
    """The subset of `headings` whose surfaces leave the name space (class
    B): bibliography, index, front matter and appendix. Never endnotes."""
    classes = classify_sections(
        headings, client=client, classes_path=classes_path, config_path=config_path
    )
    return frozenset(heading for heading, label in classes.items() if label in BACK_MATTER_CLASSES)
