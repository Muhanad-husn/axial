"""Inner unit tests for the embedding-based chunk stage (issue #151, PRD §5
stage 4 / §7.7 / §8 P0-4). Complements tests/test_chunk.py (the LOCKED outer
acceptance test) with the individual-mechanism unit tests it never exercises
directly: sentence segmentation, the consecutive-distance series + gradient
breakpoint detector, the two-sided band guard (MAX split / MIN merge), the
non-alpha-only garbage-section guard, and `run_chunk_embedding` itself
end-to-end against a monkeypatched tree (never touching the real
data/trees/ tree cache -- see src/axial/conftest.py for why in-process tests
must avoid the real cwd-relative data/ directories).
"""

from __future__ import annotations

import json
import sys

import pytest

import axial.chunk as chunk_mod
from axial.chunk import (
    CHUNK_MAX,
    CHUNK_MIN,
    EMBEDDER_ENV_VAR,
    HashingEmbedder,
    MissingSourceError,
    MissingTreeError,
    _chunk_section_text,
    _enforce_min,
    _garbage_section_skip_reason,
    _group_char_len,
    _split_group_to_max,
    consecutive_distances,
    get_embedder,
    gradient_breakpoints,
    run_chunk_embedding,
    segment_sentences,
)

# --- sentence segmentation ---------------------------------------------------


def test_segment_sentences_splits_on_terminal_punctuation():
    text = "First sentence. Second sentence! Third sentence?"
    assert segment_sentences(text) == [
        "First sentence.",
        "Second sentence!",
        "Third sentence?",
    ]


def test_segment_sentences_empty_text_returns_empty_list():
    assert segment_sentences("") == []
    assert segment_sentences("   ") == []


def test_segment_sentences_collapses_internal_whitespace_runs():
    text = "One.\n\nTwo.   Three."
    assert segment_sentences(text) == ["One.", "Two.", "Three."]


# --- consecutive-distance series + gradient breakpoints ---------------------

_TOPIC_A = [
    "The provincial government administration serves the local community government today.",
    "The provincial administration government works with the local community administration today.",
    "Provincial government local administration community services continue steadily today.",
]
_TOPIC_B = [
    "Quantum photon entanglement physics experiments quantum photon results today.",
    "Quantum entanglement photon physics quantum experiments continue quantum today.",
    "Photon quantum physics entanglement experiments quantum results quantum today.",
]


def test_consecutive_distances_returns_one_fewer_than_input_vectors():
    embedder = HashingEmbedder()
    vectors = embedder.encode(_TOPIC_A)
    distances = consecutive_distances(vectors)
    assert len(distances) == len(vectors) - 1
    assert all(0.0 <= d <= 2.0 for d in distances)


def test_consecutive_distances_is_zero_for_identical_sentences():
    embedder = HashingEmbedder()
    vectors = embedder.encode(["The same sentence.", "The same sentence."])
    distances = consecutive_distances(vectors)
    assert distances[0] == pytest.approx(0.0, abs=1e-9)


def test_gradient_breakpoints_fires_at_a_sharp_topic_shift():
    """Sentences drawn from one coherent topic, then an abrupt shift to an
    unrelated topic, then back: the distance series should spike sharply at
    the topic boundary, and gradient thresholding should flag it."""
    embedder = HashingEmbedder()
    sentences = _TOPIC_A + _TOPIC_B
    vectors = embedder.encode(sentences)
    distances = consecutive_distances(vectors)

    breakpoints = gradient_breakpoints(distances)

    # The sharpest transition is between the last TOPIC_A sentence (index 2)
    # and the first TOPIC_B sentence (index 3) -- distances index 2.
    assert breakpoints, f"expected at least one breakpoint, got none (distances={distances})"
    assert 2 in breakpoints, (
        f"expected the topic-shift gap (index 2) to be flagged, got {breakpoints}"
    )


def test_gradient_breakpoints_does_not_fire_on_uniform_shallow_noise():
    """A distance series with no sharp local spike (near-uniform small
    fluctuations) should not produce a breakpoint -- gradient thresholding
    reacts to a spike relative to the series' own variance, not to any
    nonzero distance."""
    distances = [0.10, 0.105, 0.11, 0.104, 0.109, 0.101]
    assert gradient_breakpoints(distances) == []


def test_gradient_breakpoints_needs_at_least_two_distances():
    assert gradient_breakpoints([]) == []
    assert gradient_breakpoints([0.5]) == []


# --- band guard: MAX side ----------------------------------------------------


def test_split_group_to_max_returns_unchanged_group_within_band():
    embedder = HashingEmbedder()
    group = ["Short sentence one.", "Short sentence two."]
    result = _split_group_to_max(group, embedder, chunk_max=1000)
    assert result == [group]


def test_split_group_to_max_splits_an_oversized_group_and_respects_the_cap():
    embedder = HashingEmbedder()
    sentences = [f"Sentence number {i} about the survey findings today." for i in range(40)]
    chunk_max = 200

    result = _split_group_to_max(sentences, embedder, chunk_max)

    assert len(result) >= 2, "expected the oversized group to be split into multiple pieces"
    for piece in result:
        assert _group_char_len(piece) <= chunk_max
    # No sentence lost or duplicated across the split.
    assert [s for piece in result for s in piece] == sentences


def test_split_group_to_max_hard_splits_a_single_oversized_sentence():
    """No internal sentence boundary exists inside a single "sentence" --
    the fallback raw character split still guarantees the cap."""
    embedder = HashingEmbedder()
    huge_sentence = "a" * 500
    result = _split_group_to_max([huge_sentence], embedder, chunk_max=200)

    assert len(result) >= 2
    for piece in result:
        assert _group_char_len(piece) <= 200
    assert "".join(piece[0] for piece in result) == huge_sentence


# --- band guard: MIN side ----------------------------------------------------


def test_enforce_min_merges_small_adjacent_groups_forward():
    """A below-min group ("a") absorbs the next group ("b") whether or not
    "b" is itself below min -- it merges forward until the accumulated
    group reaches `chunk_min`, preventing small-chunk proliferation. An
    already-large preceding group ("a" here is 150 chars, already >= min)
    is left untouched and never swallows a later small group."""
    groups = [["a" * 150], ["b" * 10], ["c" * 10]]
    result = _enforce_min(groups, chunk_min=100)

    assert result == [["a" * 150], [("b" * 10), ("c" * 10)]]


def test_enforce_min_leaves_a_trailing_short_group_below_min():
    """The documented exception: a section's LAST chunk may remain below
    `min` (nothing left to merge it forward into)."""
    groups = [["c" * 300], ["a" * 10]]
    result = _enforce_min(groups, chunk_min=100)

    assert len(result) == 2
    assert _group_char_len(result[-1]) < 100


def test_enforce_min_a_whole_short_section_stays_below_min():
    groups = [["short."]]
    result = _enforce_min(groups, chunk_min=1000)
    assert result == groups


# --- full section chunking: gradient + band guard together ------------------


def test_chunk_section_text_never_exceeds_chunk_max():
    embedder = HashingEmbedder()
    sentences = [f"Sentence number {i} describing local survey conditions." for i in range(60)]
    text = " ".join(sentences)

    chunks = _chunk_section_text(text, embedder, chunk_min=50, chunk_max=300)

    assert len(chunks) >= 2
    assert all(len(chunk) <= 300 for chunk in chunks)


def test_chunk_section_text_min_side_exceptions_hold():
    embedder = HashingEmbedder()
    sentences = [f"Sentence number {i} describing local survey conditions." for i in range(30)]
    text = " ".join(sentences)

    chunks = _chunk_section_text(text, embedder, chunk_min=200, chunk_max=1000)

    for chunk in chunks[:-1]:
        assert len(chunk) >= 200


def test_chunk_section_text_empty_body_yields_no_chunks():
    embedder = HashingEmbedder()
    assert _chunk_section_text("", embedder) == []
    assert _chunk_section_text("   ", embedder) == []


# --- garbage-section guard: non-alpha arm only, size never skips ------------


def test_garbage_section_skip_reason_fires_on_high_non_alpha_ratio():
    text = "; ".join(f"{n}, {n + 1}-{n + 2}" for n in range(1, 400))
    reason = _garbage_section_skip_reason(text)
    assert reason is not None
    assert "non-alpha" in reason


def test_garbage_section_skip_reason_never_fires_on_size_alone():
    """PRD §5 stage 4 / §8 P0-4: size never triggers a skip for this stage --
    only the non-alpha-ratio arm does. An enormous but ordinary-prose text
    must not be skipped."""
    text = "This is ordinary prose with normal punctuation and letters. " * 5000
    assert _garbage_section_skip_reason(text) is None


def test_garbage_section_skip_reason_none_for_ordinary_prose():
    assert _garbage_section_skip_reason("Ordinary prose, well under the ratio threshold.") is None


# --- embedder seam ------------------------------------------------------------


def test_hashing_embedder_is_deterministic_across_instances():
    a = HashingEmbedder().encode(["Some sentence to embed."])
    b = HashingEmbedder().encode(["Some sentence to embed."])
    assert a == b


def test_hashing_embedder_returns_unit_length_vectors():
    import math

    vectors = HashingEmbedder().encode(["Some sentence with real words in it."])
    norm = math.sqrt(sum(v * v for v in vectors[0]))
    assert norm == pytest.approx(1.0, abs=1e-9)


def test_get_embedder_stub_selection_returns_an_embedder(monkeypatch):
    monkeypatch.setenv(EMBEDDER_ENV_VAR, "stub")
    embedder = get_embedder()
    assert hasattr(embedder, "encode")
    assert embedder.encode(["hello world"])


def test_get_embedder_unset_env_var_selects_the_real_embedder_without_encoding(monkeypatch):
    """Issue #159: unset AXIAL_EMBEDDER now selects the real
    (fastembed-backed) production default, not the offline stub. This suite
    tier (`-m "not slow"`) must never construct-and-encode that real model
    (it would download/run the ONNX model) -- so this test only asserts
    SELECTION (the returned embedder is a usable, real, non-hashing
    embedder identified by its model_id), never calling `.encode()`. The
    actual-encode contract for the real model lives in
    tests/chunk/test_chunk_real_embedder.py's `@pytest.mark.slow` test."""
    monkeypatch.delenv(EMBEDDER_ENV_VAR, raising=False)
    embedder = get_embedder()
    assert hasattr(embedder, "encode")
    assert isinstance(embedder, chunk_mod.FastEmbedEmbedder)
    assert not isinstance(embedder, HashingEmbedder)
    assert "bge-small-en-v1.5" in embedder.model_id


# --- FastEmbedEmbedder (issue #159): the real production-default model ------


def test_fastembed_embedder_model_id_identifies_the_real_model_offline():
    """Constructing FastEmbedEmbedder and reading model_id must never import
    fastembed -- mirrors the outer acceptance test's lazy-import assertion,
    scoped to the class directly rather than through get_embedder()."""
    if "fastembed" in sys.modules:
        pytest.skip(
            "fastembed already imported earlier in this test process -- "
            "cannot meaningfully prove lazy-import behavior in that state"
        )

    embedder = chunk_mod.FastEmbedEmbedder()

    assert "bge-small-en-v1.5" in embedder.model_id
    assert "fastembed" not in sys.modules


def test_fastembed_embedder_lazy_loads_the_model_only_on_first_encode(monkeypatch):
    """The private `_get_model` accessor is called (and its result cached)
    only when `encode` actually runs -- not at construction."""
    embedder = chunk_mod.FastEmbedEmbedder()
    assert embedder._model is None

    calls = []

    class _FakeModel:
        def embed(self, texts):
            calls.append(list(texts))
            return iter([[0.1, 0.2, 0.3] for _ in texts])

    fake_model = _FakeModel()
    monkeypatch.setattr(embedder, "_get_model", lambda: fake_model)

    vectors = embedder.encode(["one", "two"])

    assert calls == [["one", "two"]]
    assert vectors == [[0.1, 0.2, 0.3], [0.1, 0.2, 0.3]]


def test_fastembed_embedder_encode_preserves_input_order_and_shape(monkeypatch):
    """`encode` returns one vector per input text, in the SAME order, each
    converted to a plain list[float] (fastembed yields numpy arrays)."""
    embedder = chunk_mod.FastEmbedEmbedder()

    class _FakeVector:
        """Stands in for a numpy row: iterable of numpy scalar-likes."""

        def __init__(self, values):
            self._values = values

        def __iter__(self):
            return iter(self._values)

    class _FakeModel:
        def embed(self, texts):
            return (_FakeVector([len(text), 0.0]) for text in texts)

    monkeypatch.setattr(embedder, "_get_model", lambda: _FakeModel())

    vectors = embedder.encode(["a", "bb", "ccc"])

    assert vectors == [[1.0, 0.0], [2.0, 0.0], [3.0, 0.0]]
    assert all(isinstance(component, float) for vector in vectors for component in vector)


@pytest.mark.slow
def test_fastembed_embedder_real_encode_returns_384_dim_vectors():
    """End-to-end proof against the real model (network/model-download
    required on a cold cache) -- excluded from the fast/CI tier, mirroring
    tests/chunk/test_chunk_real_embedder.py's own @slow test."""
    embedder = chunk_mod.FastEmbedEmbedder()

    vectors = embedder.encode(["Some sentence.", "Another sentence."])

    assert len(vectors) == 2
    for vector in vectors:
        assert len(vector) == 384
        assert any(component != 0.0 for component in vector)


# --- run_chunk_embedding: end-to-end against a monkeypatched tree -----------


def _tree_with_sections(section_bodies: dict[str, list[str]]) -> dict:
    children = []
    for index, (heading, bodies) in enumerate(section_bodies.items(), start=1):
        children.append(
            {
                "type": "prose",
                "order": str(index),
                "text": heading,
                "children": [
                    {"type": "prose", "order": f"{index}.{i + 1}", "text": body}
                    for i, body in enumerate(bodies)
                ],
            }
        )
    return {"children": children}


def _patch_tree(monkeypatch, tmp_path, tree: dict):
    tree_file = tmp_path / "tree.json"
    tree_file.write_text(json.dumps(tree), encoding="utf-8")
    monkeypatch.setattr(chunk_mod, "tree_path", lambda source_id: tree_file)
    monkeypatch.setattr(chunk_mod, "load_persisted_tree", lambda path: tree)


def test_run_chunk_embedding_missing_source_raises(tmp_path):
    missing = tmp_path / "does_not_exist.pdf"
    with pytest.raises(MissingSourceError):
        run_chunk_embedding(missing, embedder=HashingEmbedder(), chunks_dir=tmp_path / "chunks")


def test_run_chunk_embedding_missing_tree_raises_clear_error(monkeypatch, tmp_path):
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"fake pdf bytes")
    monkeypatch.setattr(chunk_mod, "tree_path", lambda source_id: tmp_path / "no_such_tree.json")

    with pytest.raises(MissingTreeError) as exc_info:
        run_chunk_embedding(source, embedder=HashingEmbedder(), chunks_dir=tmp_path / "chunks")

    assert "extract" in str(exc_info.value)


def test_run_chunk_embedding_never_needs_an_llm_client(monkeypatch, tmp_path):
    """The critical-path proof at the unit level: run_chunk_embedding has no
    `client`/LLMClient parameter at all, and completes successfully even
    with the poison AXIAL_LLM_PROVIDER=explode configured (nothing in this
    path ever constructs or calls one)."""
    monkeypatch.setenv("AXIAL_LLM_PROVIDER", "explode")
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"fake pdf bytes")
    tree = _tree_with_sections({"Overview": ["A short section with a few words of body text."]})
    _patch_tree(monkeypatch, tmp_path, tree)

    records = run_chunk_embedding(
        source, embedder=HashingEmbedder(), chunks_dir=tmp_path / "chunks"
    )

    assert records


def test_run_chunk_embedding_writes_jsonl_with_stable_chunk_ids(monkeypatch, tmp_path):
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"fake pdf bytes")
    tree = _tree_with_sections(
        {
            "Introduction": ["Intro sentence one. Intro sentence two. Intro sentence three."],
        }
    )
    _patch_tree(monkeypatch, tmp_path, tree)
    chunks_dir = tmp_path / "chunks"

    first = run_chunk_embedding(source, embedder=HashingEmbedder(), chunks_dir=chunks_dir)
    second = run_chunk_embedding(source, embedder=HashingEmbedder(), chunks_dir=chunks_dir)

    assert [r["chunk_id"] for r in first] == [r["chunk_id"] for r in second]
    for record in first:
        assert record["section"] == "Introduction"
        assert record["section_order"] == "1"


def test_run_chunk_embedding_section_order_disambiguates_shared_headings(monkeypatch, tmp_path):
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"fake pdf bytes")
    tree = {
        "children": [
            {
                "type": "prose",
                "order": "1",
                "text": "Notes",
                "children": [{"type": "prose", "order": "1.1", "text": "First notes body."}],
            },
            {
                "type": "prose",
                "order": "2",
                "text": "Notes",
                "children": [{"type": "prose", "order": "2.1", "text": "Second notes body."}],
            },
        ]
    }
    _patch_tree(monkeypatch, tmp_path, tree)

    records = run_chunk_embedding(
        source, embedder=HashingEmbedder(), chunks_dir=tmp_path / "chunks"
    )

    chunk_ids = [r["chunk_id"] for r in records]
    assert len(chunk_ids) == len(set(chunk_ids))
    assert all(r["section"] == "Notes" for r in records)


def test_run_chunk_embedding_garbage_section_skipped_and_logged(monkeypatch, tmp_path, capsys):
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"fake pdf bytes")
    garbage = "; ".join(f"{n}, {n + 1}-{n + 2}" for n in range(1, 400))
    tree = _tree_with_sections(
        {
            "Overview": ["Ordinary prose about the survey and its findings."],
            "Numeric Annex": [garbage],
        }
    )
    _patch_tree(monkeypatch, tmp_path, tree)

    records = run_chunk_embedding(
        source, embedder=HashingEmbedder(), chunks_dir=tmp_path / "chunks"
    )

    assert all(r["section"] != "Numeric Annex" for r in records)
    err = capsys.readouterr().err
    assert "Numeric Annex" in err
    assert "skip" in err.lower()


def test_run_chunk_embedding_oversized_section_is_split_never_dropped(monkeypatch, tmp_path):
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"fake pdf bytes")
    filler = [
        "The regional administration reorganized its provincial offices after the ceasefire.",
        "Local councils began coordinating water distribution across contested districts.",
        "Field teams recorded shifting patterns of return migration along the northern corridor.",
    ]
    sentences = []
    total = 0
    i = 0
    while total < CHUNK_MAX * 3:
        s = filler[i % len(filler)]
        sentences.append(s)
        total += len(s) + 1
        i += 1
    oversized_text = " ".join(sentences)

    tree = _tree_with_sections({"Field Survey Findings": [oversized_text]})
    _patch_tree(monkeypatch, tmp_path, tree)

    records = run_chunk_embedding(
        source, embedder=HashingEmbedder(), chunks_dir=tmp_path / "chunks"
    )

    assert len(records) >= 2
    assert all(len(r["text"]) <= CHUNK_MAX for r in records)


def test_run_chunk_embedding_respects_chunk_min_via_the_default_band(monkeypatch, tmp_path):
    """End-to-end MIN-side counterpart to the MAX-side test above: a section
    built from many short, choppy sentences (prone to small breakpoint
    groups) must still come out of `run_chunk_embedding` -- using the
    module's own default `CHUNK_MIN`, not a test-local override -- with
    every non-last record at or above `CHUNK_MIN` (the MIN-side band guard's
    forward-merge doing its job end-to-end, not just at the `_enforce_min`
    unit level)."""
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"fake pdf bytes")
    short_sentences = [
        "Aid arrived.",
        "Roads reopened.",
        "Markets stirred.",
        "Officials met.",
        "Records were kept.",
        "Water flowed again.",
    ]
    sentences = []
    total = 0
    i = 0
    while total < CHUNK_MIN * 4:
        s = short_sentences[i % len(short_sentences)]
        sentences.append(s)
        total += len(s) + 1
        i += 1
    text = " ".join(sentences)

    tree = _tree_with_sections({"Overview": [text]})
    _patch_tree(monkeypatch, tmp_path, tree)

    records = run_chunk_embedding(
        source, embedder=HashingEmbedder(), chunks_dir=tmp_path / "chunks"
    )

    assert len(records) >= 2, (
        "expected multiple chunks so the MIN-side exception (last chunk only) is meaningful"
    )
    for record in records[:-1]:
        assert len(record["text"]) >= CHUNK_MIN, (
            f"expected every non-last record to meet CHUNK_MIN ({CHUNK_MIN}) via "
            f"the default band, got {len(record['text'])} chars: {record!r}"
        )


def test_run_chunk_embedding_section_then_position_order(monkeypatch, tmp_path):
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"fake pdf bytes")
    tree = _tree_with_sections(
        {
            "Overview": ["First section body sentence one. First section body sentence two."],
            "Details": ["Second section body sentence one. Second section body sentence two."],
        }
    )
    _patch_tree(monkeypatch, tmp_path, tree)

    records = run_chunk_embedding(
        source, embedder=HashingEmbedder(), chunks_dir=tmp_path / "chunks"
    )

    orders = [r["section_order"] for r in records]
    assert orders == sorted(orders)


def test_run_chunk_embedding_rerun_overwrites_cleanly(monkeypatch, tmp_path):
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"fake pdf bytes")
    tree = _tree_with_sections({"Overview": ["Some prose body text about the survey findings."]})
    _patch_tree(monkeypatch, tmp_path, tree)
    chunks_dir = tmp_path / "chunks"

    run_chunk_embedding(source, embedder=HashingEmbedder(), chunks_dir=chunks_dir)
    from axial.envelope import compute_source_id

    source_id = compute_source_id(source)
    out_path = chunks_dir / f"{source_id}.jsonl"
    first_bytes = out_path.read_bytes()

    run_chunk_embedding(source, embedder=HashingEmbedder(), chunks_dir=chunks_dir)
    second_bytes = out_path.read_bytes()

    assert first_bytes == second_bytes


def test_run_chunk_embedding_no_chunkable_prose_yields_no_records_for_that_section(
    monkeypatch, tmp_path
):
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"fake pdf bytes")
    tree = {
        "children": [
            {"type": "prose", "order": "1", "text": "Empty Section", "children": []},
            {
                "type": "prose",
                "order": "2",
                "text": "Overview",
                "children": [{"type": "prose", "order": "2.1", "text": "Some real body text."}],
            },
        ]
    }
    _patch_tree(monkeypatch, tmp_path, tree)

    records = run_chunk_embedding(
        source, embedder=HashingEmbedder(), chunks_dir=tmp_path / "chunks"
    )

    assert all(r["section"] != "Empty Section" for r in records)
    assert any(r["section"] == "Overview" for r in records)
