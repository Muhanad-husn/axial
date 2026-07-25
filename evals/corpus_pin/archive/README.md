# Archived corpus pins

Superseded corpus-pin manifests, retained as history per DEC-42 (`docs/DECISIONS.md`).

`resolve_pin_id` (`axial.eval.corpus_pin`) globs `evals/corpus_pin/*.json`
non-recursively, so anything under this subdirectory is invisible to it: a
pin filed here is never resolved against, never counted toward the
"exactly one live pin" invariant, and never deleted. When a corpus rebuild
retires a pin, move it here rather than deleting it or leaving it beside the
live pin (which would make resolution ambiguous).
