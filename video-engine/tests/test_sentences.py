"""The one sentence splitter shared by TTS, the beat helper and the validators."""

from __future__ import annotations

from pebble.templates.pebble_kit import split_sentences


def test_splits_on_full_stops_questions_and_exclamations():
    assert split_sentences("One. Two? Three!") == ["One.", "Two?", "Three!"]


def test_keeps_question_and_exclamation_runs_together():
    assert split_sentences("Really?! Yes.") == ["Really?!", "Yes."]


def test_does_not_split_decimals():
    assert split_sentences("It costs 3.5 coins. Then 4.") == [
        "It costs 3.5 coins.",
        "Then 4.",
    ]


def test_does_not_split_abbreviations():
    assert split_sentences("Use a map, e.g. a notebook. It is fast.") == [
        "Use a map, e.g. a notebook.",
        "It is fast.",
    ]


def test_splits_non_latin_endings():
    assert split_sentences("यह एक वाक्य है। दूसरा वाक्य।") == [
        "यह एक वाक्य है।",
        "दूसरा वाक्य।",
    ]
    assert split_sentences("これは文です。次の文です！") == [
        "これは文です。",
        "次の文です！",
    ]


def test_single_sentence_and_empty_text():
    assert split_sentences("  Just one sentence  ") == ["Just one sentence"]
    assert split_sentences("") == []
    assert split_sentences(None) == []


def test_trailing_text_without_a_stop_is_kept():
    assert split_sentences("First one. and then this") == ["First one.", "and then this"]
