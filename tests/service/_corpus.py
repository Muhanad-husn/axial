"""A tiny, complete operator corpus root, for the snapshot tests (issue
#684).

Every artifact an `axial ask` run actually reads is present, one file each
-- see the read-side inventory on issue #684. The content is nonsense on
purpose: these tests are about which bytes end up inside a published
snapshot and which snapshot a worker reads, never about what the engine
concludes from them.
"""

from __future__ import annotations

import json
from pathlib import Path

PIN_NAME = "sim-test-v1"

SOURCE_ID = "alpha-0123456789ab"
CHUNK_ID = f"{SOURCE_ID}_1_intro_001"
CANONICAL = "Hafez al-Assad"

PIPELINE_YAML = """\
paths:
  envelopes_dir: data/envelopes
  vault_dir: data/vault
  names_dir: data/names
  map_dir: data/map
  sources_dir: data/sources

synthesis:
  evidence_char_budget: 20000
"""


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def build_corpus_root(
    root: Path, *, passage: str = "the first passage", pin: str = PIN_NAME
) -> Path:
    """Write a complete operator corpus root under `root` and return it.

    `passage` is the prose note's body and `pin` its corpus-pin name -- the
    two things a test varies between the corpus that v1 was published from
    and the corpus that v2 is published from, so a run can be told apart by
    what it read.
    """
    _write(root / "config" / "pipeline.yaml", PIPELINE_YAML)
    _write(root / "config" / "lenses" / "plain.md", "# plain\n\nSay what the sources say.\n")
    _write(
        root / "config" / "domains" / "syria" / "frame.md",
        "# frame\n\nThe domain frame reaches the model as context.\n",
    )

    vault = root / "data" / "vault"
    _write(
        vault / "prose" / f"{CHUNK_ID}.md",
        f"---\nchunk_id: {CHUNK_ID}\nsource_id: {SOURCE_ID}\n---\n\n{passage}\n",
    )
    _write(
        vault / "names" / f"{CANONICAL}.md",
        f"---\nname: {CANONICAL}\nkind: person\nmember_count: 1\n---\n\n"
        f"- [[{CHUNK_ID}]] -- Author (1979): {passage}\n",
    )
    _write(
        vault / "names.jsonl",
        json.dumps(
            {
                "name": CANONICAL,
                "filename": f"{CANONICAL}.md",
                "kind": "person",
                "member_count": 1,
                "source_count": 1,
            }
        )
        + "\n",
    )
    _write(vault / "artifacts" / f"{SOURCE_ID}_art_1.md", "---\nartifact_id: x\n---\n\ntable\n")
    # Not a real database -- nothing in these tests opens it. It is here
    # because a snapshot that omitted `notes.db` would not be a corpus.
    (vault / "notes.db").write_bytes(b"SQLite format 3\x00")

    names = root / "data" / "names"
    _write(names / "index.json", json.dumps({"names": [{"canonical": CANONICAL}]}))
    _write(names / "alias_map.json", json.dumps({"version": 1, "aliases": {}}))
    _write(names / "disagreements.jsonl", "")
    _write(names / "similarity_manifest.json", json.dumps({"model_name": "test-encoder"}))
    _write(names / "embeddings.lance" / "data.lance", "vectors\n")

    _write(
        root / "data" / "envelopes" / f"{SOURCE_ID}.json",
        json.dumps({"source_id": SOURCE_ID, "title": "Alpha", "author": "Author"}),
    )
    # The raw book. Deliberately NOT copied into a snapshot: it is the one
    # thing a hosted worker must never need (issue #684's read-side comment).
    _write(root / "data" / "sources" / "alpha.pdf", "raw book bytes\n")

    # Exactly one pin manifest, always: `resolve_pin_id` refuses an
    # ambiguous corpus, and rebuilding this root with a new pin is how a
    # test models the operator rebuilding the corpus.
    pin_dir = root / "evals" / "corpus_pin"
    if pin_dir.is_dir():
        for stale in pin_dir.glob("*.json"):
            stale.unlink()
    _write(
        pin_dir / f"{pin}.json",
        json.dumps(
            {
                "sources": [{"source_id": SOURCE_ID, "content_hash": "deadbeef"}],
                "ingest_code_sha": "0" * 40,
                "vault_snapshot_hash": "1" * 64,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )
    return root


def write_map(root: Path, map_pin: str) -> None:
    """The built argument map for `map_pin`, under `root`'s map dir."""
    outdir = root / "data" / "map" / map_pin
    _write(
        outdir / "positions.jsonl", json.dumps({"position_id": "p1", "sources": [SOURCE_ID]}) + "\n"
    )
    _write(outdir / "map.json", json.dumps({"pin": map_pin}))
