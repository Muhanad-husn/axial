"""Shared tag-value parse/validate machinery for primary+secondary
(`primary_plus_secondary` / `primary_plus_optional_secondary`) axes -- the
`TagNotInSchemaError` exception, the parser/validator pair that reads and
checks one such axis's value against the loaded schema, and the bounded
P0-6 correction re-ask that both `axial.tag` (the `field`/`claim_type`/
`theory_school` tag pass) and `axial.artifacts` (its own off-list `field`
classification) drive off of unchanged.

Moved out of `axial.tag` verbatim (issue #423, prep for #414's later
deletion of `tag.py`): `axial.artifacts` depended on these names from
`axial.tag`, but #414 deletes that module outright while leaving
`artifacts.py` unchanged ("it is content", not part of the interrogation
rewrite). This module holds exactly what `artifacts.py` reaches for --
`TagNotInSchemaError`, `parse_multi_value_tag_response`,
`validate_multi_value_tag`, `apply_correction_reask` -- plus what those
transitively need (`TagError`, `TagParseError`, `MULTI_VALUE_CARDINALITIES`,
`validate_tag` and its own helpers). `axial.tag` imports them back so it
keeps working unchanged until #414 lands.

Deliberately dependency-light: only `axial.schema` (types) and
`axial.model_json` (JSON parsing) at import time, plus `axial.llm.LLMClient`
under `TYPE_CHECKING` only (`apply_correction_reask`'s one call site never
needs the class itself, only the `.complete()` method any real client
already provides) -- so a caller that only needs these validators never
pulls in `axial.tag`'s own heavier stack (`axial.chunk`, `axial.envelope`,
`axial.codebook`)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from axial.model_json import ModelJsonError, parse_model_json
from axial.schema import Axis, Schema

if TYPE_CHECKING:
    from axial.llm import LLMClient


class TagError(Exception):
    """Base class for all tagging-pass errors."""


class TagParseError(TagError):
    """Raised when the model's tagging response is not parseable into an
    axis -> value assignment."""


class TagNotInSchemaError(TagError):
    """Raised when a tag value the model returned does not exist in the
    loaded schema's axis vocabulary (PRD §7.1, P0-6).

    Carries the controlled `vocabulary` legal for the FAILING POSITION and an
    optional human-readable `position` label (issue #102): a subtag failure's
    legal set is that specific primary's own declared subtags, NOT the axis's
    primary vocabulary, so the bounded correction re-ask can show the model
    the right options to correct against. Both are optional so every existing
    raise site (and the locked error message) is unchanged when they are
    omitted."""

    def __init__(
        self,
        axis_name: str,
        tag: Any,
        *,
        vocabulary: set[str] | None = None,
        position: str | None = None,
    ):
        self.axis_name = axis_name
        self.tag = tag
        self.vocabulary = vocabulary
        self.position = position
        super().__init__(f"tag {tag!r} is not in the schema's {axis_name!r} axis")


# Cardinalities handled by the shared multi-value parser/validator (issue
# #29 slice 03): one primary tag plus either zero-or-more secondary tags
# (Appendix A) or an optional single secondary tag (Appendix B/E). Which
# axis has which cardinality is schema data (`Axis.cardinality`), never
# branched on by axis name.
MULTI_VALUE_CARDINALITIES = {"primary_plus_secondary", "primary_plus_optional_secondary"}


def _normalize_axis_prefixed_value(axis_name: str, value: Any, vocabulary: set[str]) -> Any:
    """Normalize a string `value` of the form `"<axis_name>:<suffix>"` to
    its bare `<suffix>` -- but ONLY when the raw value is NOT already a
    member of `vocabulary` and the stripped suffix IS (issue #96: the live
    model recurringly echoes the axis's own name as a prefix, e.g.
    `field:ideology` for the `field` axis's `ideology` value).

    Deliberately narrow, so this never smooths over a genuine schema gap or
    reaches into an axis whose vocabulary is ITSELF prefix-shaped:

      - a value already in `vocabulary` (e.g. `empirical_scope`'s own
        `"scope:general"`, or `role_in_argument`'s own `"role:setup"`) is
        returned untouched -- the first condition never even fires;
      - a value prefixed with anything other than exactly `"<axis_name>:"`
        (e.g. `"scope:general"` under the `field` axis) is returned
        untouched;
      - a value whose stripped suffix is ALSO not in `vocabulary` (e.g.
        `"field:ethnicity"`) is returned untouched, so it still fails
        validation and still raises `TagNotInSchemaError` naming the
        original, unnormalized value;
      - a non-string value is returned untouched (only strings can carry a
        `"prefix:"` shape at all).
    """
    if not isinstance(value, str) or value in vocabulary:
        return value
    prefix = f"{axis_name}:"
    if value.startswith(prefix):
        suffix = value[len(prefix) :]
        if suffix in vocabulary:
            return suffix
    return value


def validate_tag(schema: Schema, axis_name: str, value: Any) -> Any:
    """Validate that `value` exists in the loaded schema's `axis_name` tag
    set; raises `TagNotInSchemaError` (naming the axis + offending tag) if
    not (PRD §7.1, P0-6).

    Before that check, normalizes `value` per `_normalize_axis_prefixed_
    value` (issue #96): a value of the form `"<axis_name>:<suffix>"` whose
    raw form is out-of-vocabulary but whose stripped suffix IS in-vocabulary
    is rewritten to that suffix first, so e.g. `field.primary ==
    "field:ideology"` validates (and is returned) as `"ideology"`. Returns
    the value to use going forward -- the normalized form when normalization
    applied, otherwise `value` unchanged -- so every caller must use the
    return value rather than assuming the passed-in `value` survives
    verbatim."""
    axis = schema.axes.get(axis_name)
    if axis is not None:
        value = _normalize_axis_prefixed_value(axis_name, value, axis.tag_ids)
    if axis is None or not isinstance(value, str) or value not in axis.tag_ids:
        raise TagNotInSchemaError(
            axis_name, value, vocabulary=(axis.tag_ids if axis is not None else None)
        )
    return value


def _axis_declares_subtags(axis: Axis) -> bool:
    """Whether `axis`'s own vocabulary structurally supports per-tag
    `subtags` at all -- a list of `{id, ...}` tag objects (e.g. claim_type),
    as opposed to a flat scalar list (field) or grouped mapping
    (theory_school). Read from the schema, never the axis's name."""
    return any(isinstance(entry, dict) for entry in axis.raw.get("values") or [])


def _declared_subtags(axis: Axis, primary: str) -> set[str]:
    """The `primary` tag's own declared `subtags` list, read from the
    axis's `raw` values (empty if that entry declares none, or if the
    axis's vocabulary isn't a list of `{id, ...}` tag objects at all --
    e.g. `field`'s flat scalar list). Never the axis's full subtag universe
    (Appendix B: "sub-tags refine, they do not multiply the count")."""
    for entry in axis.raw.get("values") or []:
        if isinstance(entry, dict) and entry.get("id") == primary:
            return set(entry.get("subtags") or [])
    return set()


def parse_multi_value_tag_response(raw: str, axis: Axis) -> dict[str, Any]:
    """Parse the model's raw tagging response for one primary+secondary axis
    (`axis.cardinality` one of `MULTI_VALUE_CARDINALITIES`), shared by every
    axis of either cardinality (issue #29 slice 03) -- never one parser per
    axis.

    Per seam decision 9 (tests/test_tag.py), the raw response nests the
    axis's value in exactly the shape the final record exposes:
    `{axis.name: {"primary": <str>, "secondary": [...] | <str> | omitted,
    "subtags": [...] (optional)}}`. `"primary_plus_secondary"` (Appendix A)
    always yields a `secondary` list (zero or more, defaulting to `[]` when
    omitted); `"primary_plus_optional_secondary"` (Appendix B/E) yields
    `secondary` as `None` or a single scalar string, never a list -- but since
    the shared tagging prompt shows the list shape for the sibling
    cardinality, a model may still answer with a list here, so `[]` is
    normalized to `None` and a single-element list to its lone element before
    anything longer than that is rejected as a genuine cardinality violation.
    A blank/whitespace-only secondary entry (the model's "no secondary"
    expressed as noise instead of an omitted key) is dropped from a
    `primary_plus_secondary` list, or collapsed to `None` for a
    `primary_plus_optional_secondary` scalar -- never a genuine
    out-of-vocabulary value, which still fails vocabulary validation
    downstream unchanged.

    When the axis's own vocabulary structurally declares subtags at all
    (`_axis_declares_subtags`), `subtags` defaults to `[]` if the model
    omitted it, so e.g. `claim_type.subtags` is always a list."""
    axis_name = axis.name
    try:
        data = parse_model_json(raw)
    except ModelJsonError as exc:
        raise TagParseError(f"model response was not valid JSON: {exc}") from exc

    if not isinstance(data, dict) or axis_name not in data:
        keys = sorted(data.keys()) if isinstance(data, dict) else type(data).__name__
        raise TagParseError(f"expected a top-level {axis_name!r} key, got: {keys}")

    axis_value = data[axis_name]
    if isinstance(axis_value, str) and axis.cardinality in MULTI_VALUE_CARDINALITIES:
        # Issue #105 (extended by the quarantine-recovery fix): a bare,
        # unambiguous string for EITHER multi-value cardinality is a known
        # model dialect for "just the primary, no secondary" -- coerce it to
        # the object shape BEFORE the shape check below, so it flows through
        # the same vocabulary validation as every other value (an
        # out-of-vocab bare string still fails vocabulary validation
        # downstream, and still triggers the #102 correction re-ask --
        # coercion never bypasses that check, it only fixes the shape ahead
        # of it). Originally scoped to `primary_plus_optional_secondary`
        # only; `primary_plus_secondary` (e.g. `field`) got no such coercion
        # and quarantined 422/577 (73%) of one corpus-wide run's chunks on
        # this exact shape (`"expected 'field' value to be an object with a
        # 'primary' key, got str"`) -- the same unambiguous dialect, just on
        # the axis's sibling cardinality. A freshly-coerced `{"primary":
        # axis_value}` dict has no `secondary` key, which the
        # `primary_plus_secondary` branch below already resolves to `[]`
        # (zero secondaries) -- exactly the dialect's intended meaning.
        axis_value = {"primary": axis_value}

    if not isinstance(axis_value, dict) or "primary" not in axis_value:
        raise TagParseError(
            f"expected {axis_name!r} value to be an object with a 'primary' "
            f"key, got {type(axis_value).__name__}: {axis_value!r}"
        )

    primary = axis_value["primary"]
    if not isinstance(primary, str):
        raise TagParseError(
            f"expected {axis_name!r}.primary to be a string, got "
            f"{type(primary).__name__}: {primary!r}"
        )

    raw_secondary = axis_value.get("secondary")
    if axis.cardinality == "primary_plus_secondary":
        secondary: Any = raw_secondary if raw_secondary is not None else []
        if not isinstance(secondary, list):
            secondary = [secondary]
        # Quarantine-recovery fix: a blank/whitespace-only secondary entry is
        # the same "meant no secondary" noise `_reject_blank_tag` already
        # treats as degenerate elsewhere -- 125 (claim_type) + 27
        # (theory_school) of one corpus-wide run's quarantines traced to
        # exactly this ("claim_type.secondary[0] tag value is
        # empty/whitespace-only: ''"). Drop it silently rather than
        # quarantining the whole chunk; a genuinely out-of-vocabulary
        # (non-blank) entry is untouched here and still fails
        # `validate_multi_value_tag` downstream exactly as before.
        secondary = [
            value for value in secondary if not (isinstance(value, str) and not value.strip())
        ]
    else:
        secondary = raw_secondary
        if isinstance(secondary, list):
            if len(secondary) == 0:
                secondary = None
            elif len(secondary) == 1:
                secondary = secondary[0]
        if isinstance(secondary, str) and not secondary.strip():
            # Same blank-secondary noise as above, collapsed to the
            # cardinality's own "no secondary" representation (`None`)
            # instead of the list's "drop the entry" -- this cardinality
            # never carries a list of secondaries to drop from.
            secondary = None
        if secondary is not None and not isinstance(secondary, str):
            raise TagParseError(
                f"expected {axis_name!r}.secondary, when present, to be a "
                f"single string, got {type(secondary).__name__}: {secondary!r}"
            )

    parsed: dict[str, Any] = {"primary": primary, "secondary": secondary}
    if "subtags" in axis_value:
        raw_subtags = axis_value["subtags"]
        parsed["subtags"] = raw_subtags if isinstance(raw_subtags, list) else [raw_subtags]
    elif _axis_declares_subtags(axis):
        parsed["subtags"] = []

    return parsed


def _validate_subtags(schema: Schema, axis_name: str, parsed: dict[str, Any]) -> None:
    """Validate+normalize `parsed['subtags']` in place against
    `parsed['primary']`'s OWN declared subtags (`_declared_subtags`), not the
    axis's full subtag universe -- shared by `validate_multi_value_tag` and
    the theory_school soft-land path (`_validate_theory_school_with_
    softland`), which validate `primary`/`secondary` differently (the latter
    softens an out-of-vocab value to `unlisted` instead of raising) but
    validate `subtags` identically: theory_school never structurally
    declares subtags (`_axis_declares_subtags`), so a hallucinated one stays
    a hard error either way, out of the soft-land's scope."""
    if "subtags" not in parsed:
        return
    declared = _declared_subtags(schema.axes[axis_name], parsed["primary"])
    normalized_subtags = []
    for subtag in parsed["subtags"]:
        normalized = _normalize_axis_prefixed_value(axis_name, subtag, declared)
        # A non-string subtag (live 2026-07-24 crash: the model answered a
        # subtag as a JSON object instead of a string) is unhashable, so
        # `in declared` (a set) would raise a bare
        # `TypeError` before this function ever gets to raise its own
        # `TagNotInSchemaError` -- checked first here, mirroring
        # `validate_tag`'s identical `not isinstance(value, str) or value
        # not in axis.tag_ids` short-circuit guard above. A malformed shape
        # is a DIFFERENT failure than a genuine out-of-vocabulary string,
        # but both are handled by the same mechanism: raise
        # `TagNotInSchemaError`, which `apply_correction_reask` already
        # re-asks on and `run_tag`'s quarantine loop already catches.
        if not isinstance(normalized, str) or normalized not in declared:
            raise TagNotInSchemaError(
                axis_name,
                subtag,
                vocabulary=declared,
                position=f"as a subtag of the primary {parsed['primary']!r}",
            )
        normalized_subtags.append(normalized)
    parsed["subtags"] = normalized_subtags


def validate_multi_value_tag(schema: Schema, axis_name: str, parsed: dict[str, Any]) -> None:
    """Validate a parsed primary+secondary axis value against the loaded
    schema: `primary` and every `secondary`/`subtags` entry must exist in
    the schema (`TagNotInSchemaError`, naming axis + offending tag), with
    subtags checked against that specific primary's OWN declared subtags
    (`_declared_subtags`), not the axis's full subtag universe.

    Normalizes `primary`, each `secondary` entry, and each `subtags` entry
    in place on `parsed` (issue #96, mirroring `validate_tag`'s own
    normalization): an axis-name-prefixed value that is out-of-vocabulary
    raw but in-vocabulary once the `"<axis_name>:"` prefix is stripped is
    rewritten before validation, so callers reading `parsed` afterward (both
    `run_tag`'s own record assembly and `axial.artifacts`, which reuses this
    validator for its own `field` classification) see the normalized value,
    never the raw prefixed one."""
    parsed["primary"] = validate_tag(schema, axis_name, parsed["primary"])

    secondary = parsed.get("secondary")
    if isinstance(secondary, list):
        parsed["secondary"] = [validate_tag(schema, axis_name, value) for value in secondary]
    elif secondary is not None:
        parsed["secondary"] = validate_tag(schema, axis_name, secondary)

    _validate_subtags(schema, axis_name, parsed)


# Appended to a pass's own base prompt to form the P0-6 bounded correction
# re-ask (issue #102). Shows the invalid value, the controlled vocabulary
# legal for the FAILING POSITION (a subtag failure shows that primary's own
# declared subtags, not the axis's primary vocabulary), and the instruction to
# return a valid value or the literal NONE. Deliberately avoids the chunk-pass
# and xref-pass prompt markers so a recorded run still counts it as a
# tag-pass-family call, not a chunk/xref one.
_CORRECTION_REASK_NOTICE = """\

CORRECTION REQUIRED. Your previous answer used {invalid!r} for the {axis!r} \
axis{position}, but that value is NOT in its controlled vocabulary. Choose one \
value strictly from this controlled vocabulary:

{vocabulary}

Reply with the FULL JSON object again -- every key exactly as instructed \
above -- replacing only the invalid value with a valid one drawn from that \
vocabulary, or the single word NONE if, and only if, none of them applies.
"""


def compose_correction_prompt(base_prompt: str, exc: TagNotInSchemaError) -> str:
    """Build the bounded correction re-ask prompt (issue #102): the pass's own
    `base_prompt` plus a correction notice naming the invalid value, the
    failing position, and the controlled vocabulary legal there (from
    `exc.vocabulary`, populated at every schema-vocabulary raise site). The
    model must return a valid value or an explicit NONE -- the code never
    guesses or normalizes the value itself."""
    if exc.vocabulary:
        vocab_text = "\n".join(f"- {value}" for value in sorted(exc.vocabulary))
    else:
        vocab_text = "(that axis's controlled vocabulary, as listed above)"
    position = f" {exc.position}" if exc.position else ""
    notice = _CORRECTION_REASK_NOTICE.format(
        invalid=exc.tag,
        axis=exc.axis_name,
        position=position,
        vocabulary=vocab_text,
    )
    return base_prompt + notice


def apply_correction_reask(
    client: "LLMClient",
    pass_name: str,
    raw_response: str,
    base_prompt: str,
    validate: Any,
) -> Any:
    """Run `validate(raw_response)`; on an out-of-vocabulary `TagNotInSchemaError`
    issue EXACTLY ONE bounded correction re-ask and re-validate that one
    correction (issue #102, PRD §7.1 / P0-6).

    `validate(raw)` parses+validates a raw tag/artifact response, raising
    `TagNotInSchemaError` on a schema-vocabulary miss and returning its own
    parsed result otherwise. The correction re-ask is a SINGLE
    `client.complete(correction_prompt, pass_name=pass_name)` call -- distinct
    from `complete_json`'s JSON/degeneracy re-ask budget -- whose prompt shows
    the failing position's controlled vocabulary and asks for a valid value or
    an explicit NONE. If the correction is still out-of-vocabulary (a literal
    NONE is in no axis's vocabulary, so it fails re-validation the same way),
    the re-validation's `TagNotInSchemaError` propagates unchanged: the P0-6
    hard error, never a silent pass and never a code-side guess. The corrected
    value can only ever come from the model's own re-ask response, re-checked
    through the identical vocabulary validation.

    Only `TagNotInSchemaError` triggers the re-ask; any other error `validate`
    raises (parse/cardinality/missing-polity) propagates unchanged, exactly
    as before this layer existed. Transport errors from `client.complete` are
    not caught here -- the caller wraps them into its own typed LLM error."""
    try:
        return validate(raw_response)
    except TagNotInSchemaError as exc:
        correction_prompt = compose_correction_prompt(base_prompt, exc)
        corrected_raw = client.complete(correction_prompt, pass_name=pass_name)
        return validate(corrected_raw)
