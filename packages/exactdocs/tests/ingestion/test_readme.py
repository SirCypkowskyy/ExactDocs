"""What a root README says about its library: first heading, first paragraph, sanitized, capped."""

import pytest

from exactdocs.ingestion.models import (
    README_DESCRIPTION_MAX,
    README_TITLE_MAX,
    ReadmeSummary,
    readme_summary,
)


@pytest.mark.parametrize(
    ("source", "title", "description"),
    [
        ("# Acme\n\nA payments SDK.\n\n## Install\n\nRun it.\n", "Acme", "A payments SDK."),
        ("# Acme\n", "Acme", None),
        ("", None, None),
        ("no heading, just text\n", None, "no heading, just text"),
        ("Intro first.\n\n# Acme\n\nAfter.\n", "Acme", "After."),
        ("## Second level\n\nText.\n", "Second level", "Text."),
        ("---\ntitle: Front\n---\n# Acme\n\nText.\n", "Acme", "Text."),
        (
            "# `acme` *SDK*\n\nUses **bold**, [links](http://x.y) and `code`.\n",
            "acme SDK",
            "Uses bold, links and code.",
        ),
        ("# Acme\n\n[![ci](a.svg)](b)\n![logo](c.png)\n\nReal text.\n", "Acme", "Real text."),
        ("# Acme\n\nline one\nline two\n\nnext\n", "Acme", "line one line two"),
        ("# Acme\n\n- item\n\nAfter list.\n", "Acme", "After list."),
        ("# Acme\n\n<img src=x>\n\nText.\n", "Acme", "Text."),
        ("# Ac\u200bme\n\nTe\u202ext\x1b[31m.\n", "Acme", "Text[31m."),
        ("#\n\nText.\n", None, "Text."),
        ("# Acme\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\nAfter table.\n", "Acme", "After table."),
        ("# Acme\n\n[Docs](http://x.y) | [API](http://x.z)\n\nReal.\n", "Acme", "Real."),
        ("# Acme\n\n[Docs](http://x.y)\n\nReal.\n", "Acme", "Real."),
        ("# [Acme](http://x.y)\n\nSee [the docs](http://x.y) now.\n", "Acme", "See the docs now."),
        ("<h1 align=center>Acme</h1>\n\nText.\n", None, "Text."),
    ],
)
def test_extraction(source: str, title: str | None, description: str | None) -> None:
    assert readme_summary(source) == ReadmeSummary(title=title, description=description)


def test_long_values_are_cut() -> None:
    summary = readme_summary(f"# {'t' * 999}\n\n{'d ' * 999}\n")

    assert summary.title is not None
    assert summary.description is not None
    assert len(summary.title) == README_TITLE_MAX
    assert len(summary.description) <= README_DESCRIPTION_MAX
