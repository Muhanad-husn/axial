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

**Endnotes are deliberately NOT back matter, and `endnotes` is one of the
labels the model may answer with.** In this genre the historiographical
quarrel happens in the notes. Measured on the corpus of record, cutting
endnotes costs 6.9% of head-page evidence for 5,132 mostly worthless pages;
bibliography plus index plus front matter costs 5.2% for 3,987. The first
run of this classifier offered four back-matter labels and `body`, with the
prompt merely telling the model not to list a note heading -- and 11 of the
64 headings it called front matter were endnotes (`NOTES`, `Notes to pages
13-22`, `Notes to p. 190`), because a note heading is plainly not ordinary
argument and the vocabulary gave it nowhere else to go. `endnotes` is now a
label of its own, recorded in the cache and excluded from
`BACK_MATTER_CLASSES`. Offering the right answer is the point of making
this a model call rather than a regex; leaving it to fall through to `body`
by accident is not enough.

**`front matter` is the material printed before the argument starts, never
the argument's own opening.** The same first run swept `CONCLUSION`,
`Epilogue`, `PROLOGUE`, `OUTLINE OF THE ARGUMENT`, `The Structure of the
Book` and a chapter title into it. A conclusion is argument. The prompt now
names those cases as body outright.

**It fails open.** A heading the classification never reached, an answer
naming a class outside the five, an index the batch never carried: all read
as body, so the surfaces in that section keep their pages. The cut is
one-way, and cutting a real name costs more than keeping a worthless one --
the same rule the router states as "an unknown label fails open to prose"
(§7.8).

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

# The four classes that take a section's surfaces out of the name space, the
# fifth the model may answer with but which keeps them, and the default.
# Written as the model is asked to write them.
BIBLIOGRAPHY_CLASS = "bibliography"
INDEX_CLASS = "index"
FRONT_MATTER_CLASS = "front matter"
APPENDIX_CLASS = "appendix"
ENDNOTES_CLASS = "endnotes"
BODY_CLASS = "body"
BACK_MATTER_CLASSES = frozenset(
    {BIBLIOGRAPHY_CLASS, INDEX_CLASS, FRONT_MATTER_CLASS, APPENDIX_CLASS}
)
# Every label a response may name. `endnotes` is here and NOT in
# `BACK_MATTER_CLASSES` on purpose: the model needs somewhere right to put a
# note heading, and what it puts there survives.
CLASSIFIED_CLASSES = BACK_MATTER_CLASSES | {ENDNOTES_CLASS}

# The largest block of headings one call may carry, in characters. A
# construction limit on request size, exactly as
# `axial.merge_names.DEFAULT_MEMBER_CHAR_BUDGET` is for a merge call -- not a
# quality knob and not tuned. The corpus of record's 2,813 distinct headings
# are a few calls at this budget.
SECTION_CHAR_BUDGET = 20_000

_PROMPT_TEMPLATE = """\
Below is a numbered list of section headings taken from academic books. Say \
which of them name apparatus around the book rather than the book's own \
argument.

Five classes, and a heading belongs to one only if it names:
- "bibliography" -- a reference list, works cited, sources consulted;
- "index" -- an index of names, subjects or places;
- "appendix" -- an appendix, annex or supplementary table section;
- "endnotes" -- notes collected away from the text: "Notes", "N O T E S", \
"Endnotes", "Notes to Chapter 3", "Notes to pages 13-22";
- "front matter" -- pages printed BEFORE the argument begins: a title page, \
a copyright or publisher page, a series page, a dedication, an epigraph, a \
table of contents, a list of figures, maps or tables, acknowledgements, or \
a preface or foreword.

EVERYTHING THE BOOK ARGUES IS "body", and you must not list it. That \
includes, whatever it is called: an introduction, a prologue, a conclusion, \
an epilogue, an afterword, an outline or plan of the book ("Outline of the \
Argument", "The Structure of the Book", "What You Will Find Here"), a part \
divider ("Part III", "P A R T I"), and any chapter or section title, \
however general or unhelpful it looks. A conclusion is argument, not front \
matter. A chapter whose title happens to start with the word "Notes" is a \
chapter.

Some headings come out of the scanner with a space between every letter \
("N O T E S", "B I B L I O G R A P H Y"). Read those as the word they spell.

If you are not sure which of the five a heading is, or whether it is one at \
all, leave it out. Every heading you list as bibliography, index, appendix \
or front matter loses all of its content permanently, and there is no way \
back; "endnotes" and anything left out are kept.

HEADINGS.
{headings}

RESPONSE. Reply with ONLY a JSON object (no prose, no markdown fences), \
carrying one key "back_matter": a list of objects, one per heading that IS \
one of the five classes above, each {{"n": <the heading's number>, "class": \
"<one of bibliography, index, appendix, endnotes, front matter>"}}. A \
heading you do not list is treated as body. An empty list is a valid answer.
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
    result: the ones the response named as one of the five classes carry
    that class, everything else carries `BODY_CLASS`. An entry whose `n` is
    not one of this batch's own numbers, or whose `class` is not one of the
    five, is dropped -- the model can only ever cut a heading it was asked
    about, and only for one of the four stated reasons that cut (`endnotes`
    is a fifth answer, and it keeps the heading)."""
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
        if not isinstance(label, str) or label.strip().casefold() not in CLASSIFIED_CLASSES:
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
    B): bibliography, index, front matter and appendix. Never `endnotes`,
    which is a label the classification can and does return, and never
    `body`."""
    classes = classify_sections(
        headings, client=client, classes_path=classes_path, config_path=config_path
    )
    return frozenset(heading for heading, label in classes.items() if label in BACK_MATTER_CLASSES)
