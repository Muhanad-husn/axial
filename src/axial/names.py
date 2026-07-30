"""Phase A v1 slice 04 (issue #415): the name inventory and similarity view
(`specs/PRODUCT.md` §7.16, P0-12's first two bullets).

D10: "Reconcile runs over names, not notes. Similarity and clustering are a
viewing aid so the merge aggressiveness can be chosen by looking at the
distribution; the model makes the merge calls with clusters as hints. Start
loose, tighten by inspection." This module builds the first two of the
three artifacts §7.16 describes under `data/names/` -- the third, the alias
map, is slice 05 (Reconcile proper), which this module never calls into and
never makes a merge decision itself:

  1. **The inventory (LLM-free).** One record per distinct name SURFACE FORM
     out of slice 02's per-note answer records
     (`data/answers/<source_id>.jsonl`, `axial.interrogate`), read from
     exactly the two fields §7.16 names -- `names[]` (which carries its own
     `kind`) and `citations[].cited` -- "the complete, lossless record of
     what the corpus said." `uses`, `defines`, `arguing_against` and
     `position_of` are deliberately NOT read here, even though an earlier
     draft of this slice's brief listed them: verified directly against the
     real 6,148-note corpus, `arguing_against`/`position_of` are
     argumentative CLAUSES describing a stance (61-74 characters on
     average, up to 310), not name surface forms, and are overwhelmingly
     unique per note; `uses`/`defines` mostly restate what `names[]` (whose
     `kind` vocabulary already includes `concept`) already carries, and
     §7.16's own inventory record shape -- `{surface, kind, count,
     chunk_ids[]}` -- has no room for a second field's kind either. Where
     the corpus gave one surface form more than one `kind`, the record
     keeps the most frequent, ties broken by first occurrence (§7.16) --
     the joined kind vocabulary (§7.15, issue #431) already removed the
     collisions that carried real information, so what a tie discards here
     is a distinction the vocabulary itself declines to make.
     **Issue #445: a locator-shaped surface form (`is_locator_shaped`) is
     scoped by source instead of collapsed into one node.** Keying the
     inventory by exact surface string is correct for `United States` (one
     surface, many books, one right page) and wrong for a figure/table
     locator, which is book-relative: `Table 4.1` in five different books is
     five different tables, not one. `build_inventory` groups a locator's
     occurrences per source and only renders a scoped identity
     (`scoped_surface_form`, "Table 4.1 (source_id)") for a surface that
     actually spans more than one source -- measured on the corpus of
     record, 52 of 358 locator-shaped surfaces, never the 306 that are
     already single-source.
  2. **The similarity view (LLM-free).** Every distinct surface form is
     embedded with the same local, deterministic, CPU sentence-transformer
     `axial.distill.embed` uses (`DEFAULT_MODEL_NAME`, lazy-imported --
     mirrors that module's own lazy-import pattern, never `run_embed`/
     `_flatten_metadata`, which are chunk-shaped and keyed on the closed tag
     axes slice 03 retired), then clustered with HDBSCAN
     (`axial.distill.readiness`'s own PCA + StandardScaler + HDBSCAN
     pipeline, reused as a pattern, not called: that module clusters chunk
     embeddings for a different question, "is this tag value ready to
     graduate off the LLM"). PCA first is not optional at this embedding
     dimensionality (384): raw-space HDBSCAN measured directly against
     20,000 real surface forms from this corpus took 316s; PCA(93, the same
     component count `axial.distill.readiness` measured against this same
     embedding model's chunk-embedding spectrum) then HDBSCAN cuts that to
     49s -- roughly 6x, from the same curse-of-dimensionality cause that
     module's own docstring names. `min_cluster_size=2`/`min_samples=1` --
     the loosest values HDBSCAN accepts -- rather than that module's tuned
     15/5: D10 says start loose, and a merge-hint viewing aid must not
     itself discard a real 2-member alias pair as noise before the founder
     ever sees it.
  3. Both artifacts persist under `data/names/` (§6's directory layout,
     `data/names/ # inventory, similarity view, alias map, index`):
     `inventory.jsonl` (one JSON object per surface form, the exact §7.16
     shape) and `embeddings.lance` (vectors + cluster labels, LanceDB,
     `axial.distill.embed`'s own write convention: `mode="overwrite"`,
     embedded/local/no server) plus a small manifest.
  4. `examine_names`/`format_names_report` read the persisted vectors back
     (zero model/embedding calls, mirroring `axial.chunk.examine_chunks`'s
     own read-only-over-persisted-data shape) and RE-CLUSTER them at a
     SWEEP of candidate tightnesses -- P0-12's full ask: "cluster counts and
     sizes at a few candidate tightnesses ... the largest clusters with
     members, and a sample of borderline pairs" -- so merge aggressiveness
     is chosen by comparing sections of one table, not by editing this
     module. Never re-embeds (measured: 835s to embed the real corpus vs.
     ~11 minutes to cluster it once -- re-embedding per candidate would make
     a sweep unusable). The candidates sweep `min_cluster_size` only, by
     default: measured directly against the real 78,115-entry similarity
     view, one HDBSCAN fit at a fixed `min_samples` takes ~657s regardless
     of `min_cluster_size` (the mutual-reachability/MST computation
     `min_samples` controls), while re-deriving labels at a different
     `min_cluster_size` from that SAME fit's tree (`_relabel_from_tree`,
     reusing `hdbscan`'s own internal `_tree_to_labels`) took ~0.6s each --
     so `min_cluster_size` is the cheap knob (swept, several values, one
     fit total) and `min_samples` is the expensive one (exposed singly, via
     `--min-samples`; comparing two values costs two full fits, ~22 minutes,
     not something to default into). Candidate values are a plain round-
     number progression (`DEFAULT_TIGHTNESS_MIN_CLUSTER_SIZES`), never
     tuned, and CLI-overridable (`axial names examine --min-cluster-sizes`)
     -- the founder's own dial, not a heuristic's magic number.

Out of scope (this slice only): making any merge decision (05, the alias
map), any LLM call, and touching `axial.distill.embed`'s existing
chunk-embedding behaviour, which this module never imports from.

**Fix (2026-07-29): `is_numeral_only_surface` gates locator residue -- a
bare page number or a plain century -- out of every model call, in both
downstream passes.** This module still builds and persists an inventory
entry for one (§7.16 is lossless: "the complete, lossless record of what
the corpus said"), so nothing here changes; `axial.merge_names.
run_merge_names` and `axial.gather.run_gather` are what filter it out, at
the point each asks the model something, so that filter takes effect on
the next `axial names merge`/`axial names gather` run with no rebuild of
this module's own artifacts required.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator

from axial.interrogate import _default_answers_dir, is_abstention
from axial.paths import DEFAULT_PIPELINE_CONFIG_PATH

# The same local, deterministic, CPU sentence-transformer `axial.distill.
# embed` embeds vault chunks with (DEC-35) -- one shared default so a name's
# vector and a chunk's vector live in the same embedding space, should a
# later slice ever want to compare them.
DEFAULT_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"

# §6's directory layout: `data/names/ # inventory, similarity view, alias
# map, index (§7.16)` -- all three of Reconcile's artifacts share one
# parent; slice 05 writes `alias_map.json` alongside these two.
DEFAULT_NAMES_DATA_DIR = Path("data/names")
DEFAULT_INVENTORY_PATH = DEFAULT_NAMES_DATA_DIR / "inventory.jsonl"
DEFAULT_EMBEDDINGS_DIR = DEFAULT_NAMES_DATA_DIR / "embeddings.lance"
DEFAULT_MANIFEST_PATH = DEFAULT_NAMES_DATA_DIR / "similarity_manifest.json"
TABLE_NAME = "names"

# HDBSCAN's own noise label (never cluster 0) -- named so no caller has to
# remember the magic number (mirrors `axial.distill.readiness.NOISE_LABEL`).
NOISE_LABEL = -1

# The loosest values HDBSCAN accepts (D10: "start loose, tighten by
# inspection") -- not `axial.distill.readiness`'s tuned 15/5, which answers a
# different question (tag-value readiness) over chunk embeddings, not
# name-alias candidates over name embeddings.
DEFAULT_MIN_CLUSTER_SIZE = 2
DEFAULT_MIN_SAMPLES = 1

# Reused from `axial.distill.readiness.DEFAULT_PCA_COMPONENTS`: measured
# against the real 18,410-chunk corpus's own 384-dim embedding spectrum
# (Kaiser criterion), for the same embedding model this module uses. Not
# re-derived for the name-surface-form distribution specifically (a
# different, shorter-text population) -- reusing an already-measured
# reduction for the same model beats leaving PCA off entirely (see module
# docstring's 316s-vs-49s finding) or inventing a second untested constant.
DEFAULT_PCA_COMPONENTS = 93

# `examine_names`'s default tightness sweep (founder-requested, P0-12):
# a plain round-number progression of `min_cluster_size` -- not a tuned
# value, the founder's own dial, overridable from the CLI
# (`axial names examine --min-cluster-sizes`). Held at the single loosest
# `min_samples` (=`DEFAULT_MIN_SAMPLES`) by default: measured directly
# against this corpus's real 78,115-entry similarity view, one HDBSCAN fit
# at fixed `min_samples` takes ~600s regardless of `min_cluster_size`
# (the mutual-reachability/MST computation `min_samples` controls, not
# `min_cluster_size`), while re-deriving labels at a different
# `min_cluster_size` from that SAME fit's tree (`_relabel_from_tree`) is
# near-instant -- so `min_cluster_size` is the cheap knob to sweep by
# default and `min_samples` is the one that costs a full refit per value
# (exposed too, but singly, via `--min-samples`, not swept).
DEFAULT_TIGHTNESS_MIN_CLUSTER_SIZES: tuple[int, ...] = (2, 5, 10, 20)

# How many borderline (near-miss) pairs `sweep_tightness` reports per
# candidate tightness -- small enough that "few candidate tightnesses" x
# this stays one readable table (P0-12: "a sample of borderline pairs").
DEFAULT_BORDERLINE_PAIRS = 5

# The two fields §7.16 names as the inventory's source: "built by reading
# every answer record's `names` and `citations`". Nothing else is read.
_NAMES_FIELD = "names"
_CITATIONS_FIELD = "citations"

_WHITESPACE = re.compile(r"\s+")

# Issue #445: a locator -- a figure, table, map or similar cross-reference --
# is book-relative. "Table 4.1" in one book and another book's own "Table
# 4.1" are not the same thing, but keying the inventory by exact surface
# string (below) collapses them into one node by construction, exactly the
# same shape of bug as v0's bipartite edge set. Measured on the corpus of
# record: 358 of 78,115 inventory surfaces are locator-shaped, and 52 of
# those actually span more than one source -- the real defect; the other 306
# are single-source and already work.
#
# A shape test, not a threshold: it carries no tunable constant, and it does
# not gate on `kind` -- a `citations[].cited` mention of a locator is exactly
# as book-relative as a `names[]` one.
LOCATOR_PATTERN = re.compile(
    r"^(fig\.?|figure|table|map|chart|graph|plate|box|diagram|appendix)\b",
    re.IGNORECASE,
)


def is_locator_shaped(surface_form: str) -> bool:
    """Whether `surface_form` reads as a book-relative locator (issue #445).
    Names not matched by this (`6.1. Aseel's displacement trajectory`,
    `Bramall table 2.2`) are already single-source and out of this issue's
    scope."""
    return bool(LOCATOR_PATTERN.match(surface_form))


# Fix (2026-07-29, first bounded `axial names gather` run): a bare page
# number or a plain `Nth century` reads as a name to no one -- it is locator
# residue from `citations[].cited`/`names[]` that survived #445's own
# book-relative scoping (a locator prefix like "Table"/"Figure" never
# matches this), not a name a merge or gather call should ever reason about.
# Measured on the corpus of record: 620 of 78,198 inventory surfaces (0.79%)
# match, 319 of those carry 2+ member notes -- the ones a pass would actually
# spend a call on; `13` alone carries 18 member notes across 12 books.
#
# A shape test, not a threshold: ordinals and "Nth century" are in scope
# (`10th century`, `11th`), a bare cardinal is in scope (`100`, `13`), and
# nothing else is -- a date range (`1050-1250`, `1060s`) or anything with a
# second token (`10 Downing Street`, `10th of Ramadan`, `1 John 5.19`) is
# deliberately NOT matched: it is a real name that happens to start with a
# digit, not locator residue. Measured against the corpus of record: 1,086
# digit-initial surfaces are near-misses this pattern correctly leaves alone.
NUMERAL_ONLY_PATTERN = re.compile(r"^[0-9]+(st|nd|rd|th)?( century)?$", re.IGNORECASE)


def is_numeral_only_surface(surface_form: str) -> bool:
    """Whether `surface_form` is bare locator residue -- a page number or a
    plain century -- rather than a name. The one place this predicate lives;
    `axial.merge_names.run_merge_names` and `axial.gather.run_gather` both
    import it rather than re-deriving it, so neither pass can ever put one of
    these in front of a model call on its own."""
    return bool(NUMERAL_ONLY_PATTERN.match(surface_form))


# Fix (2026-07-29, gather stratified sample): a chapter/footnote/endnote/
# appendix/table/figure/map/... POINTER -- "Chapter 4", "Footnote 36",
# "Table 4.1" -- is apparatus residue in the same family as the bare numerals
# above, not a name: it survived #445's own locator scoping and #471's
# numeral-only gate because it carries a label word in front of the number,
# not because it is a name. Measured on the corpus of record: 746 of 78,198
# inventory surfaces match, 211 of those carry two or more member notes --
# the ones a merge or gather call would otherwise spend a call on; `Chapter
# 4` alone carries 46.
#
# A shape test, not a threshold, reusing `LOCATOR_PATTERN`'s own label set
# (fig/figure/table/map/chart/graph/plate/box/diagram/appendix) plus the
# three chapter labels it does not cover (chapter, chap., ch.) and the two
# note-apparatus labels (footnote, endnote) -- never bare "note", which is
# not apparatus ("Note on the State" is a real name). The label must be
# followed directly by a digit or one of the English cardinal words one
# through twenty -- a closed, standard vocabulary, not a corpus-tuned one;
# real chapter/footnote counts in this corpus top out well under it -- for a
# match, so "Chapter of Sainte-Chapelle", "Table of Ranks" and "Chapter VII
# of the UN Charter" (a real citation to a treaty's own numbered chapter, not
# a pointer into the book at hand -- and Roman numerals are out of scope
# entirely, deliberately conservative rather than guessed) all survive
# untouched, and so does any bare-letter appendix/table ("Appendix A",
# "Table B.1").
_APPARATUS_LABEL_ALTERNATION = (
    r"(chapter|chap\.|ch\.|footnote|endnote|fig\.?|figure|table|map|chart|graph|plate|box|"
    r"diagram|appendix)"
)
_APPARATUS_NUMBER_WORD_ALTERNATION = (
    r"(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|"
    r"fifteen|sixteen|seventeen|eighteen|nineteen|twenty)"
)
APPARATUS_POINTER_PATTERN = re.compile(
    rf"^{_APPARATUS_LABEL_ALTERNATION}\s+([0-9]|{_APPARATUS_NUMBER_WORD_ALTERNATION}\b)",
    re.IGNORECASE,
)


def is_apparatus_pointer_shaped(surface_form: str) -> bool:
    """Whether `surface_form` reads as a pointer into a document's own
    apparatus -- a chapter, footnote, endnote, appendix, table or figure
    number -- rather than a name. Row D of issue #508's cut set: 746
    surfaces, 677 pages, and the 17 of them at 10+ member notes (`Chapter 5`
    at 52, `Chapter 4` at 50) are the point of the cut, not its risk."""
    return bool(APPARATUS_POINTER_PATTERN.match(surface_form))


# Issue #508 row F: a date or a date range is not a name. 1,012 inventory
# surfaces, 959 pages, 16 of them at 10+ member notes. Twelve month names is
# a closed, standard vocabulary in the same sense as the cardinal words
# `APPARATUS_POINTER_PATTERN` above already carries -- not a corpus-tuned
# list.
#
# A shape test, not a threshold: the WHOLE surface has to be the date. A
# year range (`1917-1918`, `1917–18`, `1990/91`), a decade (`1060s`,
# `1950s-1960s`) and a day/month/year in either order (`6 June 1975`,
# `June 6, 1975`, `March 1963`) match; a name that merely carries a date
# (`1948 War`, `June 1967 War`, `1917 Balfour Declaration`, `10th of
# Ramadan`) and a bare month (`March`, which is also a protest) do not.
# A bare year (`1963`) is already row C's, so nothing here matches one.
# Rows C and F deliberately overlap in subject and not in shape: C's own
# stated near-misses `1050-1250` and `1060s` -- left alone in 2026-07-29 as
# "a real name that happens to start with a digit" -- are exactly what F
# now cuts, and C's pattern is unchanged.
_MONTH_ALTERNATION = (
    r"(january|february|march|april|may|june|july|august|september|october|november|december)"
)
DATE_PATTERN = re.compile(
    r"^(?:"
    r"[0-9]{4}s?\s*[-‐-―/]\s*[0-9]{2,4}s?"
    r"|[0-9]{4}s"
    rf"|[0-9]{{1,2}}\s+{_MONTH_ALTERNATION}\s+[0-9]{{4}}"
    rf"|{_MONTH_ALTERNATION}\s+[0-9]{{1,2}},\s*[0-9]{{4}}"
    rf"|{_MONTH_ALTERNATION}\s+[0-9]{{4}}"
    r")$",
    re.IGNORECASE,
)


def is_date_shaped(surface_form: str) -> bool:
    """Whether `surface_form` is wholly a date or a date range (row F)."""
    return bool(DATE_PATTERN.match(surface_form))


# Issue #508 row G: a page, volume or number reference, and the Latin
# reference words a footnote uses instead of repeating a citation. 140
# surfaces, 98 pages, none at 10+ member notes -- the smallest row in the
# set, kept because what it catches is unambiguous.
#
# A shape test, not a threshold: the label must be followed by a digit, so
# the surname `Page`, the title `Pages from a Syrian Notebook` and
# `Volume One` all survive, and `P. Anderson` survives because an initial is
# not a page number. The Latin words match only as the whole surface, so
# `Ibn Khaldun` and `Nos Ancetres les Gaulois` are untouched.
_REFERENCE_LABEL_ALTERNATION = r"(pp?\.|pages?|vols?\.|volumes?|nos?\.|numbers?)"
_REFERENCE_WORD_ALTERNATION = r"(ibid|op\.?\s*cit|loc\.?\s*cit|passim|et\s+seq)"
REFERENCE_POINTER_PATTERN = re.compile(
    rf"^(?:{_REFERENCE_LABEL_ALTERNATION}\s*[0-9]|{_REFERENCE_WORD_ALTERNATION}\.?$)",
    re.IGNORECASE,
)


def is_reference_pointer_shaped(surface_form: str) -> bool:
    """Whether `surface_form` is a page/volume/number reference or one of
    the Latin reference words (row G)."""
    return bool(REFERENCE_POINTER_PATTERN.match(surface_form))


# Issue #508 row H, the largest shape row: 5,995 surfaces, 3,787 pages, 4 of
# them at 10+ member notes. A surface that carries its own citation year or
# `et al` is a reference, not a name -- the entity it refers to already
# holds its own page under its own name, which is why the collateral here is
# small however large the row is.
#
# A shape test, not a threshold: a parenthesized four-digit year with an
# optional disambiguating letter (`(1983)`, `(1983a)`), a comma followed by
# a four-digit year (`Tilly, 1990`), or `et al`. A parenthesized acronym
# (`Autonomous Administration of Northeast Syria (AANS)`, §7.16's own
# candidate rule) carries no year and is untouched, and so is a title or an
# event that merely contains a year without a comma or parentheses
# (`The 1948 War`).
AUTHOR_YEAR_PATTERN = re.compile(
    r"\((1[0-9]{3}|20[0-9]{2})[a-z]?\)|,\s*(1[0-9]{3}|20[0-9]{2})\b|\bet\s+al\b",
    re.IGNORECASE,
)


def carries_author_year_citation(surface_form: str) -> bool:
    """Whether `surface_form` carries an author-year citation (row H)."""
    return bool(AUTHOR_YEAR_PATTERN.search(surface_form))


# Issue #508 row P: a bare pointer into a source list or a bracketed
# reference marker. 661 surfaces. `Chapter 5` and `Footnote 36` are row D's
# and a bare `34` is row C's; what is left is `source 26`, `reference 12`
# and `[34]`.
#
# A shape test, not a threshold: the label must be followed by a digit
# (`Sources of Social Power` and `Reference Group Theory` survive), and the
# bracketed form must contain nothing but a number (`[Damascus]` survives).
# Bare `note` is deliberately absent for the same reason row D excludes it:
# `Note on the State` is a real name.
SOURCE_POINTER_PATTERN = re.compile(
    r"^(?:(sources?|references?)\s+[0-9]|\[\s*[0-9]+\s*\]$)",
    re.IGNORECASE,
)


def is_source_pointer_shaped(surface_form: str) -> bool:
    """Whether `surface_form` is a `source N` / `reference N` / `[N]`
    pointer (row P)."""
    return bool(SOURCE_POINTER_PATTERN.match(surface_form))


def is_cut_from_name_space(surface_form: str) -> bool:
    """Whether `surface_form` leaves the name space on shape alone -- rows
    C, D, E, F, G, H, P and S of issue #508's cut set, unioned. Row A, the
    ninth, is not a shape: it is the `citations[].cited` channel, dropped in
    `iter_name_occurrences` below.

    Row S is the interrogation's own abstention sentinel, which reached the
    inventory as a name once, with 24 member notes. `axial.interrogate.
    is_abstention` is reused rather than re-derived, so a change to what
    counts as an abstention never has to be made twice."""
    return (
        is_numeral_only_surface(surface_form)
        or is_apparatus_pointer_shaped(surface_form)
        or is_locator_shaped(surface_form)
        or is_date_shaped(surface_form)
        or is_reference_pointer_shaped(surface_form)
        or carries_author_year_citation(surface_form)
        or is_source_pointer_shaped(surface_form)
        or is_abstention(surface_form)
    )


# How a locator-shaped surface renders once its identity is scoped by source
# (issue #445): the surface plus its source in parentheses. This reuses the
# corpus's existing identifier system -- the surface-form string already IS
# the identity everywhere downstream (inventory key, embedding text,
# alias-map canonical, name-page title and filename) -- rather than inventing
# a second one. Human-readable, distinct per source, and a pure function of
# its two inputs, so it is stable across runs.
_SOURCE_SUFFIX = re.compile(r" \((?P<source_id>[^()]+)\)$")


def scoped_surface_form(surface_form: str, source_id: str) -> str:
    """The source-scoped identity for a locator-shaped `surface_form` that
    spans more than one source (`build_inventory`)."""
    return f"{surface_form} ({source_id})"


def unscope_surface_form(surface_form: str, source_id: str) -> str:
    """The exact inverse of `scoped_surface_form` for one known `source_id`
    -- what a source's own artifact caption would actually contain.
    `axial.materialize.find_artifact_links` uses this to recover the bare
    locator text from a source-scoped canonical/alias before matching
    captions. A surface form that does not carry that exact suffix is
    returned unchanged."""
    suffix = f" ({source_id})"
    return surface_form[: -len(suffix)] if surface_form.endswith(suffix) else surface_form


def parse_scoped_source(surface_form: str) -> str | None:
    """The `source_id` `scoped_surface_form` embedded in `surface_form`, or
    `None` when it is not locator-shaped or carries no such suffix (a bare,
    single-source locator, or anything else). `axial.merge_names.
    build_alias_map_nodes` uses this to refuse folding two source-scoped
    instances of the same locator into one canonical, however a cluster or
    the model proposes it."""
    if not is_locator_shaped(surface_form):
        return None
    match = _SOURCE_SUFFIX.search(surface_form)
    return match.group("source_id") if match else None


Encoder = Callable[[list[str]], list[list[float]]]
ClusterFn = Callable[[list[list[float]]], list[int]]


class NamesError(Exception):
    """Base class for all name-inventory errors."""


class NoAnswersToEmbedError(NamesError):
    """Raised when `answers_dir` holds no interrogation answer records, or
    none of them name anything -- running this pass before slice 02
    (`axial interrogate`) is a misconfigured invocation, not a valid empty
    inventory (mirrors `axial.distill.embed.NoChunksToEmbedError`'s own
    loud-failure convention)."""

    def __init__(self, answers_dir: Path):
        self.answers_dir = answers_dir
        super().__init__(
            f"no interrogation answers found under {answers_dir} to build a name "
            f"inventory from; run `axial interrogate` first"
        )


class NoNamesToClusterError(NamesError):
    """Raised when `examine_names` is asked to read a similarity view that
    does not exist yet -- running the report before `run_names` is a
    misconfigured invocation."""

    def __init__(self, embeddings_dir: Path):
        self.embeddings_dir = embeddings_dir
        super().__init__(
            f"no persisted similarity view found at {embeddings_dir}; run the name "
            f"inventory pass first"
        )


# ---------------------------------------------------------------------------
# Collecting name occurrences off the answer records (§7.16: names + citations)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NameOccurrence:
    """One mention of one surface form, in one note. `kind` is only ever
    set for a `names[]` mention -- a citation is not asked for one.
    `source_id` (issue #445) is the note's own source, read straight off the
    answer record rather than parsed out of `chunk_id` -- it decides whether
    a locator-shaped surface needs a source-scoped identity (`build_
    inventory`), and defaults to `""` so existing 3-positional-arg call
    sites (never locator-shaped) are unaffected."""

    surface_form: str
    chunk_id: str
    kind: str | None = None
    source_id: str = ""


def _clean(value: Any) -> str | None:
    """Whitespace-normalise a candidate surface form; `None` for anything
    that is not a non-blank string (never crash on a malformed answer)."""
    if not isinstance(value, str):
        return None
    cleaned = _WHITESPACE.sub(" ", value).strip()
    return cleaned or None


def iter_name_occurrences(record: dict[str, Any]) -> Iterator[NameOccurrence]:
    """Every `NameOccurrence` one answer record contributes, from `names[]`
    only (§7.16) -- skips failure/skip records (no `answers` key) and the D7
    abstention on the field.

    **This is the one place issue #508's cut set is enforced.** Row A is the
    absence of a `citations[].cited` arm here: the field keeps being
    recorded, it just stops being read into the name space. Rows C through
    H, P and S are `is_cut_from_name_space`. Row B -- a surface seen only in
    a bibliography, index, front matter or appendix -- is NOT applied: it
    needs a judgment about what a section heading means, it failed
    measurement twice, and it was re-scoped to its own issue. This pass
    makes no model call.

    A page falls out of the vault only when EVERY surface that would have
    been its member is cut, which this per-occurrence filter gives for free:
    a surface with one surviving occurrence keeps its inventory entry, and
    a canonical node with one surviving member keeps its page."""
    answers = record.get("answers")
    if not isinstance(answers, dict):
        return
    chunk_id = record.get("chunk_id", "")
    source_id = record.get("source_id", "")

    names = answers.get(_NAMES_FIELD)
    if isinstance(names, list) and not is_abstention(names):
        for entry in names:
            if not isinstance(entry, dict):
                continue
            surface_form = _clean(entry.get("name"))
            if surface_form is None or is_cut_from_name_space(surface_form):
                continue
            yield NameOccurrence(surface_form, chunk_id, _clean(entry.get("kind")), source_id)


def load_answer_records(answers_dir: Path) -> list[dict[str, Any]]:
    """Every record (answer, failure, or skip) across every
    `<source_id>.jsonl` under `answers_dir`, sorted by filename -- the same
    "filesystem order never leaks into the result" determinism convention
    `axial.distill.embed._load_chunk_records` uses. Blank lines are
    tolerated (mirrors the checkpoint reader's own tolerance)."""
    if not answers_dir.is_dir():
        return []
    records: list[dict[str, Any]] = []
    for path in sorted(answers_dir.glob("*.jsonl")):
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                records.append(json.loads(line))
    return records


def collect_occurrences(records: Iterable[dict[str, Any]]) -> Iterator[NameOccurrence]:
    """Flat-map `iter_name_occurrences` over every record."""
    for record in records:
        yield from iter_name_occurrences(record)


# ---------------------------------------------------------------------------
# The inventory: one entry per distinct surface form (§7.16's exact shape)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InventoryEntry:
    """One distinct name surface form: `{surface, kind, count, chunk_ids[]}`
    (§7.16). `kind` is the single most frequent one seen for it, ties broken
    by first occurrence -- `None` when the surface never appeared with a
    kind at all (a citation-only surface form)."""

    surface_form: str
    kind: str | None
    count: int
    chunk_ids: tuple[str, ...]


def build_inventory(occurrences: Iterable[NameOccurrence]) -> list[InventoryEntry]:
    """Group occurrences by their exact (whitespace-normalised) surface
    form -- "the complete, lossless record of what the corpus said" (§7.16).
    No casefolding, no fuzzy merge here -- two surface forms that differ by
    so much as case are two rows; embedding distance (not string identity)
    is this module's whole mechanism for saying two rows are close, and
    slice 05 is where a merge is actually decided.

    Issue #445: a locator-shaped surface (`is_locator_shaped`) is grouped
    per `(surface_form, source_id)` instead, up front, since it is
    book-relative and must not collapse across sources by construction --
    the same shape of bug the plain per-surface grouping above has for
    everything else. Whether that per-source grouping actually needs a
    scoped identity is decided once every occurrence has been seen: a
    locator mentioned in exactly one source keeps its bare surface form
    untouched (306 of 358 real locator surfaces, already correct); one that
    spans more than one source (52 of 358, the actual defect) is rendered
    via `scoped_surface_form`, so `Table 4.1` becomes as many distinct
    entries as it has sources, each with only that source's own `count`/
    `chunk_ids`.

    Returned sorted by the final (possibly scoped) surface form, for the
    same determinism reason `_load_chunk_records`/`_load_embedding_rows`
    sort by chunk_id."""
    grouped: dict[tuple[str, str | None], dict[str, Any]] = {}
    order = 0
    for occurrence in occurrences:
        scope_key = occurrence.source_id if is_locator_shaped(occurrence.surface_form) else None
        bucket = grouped.setdefault(
            (occurrence.surface_form, scope_key),
            {"count": 0, "kind_counts": {}, "kind_first_seen": {}, "chunk_ids": set()},
        )
        bucket["count"] += 1
        bucket["chunk_ids"].add(occurrence.chunk_id)
        if occurrence.kind:
            bucket["kind_counts"][occurrence.kind] = (
                bucket["kind_counts"].get(occurrence.kind, 0) + 1
            )
            bucket["kind_first_seen"].setdefault(occurrence.kind, order)
        order += 1

    # A locator-shaped surface needs a source-scoped identity only when it
    # actually spans more than one source -- decided globally, so a
    # single-source locator's bucket (scope_key not None, but the only one
    # for that surface) still renders as its own bare surface form.
    sources_by_surface: dict[str, set[str]] = {}
    for surface_form, scope_key in grouped:
        if scope_key is not None:
            sources_by_surface.setdefault(surface_form, set()).add(scope_key)

    entries = []
    for (surface_form, scope_key), bucket in grouped.items():
        if scope_key is not None and len(sources_by_surface[surface_form]) > 1:
            identity = scoped_surface_form(surface_form, scope_key)
        else:
            identity = surface_form
        kind_counts = bucket["kind_counts"]
        if kind_counts:
            # Most frequent kind; ties broken by first occurrence (§7.16).
            resolved_kind = min(
                kind_counts,
                key=lambda kind: (-kind_counts[kind], bucket["kind_first_seen"][kind]),
            )
        else:
            resolved_kind = None
        entries.append(
            InventoryEntry(
                surface_form=identity,
                kind=resolved_kind,
                count=bucket["count"],
                chunk_ids=tuple(sorted(bucket["chunk_ids"])),
            )
        )
    entries.sort(key=lambda entry: entry.surface_form)
    return entries


def write_inventory(entries: list[InventoryEntry], path: Path) -> None:
    """Write the inventory as one JSON object per line, §7.16's exact
    `{surface, kind, count, chunk_ids[]}` shape -- the complete, lossless,
    LLM-free artifact, independent of whatever the similarity view goes on
    to compute."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for entry in entries:
            handle.write(
                json.dumps(
                    {
                        "surface": entry.surface_form,
                        "kind": entry.kind,
                        "count": entry.count,
                        "chunk_ids": list(entry.chunk_ids),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )


# ---------------------------------------------------------------------------
# Embedding (the `axial.distill.embed` pattern, not its chunk-shaped code)
# ---------------------------------------------------------------------------


def _default_encoder(model_name: str) -> Encoder:
    """Lazily build the real sentence-transformer encoder (imports
    `sentence_transformers` here, never at module level, mirroring
    `axial.distill.embed._default_encoder`). CPU-only, eval-mode inference:
    deterministic given the same model checkpoint and input text."""
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(model_name)

    def encode(texts: list[str]) -> list[list[float]]:
        return model.encode(texts, convert_to_numpy=True).tolist()

    return encode


def _reduce_vectors(vectors: list[list[float]], pca_components: int = DEFAULT_PCA_COMPONENTS):
    """L2-normalise -> standardise -> PCA, the shared, tightness-independent
    half of the pipeline (reusing `axial.distill.readiness`'s own measured
    shape -- see module docstring for the real timing this step buys on this
    corpus). Computed ONCE per embedding set: a tightness sweep clusters the
    same reduced array at several `min_cluster_size`/`min_samples` settings
    rather than re-running this reduction (let alone re-embedding, which the
    real 835s-vs-~50s gap between embedding and clustering makes the one
    cost a sweep must never repeat) once per candidate."""
    import numpy as np
    from sklearn.decomposition import PCA
    from sklearn.preprocessing import StandardScaler, normalize

    array = np.asarray(vectors, dtype=np.float64)
    array = normalize(array)
    array = StandardScaler().fit_transform(array)

    n_components = max(1, min(pca_components, array.shape[0], array.shape[1]))
    return PCA(n_components=n_components, svd_solver="full", random_state=0).fit_transform(array)


def _cluster_reduced(reduced, min_cluster_size: int, min_samples: int) -> list[int]:
    """HDBSCAN over an already-PCA-reduced array -- the tightness-dependent
    half of the pipeline, cheap enough to call once per sweep candidate.
    `cluster_selection_method="leaf"`/`allow_single_cluster=True`:
    `axial.distill.readiness` measured `eom` (HDBSCAN's own implicit
    default) collapsing the whole corpus to one blob regardless of PCA dims,
    for this same embedding model family; `leaf` is reused for the same
    reason. Returns one integer label per row, in input order, unrelabelled:
    `-1` is `NOISE_LABEL`, real clusters start at `0`."""
    import hdbscan

    clusterer = hdbscan.HDBSCAN(
        min_cluster_size=min_cluster_size,
        min_samples=min_samples,
        cluster_selection_method="leaf",
        allow_single_cluster=True,
    )
    labels = clusterer.fit_predict(reduced)
    return [int(label) for label in labels]


def _default_cluster_fn(
    vectors: list[list[float]],
    *,
    pca_components: int = DEFAULT_PCA_COMPONENTS,
    min_cluster_size: int = DEFAULT_MIN_CLUSTER_SIZE,
    min_samples: int = DEFAULT_MIN_SAMPLES,
) -> list[int]:
    """`run_names`'s default single-setting `cluster_fn`: reduce once,
    cluster once. `sweep_tightness` (below) calls `_reduce_vectors`/
    `_fit_and_relabel` directly instead, to reduce once and cluster many
    times over the same persisted vectors."""
    reduced = _reduce_vectors(vectors, pca_components)
    return _cluster_reduced(reduced, min_cluster_size, min_samples)


def _relabel_from_tree(reduced, single_linkage_tree_numpy, min_cluster_size: int) -> list[int]:
    """Re-derive HDBSCAN labels at a different `min_cluster_size` from an
    ALREADY-FITTED clusterer's single-linkage tree, without recomputing the
    mutual-reachability graph/minimum-spanning tree -- the expensive part a
    fresh `HDBSCAN(...).fit_predict(...)` would redo (measured: ~600s at
    this corpus's real 78k-entry scale, independent of `min_cluster_size`).
    `min_cluster_size` only decides how the already-built tree is condensed
    into clusters -- a cheap, near-instant step -- so a `min_cluster_size`
    sweep needs exactly one fit, not one per candidate.

    Reuses `hdbscan`'s own internal `_tree_to_labels` (the same function
    `HDBSCAN.fit_predict` calls internally after building the tree) rather
    than reimplementing tree condensation -- the public API has no
    "relabel only" entry point, and hand-rolling one would duplicate a
    correctness-critical piece of the library `axial.distill.readiness`
    already trusts. Verified directly (this module's own inner unit tests)
    to reproduce byte-for-byte the same partition a fresh fit at the same
    `min_cluster_size`/`min_samples` produces."""
    from hdbscan.hdbscan_ import _tree_to_labels

    labels, _probabilities, _stabilities, _condensed_tree, _slt = _tree_to_labels(
        reduced,
        single_linkage_tree_numpy,
        min_cluster_size=min_cluster_size,
        cluster_selection_method="leaf",
        allow_single_cluster=True,
    )
    return [int(label) for label in labels]


# ---------------------------------------------------------------------------
# The pass: collect -> write inventory -> embed -> cluster -> persist
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NamesResult:
    """The outcome of one `run_names` call."""

    inventory_path: Path
    embeddings_dir: Path
    manifest_path: Path
    entry_count: int
    occurrence_count: int
    model_name: str
    embedding_dim: int
    cluster_count: int
    noise_count: int


def run_names(
    answers_dir: Path | None = None,
    inventory_path: Path | None = None,
    embeddings_dir: Path | None = None,
    manifest_path: Path | None = None,
    model_name: str = DEFAULT_MODEL_NAME,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
    encoder: Encoder | None = None,
    cluster_fn: ClusterFn | None = None,
    pca_components: int = DEFAULT_PCA_COMPONENTS,
    min_cluster_size: int = DEFAULT_MIN_CLUSTER_SIZE,
    min_samples: int = DEFAULT_MIN_SAMPLES,
) -> NamesResult:
    """Build the name inventory over every interrogation answer record under
    `answers_dir` (default resolved via `axial.interrogate._default_answers_
    dir`), write it to `inventory_path` (default `DEFAULT_INVENTORY_PATH`),
    embed each distinct surface form, cluster the embeddings, and persist
    vectors + cluster labels to a LanceDB table at `embeddings_dir` (default
    `DEFAULT_EMBEDDINGS_DIR`), plus a small JSON manifest at `manifest_path`
    (default `DEFAULT_MANIFEST_PATH`).

    `encoder`/`cluster_fn`, when given, replace the default sentence-
    transformer/HDBSCAN pipeline -- the seam this module's own inner unit
    tests use to exercise the collect/persist path without a real model or
    clustering run, mirroring `axial.distill.embed`'s own `encoder`
    injection seam.

    **Still LLM-free**, as it has always been: issue #508's cut set filters
    the surfaces this pass reads, and every rule that survived measurement
    is a shape test. Row B, the one that needed a model call, was re-scoped
    to its own issue.

    Raises `NoAnswersToEmbedError` when no answer records are found, or none
    of them name anything -- a loud failure rather than a silently empty
    inventory.
    """
    if answers_dir is None:
        answers_dir = _default_answers_dir(config_path)
    answers_dir = Path(answers_dir)
    if inventory_path is None:
        inventory_path = DEFAULT_INVENTORY_PATH
    inventory_path = Path(inventory_path)
    if embeddings_dir is None:
        embeddings_dir = DEFAULT_EMBEDDINGS_DIR
    embeddings_dir = Path(embeddings_dir)
    if manifest_path is None:
        manifest_path = DEFAULT_MANIFEST_PATH
    manifest_path = Path(manifest_path)

    records = load_answer_records(answers_dir)
    if not records:
        raise NoAnswersToEmbedError(answers_dir)

    occurrences = list(collect_occurrences(records))
    entries = build_inventory(occurrences)
    if not entries:
        raise NoAnswersToEmbedError(answers_dir)

    write_inventory(entries, inventory_path)

    if encoder is None:
        encoder = _default_encoder(model_name)
    vectors = encoder([entry.surface_form for entry in entries])

    if cluster_fn is None:
        labels = _default_cluster_fn(
            vectors,
            pca_components=pca_components,
            min_cluster_size=min_cluster_size,
            min_samples=min_samples,
        )
    else:
        labels = cluster_fn(vectors)

    rows = [
        {
            "surface_form": entry.surface_form,
            "kind": entry.kind or "",
            "count": entry.count,
            "chunk_ids_json": json.dumps(list(entry.chunk_ids), ensure_ascii=False),
            "cluster_label": label,
            "vector": list(vector),
        }
        for entry, vector, label in zip(entries, vectors, labels)
    ]

    import lancedb

    embeddings_dir.parent.mkdir(parents=True, exist_ok=True)
    db = lancedb.connect(embeddings_dir)
    db.create_table(TABLE_NAME, data=rows, mode="overwrite")

    embedding_dim = len(rows[0]["vector"])
    cluster_count = len({label for label in labels if label != NOISE_LABEL})
    noise_count = sum(1 for label in labels if label == NOISE_LABEL)

    manifest = {
        "model_name": model_name,
        "embedding_dim": embedding_dim,
        "entry_count": len(entries),
        "occurrence_count": len(occurrences),
        "cluster_count": cluster_count,
        "noise_count": noise_count,
        "table_name": TABLE_NAME,
        "inventory_path": str(inventory_path),
        "config": {
            "pca_components": pca_components,
            "min_cluster_size": min_cluster_size,
            "min_samples": min_samples,
        },
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    return NamesResult(
        inventory_path=inventory_path,
        embeddings_dir=embeddings_dir,
        manifest_path=manifest_path,
        entry_count=len(entries),
        occurrence_count=len(occurrences),
        model_name=model_name,
        embedding_dim=embedding_dim,
        cluster_count=cluster_count,
        noise_count=noise_count,
    )


# ---------------------------------------------------------------------------
# The report: read-only over persisted data, zero model/embedding calls
# (mirrors `axial.chunk.examine_chunks`/`format_examine_report`)
# ---------------------------------------------------------------------------

# How many entries the report samples per cluster for a human to read
# (mirrors `axial.chunk.EXAMINE_SAMPLE_SIZE`'s own convention).
EXAMINE_CLUSTER_SAMPLE = 5
EXAMINE_TOP_CLUSTERS = 10
# How many entries the nearest-neighbour similarity spread (and the
# borderline-pair search) is measured over -- exact pairwise cosine
# similarity is O(n^2) in memory, so this report samples rather than
# computing it over the whole inventory (the same sampling convention
# `axial.chunk.examine_chunks`'s own chunk-text sample uses; the persisted
# table itself is complete, and the sample is shared across every
# tightness candidate, computed once).
EXAMINE_SIMILARITY_SAMPLE = 500


@dataclass(frozen=True)
class TightnessStats:
    """One candidate tightness's own slice of the sweep (P0-12: "cluster
    counts and sizes at a few candidate tightnesses ... a sample of
    borderline pairs")."""

    min_cluster_size: int
    min_samples: int
    cluster_count: int
    noise_count: int
    noise_fraction: float
    cluster_sizes: list[int]  # non-noise cluster sizes, descending
    top_clusters: list[tuple[int, int, list[str]]]  # (label, size, sample surface forms)
    # (surface_a, surface_b, cosine similarity) pairs NOT placed in the same
    # cluster at this tightness, highest similarity first -- "where this
    # setting is actually deciding something" (founder ask): a high-
    # similarity pair split apart is exactly the near-miss a different
    # tightness might merge.
    borderline_pairs: list[tuple[str, str, float]]


@dataclass(frozen=True)
class NamesExamineStats:
    """What `axial names examine` reports (D10's viewing aid, P0-12): the
    inventory's own size, the overall nearest-neighbour similarity spread
    (independent of any one tightness), and the tightness sweep itself --
    one `TightnessStats` per candidate `min_cluster_size`, all re-clustered
    from the SAME persisted vectors and the SAME single HDBSCAN fit
    (`min_samples` held fixed; see `sweep_tightness`)."""

    entry_count: int
    occurrence_count: int
    similarity_min: float | None
    similarity_max: float | None
    similarity_mean: float | None
    similarity_median: float | None
    tightness: list[TightnessStats]


def _load_name_rows(embeddings_dir: Path) -> list[dict[str, Any]]:
    embeddings_dir = Path(embeddings_dir)
    if not embeddings_dir.exists():
        raise NoNamesToClusterError(embeddings_dir)

    import lancedb

    db = lancedb.connect(embeddings_dir)
    if TABLE_NAME not in db.list_tables().tables:
        raise NoNamesToClusterError(embeddings_dir)
    rows = db.open_table(TABLE_NAME).to_arrow().to_pylist()
    if not rows:
        raise NoNamesToClusterError(embeddings_dir)
    rows.sort(key=lambda row: row["surface_form"])
    return rows


def _nearest_neighbour_pairs(
    rows: list[dict[str, Any]], sample_size: int
) -> list[tuple[int, int, float]]:
    """For each of a sample of rows, its nearest OTHER row and their cosine
    similarity -- `(sample_index, nearest_index, similarity)`, computed once
    over the full persisted vector set (so a sampled row's "nearest" is
    still its true nearest neighbour, not just its nearest within the
    sample), and reused for both the overall similarity spread and every
    tightness candidate's borderline-pair search. Empty input / a single
    row yields `[]`."""
    if len(rows) < 2:
        return []

    import numpy as np

    vectors = np.asarray([row["vector"] for row in rows], dtype=np.float64)
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    normalised = vectors / norms

    sample_indices = list(range(min(sample_size, len(rows))))
    pairs = []
    for index in sample_indices:
        scores = normalised @ normalised[index]
        scores[index] = -1.0  # exclude self
        nearest = int(scores.argmax())
        pairs.append((index, nearest, float(scores[nearest])))
    return pairs


def _similarity_spread(
    pairs: list[tuple[int, int, float]],
) -> tuple[float | None, float | None, float | None, float | None]:
    if not pairs:
        return None, None, None, None
    ordered = sorted(similarity for _i, _j, similarity in pairs)
    mid = len(ordered) // 2
    median = ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2
    return ordered[0], ordered[-1], sum(ordered) / len(ordered), median


def _borderline_pairs(
    rows: list[dict[str, Any]],
    pairs: list[tuple[int, int, float]],
    labels: list[int],
    top_n: int,
) -> list[tuple[str, str, float]]:
    """The highest-similarity sampled pairs this tightness did NOT place in
    the same cluster (either member is noise, or the two carry different
    cluster labels) -- deduplicated by unordered pair, highest similarity
    first."""
    seen: set[frozenset[int]] = set()
    candidates = []
    for i, j, similarity in pairs:
        if labels[i] == NOISE_LABEL or labels[j] == NOISE_LABEL or labels[i] != labels[j]:
            key = frozenset((i, j))
            if key in seen:
                continue
            seen.add(key)
            candidates.append((rows[i]["surface_form"], rows[j]["surface_form"], similarity))
    candidates.sort(key=lambda item: item[2], reverse=True)
    return candidates[:top_n]


def _tightness_stats(
    rows: list[dict[str, Any]],
    pairs: list[tuple[int, int, float]],
    labels: list[int],
    min_cluster_size: int,
    min_samples: int,
    borderline_pairs: int,
) -> TightnessStats:
    cluster_members: dict[int, list[str]] = {}
    noise_count = 0
    for row, label in zip(rows, labels):
        if label == NOISE_LABEL:
            noise_count += 1
        else:
            cluster_members.setdefault(label, []).append(row["surface_form"])

    cluster_sizes = sorted((len(members) for members in cluster_members.values()), reverse=True)
    top_clusters = [
        (label, len(members), sorted(members)[:EXAMINE_CLUSTER_SAMPLE])
        for label, members in sorted(
            cluster_members.items(), key=lambda item: len(item[1]), reverse=True
        )[:EXAMINE_TOP_CLUSTERS]
    ]

    return TightnessStats(
        min_cluster_size=min_cluster_size,
        min_samples=min_samples,
        cluster_count=len(cluster_members),
        noise_count=noise_count,
        noise_fraction=noise_count / len(rows) if rows else 0.0,
        cluster_sizes=cluster_sizes,
        top_clusters=top_clusters,
        borderline_pairs=_borderline_pairs(rows, pairs, labels, borderline_pairs),
    )


def examine_names(
    embeddings_dir: Path = DEFAULT_EMBEDDINGS_DIR,
    min_cluster_sizes: Iterable[int] = DEFAULT_TIGHTNESS_MIN_CLUSTER_SIZES,
    min_samples: int = DEFAULT_MIN_SAMPLES,
    pca_components: int = DEFAULT_PCA_COMPONENTS,
    similarity_sample: int = EXAMINE_SIMILARITY_SAMPLE,
    borderline_pairs: int = DEFAULT_BORDERLINE_PAIRS,
) -> NamesExamineStats:
    """Read the persisted similarity view back and RE-CLUSTER it (zero model/
    embedding calls -- the vectors are already on disk; this never re-embeds,
    the one cost the founder's own performance constraint forbids repeating)
    at every candidate `min_cluster_size` in `min_cluster_sizes`, holding
    `min_samples` fixed: cluster counts and size distribution at each
    tightness, plus a sample of borderline pairs, so merge aggressiveness is
    chosen by looking (D10, P0-12) rather than by editing this module.

    One HDBSCAN fit only, at the SMALLEST `min_cluster_size` -- the
    expensive step (measured ~600s at this corpus's real 78k-entry scale,
    independent of `min_cluster_size`). Every other candidate re-derives
    labels from that one fit's tree (`_relabel_from_tree`), which is
    near-instant. Sweeping `min_samples` instead requires a fresh fit per
    value -- call this again with a different `min_samples` rather than
    passing a list; `min_cluster_sizes` is the cheap axis to sweep by
    default (see `DEFAULT_TIGHTNESS_MIN_CLUSTER_SIZES`)."""
    rows = _load_name_rows(embeddings_dir)
    vectors = [row["vector"] for row in rows]

    pairs = _nearest_neighbour_pairs(rows, similarity_sample)
    similarity_min, similarity_max, similarity_mean, similarity_median = _similarity_spread(pairs)

    sizes_sorted = sorted(set(min_cluster_sizes))
    if not sizes_sorted:
        sizes_sorted = [DEFAULT_MIN_CLUSTER_SIZE]
    smallest = sizes_sorted[0]

    import hdbscan

    reduced = _reduce_vectors(vectors, pca_components)
    clusterer = hdbscan.HDBSCAN(
        min_cluster_size=smallest,
        min_samples=min_samples,
        cluster_selection_method="leaf",
        allow_single_cluster=True,
    )
    initial_labels = [int(label) for label in clusterer.fit_predict(reduced)]
    single_linkage_tree = clusterer.single_linkage_tree_.to_numpy()

    tightness = []
    for min_cluster_size in sizes_sorted:
        labels = (
            initial_labels
            if min_cluster_size == smallest
            else _relabel_from_tree(reduced, single_linkage_tree, min_cluster_size)
        )
        tightness.append(
            _tightness_stats(rows, pairs, labels, min_cluster_size, min_samples, borderline_pairs)
        )

    return NamesExamineStats(
        entry_count=len(rows),
        occurrence_count=sum(row["count"] for row in rows),
        similarity_min=similarity_min,
        similarity_max=similarity_max,
        similarity_mean=similarity_mean,
        similarity_median=similarity_median,
        tightness=tightness,
    )


def _format_tightness(stats: TightnessStats) -> list[str]:
    lines: list[str] = [
        f"--- min_cluster_size={stats.min_cluster_size} min_samples={stats.min_samples} ---",
        f"clusters: {stats.cluster_count} non-noise cluster(s), "
        f"{stats.noise_count} noise (unclustered) entries "
        f"({stats.noise_fraction:.1%} of the inventory)",
    ]

    if stats.cluster_sizes:
        n = len(stats.cluster_sizes)
        mean_size = sum(stats.cluster_sizes) / n
        median_size = (
            stats.cluster_sizes[n // 2]
            if n % 2
            else (stats.cluster_sizes[n // 2 - 1] + stats.cluster_sizes[n // 2]) / 2
        )
        lines.append(
            "cluster size distribution: "
            f"min={stats.cluster_sizes[-1]} max={stats.cluster_sizes[0]} "
            f"mean={mean_size:.1f} median={median_size:.1f}"
        )
    else:
        lines.append("cluster size distribution: (no non-noise clusters)")

    lines.append("largest clusters:")
    if not stats.top_clusters:
        lines.append("  (none)")
    for label, size, sample in stats.top_clusters:
        lines.append(f"  cluster {label} ({size} member(s)): {sample}")

    lines.append("borderline pairs (high similarity, split apart at this tightness):")
    if not stats.borderline_pairs:
        lines.append("  (none)")
    for surface_a, surface_b, similarity in stats.borderline_pairs:
        lines.append(f"  {similarity:.3f}  {surface_a!r} <-> {surface_b!r}")

    return lines


def format_names_report(stats: NamesExamineStats) -> str:
    """Render `NamesExamineStats` into a human-readable report -- format
    left to the implementer (mirrors `axial.chunk.format_examine_report`'s
    own docstring), only that every listed number is present. The tightness
    sweep table (`stats.tightness`, one section per candidate
    `min_cluster_size`) is the deliverable this report exists for (P0-12):
    the founder picks slice 05's merge aggressiveness by comparing sections,
    not by reading one setting's numbers in isolation."""
    lines: list[str] = []

    lines.append(
        f"names examine: {stats.entry_count} distinct surface form(s), "
        f"{stats.occurrence_count} total occurrence(s)"
    )

    lines.append("")
    if stats.similarity_mean is not None:
        lines.append(
            "nearest-neighbour cosine similarity spread (sampled, all entries): "
            f"min={stats.similarity_min:.3f} max={stats.similarity_max:.3f} "
            f"mean={stats.similarity_mean:.3f} median={stats.similarity_median:.3f}"
        )
    else:
        lines.append("nearest-neighbour cosine similarity spread: (fewer than 2 entries)")

    lines.append("")
    lines.append(f"tightness sweep ({len(stats.tightness)} candidate(s)):")
    for tightness_stats in stats.tightness:
        lines.append("")
        lines.extend(_format_tightness(tightness_stats))

    return "\n".join(lines)
