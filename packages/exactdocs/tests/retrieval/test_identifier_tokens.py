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
        ("Straße_größe", "strasse_grösse", "strasse grösse"),
        ("HTTP2Server", "http2server", "http 2 server"),
        ("getHTTPResponseCode", "gethttpresponsecode", "get http response code"),
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


def test_casefolding_unifies_sharp_s() -> None:
    assert identifier_tokens("Straße") == identifier_tokens("STRASSE") == "strasse"


def test_combining_marks_stay_inside_their_word() -> None:
    assert identifier_tokens("हिन्दी") == "हिन्दी"
    assert identifier_tokens("x́Y") == "x́y x́ y"


@pytest.mark.parametrize(
    ("text", "expected"),
    [(".env", "env"), ("foo_", "foo_ foo"), ("-v", "-v v"), ("end.", "end")],
)
def test_leading_and_trailing_punctuation_of_the_whole(text: str, expected: str) -> None:
    assert identifier_tokens(text) == expected
