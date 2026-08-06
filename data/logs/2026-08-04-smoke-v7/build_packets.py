"""Assemble sealed peer-review packets (PHASE-B §9.4).

A packet is the rendered analysis or paper plus the resolved text of every
chunk its claims cite, and nothing else -- no path into the repo, no model
ids, no arm labels the reviewer could use to guess which wiring produced
what. Packets are written under the session scratchpad and never into the
repository: they carry copyrighted book text (property 7, DEC-23).

    python build_packets.py <out_dir>
"""

import json
import sys
from pathlib import Path

from axial.query.reader import ChunkNotFoundError, get_chunk

ROOT = Path(__file__).resolve().parents[3]


def _chunk_ids(claims: list[dict]) -> list[str]:
    seen: list[str] = []
    for claim in claims:
        for ground in claim.get("grounds") or []:
            ref = ground.get("ref_id")
            if ref and ref not in seen:
                seen.append(ref)
    return seen


def _evidence_block(claims: list[dict]) -> str:
    lines = ["", "---", "", "# The cited evidence", ""]
    for chunk_id in _chunk_ids(claims):
        try:
            note = get_chunk(chunk_id, vault_dir=ROOT / "data" / "vault")
        except ChunkNotFoundError:
            lines += [f"## {chunk_id}", "", "(this citation does not resolve to a passage)", ""]
            continue
        lines += [f"## {chunk_id}", "", note.chunk_text.strip(), ""]
    return "\n".join(lines)


def analysis_packet(record_path: Path, markdown_path: Path) -> str:
    record = json.loads(record_path.read_text(encoding="utf-8"))
    body = markdown_path.read_text(encoding="utf-8")
    return body + _evidence_block(record.get("claims") or [])


def paper_packet(record_path: Path) -> str:
    record = json.loads(record_path.read_text(encoding="utf-8"))
    body = Path(ROOT / record["paper_markdown_path"]).read_text(encoding="utf-8")
    return body + _evidence_block(record.get("claims") or [])


def _find(sweep: Path, case: str) -> tuple[Path, Path]:
    """(record, rendered markdown) for one case's draw 0."""
    directory = sweep / "analyses" / case / "draw0"
    record = next(p for p in directory.glob("*.json") if p.stem != "gates")
    return record, record.with_suffix(".md")


def main(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []

    # 1. The head-to-head. Arm labels are deliberately opaque: a reviewer who
    #    can tell which is which is not blind (§9.4 property 1).
    for case in ("B", "C"):
        open_record, open_md = _find(ROOT / "data/runs/eval-v3", case)
        closed_record, closed_md = _find(ROOT / "data/runs/eval-v3-closed", case)
        packet = "\n\n".join(
            [
                f"# Two answers to the same question ({case})",
                "",
                "Two independent systems answered the same question against the same",
                "library. Judge them on what is in front of you.",
                "",
                "---",
                "",
                "# ANSWER ONE",
                "",
                analysis_packet(open_record, open_md),
                "",
                "---",
                "",
                "# ANSWER TWO",
                "",
                analysis_packet(closed_record, closed_md),
            ]
        )
        path = out_dir / f"head-to-head-{case}.md"
        path.write_text(packet, encoding="utf-8")
        written.append((path, "ONE=open ARM, TWO=closed ARM"))

    # 2. The two papers.
    for paper_id, name in (
        ("b02d747edc0bb416", "privilege-and-the-contracted-out-militia"),
        ("d5f983eafb05f8d6", "what-the-mandate-built"),
    ):
        path = out_dir / f"paper-{name}.md"
        path.write_text(paper_packet(ROOT / f"data/papers/{paper_id}.json"), encoding="utf-8")
        written.append((path, paper_id))

    for path, note in written:
        print(f"{path.name}\t{len(path.read_text(encoding='utf-8')):>8} chars\t{note}")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
