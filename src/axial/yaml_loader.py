"""The YAML loader every read in `src/` goes through (issue #541).

PyYAML's `safe_load` uses its pure-Python parser, and on this corpus that
parser is most of a brief's non-model wall clock. The vault's frontmatter is
why: `chunk_text` and the whole `answers` block live INSIDE a note's
frontmatter, so the median prose note's block is ~10.8k characters, and any
whole-vault scan parses all of it. Building the cold `chunk_id` index over
the 6,148 real prose notes took 123-142s, of which reading the blocks off
disk was ~2.6s -- the rest was parsing.

`yaml.CSafeLoader` (libyaml) is a drop-in for `SafeLoader`'s semantics and
is ~14x faster. It is not guaranteed on every install -- PyYAML falls back
to a pure-Python-only build when no libyaml/C toolchain is available -- so
this resolves once, here, and every call site imports the result instead of
repeating the try/except.
"""

from __future__ import annotations

try:
    from yaml import CSafeLoader as SAFE_LOADER
except ImportError:  # pragma: no cover - only on a PyYAML built without libyaml
    from yaml import SafeLoader as SAFE_LOADER

__all__ = ["SAFE_LOADER"]
