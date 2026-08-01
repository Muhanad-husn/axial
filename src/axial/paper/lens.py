"""Lens resolution for the paper (specs/PHASE-C.md §7.1, §0).

**The lens is the register the argument is made in.** It is the difference
between a paper and a list of true sentences, which is why §7.1 gives a paper
brief its own rather than letting it inherit whatever its source records
happened to be read through.

**This reads the lens file's `description`, not just its filename.** Phase B's
`resolve_lens` returns a stem and its prompt interpolates `Lens: "<stem>"`;
nothing in `src/` ever opens a lens file, so the `description` that defines
what the lens actually does is unread data. That is Phase B's to fix and is
recorded at §0. Phase C does not inherit the defect: a lens reaches a model
here as its name AND the sentence that says what reading through it means.

**Not imported from `axial.analyze.synthesis`, deliberately.** That module
holds the same resolution logic, and importing it executes
`axial/analyze/__init__.py`, which pulls `axial.brief.interrogate` and
`axial.retrieve.loop` -- the interrogation pre-pass and the retrieval loop --
into Phase C's import graph. §3 non-goal 1 ("Phase C never runs Phase B") is a
structural guarantee, and a directory glob is a cheap price for keeping it
true by construction rather than by promise. Measured, not assumed: the import
was tried, and those six modules are what it drags in.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from axial.yaml_loader import SAFE_LOADER

# Same directory Phase B reads (PHASE-B §7.1). The vocabulary is data, and it
# is shared: a lens means the same thing at both layers.
DEFAULT_LENSES_DIR = Path("config/lenses")


class LensError(Exception):
    """Base class for lens resolution failures."""


class UnknownLensError(LensError):
    """Raised when a paper brief names a lens that does not exist."""

    def __init__(self, lens_name: str, lenses_dir: Path, available: list[str]):
        self.lens_name = lens_name
        self.lenses_dir = lenses_dir
        self.available = list(available)
        super().__init__(
            f"unknown lens {lens_name!r}: no file found under {lenses_dir}; "
            f"available: {sorted(available)!r}"
        )


class NoLensesAvailableError(LensError):
    """Raised when a paper brief omits `lens` and there is none to select."""

    def __init__(self, lenses_dir: Path):
        self.lenses_dir = lenses_dir
        super().__init__(f"no lens available to auto-select under {lenses_dir}")


@dataclass(frozen=True)
class Lens:
    """A resolved lens: what it is called, and what reading through it means.

    `description` is `None` when the file carries none. That is rendered as a
    stated absence rather than silently dropped, so a lens whose content was
    never written does not quietly become a bare name again -- which is the
    exact failure this module exists not to repeat."""

    name: str
    description: str | None

    def for_prompt(self) -> str:
        """The lens as a model should receive it: the name, and the sentence
        that defines it."""
        if not self.description:
            return f'"{self.name}" (no description is recorded for this lens)'
        return f'"{self.name}" - {self.description.strip()}'


def available_lenses(lenses_dir: Path | None = None) -> list[str]:
    """Every lens name available, sorted. The deterministic ordering
    `resolve_lens` selects from when a brief names none."""
    lenses_dir = Path(lenses_dir) if lenses_dir is not None else DEFAULT_LENSES_DIR
    if not lenses_dir.is_dir():
        return []
    return sorted(path.stem for path in lenses_dir.glob("*.yaml"))


def resolve_lens(lens_name: str | None, *, lenses_dir: Path | None = None) -> Lens:
    """Resolve the lens this paper applies (§7.1).

    A named lens must exist; an absent one selects the alphabetically-first
    available, so the same corpus of lenses always auto-selects the same one
    and the choice is recorded on the record rather than left null."""
    lenses_dir = Path(lenses_dir) if lenses_dir is not None else DEFAULT_LENSES_DIR
    available = available_lenses(lenses_dir)

    if lens_name is not None:
        if lens_name not in available:
            raise UnknownLensError(lens_name, lenses_dir, available)
        resolved = lens_name
    else:
        if not available:
            raise NoLensesAvailableError(lenses_dir)
        resolved = available[0]

    return Lens(name=resolved, description=_description_of(resolved, lenses_dir))


def _description_of(lens_name: str, lenses_dir: Path) -> str | None:
    """The lens file's `description`, or `None` when unreadable or absent.

    An unreadable lens file is not an error: the lens still resolves by name,
    and `for_prompt` says plainly that no description is recorded. Failing the
    whole paper because a data file is malformed would be a worse trade than
    disclosing the gap."""
    path = lenses_dir / f"{lens_name}.yaml"
    try:
        raw = yaml.load(path.read_text(encoding="utf-8"), Loader=SAFE_LOADER)
    except (OSError, yaml.YAMLError):
        return None
    if not isinstance(raw, dict):
        return None
    description = raw.get("description")
    return description if isinstance(description, str) and description.strip() else None
