"""What a root README says about its library: its H1 or logo, first paragraph, sanitized, capped."""

from pathlib import Path

import pytest

from exactdocs.ingestion.constants import README_DESCRIPTION_MAX, README_TITLE_MAX
from exactdocs.ingestion.models import readme_summary


@pytest.mark.parametrize(
    ("source", "title", "description"),
    [
        ("# Acme\n\nA payments SDK.\n\n## Install\n\nRun it.\n", "Acme", "A payments SDK."),
        ("# Acme\n", "Acme", None),
        ("", None, None),
        ("no heading, just text\n", None, "no heading, just text"),
        ("Intro first.\n\n# Acme\n\nAfter.\n", "Acme", "After."),
        ("## Second level\n\nText.\n", None, "Text."),
        ("Intro.\n\n## Sponsors\n\nAcme Corp.\n", None, "Intro."),
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
        ("<h1 align=center>Acme</h1>\n\nText.\n", "Acme", "Text."),
        ('<h1 align="center"><img src="logo.svg" alt="Acme"></h1>\n\nText.\n', "Acme", "Text."),
        ("# ![Acme](logo.png)\n\nText.\n", "Acme", "Text."),
        ("# [![Acme logo](logo.png)](https://acme.dev)\n\nText.\n", "Acme", "Text."),
        ('# <img src="logo.png" alt="Acme">\n\nText.\n', "Acme", "Text."),
        ("![Acme](logo.png)\n\nText.\n\n## Install\n\nRun it.\n", "Acme", "Text."),
        ('<p><img src="logo.png" alt="Acme"></p>\n\n## Install\n\nRun it.\n', "Acme", "Run it."),
        ("[![ci](https://img.shields.io/x.svg)](b)\n\n## Install\n\nRun it.\n", None, "Run it."),
        ('<img src="ci/badge.svg" alt="CI">\n\n## Install\n\nRun it.\n', None, "Run it."),
        ("![logo](logo.png)\n\n## Install\n\nRun it.\n", None, "Run it."),
        ("Text first.\n\n![Diagram](d.png)\n\n## Install\n", None, "Text first."),
        ("![Acme](logo.png)\n\n# Acme Payments\n\nText.\n", "Acme Payments", "Text."),
        ("# Acme\n\n> A quote.\n\nText.\n", "Acme", "Text."),
        ("# Acme\n\n**Docs**: [https://x.y](https://x.y)\n\nText.\n", "Acme", "Text."),
        ("# Acme\n\n**Acme** is an SDK: [docs](https://x.y).\n", "Acme", "Acme is an SDK: docs."),
    ],
)
def test_extraction(source: str, title: str | None, description: str | None) -> None:
    summary = readme_summary(source)  # its logo candidates: tests/ingestion/test_logos.py

    assert (summary.title, summary.description) == (title, description)


def test_long_values_are_cut() -> None:
    summary = readme_summary(f"# {'t' * 999}\n\n{'d ' * 999}\n")

    assert summary.title is not None
    assert summary.description is not None
    assert len(summary.title) == README_TITLE_MAX
    assert len(summary.description) <= README_DESCRIPTION_MAX


READMES = Path(__file__).parents[1] / "fixtures" / "readmes"


@pytest.mark.parametrize(
    ("name", "title", "description"),
    [
        (
            "fastapi.md",
            "FastAPI",
            (
                "FastAPI is a modern, fast (high-performance), web framework for building APIs "
                "with Python based on standard Python type hints."
            ),
        ),
        (
            "pydantic-ai.md",
            "Pydantic AI",
            (
                "Pydantic AI is the Python AI SDK: a typed, extensible agent loop with every "
                "model a string swap away."
            ),
        ),
    ],
)
def test_a_logo_names_the_project_never_a_section_heading(
    name: str, title: str, description: str
) -> None:
    summary = readme_summary((READMES / name).read_text(encoding="utf-8"))

    assert (summary.title, summary.description) == (title, description)
