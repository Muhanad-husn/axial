"""Inner unit tests for `content_words`/`content_word_runs` (issue #649: the
intake fork-check's own phrase-resolution tokenizer, co-located separately
from `test_names.py` since these two functions carry no vault/names-dir
dependency at all -- pure text in, tokens out)."""

from __future__ import annotations

from axial.query.names import content_word_runs, content_words


def test_content_words_drops_stopwords_keeps_order():
    assert content_words("What is the situation in Syria?") == ["What", "situation", "Syria?"]


def test_content_word_runs_splits_on_stopwords():
    """Two content words separated by a stopword are two different runs --
    never joined into one, so a caller never tests a "phrase" that was
    never actually adjacent in the question's own words."""
    runs = content_word_runs("the sources of regime durability in Syria")
    assert runs == [["sources"], ["regime", "durability"], ["Syria"]]


def test_content_word_runs_keeps_a_true_multi_word_run_together():
    runs = content_word_runs("Did the civil war change the sources")
    assert runs == [["Did"], ["civil", "war", "change"], ["sources"]]


def test_content_word_runs_splits_on_hyphens_too():
    """`_WORD_SPLIT` treats a hyphen as a separator, the same rule
    `content_words` already follows -- "2011-2024" yields two adjacent
    tokens in one run, not one token."""
    runs = content_word_runs("Syria, 2011-2024")
    assert runs == [["Syria,", "2011", "2024"]]


def test_content_word_runs_empty_text_yields_no_runs():
    assert content_word_runs("") == []


def test_content_word_runs_all_stopwords_yields_no_runs():
    assert content_word_runs("or is it that") == []
