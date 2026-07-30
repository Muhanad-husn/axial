"""Read-only validation for issue #500 (D1): the bracket-reservation fix in
`render_packet`, measured against the live corpus, before and after, in one
run.

LLM-free, zero model calls, read-only. Never writes into `data/answers/`,
`data/names/`, or anywhere else under `data/` except its own log directory
below. It never runs `axial names gather` and never opens `data/chunks/`.

**"Before" is `main`'s own `render_packet`, not a description of it.** This
script inserts THIS WORKTREE's `src/` at the front of `sys.path` for the
"after" measurement (`gather_after`, this branch's real module), then reads
`src/axial/gather.py` OUT OF THE `main` REF via `git show` and executes that
source as a second, separately-named module (`gather_before`) -- so "before"
is the actual function `main` runs today, not a hand-written stand-in for
it, and it stays current even if `main` moves after this branch was cut.
Only `gather.py` differs between the two (verified: `git diff --stat
main...HEAD` touches only `src/axial/gather.py` under `src/`), so every
other import `gather.py` makes (`build_packets`, `load_gather_context`, and
everything from `axial.checkpoint`/`intake`/`interrogate`/`materialize`/
`merge_names`/`model_json`/`names`/`paths`/`vault`) is identical either way
-- both versions of `render_packet` are called on the exact SAME built
`MemberPacket` objects, so the comparison is over identical inputs.

**`before` and `after` no longer share one cap (founder correction,
2026-07-30).** `main` still caps at 400; this branch moved
`MEMBER_PACKET_CHARS` to 800 once the corpus showed the bracket itself is
not "short and bounded" -- median 221 characters, p90 387, max 978 -- so 400
put 11.5% of notes into the degenerate fallback before `claim` ever saw a
remainder. Each side is measured against its OWN module's own cap; nothing
here assumes they match, and the report states both.

Run it from the orchestrator's main checkout, where `data/` actually exists
(it does not exist inside a worktree):

    cd D:/axial
    uv run python .claude/worktrees/01-bracket-survives-cap/scratchpad/validate_500.py

Expected published figures to check this script's own "before" numbers
against (issue #500's own measurement, `plans/name-layer-rekey/README.md`):
6,148 notes carrying an interrogation answer, 4,241 (69.0%) of rendered
packets over the 400-char cap, 1,379 (22.4%) losing `arguing_against`
entirely, median untruncated packet 483 characters, median `claim` length
245 characters. If this script's own count disagrees, say so rather than
tuning the script to match -- the corpus may have grown since #500 was
filed, or the published 22.4% may use a different reading of "entirely"
than one of the two this script now reports (see `_label_absent` vs.
`_value_incomplete` below): the label absent outright is the coarser,
published-comparable reading; a present label whose value is only partly
cut is a real loss too, and only the stricter check catches it.
"""

from __future__ import annotations

import json
import subprocess
import sys
import types
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any, Callable

_WORKTREE_ROOT = Path(__file__).resolve().parent.parent
_WORKTREE_SRC = _WORKTREE_ROOT / "src"
sys.path.insert(0, str(_WORKTREE_SRC))

import axial.gather as gather_after  # noqa: E402
from axial.intake import SOURCE_META_DIR  # noqa: E402
from axial.interrogate import _default_answers_dir  # noqa: E402
from axial.paths import DEFAULT_PIPELINE_CONFIG_PATH  # noqa: E402

DEFAULT_LOG_DIR = Path("data/logs/2026-07-30-validate-500")


def _load_gather_module_from_git_ref(ref: str) -> types.ModuleType:
    """`src/axial/gather.py` exactly as `ref` has it on disk in git, executed
    as an isolated module under its own name -- not a reimplementation. Its
    own imports (`from axial.checkpoint import ...` etc.) resolve through
    `sys.path`, which already has this worktree's `src/` at the front; that
    is safe here because those other modules are byte-identical between
    `ref` and this branch (only `gather.py` itself differs)."""
    result = subprocess.run(
        ["git", "-C", str(_WORKTREE_ROOT), "show", f"{ref}:src/axial/gather.py"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    module_name = f"_gather_at_{ref}"
    module = types.ModuleType(module_name)
    module.__file__ = f"<git:{ref}:src/axial/gather.py>"
    sys.modules[module_name] = module
    exec(compile(result.stdout, module.__file__, "exec"), module.__dict__)
    return module


def _untruncated_length(packet: Any) -> int:
    """The packet's own field concatenation per Sec 7.18's documented format
    (author, year, claim, then the bracket), with NO cap applied. This is
    not the fix under test -- it is the shared starting point both the old
    and the new `render_packet` truncate FROM, needed here only to classify
    which packets would need any truncation at all (against EACH side's own
    cap) and to measure the corpus's own raw packet-length distribution,
    which does not depend on either cap."""
    bracket = [f"position of: {packet.position_of}", f"arguing against: {packet.arguing_against}"]
    if packet.position is not None:
        bracket.append(f"position: {packet.position}")
    return len(f"{packet.author} ({packet.year}): {packet.claim} [{'; '.join(bracket)}]")


def _bracket_length(packet: Any) -> int:
    """The bracket alone (`position_of`; `arguing_against`; `position` where
    present), no author/year/claim. This is the quantity whose distribution
    (measured median 221, p90 387, max 978) is why 400 could not deliver
    D1's promise and the cap moved to 800."""
    bracket = [f"position of: {packet.position_of}", f"arguing against: {packet.arguing_against}"]
    if packet.position is not None:
        bracket.append(f"position: {packet.position}")
    return len(f" [{'; '.join(bracket)}]")


def _is_degenerate(render_packet: Callable[[Any], str], packet: Any) -> bool:
    """Probes the REAL `render_packet` function, not a copy of its
    arithmetic: `claim_budget` never depends on `claim`'s own length, so
    forcing `claim` to empty and checking whether the function still had to
    truncate tells us whether the bracket (plus author/year) alone met or
    exceeded ITS OWN module's cap -- the one degenerate case named in issue
    #500/D1. Meaningful for either render function at its own cap: both
    build the same head/bracket strings from the same fields before doing
    anything about `claim`."""
    probe = render_packet(replace(packet, claim=""))
    return probe.endswith("\u2026")


def _label_absent(rendered: str, label: str) -> bool:
    """The published metric's own reading of "loses X entirely": the
    field's LABEL text does not appear anywhere in the render. Blind to
    whether a present label's value came through complete or half-cut --
    the coarser of the two checks, and the one comparable to the published
    22.4%."""
    return f"{label}:" not in rendered


def _value_incomplete(rendered: str, label: str, value: str) -> bool:
    """The full `"<label>: <value>"` clause is not present, verbatim --
    true whether the label itself was cut or only part of `value` survived.
    Stricter than `_label_absent`: a present label with a value chopped
    mid-word still counts as a loss here, because a half-truncated answer is
    not a field Gather can actually read. NOT the published metric's own
    definition -- report both, side by side, rather than picking one."""
    return f"{label}: {value}" not in rendered


def _share(count: int, denom: int) -> float:
    return round(100 * count / denom, 1) if denom else 0.0


def main() -> None:
    answers_dir = _default_answers_dir(DEFAULT_PIPELINE_CONFIG_PATH)
    if not answers_dir.is_dir():
        print(
            f"no answers directory at {answers_dir.resolve()} -- run this from the main "
            "checkout (D:/axial), where `data/` exists, not from a worktree",
            file=sys.stderr,
        )
        raise SystemExit(1)

    gather_before = _load_gather_module_from_git_ref("main")
    cap_before = gather_before.MEMBER_PACKET_CHARS
    cap_after = gather_after.MEMBER_PACKET_CHARS

    answers_by_chunk_id, author_year = gather_after.load_gather_context(
        answers_dir, SOURCE_META_DIR
    )
    packets = gather_after.build_packets(
        list(answers_by_chunk_id.keys()), answers_by_chunk_id, author_year
    )

    total = len(packets)
    untruncated_lengths = [_untruncated_length(p) for p in packets]
    bracket_lengths = [_bracket_length(p) for p in packets]
    claim_lengths = [len(p.claim) for p in packets]
    over_cap_before = sum(1 for length in untruncated_lengths if length > cap_before)
    over_cap_after = sum(1 for length in untruncated_lengths if length > cap_after)
    with_position_key = sum(1 for p in packets if p.position is not None)

    metric_keys = [
        "arguing_against_label_absent",
        "arguing_against_value_incomplete",
        "position_label_absent",
        "position_value_incomplete",
        "claim_truncated",
        "degenerate",
    ]
    counts: dict[str, dict[str, int]] = {
        side: dict.fromkeys(metric_keys, 0) for side in ("before", "after")
    }

    for packet in packets:
        rendered_before = gather_before.render_packet(packet)
        rendered_after = gather_after.render_packet(packet)
        assert len(rendered_before) <= cap_before, "main's own cap guarantee should never break"
        assert len(rendered_after) <= cap_after, "D1's cap guarantee must never break"

        for side, rendered in (("before", rendered_before), ("after", rendered_after)):
            if _label_absent(rendered, "arguing against"):
                counts[side]["arguing_against_label_absent"] += 1
            if _value_incomplete(rendered, "arguing against", packet.arguing_against):
                counts[side]["arguing_against_value_incomplete"] += 1
            if packet.position is not None:
                if _label_absent(rendered, "position"):
                    counts[side]["position_label_absent"] += 1
                if _value_incomplete(rendered, "position", packet.position):
                    counts[side]["position_value_incomplete"] += 1
            if packet.claim not in rendered:
                counts[side]["claim_truncated"] += 1

        if _is_degenerate(gather_before.render_packet, packet):
            counts["before"]["degenerate"] += 1
        if _is_degenerate(gather_after.render_packet, packet):
            counts["after"]["degenerate"] += 1

    def _side_report(side: str) -> dict[str, Any]:
        c = counts[side]
        return {
            "arguing_against_label_absent": c["arguing_against_label_absent"],
            "arguing_against_label_absent_share_pct": _share(
                c["arguing_against_label_absent"], total
            ),
            "arguing_against_value_incomplete": c["arguing_against_value_incomplete"],
            "arguing_against_value_incomplete_share_pct": _share(
                c["arguing_against_value_incomplete"], total
            ),
            "position_label_absent": c["position_label_absent"],
            "position_label_absent_share_of_notes_with_key_pct": _share(
                c["position_label_absent"], with_position_key
            ),
            "position_value_incomplete": c["position_value_incomplete"],
            "position_value_incomplete_share_of_notes_with_key_pct": _share(
                c["position_value_incomplete"], with_position_key
            ),
            "claim_truncated": c["claim_truncated"],
            "claim_truncated_share_pct": _share(c["claim_truncated"], total),
            "degenerate_bracket_over_cap": c["degenerate"],
            "degenerate_share_pct": _share(c["degenerate"], total),
        }

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "answers_dir": str(answers_dir.resolve()),
        "member_packet_chars_before_main": cap_before,
        "member_packet_chars_after_this_branch": cap_after,
        "notes_with_answer": total,
        "notes_over_cap_before": over_cap_before,
        "notes_over_cap_before_share_pct": _share(over_cap_before, total),
        "notes_over_cap_after": over_cap_after,
        "notes_over_cap_after_share_pct": _share(over_cap_after, total),
        "median_untruncated_packet_chars": median(untruncated_lengths) if packets else None,
        "median_bracket_chars": median(bracket_lengths) if packets else None,
        "median_claim_chars": median(claim_lengths) if packets else None,
        "notes_with_position_key": with_position_key,
        "before": _side_report("before"),
        "after": _side_report("after"),
        "published_for_reference": {
            "notes_with_answer": 6148,
            "notes_over_cap_at_400": 4241,
            "notes_over_cap_at_400_share_pct": 69.0,
            "arguing_against_lost_at_400": 1379,
            "arguing_against_lost_at_400_share_pct": 22.4,
            "median_untruncated_packet_chars": 483,
            "median_claim_chars": 245,
        },
    }

    print("issue #500 (D1) -- bracket-reservation fix, measured over the live corpus")
    print("-" * 78)
    print(f"{'notes carrying an interrogation answer':<55} {total:>8}")
    print(
        f"{'median untruncated packet length':<55} {report['median_untruncated_packet_chars']:>8}"
    )
    print(
        f"{'median bracket length (position_of+arguing_against+position)':<55} {report['median_bracket_chars']:>8}"
    )
    print(f"{'median claim length':<55} {report['median_claim_chars']:>8}")
    print(f"{'notes whose answer record carries a position key':<55} {with_position_key:>8}")
    print()
    before_header = f"before (main, cap {cap_before})"
    after_header = f"after (this branch, cap {cap_after})"
    print(f"{'':<52}{before_header:>24}{after_header:>29}")
    before_over_cap_cell = f"{over_cap_before} ({report['notes_over_cap_before_share_pct']}%)"
    after_over_cap_cell = f"{over_cap_after} ({report['notes_over_cap_after_share_pct']}%)"
    print(
        f"{'over its own cap (untruncated length)':<52}"
        f"{before_over_cap_cell:>24}{after_over_cap_cell:>29}"
    )
    for row_label, key, denom in [
        (
            "loses arguing_against -- label absent (published)",
            "arguing_against_label_absent",
            total,
        ),
        (
            "loses arguing_against -- value incomplete (stricter)",
            "arguing_against_value_incomplete",
            total,
        ),
        ("loses position -- label absent", "position_label_absent", with_position_key),
        ("loses position -- value incomplete", "position_value_incomplete", with_position_key),
        ("claim truncated", "claim_truncated", total),
        ("hits the degenerate bracket-over-cap path", "degenerate", total),
    ]:
        before_count = counts["before"][key]
        after_count = counts["after"][key]
        before_cell = f"{before_count} ({_share(before_count, denom)}%)"
        after_cell = f"{after_count} ({_share(after_count, denom)}%)"
        print(f"{row_label:<52}{before_cell:>24}{after_cell:>29}")

    print("\npublished, for reference (plans/name-layer-rekey/README.md, main):")
    for label, value in report["published_for_reference"].items():
        print(f"  {label:<45} {value}")

    DEFAULT_LOG_DIR.mkdir(parents=True, exist_ok=True)
    report_path = DEFAULT_LOG_DIR / "report.json"
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"\nwrote {report_path.resolve()}")


if __name__ == "__main__":
    main()
