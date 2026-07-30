"""Inner unit tests for `axial.yaml_loader.SAFE_LOADER` (issue #541).

The contract is "same parse result, faster", so these compare the shared
loader against PyYAML's own `safe_load` on the shapes the product actually
reads -- a vault note's frontmatter block and the pipeline config -- rather
than asserting which loader class got selected. The one structural
assertion is the error type: every call site in `src/` catches
`yaml.YAMLError`, and that must still be what a malformed document raises.
"""

from __future__ import annotations

import pytest
import yaml

from axial.yaml_loader import SAFE_LOADER

# A prose note's frontmatter block, in the shape `axial.vault` writes it:
# `chunk_text` and the whole `answers` block live INSIDE the frontmatter, so
# the block carries block scalars, nested mappings, lists of mappings, nulls,
# booleans, numbers, non-ASCII text, and strings whose content includes
# colons and quotes.
_REAL_FRONTMATTER = """\
chunk_id: agamben-2005-b22edc40e0fc_10_4-chapter-one_001
section: Chapter One
source_meta:
  author: Giorgio Agamben
  title: 'State of Exception: Homo Sacer II'
  year: 2005
  pages: null
chunk_text: |
  The immediately biopolitical significance of the state of exception
  as the original structure in which law encompasses living beings.

  "Necessity has no law" -- a maxim Gratian's Decretum reports; cf. naïve
  readings that treat it as a mere adage.
polities_touched:
  - Syria
  - United States
artifact_refs: []
answers:
  claim: The state of exception is a zone of indistinction.
  move: refutes
  position_of: the author
  position: null
  arguing_against:
    - Carl Schmitt
    - 'Rossiter, C. (1948)'
  names:
    - name: Carl Schmitt
      kind: person
    - name: Weimar Republic
      kind: polity
  citations: []
  about: sovereignty
  concedes: null
  assumes:
    - that law and life are separable
  mechanism: >
    Law suspends itself, and in suspending itself
    applies to what it excludes.
  evidence: true
  comparison: no
"""

_PIPELINE_CONFIG_SHAPE = """\
paths:
  vault_dir: data/vault
  names_dir: data/names
llm:
  provider: openrouter
  by_pass:
    interrogate:
      model: some/model
      temperature: 0.0
      max_tokens: 4096
smoke:
  max_usd_per_brief: null
  max_seconds_per_brief: 180
"""


@pytest.mark.parametrize(
    "document", [_REAL_FRONTMATTER, _PIPELINE_CONFIG_SHAPE], ids=["frontmatter", "pipeline_config"]
)
def test_the_shared_loader_parses_identically_to_pyyaml_safe_load(document: str):
    assert yaml.load(document, Loader=SAFE_LOADER) == yaml.safe_load(document)


def test_yaml_1_1_scalar_resolution_is_unchanged():
    """The implicit-resolver corner the two loaders would be most likely to
    disagree on: YAML 1.1 reads bare `no`/`yes`/`on` as booleans and
    sexagesimals like `12:30` as integers, and a note's `answers` block is
    free-text enough to hit both. A divergence here would silently change a
    parsed answer's TYPE."""
    document = "a: no\nb: yes\nc: on\nd: 12:30\ne: 0o17\nf: ~\ng: .inf\n"
    assert yaml.load(document, Loader=SAFE_LOADER) == yaml.safe_load(document)


def test_the_shared_loader_raises_yamlerror_on_a_malformed_document():
    """Every reader in `src/` that tolerates a bad note catches
    `yaml.YAMLError` specifically (`axial.query.reader._read_id_only`,
    `_read_frontmatter`, `axial.query.names._read_name_page_head`), so the
    swapped loader must keep raising that and not some C-level exception
    those handlers would miss."""
    with pytest.raises(yaml.YAMLError):
        yaml.load("key: [unclosed\n", Loader=SAFE_LOADER)


def test_the_shared_loader_refuses_an_arbitrary_python_tag():
    """`safe_load`'s actual safety property: an unknown tag is refused
    rather than constructed. The swap must not widen what the product will
    deserialize from a note or a config file."""
    with pytest.raises(yaml.YAMLError):
        yaml.load("!!python/object/apply:os.system ['echo']", Loader=SAFE_LOADER)
