"""Stage-5 corpus-pin staleness check (DEC-35, issue #296): the small,
reusable seam every stage-5 artifact (this slice's embedding manifest,
5b's cluster assignments, 5c/5d's trained classifiers) uses to tell "this
still matches production" from "the corpus moved, re-derive" -- without
inventing a second, parallel pinning mechanism.

Extends `axial.eval.corpus_pin` (#248), which already computes exactly what
stage 5 needs to key artifacts on -- `vault_snapshot_hash` (a sha256 over
every `(chunk_id, tags)` pair, so it moves whenever corpus size/composition/
tag distribution moves) and the pin's own name (`resolve_pin_id`) -- rather
than building a competing one.

Kept in its own module, importing only `axial.eval.corpus_pin` (itself
dependency-light: `pathlib`/`hashlib`/`json`/`yaml`/`subprocess`, no model or
embedding client on any path), mirroring `axial.paths`'s own precedent of
splitting a config-lookup helper out of a heavier sibling module
(`axial.vault`) so a caller that only wants the staleness check -- a later
5b/5c artifact, say -- never pays for `axial.distill.embed`'s
`sentence-transformers`/`lancedb` import chain just to ask "is this stale?"
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TypedDict

from axial.eval import corpus_pin


class CorpusPinSnapshot(TypedDict):
    corpus_pin_id: str
    vault_snapshot_hash: str


def resolve_current_pin(evals_dir: Path | None = None) -> CorpusPinSnapshot:
    """The currently resolvable corpus pin's id and `vault_snapshot_hash`
    (`axial.eval.corpus_pin.resolve_pin_id` -- the sole manifest under
    `evals_dir`, default `evals/corpus_pin/`). Propagates
    `corpus_pin.MissingCorpusPinError`/`AmbiguousCorpusPinError` unchanged:
    a caller with no pin to resolve has nothing to record or compare
    against, which is a misconfigured install, never a silently-skippable
    case."""
    if evals_dir is None:
        evals_dir = corpus_pin.EVALS_DIR
    evals_dir = Path(evals_dir)
    pin_id = corpus_pin.resolve_pin_id(evals_dir)
    manifest = json.loads((evals_dir / f"{pin_id}.json").read_text(encoding="utf-8"))
    return {"corpus_pin_id": pin_id, "vault_snapshot_hash": manifest["vault_snapshot_hash"]}


def check_staleness(
    recorded_pin_id: str,
    recorded_vault_snapshot_hash: str,
    evals_dir: Path | None = None,
) -> bool:
    """True when a stage-5 artifact's own recorded `(corpus_pin_id,
    vault_snapshot_hash)` still match the currently resolvable corpus pin --
    the artifact is NOT stale and needs no re-derivation. False means the
    corpus has moved (a different pin was written, and/or the vault's tagged
    content changed under the same pin name) and the artifact should be
    re-derived against the current corpus.

    Propagates `corpus_pin.MissingCorpusPinError`/`AmbiguousCorpusPinError`
    the same way `resolve_current_pin` does -- there is no "unknown, assume
    fresh" fallback."""
    current = resolve_current_pin(evals_dir)
    return (
        current["corpus_pin_id"] == recorded_pin_id
        and current["vault_snapshot_hash"] == recorded_vault_snapshot_hash
    )
