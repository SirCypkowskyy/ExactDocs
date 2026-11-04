import sys

import pytest

from exactdocs_kernel import MAX_TAG_LENGTH, normalize_tag


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (" API ", "api"),
        ("Getting  Started", "getting-started"),
        ("v1.2+beta", "v1.2+beta"),
        ("a_b", "a_b"),
        ("\uff21\uff30\uff29", "api"),  # full-width letters, NFKC
        ("zażółć", "zażółć"),
        ("c++", "c++"),
        ("a" * MAX_TAG_LENGTH, "a" * MAX_TAG_LENGTH),
        ("हिन्दी", "हिन्दी"),  # Devanagari: vowel signs and virama are combining marks
        ("كِتَاب", "كِتَاب"),  # Arabic harakat
        ("Straße", "strasse"),
        ("STRASSE", "strasse"),
        ("ΟΔΟΣ", "οδοσ"),  # final sigma folds to the plain one
        ("οδος", "οδοσ"),
    ],
)
def test_a_tag_has_one_form(raw: str, expected: str) -> None:
    assert normalize_tag(raw) == expected


def test_a_dotted_capital_i_folds_to_the_same_tag_as_the_typed_word() -> None:
    folded = normalize_tag("\u0130stanbul")
    assert folded is not None
    assert normalize_tag(folded) == folded
    assert folded.startswith("i")


@pytest.mark.parametrize(
    "raw",
    [
        "",
        " ",
        "a" * (MAX_TAG_LENGTH + 1),
        "-lead",
        "_lead",
        ".lead",
        "a,b",
        "a\uff0cb",  # fullwidth comma folds to a comma
        "a/b",
        "<script>",
        "emoji\U0001f600",
        "a\u200bb",  # zero-width space
        "a\u200db",  # zero-width joiner
        "a\u00adb",  # soft hyphen
        "a\u202eb",  # bidi override
        "not a tag!",
        "\u0301a",  # starts with a combining mark
    ],
)
def test_what_cannot_be_a_tag_is_refused(raw: str) -> None:
    assert normalize_tag(raw) is None


def test_normalizing_twice_changes_nothing_for_any_code_point() -> None:
    for code in range(sys.maxunicode + 1):
        if 0xD800 <= code <= 0xDFFF:
            continue
        for raw in (chr(code), f"a{chr(code)}", f"{chr(code)}a"):
            once = normalize_tag(raw)
            if once is not None:
                assert normalize_tag(once) == once, hex(code)
