"""`axial eval coherence` argparse wiring (specs/PHASE-C.md §8 P0-12, issue
#611).

Ships unrun (see PR body): a coherence sample needs more than one paper per
tier and per model combination to stratify, and the corpus does not yet
hold enough papers to build one. This test pins the CLI surface -- argument
parsing and dispatch -- without spending a call or touching data/papers/.
The runtime behavior itself (stratification validation, the panel run) is
unit-tested directly in `src/axial/panel/test_sample.py` and
`test_coherence_eval.py`.
"""

from __future__ import annotations

import pytest

from axial.cli import build_parser


def test_bare_eval_keeps_its_original_kappa_behavior():
    """Adding subcommands to the pre-existing `eval` command must not
    disturb its original no-subcommand invocation (the gold-set kappa
    score)."""
    args = build_parser().parse_args(["eval"])
    assert args.command == "eval"
    assert args.eval_command is None


def test_eval_coherence_parses_its_arguments():
    args = build_parser().parse_args(
        [
            "eval",
            "coherence",
            "--sample",
            "evals/samples/x.json",
            "--reviewers",
            "5",
            "--out",
            "o.json",
        ]
    )
    assert args.command == "eval"
    assert args.eval_command == "coherence"
    assert args.sample == "evals/samples/x.json"
    assert args.reviewers == 5
    assert args.out == "o.json"


def test_eval_coherence_reviewers_and_out_default():
    args = build_parser().parse_args(["eval", "coherence", "--sample", "evals/samples/x.json"])
    assert args.reviewers == 3
    assert args.out is None


def test_eval_coherence_requires_a_sample_argument():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["eval", "coherence"])
