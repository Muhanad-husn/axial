"""Stage-4 synthesis pass (specs/PHASE-B.md §7.4, §7.11, §8 P0-4, issue
#256): takes the evidence set slice 01's `assemble_evidence`
(`axial.analyze.assembly`) built, applies a named lens from
`config/lenses/` (selecting and recording one when the brief omits `lens`,
§7.1), and performs axial coding across the evidence in one bounded model
call to emit the §7.4 claim graph.

Grounded by construction: the prompt (`compose_prompt`) forbids asserting
from parametric memory or the open web, instructs the model to reason only
over the supplied evidence, and states that a cross-source inference is
marked (b) and never voiced as a source assertion -- the same "assert this
as a prompt-content property" pattern the #228 anti-anecdote test already
uses for the envelope pass. `parse_synthesis_response` is the deterministic
half: every claim's `kind` is validated against `{a, b, c}`, every (a)/(b)
claim's `grounds` must be non-empty, and every grounds entry must resolve to
a real vault id. A `chunk` grounds ref_id resolves ONLY by exact lookup in
the `handle_map` `compose_prompt` handed out alongside the same call's
prompt (issue #410, `SynthesisPrompt`): the model is shown a short opaque
handle (`[c3]`) per evidence chunk, never the real `<author>-<year>-
<digest>_<n>_<slug>_<nnn>` id, so it has nothing long to transcribe,
truncate, or blend across two similar sources -- a real benchmark run twice
blended two similar Syria books' ~200-char ids this way, correctly raising
`UnresolvableGroundError` both times (the issue's own analysis: a
component-matching repair of a blended id was scoped and deliberately
abandoned, because it would silently manufacture a claim whose prose credits
one scholar and whose evidence is another's -- `source_id` is never fuzzed).
An `artifact` grounds ref_id is unaffected by the handle scheme (artifacts
are never listed under a handle -- see `compose_prompt`'s own docstring) and
still resolves via `axial.query.reader.get_artifact`, exact match first,
falling back to a unique-suffix then unique-prefix repair of a truncated
citation via `_resolve_truncated_ref_id` (DEC-42 grew ids to ~200 chars and
the model drops either end). Every claim's `confidence` is validated
against the closed §7.4 three-band vocabulary `CONFIDENCE_BANDS` (issue
#402 -- a real run emitted "medium-high", a band the calibration gate
correctly refused to score; caught here instead, at generation), and
`names_touched` is computed here -- never trusted from the model -- as the
union of the canonical names the claim's grounds CHUNKS are members of
(§7.4, issue #489): each note's own `names` answers are surface forms,
resolved through the alias map alone
(`axial.query.names.canonical_name_for_surface`), and a surface the index
does not carry is DROPPED rather than invented. Never through `find_names`'
embedding tier -- a nearest-neighbour match here would fabricate coverage of
a name the passage never named. An artifact ground names nothing of its own,
so it contributes nothing. `claim_id` is a deterministic hash over each
claim's own parsed content, so the same response parses to the same ids on
every run.

**The prompt is built on the interrogation's answers** (Phase B v1 slice 04,
issue #489). It used to list five closed-vocabulary tag axes per chunk, all
of which Phase A v1 deleted, so every one of them rendered empty. It now
lists each note's own answers (`axial.analyze.assembly.EvidenceChunk.
answers`) -- claim, move, whose position and what it is, who it argues
against, mechanism, evidence, comparison, what it defines/uses, concedes,
assumes, the names it names and who it cites with what stance -- alongside
the real prose. An abstained field never appears at all: assembly filtered
it out (`axial.query.reader.is_abstention`), which is what keeps "the
passage does not support an answer" from reaching the model as an answer.

Out of scope for this slice (see plans/analysis-synthesis/02-synthesis-claim-
graph.md): the attribution validator, the grounding check, the coverage map,
and persisting the claim graph.

`generate_counter_position` (issue #399, §7.8) is the counter-position
GENERATION half this module gained after that slice: a follow-up call, made
only when `axial.validators.counter_position.detect_contested` (reused
verbatim, never reimplemented) reports the just-produced claim graph's own
evidence as contested. It never asks the model to invent an opposing
position from nothing: the candidate pool it offers is a whitelist of real
vault notes already in hand (`_counter_position_candidates`, issue #490) --
this run's own grounds notes whose stated position differs from the majority
among that evidence, the notes `who_argues_against` returns for a name the
run touched, and the member notes of a Gather finding at such a name -- never
a fresh retrieval. A `present: true`
response may only cite grounds from that whitelist (checked mechanically
after resolution, `CounterPositionGroundNotOfferedError` otherwise); the
model is told plainly that disclosing the corpus as one-sided is the
correct, honest answer whenever the candidates do not cash out to a real
opposing stance, never a failure -- the deliberately easier path, so a model
under pressure to "find" a counter-position has nothing to gain by
fabricating one. An uncontested brief (including a `refuse` disposition,
whose empty claim list is trivially uncontested) never reaches the model
call at all.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import httpx
import yaml

from axial.analyze.assembly import EvidenceSet, name_surfaces
from axial.brief.intake import Brief
from axial.llm import COUNTER_POSITION_GENERATE_PASS_NAME, SYNTHESIZE_PASS_NAME, LLMClient, LLMError
from axial.model_json import ModelJsonError, complete_json, parse_model_json
from axial.paths import DEFAULT_PIPELINE_CONFIG_PATH
from axial.query.names import NameNotFoundError, canonical_name_for_surface, get_name
from axial.query.names import who_argues_against as who_argues_against_name
from axial.query.reader import (
    ArtifactNotFoundError,
    ChunkNotFoundError,
    ChunkNote,
    find_artifact_ids_ending_with,
    find_artifact_ids_starting_with,
    find_chunk_ids_ending_with,
    find_chunk_ids_starting_with,
    get_artifact,
    get_chunk,
)
from axial.validators.counter_position import (
    SIGNAL_GATHER_DISAGREEMENT,
    SIGNAL_NAMES_OPPONENT,
    SIGNAL_OPPOSED_POSITIONS,
    _opposition_surfaces,
    detect_contested,
    notes_naming_an_opponent,
    opposed_grounds_notes,
    resolve_grounds_notes,
    stated_position,
)
from axial.validators.coverage import coverage_scope
from axial.yaml_loader import SAFE_LOADER

# The §7.4 claim-kind vocabulary -- closed, not open text: a value outside
# this set is a named parse error, never silently accepted or coerced.
CLAIM_KINDS = frozenset({"a", "b", "c"})

# The §7.4 confidence-band vocabulary -- exactly three discrete bands, never
# a numeric score and never a fourth invented one (issue #402: a real run
# emitted "medium-high", which the calibration gate correctly refused to
# score/impute -- `axial.gates.calibration.InvalidConfidenceBandError` -- but
# that only caught it at scoring time, after the record was already
# persisted. Caught here instead, at generation, same shape as
# `CLAIM_KINDS` above. Mirrors (does not import) `axial.gates.calibration.
# CONFIDENCE_BANDS` -- generation stays independent of the evaluation layer.
CONFIDENCE_BANDS = frozenset({"high", "medium", "low"})

# Kinds whose `grounds` must be non-empty (§7.4: "required non-empty for
# every (a) and (b) claim"). A (c) claim may carry partial or empty grounds.
_GROUNDED_KINDS = frozenset({"a", "b"})

# The §7.5 ref_type vocabulary a grounds entry may point at.
_REF_TYPES = frozenset({"chunk", "artifact"})

# Fixed data directory for the lens vocabulary (§7.1: "config/lenses/, ...
# no country-specific logic in src/"). Not a runtime-configurable path --
# mirrors `axial.tag.DEFAULT_DOMAIN_DIR`'s own fixed-location convention for
# swappable domain data.
DEFAULT_LENSES_DIR = Path("config/lenses")

# `claim_id` truncation length -- long enough to be effectively
# collision-free within one brief run's claim count, short enough to stay
# readable (mirrors `axial.brief.intake._BRIEF_ID_LENGTH`).
_CLAIM_ID_LENGTH = 16

# Total evidence-text budget fed into the synthesis prompt (issue #358): the
# retrieval loop's `step_budget` (config/pipeline.yaml `retrieve.step_budget`)
# bounds the number of TOOL CALLS one retrieval run makes, not the number of
# chunks a single call can return (`query_by_source`/`query_by_tag` are
# unbounded) -- a real brief run assembled enough chunk text that the
# synthesis prompt, combined with the fixed `max_tokens=60000` completion
# budget sent on every call (`axial.llm._MAX_COMPLETION_TOKENS`), pushed past
# the model's context window and OpenRouter rejected the request outright.
# Character-based, not a real tokenizer (this repo's "measure, don't
# speculate" philosophy, and no per-model context-window lookup table):
# ~4 chars/token is a standard rough estimate for English prose, so 100_000
# chars is roughly 25k tokens of evidence text -- conservative headroom
# under a 128k-class context window even after the 60k-token completion
# reservation and the prompt's own small fixed overhead (case/request/
# instructions). [TENTATIVE], mirroring `retrieve.step_budget`/
# `retrieve.thin_result_floor`'s own starting-value status: not yet measured
# against a real brief run, tuning it is a later, separate pass.
DEFAULT_EVIDENCE_CHAR_BUDGET = 100_000


def _resolve_evidence_char_budget(config_path: Path | None = None) -> int:
    """Read `synthesis.evidence_char_budget` from `config_path` (mirrors
    `axial.retrieve.loop._resolve_step_budget`'s own config-read shape),
    falling back to `DEFAULT_EVIDENCE_CHAR_BUDGET` when the file, the
    `synthesis` block, or the key itself is absent."""
    if config_path is None:
        config_path = DEFAULT_PIPELINE_CONFIG_PATH
    if not config_path.is_file():
        return DEFAULT_EVIDENCE_CHAR_BUDGET
    with config_path.open("r", encoding="utf-8") as handle:
        document = yaml.load(handle, Loader=SAFE_LOADER) or {}
    synthesis_config = document.get("synthesis") or {}
    return int(synthesis_config.get("evidence_char_budget", DEFAULT_EVIDENCE_CHAR_BUDGET))


class SynthesisError(Exception):
    """Base class for all stage-4 synthesis errors."""


class SynthesisFailedError(SynthesisError):
    """Raised when the underlying model call transport-fails or never
    returns parseable JSON within `complete_json`'s bounded re-ask budget."""


class SynthesisParseError(SynthesisError):
    """Raised when a well-formed-JSON model response does not match the
    §7.4 claim-graph shape."""


class InvalidClaimKindError(SynthesisParseError):
    """Raised when a claim's `kind` is absent, empty, or outside
    `CLAIM_KINDS` -- names the offending claim (by index and, when present,
    its text) so the failure is diagnosable without a raw JSON dump."""

    def __init__(self, index: int, text: Any, kind: Any):
        self.index = index
        self.text = text
        self.kind = kind
        super().__init__(
            f"claim #{index} ({text!r}) has kind {kind!r}, expected one of {sorted(CLAIM_KINDS)!r}"
        )


class InvalidClaimConfidenceError(SynthesisParseError):
    """Raised when a claim's `confidence` is absent or outside the §7.4
    three-band vocabulary `CONFIDENCE_BANDS` -- names the offending claim so
    a fourth invented band (e.g. "medium-high") is caught at generation,
    never silently accepted or coerced into a real band."""

    def __init__(self, index: int, text: Any, confidence: Any):
        self.index = index
        self.text = text
        self.confidence = confidence
        super().__init__(
            f"claim #{index} ({text!r}) has confidence {confidence!r}, expected "
            f"one of {sorted(CONFIDENCE_BANDS)!r}"
        )


class UngroundedClaimError(SynthesisParseError):
    """Raised when an (a) or (b) claim carries absent or empty `grounds`
    (§7.4: required non-empty for both kinds) -- names the offending claim."""

    def __init__(self, index: int, text: Any, kind: str):
        self.index = index
        self.text = text
        self.kind = kind
        super().__init__(
            f"claim #{index} ({text!r}) has kind {kind!r} but empty/absent "
            "grounds -- (a)/(b) claims must carry at least one grounds entry"
        )


class InvalidGroundRefTypeError(SynthesisParseError):
    """Raised when a grounds entry's `ref_type` is outside `{chunk,
    artifact}` -- names the offending claim and the bad ref_type."""

    def __init__(self, index: int, text: Any, ref_type: Any):
        self.index = index
        self.text = text
        self.ref_type = ref_type
        super().__init__(
            f"claim #{index} ({text!r}) has a grounds entry with ref_type "
            f"{ref_type!r}, expected one of {sorted(_REF_TYPES)!r}"
        )


class UnresolvableGroundError(SynthesisParseError):
    """Raised when a grounds entry's `ref_id` does not resolve to a real
    vault id -- a hallucinated citation never reaches the claim graph.
    Names the offending claim and the unresolved id."""

    def __init__(self, index: int, text: Any, ref_type: str, ref_id: str):
        self.index = index
        self.text = text
        self.ref_type = ref_type
        self.ref_id = ref_id
        super().__init__(
            f"claim #{index} ({text!r}) cites {ref_type} {ref_id!r}, which "
            "does not resolve to a real vault id"
        )


class UnknownLensError(SynthesisError):
    """Raised when a brief names a `lens` that does not exist under
    `config/lenses/` -- names the offending lens."""

    def __init__(self, lens_name: str, lenses_dir: Path):
        self.lens_name = lens_name
        self.lenses_dir = lenses_dir
        super().__init__(f"unknown lens {lens_name!r}: no file found under {lenses_dir}")


class NoLensesAvailableError(SynthesisError):
    """Raised when a brief omits `lens` and `config/lenses/` holds no lens
    to auto-select -- a misconfigured install, never silently swallowed."""

    def __init__(self, lenses_dir: Path):
        self.lenses_dir = lenses_dir
        super().__init__(f"no lens available to auto-select under {lenses_dir}")


class CounterPositionGenerationError(SynthesisError):
    """Base class for all counter-position GENERATION errors (§7.8, issue
    #399) -- a separate family from the claim-graph parse errors above.

    Raised out of `generate_counter_position` completely unchanged (every
    existing unit test that asserts one of these propagating still passes):
    this class is not where the resilience below lives. It is `axial.answer.
    record.build_record` that decides not to let it abort the whole run
    (issue #557/#558): by the time this stage runs, interrogation, retrieval
    and synthesis have already completed and cost real money, and a real
    paid eval run was once destroyed in full because this stage's own raise
    discarded all of it. `build_record` catches this family and persists the
    record anyway, with the §7.8 section marked `failed: True` and
    `failure_reason` carrying this exception's own message
    (`failed_counter_position_section`) -- a third, distinguishable state,
    never laundered into `corpus_one_sided` (that would misattribute a bug
    to a finding about the corpus) and never satisfying the §7.9
    presence-or-disclosure check."""


class CounterPositionGenerationFailedError(CounterPositionGenerationError):
    """Raised when the counter-position-generation model call transport-fails
    or never returns parseable JSON within `complete_json`'s bounded re-ask
    budget."""


class InvalidCounterPositionResponseError(CounterPositionGenerationError):
    """Raised when a well-formed-JSON counter-position response does not
    match the §7.8 shape -- including naming both, or neither, of the two
    mutually exclusive present/one-sided channels."""


class UnresolvableCounterPositionGroundError(CounterPositionGenerationError):
    """Raised when a `present: true` response's grounds `ref_id` does not
    resolve to a real vault id at all (exact match nor unique-suffix
    repair) -- a hallucinated citation never reaches the record, exactly
    like `UnresolvableGroundError` does for a claim."""

    def __init__(self, ref_id: str):
        self.ref_id = ref_id
        super().__init__(
            f"counter-position cites chunk {ref_id!r}, which does not resolve to a real vault id"
        )


class CounterPositionGroundNotOfferedError(CounterPositionGenerationError):
    """Raised when a `present: true` response's grounds resolve to a REAL
    vault id that was never among the whitelisted candidate opposing-evidence
    chunks offered in the prompt (module docstring's anti-fabrication
    design): the model may only ground the counter-position in the
    candidates it was given, so a well-formed but off-list citation is
    rejected exactly as firmly as a wholly unresolvable one -- resolving is
    necessary but not sufficient."""

    def __init__(self, ref_id: str):
        self.ref_id = ref_id
        super().__init__(
            f"counter-position cites chunk {ref_id!r}, which resolves to a real "
            "vault id but was never among the opposing-evidence chunks offered "
            "-- the model may only ground the counter-position in the candidates "
            "it was given, never reach outside that whitelist"
        )


@dataclass(frozen=True)
class SynthesisPrompt:
    """`compose_prompt`'s return (issue #410): the composed prompt `text`
    plus the `handle_map` assigned alongside it -- `{"[c1]": "<real chunk
    id>", ...}` for every evidence chunk that made it into the prompt (same
    order, same budget cutoff `compose_prompt` already applies). The model
    is shown only the short bracketed handle, never the real
    `<author>-<year>-<digest>_<n>_<slug>_<nnn>` id, so it has nothing long
    to transcribe and nothing to blend across two similar sources -- the
    opaque-handle mitigation the module docstring's `parse_synthesis_response`
    section still needs `handle_map` to resolve a cited handle back to the
    real id it stands for. Held in memory only for the one call it was
    built for: never persisted, never reused across a later prompt, so a
    stale handle from an earlier call can never resolve against this one's
    grounds."""

    text: str
    handle_map: dict[str, str]


@dataclass(frozen=True)
class Ground:
    """One `{ref_type, ref_id}` grounds pointer (§7.4): `ref_type` is
    `chunk` or `artifact`, `ref_id` is a real vault id that has already been
    resolved against the vault by the time a `Ground` exists -- a
    `Ground` is never constructed for an id that failed to resolve."""

    ref_type: str
    ref_id: str


@dataclass(frozen=True)
class Claim:
    """One §7.4 claim: `{claim_id, text, kind, grounds, confidence,
    names_touched}`. `confidence` is validated against `CONFIDENCE_BANDS`
    (issue #402) before a `Claim` is ever constructed -- never a value
    outside the three-band vocabulary. `names_touched` is the union of the
    canonical names this claim's grounds notes are members of, computed in
    code (see the module docstring), which is what makes the §7.7 coverage
    map computable from the claim graph."""

    claim_id: str
    text: str
    kind: str
    grounds: list[Ground]
    confidence: Any
    names_touched: list[str]


@dataclass(frozen=True)
class ClaimGraph:
    """The full stage-4 output: the lens actually applied (always recorded,
    §7.1) plus the parsed, validated, grounded claim list.

    `evidence_composed_count` (issue #545) is `len(composed.handle_map)` --
    how many of the evidence chunks `compose_prompt` assembled actually made
    it past `synthesis.evidence_char_budget`'s prefix walk and into the
    prompt the model read. Carried here, alongside `claims`, because it is
    the one number `compose_prompt` computes and then discards: the walk
    breaks silently (see that function's own docstring), and this is what
    lets a caller (`axial.answer.record.build_record`) disclose the drop
    against the assembled count it already has (`EvidenceSet.chunk_ids`)."""

    lens: str
    claims: list[Claim]
    evidence_composed_count: int


def _available_lenses(lenses_dir: Path) -> list[str]:
    """Every lens name available under `lenses_dir` (its `.yaml` files'
    stems), sorted -- the deterministic ordering `resolve_lens` picks its
    auto-selected default from."""
    if not lenses_dir.is_dir():
        return []
    return sorted(path.stem for path in lenses_dir.glob("*.yaml"))


def resolve_lens(lens_name: str | None, *, lenses_dir: Path | None = None) -> str:
    """Resolve the lens this run applies (§7.1): a named `lens_name` must
    exist under `lenses_dir` (raises `UnknownLensError`, naming it,
    otherwise); an absent `lens_name` (the brief omitted `lens`) selects the
    alphabetically-first available lens -- simple and deterministic, so the
    same corpus of lenses always auto-selects the same one, and the choice
    is always recorded on the result rather than left null. Raises
    `NoLensesAvailableError` if no lens exists to select at all."""
    if lenses_dir is None:
        lenses_dir = DEFAULT_LENSES_DIR
    available = _available_lenses(lenses_dir)

    if lens_name is not None:
        if lens_name not in available:
            raise UnknownLensError(lens_name, lenses_dir)
        return lens_name

    if not available:
        raise NoLensesAvailableError(lenses_dir)
    return available[0]


# How each §7.15 answer field is labelled in the prompt (issue #489). Display
# copy, so the model reads a question rather than a schema key: the field names
# themselves are terse and two of them (`position_of` = whose position,
# `position` = what that position is) are only distinguishable by their
# wording. Order comes from `assembly.EVIDENCE_ANSWER_FIELDS`, not from here.
_ANSWER_LABELS = {
    "claim": "claim",
    "move": "move in the argument",
    "position_of": "whose position",
    "position": "the position",
    "arguing_against": "arguing against",
    "about": "about",
    "ranges_over": "ranges over",
    "stops_holding": "stops holding",
    "mechanism": "mechanism",
    "evidence": "evidence offered",
    "comparison": "comparison",
    "defines": "defines",
    "uses": "uses",
    "concedes": "concedes or hedges",
    "assumes": "assumes",
    "names": "names",
    "citations": "cites",
}


def _render_name(entry: Any) -> str:
    """One `names` answer entry (§7.15: `{name, kind}`) as `Name (kind)`. A
    bare string is accepted as its own name, the same tolerance
    `axial.query.names._read_note_answers` applies to a free-text answer."""
    if isinstance(entry, dict) and isinstance(entry.get("name"), str):
        kind = entry.get("kind")
        return (
            f"{entry['name']} ({kind})" if isinstance(kind, str) and kind.strip() else entry["name"]
        )
    return str(entry)


def _render_citation(entry: Any) -> str:
    """One `citations` answer entry (§7.15: `{cited, stance, about}`) as
    `Cited [stance] -- about`, so the author's own support / foil / authority
    stance travels with the reference instead of being flattened away."""
    if not isinstance(entry, dict) or not isinstance(entry.get("cited"), str):
        return str(entry)
    rendered = entry["cited"]
    stance = entry.get("stance")
    if isinstance(stance, str) and stance.strip():
        rendered += f" [{stance}]"
    about = entry.get("about")
    if isinstance(about, str) and about.strip():
        rendered += f" -- {about}"
    return rendered


def _render_answer_value(field_name: str, value: Any) -> str:
    if isinstance(value, list):
        if not value:
            # `[]` is an ANSWER (§7.15): the passage names none of that kind
            # of thing. Said in words, because an empty bracket pair reads to
            # a model as a missing field rather than as a read.
            return "(the passage names none)"
        if field_name == "names":
            return "; ".join(_render_name(entry) for entry in value)
        if field_name == "citations":
            return "; ".join(_render_citation(entry) for entry in value)
        return "; ".join(str(entry) for entry in value)
    return str(value)


def _render_evidence_chunk(handle: str, chunk: Any, chunk_text: str) -> str:
    """One evidence chunk as the model sees it: its opaque handle, its
    source's own author/year/title, every substantive interrogation answer it
    carries, then its verbatim prose. The real `chunk_id` appears nowhere
    (issue #410)."""
    meta = chunk.source_meta or {}
    header = f"- chunk={handle}"
    for key in ("author", "date", "title"):
        value = meta.get(key)
        if value not in (None, ""):
            header += f" {key}={value}"
    lines = [header]
    for field_name, value in chunk.answers.items():
        label = _ANSWER_LABELS.get(field_name, field_name)
        lines.append(f"  {label}: {_render_answer_value(field_name, value)}")
    lines.append(f"  text: {chunk_text}")
    return "\n".join(lines)


def compose_prompt(
    brief: Brief,
    lens_name: str,
    evidence: EvidenceSet,
    *,
    vault_dir: Path | None = None,
    config_path: Path | None = None,
    evidence_char_budget: int | None = None,
) -> SynthesisPrompt:
    """Assemble the synthesis prompt (§7.4/P0-4): the brief's case/request,
    the applied lens, and every evidence chunk's real prose TEXT plus the
    interrogation's own answers about it (issue #489 --
    `axial.analyze.assembly` already dropped every abstained field, so a
    question the passage did not support never reaches the model as an
    answer). `EvidenceSet.chunks` (`EvidenceChunk`) deliberately does not
    carry `chunk_text`, so the prompt re-fetches each evidence chunk's full
    text via `axial.query.reader.get_chunk`: the model reasons over real
    prose, and grounds pointers are drawn from what was actually supplied
    rather than invented. Every phrase this module's acceptance test checks
    against the recorded prompt lives verbatim in this template, so a prompt
    wording change is a deliberate, visible diff, not silent drift.

    D4 is stated in the prompt, not just in the code: a Gather-pass
    disagreement is another pass's reading of the corpus and is never
    citable. The 575 findings have never been scored (DEC-55), so a claim
    resting on one would launder unscored prose into an attributed answer.
    `ref_type` stays `chunk` or `artifact`; it gains no third value.

    Issue #410 (opaque-handle mitigation): the model is never shown a real
    `chunk_id` at all. Each included chunk is offered under a short, per-call
    handle (`[c1]`, `[c2]`, ...), assigned in the same walk that composes the
    evidence list, and returned alongside the prompt text as `SynthesisPrompt.
    handle_map` (`{"[c1]": "<real chunk_id>", ...}`). A real synthesis run
    logged 157k-195k prompt chars, and under that load the model twice blended
    two similar sources' ~200-char ids into one that pointed at the wrong
    scholar's work (`UnresolvableGroundError`, correctly, both times -- see
    the issue). A short opaque handle removes the whole failure class rather
    than repairing a blended id after the fact: there is no long id in the
    prompt to transcribe, truncate, or blend in the first place.
    `parse_synthesis_response` resolves a cited handle back to the real id by
    exact lookup in `handle_map` alone -- no fuzzy match, no suffix repair,
    nothing left to fuzz (`source_id` is never fuzzed, unchanged).

    `evidence_char_budget` (issue #358, default `_resolve_evidence_char_budget`
    off `config_path`/`DEFAULT_EVIDENCE_CHAR_BUDGET`) bounds the combined
    length of every included chunk's `chunk_text`: chunks are walked in
    `evidence.chunk_ids`' existing order -- which is SOURCE ROUND-ROBIN, not
    first-seen retrieval order, since issue #517 slice 2 reordered it in
    `axial.retrieve.loop.assemble_evidence_ids` -- and the included evidence
    set is a deterministic PREFIX of that order. The walk stops (never
    mid-text truncating a chunk) at the first chunk that would push the
    running total over budget, so every later chunk is dropped too. The
    round-robin is why a late-arriving id from an under-represented source
    can displace one already inside the prefix: it lands at the FRONT of its
    own source's rotation slot, not at the tail of the walk (measured on
    seven persisted brief runs, issue #542).
    A dropped chunk gets no handle and never appears in the evidence list, so
    the model has nothing to cite it with (grounds validation already rejects
    a handle absent from `handle_map`)."""
    if evidence_char_budget is None:
        evidence_char_budget = _resolve_evidence_char_budget(config_path)

    lines: list[str] = []
    handle_map: dict[str, str] = {}
    running_total = 0
    for chunk_id, chunk in zip(evidence.chunk_ids, evidence.chunks):
        note = get_chunk(chunk_id, vault_dir=vault_dir)
        if running_total + len(note.chunk_text) > evidence_char_budget:
            # The budget is exhausted: stop here rather than skipping ahead
            # to a later, smaller chunk -- the included evidence set is
            # always a deterministic PREFIX of the retrieval order, simple
            # to reason about and to reproduce.
            break
        running_total += len(note.chunk_text)
        handle = f"[c{len(handle_map) + 1}]"
        handle_map[handle] = chunk_id
        lines.append(_render_evidence_chunk(handle, chunk, note.chunk_text))
    evidence_lines = "\n".join(lines) or "(no evidence chunks were retrieved for this brief)"

    text = f"""You are the stage-4 synthesis pass of an analysis engine (specs/PHASE-B.md §7.4). Apply the lens named below and perform axial coding across ONLY the evidence chunks supplied below -- reason only over the grounds supplied here, never from your own parametric memory or the open web. Any assertion not traceable to a supplied grounds pointer is not a claim this pass may emit.

Case: "{brief.case}"
Request: "{brief.request}"
Lens: "{lens_name}"

Each evidence chunk below carries its source's author and title, then what a first reading of that passage answered about it -- what it claims, what it is doing in the argument, whose position it is and what that position is, who it argues against, who it cites and whether as support, foil or authority, and the rest -- and finally its verbatim prose. Those answers are another reading of the same passage, not a second source: where an answer and the prose differ, the prose is what the passage says. A question that passage did not support an answer for is ABSENT from its list; read nothing into the absence, and never treat it as a "no".

Evidence chunks -- cite ONLY the bracketed handle shown for each (e.g. "[cN]") as your grounds ref_id for a chunk, or an artifact_id as your grounds ref_id for an artifact. Reproduce a handle EXACTLY as shown; never invent one and never write out any other id:
{evidence_lines}

Retrieval may have reached this evidence by following a disagreement another pass of this system wrote about a name. Such a finding is that pass's own reading of the corpus, never a source and never scored: it is not quotable, not citable, and no claim may rest on one. Your grounds are the chunk handles and artifact_ids listed above, and nothing else.

For every claim you emit, mark its kind:
- "a" (source-says) -- a single source directly asserts this; grounds must name that source's chunk(s)/artifact(s).
- "b" (tool-infers-across-sources) -- YOUR inference drawn across two or more sources; grounds must name every source it draws on. A (b) claim is always marked as the tool's own inference and must NEVER be voiced as though a single source asserted it -- a cross-source inference is marked (b), never phrased as a source assertion.
- "c" (speculation) -- neither of the above; may carry partial or empty grounds.

Every (a) and (b) claim MUST carry at least one grounds pointer to a chunk handle or artifact_id listed above -- an unlisted or invented one is never acceptable.

Mark every claim's confidence as exactly one of "high", "medium", or "low" -- never a numeric score and never any other value (e.g. "medium-high" is not a valid band).

Return ONLY this JSON object, no prose and no code fence:
{{"claims": [{{"text": "<claim text>", "kind": "a|b|c", "grounds": [{{"ref_type": "chunk|artifact", "ref_id": "<handle for a chunk, e.g. [cN]; a real artifact_id for an artifact>"}}], "confidence": "high|medium|low"}}]}}"""

    return SynthesisPrompt(text=text, handle_map=handle_map)


def _dedupe_preserving_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered


# Matches a `ref_id`'s own trailing per-chunk index component (e.g. the
# `_002` in `..._59_002`) -- the second anchor `_resolve_head_and_index`
# needs, once neither existing repair has already resolved a truncated id on
# its own.
_TRAILING_INDEX_RE = re.compile(r"_(\d+)$")


def _resolve_head_and_index(
    ref_id: str, *, prefix_finder: Callable[[str], list[str]]
) -> str | None:
    """The third truncation repair, shared by `_resolve_truncated_ref_id`
    (artifact grounds) and `_resolve_counter_position_ground` (counter-
    position chunk grounds): tried only after each caller's own suffix and
    prefix repairs have both already failed to find a unique match.

    A real paid eval run died citing `<digest>_59_002`: the model kept the
    id's head (source digest, order key) AND its trailing per-chunk index,
    but elided the slug between them. Neither existing repair catches this
    shape -- the suffix repair's tail anchor (`..._59_002`) matches nothing,
    because no real id ends with the index alone (the slug always sits
    between the order key and it); the prefix repair's head anchor
    (`<digest>_59_002_`) matches nothing either, because `002` is not a
    component of any real id's head. The two real anchors the model DID keep
    -- the head and the index -- together identify the chunk uniquely; this
    repair is what uses both at once.

    Splits `ref_id` at its LAST `_<digits>` component into that head and
    that index, then requires a real id that starts with the component-
    bounded head prefix (`f"{head}_"`, same boundary rule the prefix repair
    already uses, so a head naming section 59 can never reach section 590)
    AND ends with the index suffix (`f"_{index}"`). This is not a loosening
    of the anti-confabulation argument the two existing repairs rest on:
    each anchor alone is exactly as restrictive as it already is on its own
    repair above, and this only accepts an id that satisfies BOTH
    simultaneously -- a wider match on either anchor alone is never enough.
    Returns `None`, never raises, when `ref_id` carries no trailing
    `_<digits>` component to split on, or when 0 or 2+ real ids satisfy both
    anchors at once: the caller keeps raising its own hard error exactly as
    it did before this repair existed, so ambiguity or absence stays exactly
    as firm a failure as an exact-match miss always was."""
    match = _TRAILING_INDEX_RE.search(ref_id)
    if match is None or not ref_id[: match.start()]:
        return None
    head = ref_id[: match.start()]
    trailing_index = match.group(1)
    candidates = prefix_finder(f"{head}_")
    matches = [candidate for candidate in candidates if candidate.endswith(f"_{trailing_index}")]
    return matches[0] if len(matches) == 1 else None


def _resolve_truncated_ref_id(
    index: int, text: Any, ref_type: str, ref_id: str, *, vault_dir: Path | None
) -> str:
    """Fallback for a grounds `ref_id` that failed an exact match: after the
    DEC-42 corpus rebuild, `chunk_id`/`artifact_id` values run to ~200
    characters (the raw download filename plus digest, order key, slug, and
    index), and the model sometimes echoes only part of one -- stochastic
    truncation, not a pipeline bug (a real benchmark run's succeeding claims
    cited the full id correctly).

    Three repairs, tried in that order: the SOLE real id ending with
    `ref_id` (the model dropped the long human-readable head), the SOLE real
    id starting with `f"{ref_id}_"` (issue #524: the model kept the head and
    dropped the slug and index), then `_resolve_head_and_index` (the model
    kept BOTH the head and the trailing index and dropped only the slug
    between them -- see that function's own docstring for the production
    failure that motivated it). None of the three is a loosening of
    anti-confabulation. A cited tail carries the source's 12-hex content
    digest plus the chunk's order key, slug and index, unique across the
    corpus in practice; a cited head carries the digest and order key, and
    the trailing separator makes the boundary a component boundary, so a head
    naming section 18 can never reach section 180; the third repair pins
    both of those same anchors to one real id at once, never loosening
    either on its own. A genuinely hallucinated id will not happen to match
    exactly one real id under any of the three. Zero or 2+ matches at every
    repair raise `UnresolvableGroundError` unchanged -- ambiguity or absence
    is still a hard error, never guessed at."""
    if ref_type == "chunk":
        suffix_finder, prefix_finder = find_chunk_ids_ending_with, find_chunk_ids_starting_with
    else:
        suffix_finder, prefix_finder = (
            find_artifact_ids_ending_with,
            find_artifact_ids_starting_with,
        )
    matches = suffix_finder(ref_id, vault_dir=vault_dir)
    kind = "suffix"
    if len(matches) != 1:
        matches = prefix_finder(f"{ref_id}_", vault_dir=vault_dir)
        kind = "prefix"
    if len(matches) != 1:
        head_index_match = _resolve_head_and_index(
            ref_id, prefix_finder=lambda prefix: prefix_finder(prefix, vault_dir=vault_dir)
        )
        if head_index_match is not None:
            matches = [head_index_match]
            kind = "head+index"
    if len(matches) != 1:
        raise UnresolvableGroundError(index, text, ref_type, ref_id)

    resolved_id = matches[0]
    print(
        f"synthesize: repaired truncated grounds ref_id on claim #{index}: "
        f"{ref_id!r} -> {resolved_id!r} (unique {kind} match)",
        file=sys.stderr,
    )
    return resolved_id


def _canonical_names_of(note: Any, *, names_dir: Path | None) -> list[str]:
    """The canonical names one grounds note is a member of (§7.4): every
    surface form its own `names` answer gave, resolved through the alias map
    alone (`axial.query.names.canonical_name_for_surface`).

    A surface the index does not carry is DROPPED, never invented -- and never
    retried against `find_names`' embedding tier, which would land the claim
    on a plausible neighbouring name and fabricate coverage the corpus does not
    have. An abstained `names` answer contributes nothing: `name_surfaces`
    applies the abstention predicate before any surface is read, so
    `not-in-passage` can never be minted as a name here (the same trap §7.16
    names for Reconcile's inventory)."""
    resolved: list[str] = []
    for surface in name_surfaces(note.names):
        canonical = canonical_name_for_surface(surface, names_dir=names_dir)
        if canonical is not None:
            resolved.append(canonical)
    return resolved


def _resolve_grounds(
    index: int,
    text: Any,
    raw_grounds: Any,
    *,
    vault_dir: Path | None,
    handle_map: dict[str, str],
    names_dir: Path | None = None,
) -> tuple[list[Ground], list[str]]:
    """Validate and resolve one claim's raw `grounds` list: structural
    shape, `ref_type` in `_REF_TYPES`, and `ref_id` resolving to a real
    note. The `Ground` recorded always carries the resolved (full, real)
    id, never the ref_id as the model emitted it. Returns the resolved
    `Ground` list plus the `names_touched` union computed from resolved CHUNK
    grounds only (`_canonical_names_of`) -- an artifact ground names nothing
    of its own, so it contributes nothing, unchanged from the field this
    replaced.

    A `chunk` ref_id is resolved against `handle_map` alone (issue #410):
    the model was never shown a real chunk_id, only a short opaque handle
    (`compose_prompt`), so a handle the model invents that is not an EXACT
    key of `handle_map` is `UnresolvableGroundError`, same as an
    unresolvable id always was -- no fuzzy match, no suffix repair, nothing
    left to fuzz. An `artifact` ref_id is unaffected: artifacts are never
    listed under a handle in the prompt (an artifact ground has always
    resolved against the real vault id directly), so it still resolves via
    exact match falling back to `_resolve_truncated_ref_id`'s unique-suffix
    repair, unchanged."""
    if raw_grounds is None:
        return [], []
    if not isinstance(raw_grounds, list):
        raise SynthesisParseError(
            f"claim #{index} ({text!r}) has non-list grounds: {raw_grounds!r}"
        )

    grounds: list[Ground] = []
    touched: list[str] = []
    for entry in raw_grounds:
        if not isinstance(entry, dict):
            raise SynthesisParseError(
                f"claim #{index} ({text!r}) has a non-object grounds entry: {entry!r}"
            )
        ref_type = entry.get("ref_type")
        ref_id = entry.get("ref_id")
        if ref_type not in _REF_TYPES:
            raise InvalidGroundRefTypeError(index, text, ref_type)
        if not isinstance(ref_id, str) or not ref_id.strip():
            raise SynthesisParseError(
                f"claim #{index} ({text!r}) has a grounds entry with a missing/blank ref_id"
            )

        if ref_type == "chunk":
            resolved_id = handle_map.get(ref_id)
            if resolved_id is None:
                raise UnresolvableGroundError(index, text, ref_type, ref_id)
            note = get_chunk(resolved_id, vault_dir=vault_dir)
            touched.extend(_canonical_names_of(note, names_dir=names_dir))
        else:
            resolved_id = ref_id
            try:
                get_artifact(ref_id, vault_dir=vault_dir)
            except ArtifactNotFoundError:
                resolved_id = _resolve_truncated_ref_id(
                    index, text, ref_type, ref_id, vault_dir=vault_dir
                )
                get_artifact(resolved_id, vault_dir=vault_dir)

        grounds.append(Ground(ref_type=ref_type, ref_id=resolved_id))

    return grounds, _dedupe_preserving_order(touched)


def _compute_claim_id(index: int, kind: str, text: str, grounds: list[Ground]) -> str:
    """A stable, deterministic id over this claim's own parsed content
    (mirrors `axial.brief.intake.compute_brief_id`'s sorted-key JSON
    canonicalisation): the same response parses to the same `claim_id`s on
    every run (no randomness, no timestamps), and `index` keeps two
    same-text claims in one response from colliding."""
    canonical = json.dumps(
        {
            "index": index,
            "kind": kind,
            "text": text,
            "grounds": [{"ref_type": g.ref_type, "ref_id": g.ref_id} for g in grounds],
        },
        sort_keys=True,
        ensure_ascii=True,
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return digest[:_CLAIM_ID_LENGTH]


def parse_synthesis_response(
    raw: str,
    *,
    vault_dir: Path | None = None,
    handle_map: dict[str, str] | None = None,
    names_dir: Path | None = None,
) -> list[Claim]:
    """Parse a raw synthesis completion into a validated `Claim` list
    (§7.4). Raises `ModelJsonError` (via `parse_model_json`) when `raw`
    isn't parseable JSON at all, `SynthesisParseError` (or a more specific
    subclass) when it parses but the claim-graph shape is violated. Never
    returns a partial result alongside an error, and never silently
    downgrades a malformed response into an empty claim list -- an empty
    `claims` list is only ever returned when the response itself genuinely
    names one.

    `handle_map` (issue #410) is the `{"[c1]": "<real chunk_id>", ...}` map
    `compose_prompt` handed out alongside the same call's prompt: every
    `chunk` grounds ref_id is resolved against it by exact lookup only
    (`_resolve_grounds`). Omitting it (the default, `None`, treated as
    empty) means no handle resolves -- correct for a caller that never
    offered any, never a silent pass-through to some other resolution
    path.

    `names_dir` (issue #489) is where the alias map `names_touched` resolves
    surface forms through lives (`data/names/`, `axial.paths.
    default_names_dir` when omitted) -- the same optional-directory
    convention every name-layer tool already takes."""
    handle_map = handle_map or {}
    data = parse_model_json(raw)
    if not isinstance(data, dict):
        raise SynthesisParseError(
            f"synthesis response must be a JSON object, got {type(data).__name__}"
        )
    if "claims" not in data or not isinstance(data["claims"], list):
        raise SynthesisParseError(f"synthesis response is missing a 'claims' list: {data!r}")

    claims: list[Claim] = []
    for index, entry in enumerate(data["claims"], start=1):
        if not isinstance(entry, dict):
            raise SynthesisParseError(f"claim #{index} must be an object, got {entry!r}")

        text = entry.get("text")
        if not isinstance(text, str) or not text.strip():
            raise SynthesisParseError(f"claim #{index} has a missing/blank text field: {entry!r}")
        text = text.strip()

        kind = entry.get("kind")
        if kind not in CLAIM_KINDS:
            raise InvalidClaimKindError(index, text, kind)

        confidence = entry.get("confidence")
        if confidence not in CONFIDENCE_BANDS:
            raise InvalidClaimConfidenceError(index, text, confidence)

        grounds, names_touched = _resolve_grounds(
            index,
            text,
            entry.get("grounds"),
            vault_dir=vault_dir,
            handle_map=handle_map,
            names_dir=names_dir,
        )
        if kind in _GROUNDED_KINDS and not grounds:
            raise UngroundedClaimError(index, text, kind)

        claim_id = _compute_claim_id(index, kind, text, grounds)
        claims.append(
            Claim(
                claim_id=claim_id,
                text=text,
                kind=kind,
                grounds=grounds,
                confidence=confidence,
                names_touched=names_touched,
            )
        )

    return claims


def synthesize(
    evidence: EvidenceSet,
    brief: Brief,
    *,
    client: LLMClient,
    vault_dir: Path | None = None,
    lenses_dir: Path | None = None,
    config_path: Path | None = None,
    names_dir: Path | None = None,
) -> ClaimGraph:
    """Run the §7.4 synthesis pass over `evidence`: resolve the lens
    (`resolve_lens`), compose the grounded-by-construction prompt
    (`compose_prompt` -- including its `evidence_char_budget` cap, issue
    #358, resolved from `config_path`/`config/pipeline.yaml`'s
    `synthesis.evidence_char_budget`, and its `handle_map`, issue #410),
    make ONE bounded model call (`pass_name=SYNTHESIZE_PASS_NAME`, routable
    through `model_by_pass`/`reasoning_by_pass`, §7.11), and parse+validate
    the result (`parse_synthesis_response`, passed that same `handle_map` to
    resolve cited handles back to real ids) into a `ClaimGraph`.

    Raises `SynthesisFailedError` when the underlying model call
    transport-fails or never returns parseable JSON within
    `complete_json`'s bounded re-ask budget; raises `SynthesisParseError`
    (or a more specific subclass) when the response parses as JSON but
    violates the §7.4 shape -- both are named, immediately-fatal failures.
    `UnknownLensError`/`NoLensesAvailableError` propagate unchanged from
    `resolve_lens` when the brief names a lens that does not exist.

    `names_dir` is forwarded to `parse_synthesis_response` for
    `names_touched`'s alias-map resolution (§7.4), defaulting to
    `data/names/` exactly as every name-layer tool does."""
    lens_name = resolve_lens(brief.lens, lenses_dir=lenses_dir)
    composed = compose_prompt(
        brief, lens_name, evidence, vault_dir=vault_dir, config_path=config_path
    )
    print(
        f"synthesize: starting, lens={lens_name!r}, {len(evidence.chunk_ids)} evidence item(s) "
        f"assembled, {len(composed.handle_map)} composed into the prompt",
        file=sys.stderr,
    )

    try:
        raw = complete_json(client, composed.text, pass_name=SYNTHESIZE_PASS_NAME)
    except (LLMError, httpx.HTTPError, ModelJsonError) as exc:
        raise SynthesisFailedError(f"synthesis call failed: {exc}") from exc

    claims = parse_synthesis_response(
        raw, vault_dir=vault_dir, handle_map=composed.handle_map, names_dir=names_dir
    )
    print(f"synthesize: done, {len(claims)} claim(s)", file=sys.stderr)
    return ClaimGraph(
        lens=lens_name, claims=claims, evidence_composed_count=len(composed.handle_map)
    )


# ---------------------------------------------------------------------------
# Counter-position generation (§7.8, issue #399) -- module docstring has the
# full design. Runs AFTER the claim graph above: contested-ness is a
# property of the claim graph's OWN resolved evidence, so there is nothing
# to detect until `synthesize()` has already produced one.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CounterPositionResult:
    """`generate_counter_position`'s own return shape: the persisted §7.8
    `section` dict, plus `model_called` -- whether the counter-position
    GENERATION model call actually ran. `model_by_pass`/`cost` (§7.3/§7.14)
    name a pass only when it really ran (the same "empty on `refuse`"
    convention `run_brief` already follows for retrieve/synthesize), so the
    caller (`axial.answer.record.build_record`) needs this explicit signal
    to extend those two fields correctly -- inferring it from the section's
    own shape would conflate "uncontested, never called" with "contested,
    every grounds chunk unresolvable, never called" (both disclose,
    differently) against "contested, model called, model itself judged
    one-sided" (also discloses) -- three states, only one of which spent a
    real completion call.

    A fourth state -- generation attempted and failed -- is never returned
    by `generate_counter_position` itself; that function still raises a
    `CounterPositionGenerationError` exactly as before (issue #558). It is
    `build_record` that catches the raise and constructs a
    `CounterPositionResult` directly around `failed_counter_position_section`,
    with `model_called=True` (a real call was attempted -- see that
    function's own docstring)."""

    section: dict[str, Any]
    model_called: bool


def _empty_counter_position() -> dict[str, Any]:
    """The §7.8 shape at its emptiest, honest value -- returned whenever the
    brief is not contested (§7.8: "an uncontested brief never requires the
    section at all"), including a `refuse` disposition's trivially-empty
    claim list. Identical shape to the pre-#399 placeholder; the difference
    is this is now a genuinely correct steady state, not a stand-in for
    unbuilt logic."""
    return {
        "present": False,
        "stance": None,
        "grounds": [],
        "corpus_one_sided": False,
        "one_sided_reason": None,
    }


def failed_counter_position_section(reason: str) -> dict[str, Any]:
    """The §7.8 shape's third, additive state (issue #558): counter-position
    GENERATION was attempted -- the brief was contested, so
    `generate_counter_position` made its one bounded model call -- and it
    failed: a transport failure, a malformed response, an unresolvable
    grounds id, or a citation outside the anti-fabrication whitelist (any
    `CounterPositionGenerationError` subclass). `reason` is that exception's
    own message, carried so the failure is diagnosable from the record alone.

    `present` and `corpus_one_sided` both stay `False` on purpose: this state
    must never be misread as "the corpus is one-sided" (that would launder a
    bug into a finding about the corpus, exactly backwards) and it must
    never satisfy the §7.9 presence-or-disclosure check by accident --
    `_check_presence_or_disclosure` (`axial.validators.counter_position`)
    treats this exactly like an unattempted absence and fails the same way,
    because the run genuinely owes the brief a counter-position it did not
    produce. `failed`/`failure_reason` are the only two keys this state adds;
    every other counter_position-producing path (`_empty_counter_position`,
    a model-generated `present`/`corpus_one_sided` section) simply omits
    them, so a reader checks `.get("failed")` rather than relying on a
    `False`/`None` default being written everywhere."""
    return {
        "present": False,
        "stance": None,
        "grounds": [],
        "corpus_one_sided": False,
        "one_sided_reason": None,
        "failed": True,
        "failure_reason": reason,
    }


# The most candidate notes one counter-position prompt ever carries. A
# whitelist that reaches beyond this run's own grounds (`who_argues_against`
# over a dense name, a Gather finding's member list) is unbounded on the real
# corpus -- `Syria` alone has 962 member notes -- and the first real
# `brief examine` already blew a prompt to 72,000 characters by re-sending one
# such list (issue #505). This is a bound on prompt size, not a quality knob:
# the ordering below puts the run's OWN grounds notes first, so what a cap
# ever drops is the vault-wide tail, never evidence the answer already cites.
MAX_COUNTER_POSITION_CANDIDATES = 20


def _counter_position_candidates(
    claims: list[dict[str, Any]],
    trajectory: list[dict[str, Any]] | None,
    *,
    vault_dir: Path | None,
    names_dir: Path | None = None,
) -> list[ChunkNote]:
    """The whitelist of real, resolvable vault notes (`ChunkNote`) offered as
    candidate counter-position grounds (§7.8, issues #490 and #550). Four
    sources, in this order, deduplicated on `chunk_id` and truncated at
    `MAX_COUNTER_POSITION_CANDIDATES` -- the run's own cited evidence
    outranks name-layer material, and a paired opposition outranks a note
    that names an opponent unpaired:

    1. **Both sides of every stated opposition among this run's own grounds
       notes** (`opposed_grounds_notes` -- the same function the contested
       predicate's `opposed_positions` path reads).
    2. **Every other grounds note whose own `arguing_against` names an
       opponent at all** (`notes_naming_an_opponent` -- the contested
       predicate's `names_opponent` path, issue #550), no pairing required.
       This is what puts Caspersen's note on the whitelist when it states and
       rejects Pegg's position: Pegg is not an author in this corpus, so
       Caspersen's note never pairs under source 1, but it is still this
       run's own cited opposition and belongs ahead of name-layer material.
       A note source 1 already added is not re-added here (`opposed_grounds_
       notes`'s own arguing side is a strict subset of this wider pool).
    3. **The notes `who_argues_against` returns** for a name the run touched
       (the §7.7 coverage scope) -- real vault ids reached deterministically
       from the name layer, never a fresh model-driven retrieval. Called with
       `limit=MAX_COUNTER_POSITION_CANDIDATES` (issue #505): this whitelist
       never keeps more than that many candidates in total, so it never needs
       more than that many from any one name either, and no new constant is
       introduced to state that.
    4. **The member notes of a Gather finding** at such a name (D4). The
       finding itself is a pointer and is never offered, quoted or cited; its
       page's own member notes are, because they are the passages the finding
       is about. Without this clause a brief that fires contested on the
       `gather_disagreement` path alone can reach the empty-candidates guard,
       whose disclosure would then say the grounds chunks did not resolve --
       which is false: they resolved and simply carry no opposing position.

    Not guaranteed non-empty even on a contested brief, which is why the
    caller still guards that case: a grounds id can fail to resolve here
    exactly as it does in `detect_contested` (skipped -- a broken grounds
    pointer is the attribution validator's job)."""
    grounds_notes = resolve_grounds_notes(claims, vault_dir=vault_dir)

    candidates: dict[str, ChunkNote] = {}
    for note in opposed_grounds_notes(grounds_notes, names_dir=names_dir):
        candidates[note.chunk_id] = note
    for note in notes_naming_an_opponent(grounds_notes):
        candidates.setdefault(note.chunk_id, note)

    scope = coverage_scope([c for c in claims if isinstance(c, dict)], trajectory or [])
    for canonical in scope:
        edges, _total = who_argues_against_name(
            canonical, MAX_COUNTER_POSITION_CANDIDATES, vault_dir=vault_dir, names_dir=names_dir
        )
        for edge in edges:
            if edge.chunk_id in candidates:
                continue
            try:
                candidates[edge.chunk_id] = get_chunk(edge.chunk_id, vault_dir=vault_dir)
            except ChunkNotFoundError:
                continue
    for canonical in scope:
        try:
            page = get_name(
                canonical, MAX_COUNTER_POSITION_CANDIDATES, vault_dir=vault_dir, names_dir=names_dir
            )
        except NameNotFoundError:
            continue
        if page.disagreement is None:
            continue
        for member in page.members:
            if member.chunk_id in candidates:
                continue
            try:
                candidates[member.chunk_id] = get_chunk(member.chunk_id, vault_dir=vault_dir)
            except ChunkNotFoundError:
                continue

    return list(candidates.values())[:MAX_COUNTER_POSITION_CANDIDATES]


def _describe_candidate(note: ChunkNote) -> str:
    """One candidate's line in the prompt: the ids and answers that make its
    opposition legible (§7.15's own words), then its prose. No tag axis is
    named -- every one of them was deleted with the tag pass."""
    position = stated_position(note) or "(the passage does not state one)"
    opposes = _opposition_surfaces(note)
    author = (note.source_meta or {}).get("author")
    return (
        f"- chunk_id={note.chunk_id}\n"
        f"  author: {author}\n"
        f"  stated position: {position}\n"
        f"  arguing against: {', '.join(opposes) if opposes else '(nothing named)'}\n"
        f"  text: {note.chunk_text}"
    )


# The §7.8 contested-signal vocabulary, in the model's own words (issue
# #550). Once `names_opponent` joined the predicate, 86% of grounds notes
# name an opponent (measured over the six smoke-v4 records, `data/logs/
# 2026-07-31-panel-smoke-v4/`), so "mechanically flagged CONTESTED" reads as
# selective when it is now the common case. The prompt states which signal
# actually fired instead of asserting a single, increasingly-meaningless
# verdict.
_CONTESTED_SIGNAL_DESCRIPTIONS = {
    SIGNAL_OPPOSED_POSITIONS: (
        "two of this run's own cited passages state opposing positions, and one of them "
        "names the other's side directly"
    ),
    SIGNAL_NAMES_OPPONENT: (
        "one of this run's own cited passages states and argues against an opposing "
        "position, even though no note on that other side is itself part of this run's "
        "own evidence"
    ),
    SIGNAL_GATHER_DISAGREEMENT: (
        "a name this answer rests on carries a disagreement the corpus's own authors are "
        "recorded as holding"
    ),
}


def _describe_contested_signal(signal: str | None) -> str:
    """The §7.8 prompt's own words for whichever contested signal fired
    (issue #550) -- never a generic "mechanically flagged" claim. Falls back
    to a plain, still-honest statement for a signal this dict does not name
    (a caller-supplied `None`, or a future signal added here without
    updating this map first)."""
    return _CONTESTED_SIGNAL_DESCRIPTIONS.get(
        signal, "this run's own resolved evidence states a disagreement"
    )


def _compose_counter_position_prompt(
    brief: Brief, claims: list[dict[str, Any]], candidates: list[ChunkNote], signal: str | None
) -> str:
    claim_lines = (
        "\n".join(
            f"- ({claim.get('kind')}) {claim.get('text')}"
            for claim in claims
            if isinstance(claim, dict) and claim.get("text")
        )
        or "(no claims)"
    )
    candidate_lines = "\n".join(_describe_candidate(note) for note in candidates)
    signal_description = _describe_contested_signal(signal)
    return f"""You are the stage-4 counter-position pass of an analysis engine (specs/PHASE-B.md §7.8). This brief is CONTESTED because {signal_description}. Your job is to state the strongest opposing position the corpus itself supports, or to say plainly that it does not -- never to invent one.

Case: "{brief.case}"
Request: "{brief.request}"

The primary claims already synthesized for this brief:
{claim_lines}

Candidate opposing-evidence chunks -- cite ONLY these chunk_ids as grounds. An id not listed here is never acceptable, even if it looks like a real one:
{candidate_lines}

Decide between exactly two outcomes, never both, never neither:
1. PRESENT -- the candidates above genuinely support a coherent position opposing the primary claims, at its STRONGEST (a steelman, not a strawman). Cite one or more candidate chunk_ids as grounds.
2. ONE-SIDED -- the candidates above are too thin, tangential, or incidental to construct a genuine opposing position, even though the mechanical signal fired. Say so plainly and name why, attributing the gap to the CORPUS, never to your own inability to argue one side.

Disclosing ONE-SIDED when the candidates do not truly ground an opposing stance is the correct, honest answer -- not a failure. Never manufacture opposition the candidates do not support.

Return ONLY this JSON object, no prose and no code fence:
{{"present": true|false, "stance": "<the opposing stance, or null>", "grounds": [{{"ref_type": "chunk", "ref_id": "<candidate chunk_id>"}}], "corpus_one_sided": true|false, "one_sided_reason": "<reason, or null>"}}"""


def _resolve_counter_position_ground(ref_id: str, *, vault_dir: Path | None) -> str:
    """Resolve one counter-position grounds `ref_id` against the vault --
    exact match first, then the same three truncated-citation repairs
    `_resolve_truncated_ref_id` applies (mirrors that function's own set
    exactly, DEC-42: ids run to ~200 chars and a model drops part of one even
    when shown the full id, as here). The head-truncation (prefix) repair is
    what issue #524 added, after a live brief died at this line after 998.6s
    of paid work on `caspersen-2012-fbc0efe4fffc_18`; the third,
    `_resolve_head_and_index`, is what a later paid run needed after it died
    citing `malesevic-2007-323a2518e61b_59_002` -- head and index both kept,
    only the slug between them dropped, a shape neither of the first two
    repairs resolves (see that function's own docstring). Kept in lockstep
    with `_resolve_truncated_ref_id` deliberately: this section's chunk
    grounds carry the identical ~200-char ids and the identical model
    truncation behaviour as that path's artifact grounds, so a repair added
    to one and not the other would leave the two silently diverging on the
    same failure mode. Raises `UnresolvableCounterPositionGroundError` --
    not `UnresolvableGroundError`, whose message names a "claim", misleading
    for a section that is not one -- on zero or 2+ matches at every repair,
    exactly as firm as an exact-match miss."""
    try:
        get_chunk(ref_id, vault_dir=vault_dir)
        return ref_id
    except ChunkNotFoundError:
        pass
    matches = find_chunk_ids_ending_with(ref_id, vault_dir=vault_dir)
    kind = "suffix"
    if len(matches) != 1:
        matches = find_chunk_ids_starting_with(f"{ref_id}_", vault_dir=vault_dir)
        kind = "prefix"
    if len(matches) != 1:
        head_index_match = _resolve_head_and_index(
            ref_id,
            prefix_finder=lambda prefix: find_chunk_ids_starting_with(prefix, vault_dir=vault_dir),
        )
        if head_index_match is not None:
            matches = [head_index_match]
            kind = "head+index"
    if len(matches) != 1:
        raise UnresolvableCounterPositionGroundError(ref_id)
    resolved_id = matches[0]
    print(
        f"generate_counter_position: repaired truncated grounds ref_id: "
        f"{ref_id!r} -> {resolved_id!r} (unique {kind} match)",
        file=sys.stderr,
    )
    return resolved_id


def _parse_counter_position_response(
    raw: str, candidates: list[Any], *, vault_dir: Path | None
) -> dict[str, Any]:
    """Parse+validate one counter-position-generation response into the
    §7.8 shape. `present` and `corpus_one_sided` must be booleans naming
    EXACTLY one channel (never both, never neither); a `present: true`
    response's `grounds` must be non-empty, `ref_type: "chunk"` only (the
    candidate pool is prose notes only -- an artifact note carries no
    interrogation answers and states no position),
    each `ref_id` resolved (`_resolve_counter_position_ground`) AND a
    member of `candidates` (`CounterPositionGroundNotOfferedError`
    otherwise) -- resolving is necessary but not sufficient, the whitelist
    is what makes this generation anti-confabulation by construction rather
    than by prompt wording alone."""
    data = parse_model_json(raw)
    if not isinstance(data, dict):
        raise InvalidCounterPositionResponseError(
            f"counter-position response must be a JSON object, got {type(data).__name__}"
        )

    present = data.get("present")
    corpus_one_sided = data.get("corpus_one_sided")
    if not isinstance(present, bool) or not isinstance(corpus_one_sided, bool):
        raise InvalidCounterPositionResponseError(
            f"counter-position response must carry boolean 'present'/'corpus_one_sided': {data!r}"
        )
    if present == corpus_one_sided:
        raise InvalidCounterPositionResponseError(
            "counter-position response must name EXACTLY ONE of present/corpus_one_sided "
            f"(§7.8 is either/or), got present={present!r} corpus_one_sided={corpus_one_sided!r}"
        )

    if not present:
        reason = data.get("one_sided_reason")
        if not isinstance(reason, str) or not reason.strip():
            raise InvalidCounterPositionResponseError(
                f"a corpus_one_sided disclosure must carry a non-blank 'one_sided_reason': {data!r}"
            )
        return {
            "present": False,
            "stance": None,
            "grounds": [],
            "corpus_one_sided": True,
            "one_sided_reason": reason.strip(),
        }

    stance = data.get("stance")
    if not isinstance(stance, str) or not stance.strip():
        raise InvalidCounterPositionResponseError(
            f"a present counter-position must carry a non-blank 'stance': {data!r}"
        )
    raw_grounds = data.get("grounds")
    if not isinstance(raw_grounds, list) or not raw_grounds:
        raise InvalidCounterPositionResponseError(
            f"a present counter-position must carry non-empty 'grounds': {data!r}"
        )

    candidate_ids = {chunk.chunk_id for chunk in candidates}
    grounds: list[dict[str, str]] = []
    for entry in raw_grounds:
        if not isinstance(entry, dict):
            raise InvalidCounterPositionResponseError(
                f"counter-position grounds entry must be an object, got {entry!r}"
            )
        ref_type = entry.get("ref_type")
        ref_id = entry.get("ref_id")
        if ref_type != "chunk" or not isinstance(ref_id, str) or not ref_id.strip():
            raise InvalidCounterPositionResponseError(
                "counter-position grounds entry must be "
                f"{{'ref_type': 'chunk', 'ref_id': <id>}}: {entry!r}"
            )
        resolved_id = _resolve_counter_position_ground(ref_id, vault_dir=vault_dir)
        if resolved_id not in candidate_ids:
            raise CounterPositionGroundNotOfferedError(resolved_id)
        grounds.append({"ref_type": "chunk", "ref_id": resolved_id})

    return {
        "present": True,
        "stance": stance.strip(),
        "grounds": grounds,
        "corpus_one_sided": False,
        "one_sided_reason": None,
    }


def generate_counter_position(
    claims: list[dict[str, Any]],
    brief: Brief,
    *,
    client: LLMClient,
    trajectory: list[dict[str, Any]] | None = None,
    vault_dir: Path | None = None,
    names_dir: Path | None = None,
) -> CounterPositionResult:
    """The §7.8 counter-position section, for real. Reuses
    `axial.validators.counter_position.detect_contested` VERBATIM to decide
    whether this brief is contested, over the just-produced claim graph's
    own resolved evidence -- never reimplements that predicate (issue #399's
    explicit instruction). Zero model calls on an uncontested brief
    (`_empty_counter_position`); on a contested brief, offers the model a
    whitelisted pool of real opposing notes (`_counter_position_candidates`)
    and makes ONE bounded call under
    `pass_name=COUNTER_POSITION_GENERATE_PASS_NAME` (routable through
    `model_by_pass`/`reasoning_by_pass` independently of
    `SYNTHESIZE_PASS_NAME`, though it is still the GENERATING model and
    config routes both to the same tier -- see that pass name's own
    comment in axial.llm).

    `trajectory` is the run's own §7.6 log. Both the contested predicate's
    path 2 and the whitelist's name-layer sources read the §7.7 coverage
    scope off it, so a caller that omits it gets the grounds-only halves of
    both -- honest, and never a crash.

    Raises `CounterPositionGenerationFailedError` when the model call
    transport-fails or never returns parseable JSON within
    `complete_json`'s bounded re-ask budget; raises
    `InvalidCounterPositionResponseError`,
    `UnresolvableCounterPositionGroundError`, or
    `CounterPositionGroundNotOfferedError` when the response parses as JSON
    but violates the §7.8 shape or its anti-fabrication whitelist -- all
    immediately fatal, exactly like a claim-graph parse failure."""
    contested = detect_contested(claims, trajectory, vault_dir=vault_dir, names_dir=names_dir)
    if not contested.contested:
        return CounterPositionResult(section=_empty_counter_position(), model_called=False)

    candidates = _counter_position_candidates(
        claims, trajectory, vault_dir=vault_dir, names_dir=names_dir
    )
    if not candidates:
        # Guarded, not asserted-impossible (see _counter_position_candidates'
        # own docstring). The disclosure names what is actually true of each
        # path: on `opposed_positions` the grounds notes are what failed to
        # resolve; on `gather_disagreement` they resolved fine and simply
        # carry no opposing position, and saying otherwise would be a false
        # reason in the record (§7.8, issue #490).
        if contested.signal == SIGNAL_GATHER_DISAGREEMENT:
            reason = (
                "a name this answer rests on carries a recorded disagreement, but none of "
                "this run's grounds notes states an opposing position and the name's own "
                "member notes are not reachable as candidates, so the corpus offers no "
                "opposing material to ground a counter-position here"
            )
        else:
            reason = (
                "this run's evidence signalled a contested brief (signal="
                f"{contested.signal!r}), but none of the underlying grounds chunks "
                "resolved in the vault, so no opposing material is available to "
                "ground a counter-position"
            )
        return CounterPositionResult(
            section={
                "present": False,
                "stance": None,
                "grounds": [],
                "corpus_one_sided": True,
                "one_sided_reason": reason,
            },
            model_called=False,
        )

    prompt = _compose_counter_position_prompt(brief, claims, candidates, contested.signal)
    print(
        f"generate_counter_position: starting, signal={contested.signal!r}, "
        f"{len(candidates)} candidate(s)",
        file=sys.stderr,
    )
    try:
        raw = complete_json(client, prompt, pass_name=COUNTER_POSITION_GENERATE_PASS_NAME)
    except (LLMError, httpx.HTTPError, ModelJsonError) as exc:
        raise CounterPositionGenerationFailedError(
            f"counter-position generation call failed: {exc}"
        ) from exc

    section = _parse_counter_position_response(raw, candidates, vault_dir=vault_dir)
    print(f"generate_counter_position: done, present={section['present']}", file=sys.stderr)
    return CounterPositionResult(section=section, model_called=True)
