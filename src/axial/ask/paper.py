"""The paper an ask ends in (issue #668, lifted here by issue #784).

PHASE-C §0 calls this "a call plus a mechanical module move", and that is all
it is: an ask produces exactly one analysis record, the question the analyst
typed is that paper's organizing question (§7.1's definition of `thesis`), and
Phase C is a consumer of records that never triggers a Phase B run (DEC-41,
§3 non-goal 1) -- the record already exists when this is called.

It lived inside `cli._ask_paper` from #668 until #784, which is why the web
client never saw an essay: `axial ask` drafted one every turn and the service
worker did not. Nothing about the composition changed on the way out; what
changed is that two callers can now reach it. The CLI keeps its own printing
and exit code, the worker keeps its own event and cost accounting, and neither
owns the composition any more.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from axial.llm import LLMError
from axial.model_json import ModelJsonError
from axial.paper.biblio import BibliographyError
from axial.paper.brief import PaperBriefContent, build_paper_brief
from axial.paper.citations import CitationError
from axial.paper.claims import PaperClaimError
from axial.paper.coverage import PaperCoverageError
from axial.paper.draft import DraftError
from axial.paper.intake import PaperIntakeError
from axial.paper.lens import LensError
from axial.paper.plan import PlanError
from axial.paper.record import PaperRunError, run_paper
from axial.paper.shape import ShapeCheckError

# The disposition PHASE-C §7.1 rejects at paper intake: a refusal carries no
# claims, so there is nothing to draft from.
_REFUSAL_DISPOSITION = "refuse"

# Every failure `axial.paper`'s five stages can raise before a record is
# persisted. Moved here from `cli._PAPER_PIPELINE_ERRORS` (issue #784) so the
# CLI and the service worker catch the same set rather than each keeping its
# own idea of what a drafting failure is; `cli` re-exports it under the old
# name. `PaperRunError` is `run_paper`'s own base class, held open for a
# whole-pipeline failure though nothing raises it yet.
PAPER_PIPELINE_ERRORS = (
    PaperIntakeError,
    LensError,
    PlanError,
    DraftError,
    ShapeCheckError,
    PaperClaimError,
    CitationError,
    PaperCoverageError,
    BibliographyError,
    PaperRunError,
    LLMError,
    ModelJsonError,
)


def paper_brief_for_turn(turn: Any):
    """The in-memory paper brief one finished ask implies: the turn's
    question as the thesis, the record it just produced as the whole
    `analysis_ids`, and no lens named so stage 1 chooses and records its own
    (§7.1).

    The thesis is the question the analyst typed, not the brief's own
    `request` -- on a follow-up turn the engine folds the previous turn's
    context into that request, and the thesis a reader is owed is the thing
    they asked.
    """
    return build_paper_brief(
        PaperBriefContent(thesis=turn.question, analysis_ids=(turn.brief.brief_id,))
    )


def draft_paper_for_turn(
    client: Any,
    turn: Any,
    *,
    analyses_dir: Path | None = None,
    papers_dir: Path | None = None,
    lenses_dir: Path | None = None,
    source_meta_dir: Path | None = None,
    vault_dir: Path | None = None,
) -> dict[str, Any] | None:
    """Run stages 1-5 over the one record `turn` just produced, returning
    the persisted §7.3 paper record -- or `None` when the ask was refused
    and there is nothing to draft.

    Every directory is optional and falls through to `run_paper`'s own
    defaults, which is what the CLI wants. A hosted worker passes all of
    them, because `run_paper`'s `PAPERS_DIR` is a bare relative
    `data/papers` that would put one principal's paper in the repo rather
    than under their own scoped directory.

    Raises any member of `PAPER_PIPELINE_ERRORS` on a drafting failure. It is
    the caller's job to decide what that means: the CLI reports it and exits
    non-zero, the service records it against a job that still completed,
    because the analysis is already persisted and already paid for.
    """
    record = turn.result.record
    if (record.get("interrogation") or {}).get("disposition") == _REFUSAL_DISPOSITION:
        return None

    return run_paper(
        client,
        paper_brief_for_turn(turn),
        analyses_dir=analyses_dir,
        lenses_dir=lenses_dir,
        source_meta_dir=source_meta_dir,
        vault_dir=vault_dir,
        papers_dir=papers_dir,
    )
