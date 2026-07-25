"""Vendor resolution for the sealed-packet reviewer panel (issue #385,
specs/PHASE-B.md §9.4 property 3).

**Vendor means the training lab, never the API provider.** OpenRouter serves
every lab's models behind one endpoint, so "who served this response" carries
no independence signal at all. What matters is who trained the weights:
shared training priors survive within a family, so a family-mate's agreement
with the generating model is weak evidence.

This is deliberately stricter than the `SelfGradingError` guard the five
rung-3 gates carry, which requires only a different model id.

**An unknown model id is a hard error, never an assumed-distinct default.**
That direction is the whole point: defaulting an unrecognised id to "probably
a different vendor" would let a family-mate through silently, which is the
exact failure the bar exists to prevent. Adding a model means adding a row
here -- a deliberate act, in the same commit as the wiring that uses it.

The table maps an OpenRouter-style `<publisher>/<model>` id's publisher
segment to a training lab. Publisher usually IS the lab, but not always, so
this is a lookup of a fact about the world rather than a tunable: `nvidia/`
serves NVIDIA fine-tunes of Meta base models, and `z-ai/` is Zhipu. A bare id
with no `/` is resolved through the same table by exact match, so a
tier-resolved local/stub name still has to be declared.
"""

from __future__ import annotations

# Publisher segment -> training lab. Lower-case keys; lookup is case-folded.
VENDOR_BY_PUBLISHER: dict[str, str] = {
    "anthropic": "anthropic",
    "openai": "openai",
    "google": "google",
    "deepseek": "deepseek",
    "z-ai": "zhipu",
    "zhipuai": "zhipu",
    "moonshotai": "moonshot",
    "qwen": "alibaba",
    "alibaba": "alibaba",
    "mistralai": "mistral",
    "meta-llama": "meta",
    "x-ai": "xai",
    "microsoft": "microsoft",
    "cohere": "cohere",
    "ai21": "ai21",
    # NVIDIA publishes fine-tunes of other labs' base models (Nemotron over
    # Llama). Treated as its own vendor: the post-training that shapes a
    # judge's behaviour is NVIDIA's, and this table is about who shaped the
    # weights doing the judging.
    "nvidia": "nvidia",
    # The no-network test seams. Declared rather than special-cased so a
    # stub-backed panel exercises the identical guard path as a real one --
    # every one of them is its own vendor, so a stub reviewer never collides
    # with a stub generator and tests can drive both arms explicitly.
    "stub": "stub",
    "record": "record",
    "explode": "explode",
}


class VendorError(Exception):
    """Base class for vendor-resolution failures."""


class UnknownVendorError(VendorError):
    """Raised when a model id resolves to no declared training lab. A hard
    error by design (module docstring): an unrecognised id must never be
    assumed distinct from the generating model's vendor."""

    def __init__(self, model: str):
        self.model = model
        super().__init__(
            f"model {model!r} resolves to no declared training lab in "
            f"VENDOR_BY_PUBLISHER (known publishers: "
            f"{sorted(VENDOR_BY_PUBLISHER)!r}) -- add a row for it rather "
            "than letting an unknown id pass the different-vendor bar"
        )


class VendorCollisionError(VendorError):
    """Raised when a reviewer resolves to the same training lab as the model
    that generated the analysis (§9.4 property 3). Raised BEFORE any reviewer
    call is made; zero calls are made when this fires."""

    def __init__(self, *, reviewer_model: str, generating_model: str, vendor: str):
        self.reviewer_model = reviewer_model
        self.generating_model = generating_model
        self.vendor = vendor
        super().__init__(
            f"reviewer model {reviewer_model!r} and generating model "
            f"{generating_model!r} share the training lab {vendor!r} -- the "
            "panel requires a different VENDOR, not merely a different model "
            "id, because shared training priors survive within a family"
        )


def vendor_of(model: str) -> str:
    """The training lab behind `model`. Raises `UnknownVendorError` for any
    id this module does not declare."""
    if not model:
        raise UnknownVendorError(model)
    publisher = model.split("/", 1)[0] if "/" in model else model
    vendor = VENDOR_BY_PUBLISHER.get(publisher.strip().lower())
    if vendor is None:
        raise UnknownVendorError(model)
    return vendor


def guard_distinct_vendor(*, reviewer_model: str, generating_model: str) -> str:
    """Assert `reviewer_model` comes from a different training lab than
    `generating_model`, returning the reviewer's vendor. Raises
    `UnknownVendorError` for either id if undeclared, `VendorCollisionError`
    when they share a lab."""
    reviewer_vendor = vendor_of(reviewer_model)
    generating_vendor = vendor_of(generating_model)
    if reviewer_vendor == generating_vendor:
        raise VendorCollisionError(
            reviewer_model=reviewer_model,
            generating_model=generating_model,
            vendor=reviewer_vendor,
        )
    return reviewer_vendor
