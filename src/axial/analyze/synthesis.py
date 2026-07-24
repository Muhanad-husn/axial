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
claim's `grounds` must be non-empty, every grounds entry must resolve to a
real vault id (`axial.query.reader.get_chunk`/`get_artifact`), and
`polities_touched` is computed here -- never trusted from the model -- as
the union of the claim's grounds CHUNKS' `polities_touched` facets (an
artifact ground carries no such facet of its own, so it contributes
nothing). `claim_id` is a deterministic hash over each claim's own parsed
content, so the same response parses to the same ids on every run.

Out of scope for this slice (see plans/analysis-synthesis/02-synthesis-claim-
graph.md): the attribution validator, the grounding check, the counter-
position section, the coverage map, a hardcoded confidence vocabulary
(`confidence` is carried through untyped), and persisting the claim graph.
"""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import yaml

from axial.analyze.assembly import EvidenceSet
from axial.brief.intake import Brief
from axial.llm import SYNTHESIZE_PASS_NAME, LLMClient, LLMError
from axial.model_json import ModelJsonError, complete_json, parse_model_json
from axial.paths import DEFAULT_PIPELINE_CONFIG_PATH
from axial.query.reader import (
    ArtifactNotFoundError,
    ChunkNotFoundError,
    get_artifact,
    get_chunk,
)

# The §7.4 claim-kind vocabulary -- closed, not open text: a value outside
# this set is a named parse error, never silently accepted or coerced.
CLAIM_KINDS = frozenset({"a", "b", "c"})

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
        document = yaml.safe_load(handle) or {}
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
    polities_touched}`. `confidence` is carried through exactly as the model
    emitted it -- no vocabulary is enforced here (the band-vs-numeric
    question is an open question per §7.4/plan, out of this slice's scope)."""

    claim_id: str
    text: str
    kind: str
    grounds: list[Ground]
    confidence: Any
    polities_touched: list[str]


@dataclass(frozen=True)
class ClaimGraph:
    """The full stage-4 output: the lens actually applied (always recorded,
    §7.1) plus the parsed, validated, grounded claim list."""

    lens: str
    claims: list[Claim]


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


def compose_prompt(
    brief: Brief,
    lens_name: str,
    evidence: EvidenceSet,
    *,
    vault_dir: Path | None = None,
    config_path: Path | None = None,
    evidence_char_budget: int | None = None,
) -> str:
    """Assemble the synthesis prompt (§7.4/P0-4): the brief's case/request,
    the applied lens, and every evidence chunk's id, its real prose TEXT, and
    its synthesis-relevant frontmatter. `EvidenceSet.chunks` (`EvidenceChunk`)
    deliberately does not carry `chunk_text` (`axial.analyze.assembly`'s own
    module docstring: "chunk_text ... stay[s] reachable via ... get_chunk when
    synthesis (slice 02) actually needs them") -- this is that need: the
    prompt re-fetches each evidence chunk's full text via
    `axial.query.reader.get_chunk` so the model reasons over real prose, not
    just tag facets, and grounds pointers are drawn from what was actually
    supplied rather than invented. Every phrase this module's acceptance
    test checks against the recorded prompt lives verbatim in this
    template, so a prompt wording change is a deliberate, visible diff, not
    silent drift.

    `evidence_char_budget` (issue #358, default `_resolve_evidence_char_budget`
    off `config_path`/`DEFAULT_EVIDENCE_CHAR_BUDGET`) bounds the combined
    length of every included chunk's `chunk_text`: chunks are walked in
    `evidence.chunk_ids`' existing (first-seen retrieval) order, and the
    included evidence set is a deterministic PREFIX of that order -- the walk
    stops (never mid-text truncating a chunk) at the first chunk that would
    push the running total over budget, so every later chunk is dropped too.
    A dropped chunk's id never appears in the evidence list, so the model has
    nothing to cite it with (grounds validation already rejects an unlisted
    id)."""
    if evidence_char_budget is None:
        evidence_char_budget = _resolve_evidence_char_budget(config_path)

    lines: list[str] = []
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
        lines.append(
            f"- chunk_id={chunk_id} role_in_argument={chunk.role_in_argument} "
            f"polities_touched={chunk.polities_touched} "
            f"theory_school={chunk.theory_school.get('primary')} "
            f"claim_type={chunk.claim_type.get('primary')} "
            f"empirical_scope={chunk.empirical_scope.get('value')}\n"
            f"  text: {note.chunk_text}"
        )
    evidence_lines = "\n".join(lines) or "(no evidence chunks were retrieved for this brief)"

    return f"""You are the stage-4 synthesis pass of an analysis engine (specs/PHASE-B.md §7.4). Apply the lens named below and perform axial coding across ONLY the evidence chunks supplied below -- reason only over the grounds supplied here, never from your own parametric memory or the open web. Any assertion not traceable to a supplied grounds pointer is not a claim this pass may emit.

Case: "{brief.case}"
Request: "{brief.request}"
Lens: "{lens_name}"

Evidence chunks (cite ONLY these chunk_ids/artifact_ids as grounds):
{evidence_lines}

For every claim you emit, mark its kind:
- "a" (source-says) -- a single source directly asserts this; grounds must name that source's chunk(s)/artifact(s).
- "b" (tool-infers-across-sources) -- YOUR inference drawn across two or more sources; grounds must name every source it draws on. A (b) claim is always marked as the tool's own inference and must NEVER be voiced as though a single source asserted it -- a cross-source inference is marked (b), never phrased as a source assertion.
- "c" (speculation) -- neither of the above; may carry partial or empty grounds.

Every (a) and (b) claim MUST carry at least one grounds pointer to a chunk_id or artifact_id listed above -- an unlisted or invented id is never acceptable.

Return ONLY this JSON object, no prose and no code fence:
{{"claims": [{{"text": "<claim text>", "kind": "a|b|c", "grounds": [{{"ref_type": "chunk|artifact", "ref_id": "<id>"}}], "confidence": "<your confidence>"}}]}}"""


def _dedupe_preserving_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered


def _resolve_grounds(
    index: int, text: Any, raw_grounds: Any, *, vault_dir: Path | None
) -> tuple[list[Ground], list[str]]:
    """Validate and resolve one claim's raw `grounds` list against the
    vault: structural shape, `ref_type` in `_REF_TYPES`, and `ref_id`
    resolving to a real note. Returns the resolved `Ground` list plus the
    `polities_touched` union computed from resolved CHUNK grounds only (an
    artifact ground contributes nothing -- `ArtifactNote` carries no
    `polities_touched` facet of its own)."""
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
            try:
                note = get_chunk(ref_id, vault_dir=vault_dir)
            except ChunkNotFoundError as exc:
                raise UnresolvableGroundError(index, text, ref_type, ref_id) from exc
            touched.extend(note.polities_touched)
        else:
            try:
                get_artifact(ref_id, vault_dir=vault_dir)
            except ArtifactNotFoundError as exc:
                raise UnresolvableGroundError(index, text, ref_type, ref_id) from exc

        grounds.append(Ground(ref_type=ref_type, ref_id=ref_id))

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


def parse_synthesis_response(raw: str, *, vault_dir: Path | None = None) -> list[Claim]:
    """Parse a raw synthesis completion into a validated `Claim` list
    (§7.4). Raises `ModelJsonError` (via `parse_model_json`) when `raw`
    isn't parseable JSON at all, `SynthesisParseError` (or a more specific
    subclass) when it parses but the claim-graph shape is violated. Never
    returns a partial result alongside an error, and never silently
    downgrades a malformed response into an empty claim list -- an empty
    `claims` list is only ever returned when the response itself genuinely
    names one."""
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

        grounds, polities_touched = _resolve_grounds(
            index, text, entry.get("grounds"), vault_dir=vault_dir
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
                confidence=entry.get("confidence"),
                polities_touched=polities_touched,
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
) -> ClaimGraph:
    """Run the §7.4 synthesis pass over `evidence`: resolve the lens
    (`resolve_lens`), compose the grounded-by-construction prompt
    (`compose_prompt` -- including its `evidence_char_budget` cap, issue
    #358, resolved from `config_path`/`config/pipeline.yaml`'s
    `synthesis.evidence_char_budget`), make ONE bounded model call
    (`pass_name=SYNTHESIZE_PASS_NAME`, routable through
    `model_by_pass`/`reasoning_by_pass`, §7.11), and parse+validate the
    result (`parse_synthesis_response`) into a `ClaimGraph`.

    Raises `SynthesisFailedError` when the underlying model call
    transport-fails or never returns parseable JSON within
    `complete_json`'s bounded re-ask budget; raises `SynthesisParseError`
    (or a more specific subclass) when the response parses as JSON but
    violates the §7.4 shape -- both are named, immediately-fatal failures.
    `UnknownLensError`/`NoLensesAvailableError` propagate unchanged from
    `resolve_lens` when the brief names a lens that does not exist."""
    lens_name = resolve_lens(brief.lens, lenses_dir=lenses_dir)
    prompt = compose_prompt(
        brief, lens_name, evidence, vault_dir=vault_dir, config_path=config_path
    )
    print(
        f"synthesize: starting, lens={lens_name!r}, {len(evidence.chunk_ids)} evidence item(s)",
        file=sys.stderr,
    )

    try:
        raw = complete_json(client, prompt, pass_name=SYNTHESIZE_PASS_NAME)
    except (LLMError, httpx.HTTPError, ModelJsonError) as exc:
        raise SynthesisFailedError(f"synthesis call failed: {exc}") from exc

    claims = parse_synthesis_response(raw, vault_dir=vault_dir)
    print(f"synthesize: done, {len(claims)} claim(s)", file=sys.stderr)
    return ClaimGraph(lens=lens_name, claims=claims)
