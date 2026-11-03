import pytest

from exactdocs.retrieval.models import identifier_tokens


@pytest.mark.parametrize(
    ("identifier", "whole", "parts"),
    [
        ("retryPolicy", "retrypolicy", "retry policy"),
        ("max_retries", "max_retries", "max retries"),
        ("--dry-run", "--dry-run", "dry run"),
        ("pkg.mod.fn", "pkg.mod.fn", "pkg mod fn"),
        ("HTTPServer", "httpserver", "http server"),
        ("XMLHttpRequest", "xmlhttprequest", "xml http request"),
        ("base64Decode", "base64decode", "base 64 decode"),
        ("HTTP2", "http2", "http 2"),
        ("getÜberTest", "getübertest", "get über test"),
        ("Straße_größe", "straße_größe", "straße größe"),
    ],
)
def test_identifier_is_indexed_whole_and_by_its_parts(
    identifier: str, whole: str, parts: str
) -> None:
    assert identifier_tokens(identifier) == f"{whole} {parts}"


@pytest.mark.parametrize("word", ["retry", "Retry", "42", "日本語"])
def test_a_plain_word_is_a_single_token(word: str) -> None:
    assert identifier_tokens(word) == word.lower()


def test_a_query_gets_the_same_tokens_as_the_indexed_text() -> None:
    assert identifier_tokens("retryPolicy") == identifier_tokens("`retryPolicy`")


def test_punctuation_around_identifiers_is_dropped() -> None:
    text = "Pass `--dry-run`, or set max_retries (see pkg.mod.fn.)."
    assert identifier_tokens(text).split() == [
        "pass",
        "--dry-run",
        "dry",
        "run",
        "or",
        "set",
        "max_retries",
        "max",
        "retries",
        "see",
        "pkg.mod.fn",
        "pkg",
        "mod",
        "fn",
    ]


def test_precomposed_and_decomposed_unicode_give_the_same_tokens() -> None:
    assert identifier_tokens("caféAu") == identifier_tokens("caféAu")


@pytest.mark.parametrize("text", ["", "   ", "---", "...", "`` ,"])
def test_text_without_letters_or_digits_yields_nothing(text: str) -> None:
    assert not identifier_tokens(text)
