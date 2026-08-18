"""House style, loaded from the domain frame (issue #787 slice 05).

**The prose conventions a paper is written to are domain data.** CLAUDE.md is
explicit that the domain frame lives in `config/domains/<domain>/`, loads at
runtime, and reaches the model as context and examples, never as a gate. This
module is that rule applied to writing: it reads
`<domain-dir>/house_style.yaml`, hands the conventions to the two
prose-writing prompts (`axial.paper.draft` and `axial.paper.abstract`) as a
block of context, and stops there. Nothing checks, scores or rejects prose
against the block, and no convention exists anywhere in `src/` as a literal or
a branch -- editing the domain file is how house style changes.

**It takes a domain DIRECTORY, not a domain name** (`axial.schema.load_schema`,
PRD §4). No code path here knows which domain it is looking at; swapping
domains means pointing at a different directory. `None` resolves the
configured one -- `paths.domain_dir` from `config/pipeline.yaml`, falling back
to `axial.paths.DEFAULT_DOMAIN_DIR`, the same config-then-fallback resolution
`axial.interrogate._default_domain_dir` already uses.

**An absent file is not an error; a malformed one is.** A domain that declares
no house style loads as `None`, and both prompts are then byte-identical to
what they were before this module existed -- four slices' worth of measured
prompt behaviour sits behind that, so it is pinned in
`tests/paper/test_draft_house_style.py` against goldens composed on 5a34d45. A
file that exists but cannot be read as conventions raises
`MalformedHouseStyleError` instead, because the alternative is a domain frame
an analyst edited and a paper that silently ignored it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from axial.paths import DEFAULT_DOMAIN_DIR, DEFAULT_PIPELINE_CONFIG_PATH, _read_configured_dir
from axial.yaml_loader import SAFE_LOADER

HOUSE_STYLE_FILENAME = "house_style.yaml"

# How the block introduces itself to a model. Framing, not content: what the
# conventions ARE lives in the domain file and only there.
_PROMPT_HEADER = (
    "House style -- the conventions this domain's papers are written to. They "
    "govern how the prose reads, never what it argues, and nothing here "
    "overrides an instruction above about grounds, markers or honesty:"
)


class HouseStyleError(Exception):
    """Base class for house-style loading failures."""


class MalformedHouseStyleError(HouseStyleError):
    """Raised when `<domain-dir>/house_style.yaml` exists but cannot be read
    as a list of conventions -- invalid YAML, the wrong shape, or an entry
    that is not a non-empty string."""

    def __init__(self, path: Path, reason: str):
        self.path = path
        self.reason = reason
        super().__init__(f"house style at {path} is unusable: {reason}")


@dataclass(frozen=True)
class HouseStyle:
    """The conventions a domain declares, in the order it declares them."""

    conventions: tuple[str, ...]

    def for_prompt(self) -> str:
        """The block as a model receives it: the header, then one line per
        convention."""
        lines = "\n".join(f"- {convention}" for convention in self.conventions)
        return f"{_PROMPT_HEADER}\n{lines}"


def prompt_block(house_style: HouseStyle | None) -> str:
    """The block as it is spliced into a prompt: the conventions, then the
    blank line separating them from whatever follows.

    One function, called by both prose-writing prompts, so the drafter and
    the abstract are guaranteed the identical block rather than two renderings
    that agree today. `None` -- a domain that declares no house style --
    returns an empty string, which is what makes both prompts byte-identical
    to what they were before this existed."""
    if house_style is None:
        return ""
    return f"{house_style.for_prompt()}\n\n"


def default_domain_dir(config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH) -> Path:
    """Honour `paths.domain_dir` when the pipeline config declares it, else
    `DEFAULT_DOMAIN_DIR`."""
    return _read_configured_dir(config_path, "domain_dir", DEFAULT_DOMAIN_DIR)


def _conventions_of(path: Path, raw: Any) -> tuple[str, ...]:
    if not isinstance(raw, dict):
        raise MalformedHouseStyleError(path, f"expected a mapping, got {type(raw).__name__}")

    declared = raw.get("conventions")
    if not isinstance(declared, list) or not declared:
        raise MalformedHouseStyleError(path, f"'conventions' is {declared!r}, not a non-empty list")

    conventions = []
    for entry in declared:
        if not isinstance(entry, str) or not entry.strip():
            raise MalformedHouseStyleError(path, f"convention {entry!r} is not a non-empty string")
        conventions.append(entry.strip())
    return tuple(conventions)


def load_house_style(domain_dir: str | Path | None = None) -> HouseStyle | None:
    """The house style `domain_dir` declares, or `None` when it declares
    none.

    `None` for `domain_dir` resolves the configured domain directory. A
    missing directory or a missing `house_style.yaml` returns `None`; a file
    that exists but is unusable raises `MalformedHouseStyleError`."""
    directory = Path(domain_dir) if domain_dir is not None else default_domain_dir()
    path = directory / HOUSE_STYLE_FILENAME
    if not path.is_file():
        return None

    try:
        raw = yaml.load(path.read_text(encoding="utf-8"), Loader=SAFE_LOADER)
    except yaml.YAMLError as exc:
        raise MalformedHouseStyleError(path, f"not valid YAML: {exc}") from exc
    except OSError as exc:  # pragma: no cover - unreadable file, same disclosure
        raise MalformedHouseStyleError(path, str(exc)) from exc

    return HouseStyle(conventions=_conventions_of(path, raw))
