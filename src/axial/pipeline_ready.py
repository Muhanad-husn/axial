"""Pipeline-ready canary gate (issue #121; postmortem
`docs/postmortem/gold-run-2026-07/canary-set.md`, "The 'pipeline ready'
bar").

`axial pipeline-ready --manifest <path>` loads a TOML manifest of canaries
(`[[canary]]` entries, each carrying `source_id`, `source_path`,
`time_envelope_sec`, `quarantine_budget`), ingests every one end-to-end via
the existing `axial.vault.run_vault_write` in a single attempt, and
evaluates it against the first three of the postmortem's four "pipeline
ready" criteria (the fourth, a green unit/acceptance suite, is out of this
command's scope -- it is checked separately, by CI):

  1. Single-attempt completion: the source ingests without a fatal abort.
  2. Zero source-fatal chunk errors, and the quarantined-chunk fraction
     (post-#120: `content_filter`/`malformed_json` quarantines recorded to
     the tag checkpoint) stays STRICTLY UNDER the canary's own
     `quarantine_budget`.
  3. Bounded wall clock: the recorded ingest duration stays within the
     canary's own `time_envelope_sec`.

Quarantine bridge (module docstring, issue #121 dispatch): `run_vault_write`
discards `run_tag`'s own `quarantine_count`, and `axial.ingest`'s results TSV
has no quarantine column. Rather than thread a new return value through
`run_vault_write` (touching an established, multi-caller signature), this
module reads the tag-pass checkpoint (`axial.tag.tags_checkpoint_path`)
directly after each canary's ingest attempt: every chunk `run_tag` processes
-- ordinary or quarantined -- is checkpointed as exactly one JSONL record
(module docstring of `axial.tag`), so the checkpoint's own record count is
the source's total chunk count, and the subset carrying a `quarantine_reason`
is the quarantined count. This is the smaller, additive change: `vault.py`
and `ingest.py` are untouched.

Each canary's own `source_id` is always recomputed fresh from its
`source_path` (`axial.envelope.compute_source_id`), mirroring
`run_vault_write`'s own "never trust a passed-in identity" convention --
the manifest's own `source_id` field is a display label, never consumed for
lookups.
"""

from __future__ import annotations

import time
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from axial.envelope import compute_source_id
from axial.llm import DEFAULT_PIPELINE_CONFIG_PATH, LLMClient
from axial.tag import TagError, _default_tags_dir, load_tag_checkpoint, tags_checkpoint_path
from axial.vault import VaultError, run_vault_write

PASS_VERDICT = "PASS"
FAIL_VERDICT = "FAIL"

# Column order for the printed table (module docstring, seam decision 3 of
# the locked outer test): `source_id` and `verdict` are the two columns the
# outer test parses by name; the rest are diagnostic detail free to change.
TABLE_COLUMNS = (
    "source_id",
    "verdict",
    "completed",
    "quarantine_fraction",
    "quarantine_budget",
    "duration_sec",
    "time_envelope_sec",
    "reason",
)


class PipelineReadyError(Exception):
    """Base class for fatal pipeline-ready errors -- ones that stop the
    whole run (an unreadable/malformed manifest), as opposed to a single
    canary's own FAIL verdict, which is recorded as a table row and never
    raises."""


class ManifestError(PipelineReadyError):
    """Raised when the manifest file cannot be read or does not carry the
    expected `[[canary]]` shape."""

    def __init__(self, path: Path, cause: Exception | str):
        self.path = path
        self.cause = cause
        super().__init__(f"cannot read manifest {path}: {cause}")


@dataclass
class Canary:
    """One `[[canary]]` manifest entry (module docstring): the three
    founder-ratified fields (`source_id`, `time_envelope_sec`,
    `quarantine_budget`) plus `source_path`, the on-disk location this
    command resolves and ingests."""

    source_id: str
    source_path: Path
    time_envelope_sec: float
    quarantine_budget: float


@dataclass
class CanaryResult:
    """The evaluated outcome of one canary's single-attempt ingest, against
    the three criteria this command checks (module docstring)."""

    canary: Canary
    source_id: str
    verdict: str
    completed: bool
    quarantine_count: int
    total_chunks: int
    duration_sec: float
    reasons: list[str]

    @property
    def quarantine_fraction(self) -> float:
        if self.total_chunks == 0:
            return 0.0
        return self.quarantine_count / self.total_chunks


def load_manifest(manifest_path: str | Path) -> list[Canary]:
    """Load `[[canary]]` entries from a TOML manifest (module docstring).
    Raises `ManifestError` if the file is missing, is not valid TOML, carries
    a `canary` value that is not an array of tables (e.g. a single `[canary]`
    table instead of `[[canary]]`), or an entry is missing a required field
    or carries a wrong-typed value (e.g. `time_envelope_sec = "nope"`) --
    never a bare traceback (reviewer finding 2, issue #121)."""
    path = Path(manifest_path)
    if not path.is_file():
        raise ManifestError(path, "file not found")

    try:
        with path.open("rb") as handle:
            document = tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise ManifestError(path, exc) from exc

    entries = document.get("canary", [])
    if not isinstance(entries, list):
        raise ManifestError(
            path,
            "expected `canary` to be an array of tables (`[[canary]]`), got "
            f"{type(entries).__name__}: {entries!r} -- did you write a single "
            "`[canary]` table instead?",
        )

    canaries: list[Canary] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ManifestError(path, f"expected each canary entry to be a table, got {entry!r}")
        try:
            canaries.append(
                Canary(
                    source_id=str(entry["source_id"]),
                    source_path=Path(entry["source_path"]),
                    time_envelope_sec=float(entry["time_envelope_sec"]),
                    quarantine_budget=float(entry["quarantine_budget"]),
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ManifestError(path, f"invalid canary entry ({exc}): {entry!r}") from exc

    return canaries


def _count_chunks(tags_dir: Path, source_id: str) -> tuple[int, int]:
    """Total chunk count and quarantined-chunk count for `source_id`, read
    straight from its tag-pass checkpoint (module docstring: the quarantine
    bridge). `(0, 0)` when no checkpoint exists yet (e.g. the ingest aborted
    before tagging a single chunk)."""
    checkpoint_path = tags_checkpoint_path(source_id, tags_dir)
    records = load_tag_checkpoint(checkpoint_path)
    total = len(records)
    quarantined = sum(1 for record in records if record.get("quarantine_reason") is not None)
    return total, quarantined


def evaluate_canary(
    canary: Canary,
    client: LLMClient | None = None,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
) -> CanaryResult:
    """Ingest one canary end-to-end (a single `run_vault_write` attempt) and
    evaluate it against the three criteria this command checks (module
    docstring)."""
    source_id = compute_source_id(canary.source_path)
    tags_dir = _default_tags_dir(config_path)

    reasons: list[str] = []
    completed = True

    start = time.monotonic()
    try:
        run_vault_write(
            canary.source_path,
            client=client,
            config_path=config_path,
            tags_dir=tags_dir,
        )
    except VaultError as exc:
        completed = False
        reasons.append(f"source-fatal error (no single-attempt completion): {exc}")
    duration_sec = time.monotonic() - start

    # A corrupt/unreadable tag checkpoint (e.g. a torn tail from a hard kill
    # mid-write -- the exact incident that motivated this gate, issue #121
    # reviewer finding 1) must fail THIS canary's row, not abort the whole
    # gate run: the quarantine fraction can't be verified, so this canary
    # fails safe rather than crashing with a bare traceback.
    try:
        total_chunks, quarantine_count = _count_chunks(tags_dir, source_id)
    except TagError as exc:
        total_chunks, quarantine_count = 0, 0
        reasons.append(
            f"corrupt or unreadable tag checkpoint (cannot verify quarantine budget): {exc}"
        )

    result = CanaryResult(
        canary=canary,
        source_id=source_id,
        verdict=PASS_VERDICT,
        completed=completed,
        quarantine_count=quarantine_count,
        total_chunks=total_chunks,
        duration_sec=duration_sec,
        reasons=reasons,
    )

    if result.quarantine_fraction >= canary.quarantine_budget:
        reasons.append(
            f"quarantined fraction {result.quarantine_fraction:.4f} "
            f">= budget {canary.quarantine_budget:.4f}"
        )

    if duration_sec > canary.time_envelope_sec:
        reasons.append(f"duration {duration_sec:.3f}s > time envelope {canary.time_envelope_sec}s")

    if reasons:
        result.verdict = FAIL_VERDICT

    return result


def render_table(results: list[CanaryResult]) -> str:
    """Render the per-canary PASS/FAIL table: a tab-separated header row
    (module docstring, seam decision 3 of the locked outer test) followed by
    one tab-separated data row per canary."""
    lines = ["\t".join(TABLE_COLUMNS)]
    for result in results:
        row: dict[str, Any] = {
            "source_id": result.source_id,
            "verdict": result.verdict,
            "completed": str(result.completed),
            "quarantine_fraction": f"{result.quarantine_fraction:.4f}",
            "quarantine_budget": f"{result.canary.quarantine_budget:.4f}",
            "duration_sec": f"{result.duration_sec:.3f}",
            "time_envelope_sec": str(result.canary.time_envelope_sec),
            "reason": "; ".join(result.reasons) if result.reasons else "-",
        }
        lines.append("\t".join(row[column] for column in TABLE_COLUMNS))
    return "\n".join(lines)


def _unexpected_failure_result(canary: Canary, exc: Exception) -> CanaryResult:
    """Build a FAIL row for a canary whose evaluation raised something
    `evaluate_canary`'s own try/except blocks don't cover (e.g. a missing
    source file). Reviewer finding 1, issue #121: one canary's unexpected
    crash must never prevent every other canary in the manifest from being
    evaluated and reported -- the gate must degrade to a FAIL row, never a
    bare traceback that drops the whole run's table."""
    try:
        source_id = compute_source_id(canary.source_path)
    except Exception:
        # Even `compute_source_id` itself can fail here (e.g. the source file
        # is missing) -- fall back to the manifest's own declared source_id
        # (a display label, module docstring) so this canary still gets a
        # row in the table instead of being silently dropped.
        source_id = canary.source_id

    return CanaryResult(
        canary=canary,
        source_id=source_id,
        verdict=FAIL_VERDICT,
        completed=False,
        quarantine_count=0,
        total_chunks=0,
        duration_sec=0.0,
        reasons=[f"unexpected error evaluating canary: {exc}"],
    )


def run_pipeline_ready(
    manifest_path: str | Path,
    client: LLMClient | None = None,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
) -> tuple[str, int]:
    """Load the manifest, ingest and evaluate every canary in it, and return
    `(table_text, exit_code)`: exit code 0 iff every canary's verdict is
    PASS, non-zero if any FAIL (module docstring). Each canary's evaluation
    is isolated (reviewer finding 1, issue #121): an unexpected exception
    evaluating one canary is recorded as that canary's own FAIL row, never
    allowed to abort evaluation of the rest or crash the whole gate run
    without printing a table at all -- the same "unattended, no operator
    intervention" bar this command itself checks for.
    """
    canaries = load_manifest(manifest_path)

    results: list[CanaryResult] = []
    for canary in canaries:
        try:
            results.append(evaluate_canary(canary, client=client, config_path=config_path))
        except Exception as exc:
            results.append(_unexpected_failure_result(canary, exc))

    table_text = render_table(results)
    exit_code = 0 if all(result.verdict == PASS_VERDICT for result in results) else 1
    return table_text, exit_code
