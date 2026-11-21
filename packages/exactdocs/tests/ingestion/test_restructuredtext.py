"""reStructuredText (Sphinx) articles: each construct, written as the Markdown the chunker takes."""

from collections.abc import Mapping
from pathlib import Path
from textwrap import dedent

import pytest
from markdown_it import MarkdownIt

from exactdocs.ingestion.adapters.driven.markdown_chunker import MarkdownChunker
from exactdocs.ingestion.adapters.driven.restructuredtext import RestructuredTextConverter
from exactdocs.ingestion.constants import MAX_INCLUDE_DEPTH
from exactdocs.ingestion.models import (
    ConvertedArticle,
    IncludeRefused,
    PathSelection,
    converted_article,
    converted_key,
    is_restructuredtext,
)

SPHINX = Path(__file__).parents[1] / "fixtures" / "sphinx-docs"
PAGE = "doc/build/guide/page.rst"


class Files:
    """A fake ``IncludedFiles``: the given files, everything else refused; records what is read."""

    def __init__(self, files: Mapping[str, str] | None = None) -> None:
        self.files = dict(files or {})
        self.asked: list[str] = []

    def read(self, path: str) -> str | IncludeRefused:
        self.asked.append(path)
        if path in self.files:
            return self.files[path]
        return IncludeRefused(reason="not among the imported files")


class FixtureFiles:
    """The fixture Sphinx documentation, read from disk."""

    def read(self, path: str) -> str | IncludeRefused:
        file = SPHINX / path
        if file.is_file():
            return file.read_text(encoding="utf-8")
        return IncludeRefused(reason="not among the imported files")


def convert(
    source: str, files: Mapping[str, str] | None = None, path: str = PAGE
) -> ConvertedArticle:
    return RestructuredTextConverter().convert(path, dedent(source).lstrip("\n"), Files(files))


def body(source: str, files: Mapping[str, str] | None = None, path: str = PAGE) -> str:
    return convert(source, files, path).body


def fixture(path: str) -> ConvertedArticle:
    text = (SPHINX / path).read_text(encoding="utf-8")
    return RestructuredTextConverter().convert(path, text, FixtureFiles())


# --- sections and headings ---


def test_heading_levels_follow_the_nesting_whatever_the_adornment_style() -> None:
    text = body(
        """
        ########
        Overline
        ########

        Equals
        ======

        Tilde
        ~~~~~

        Back to equals
        ==============
        """
    )
    assert text.splitlines()[::2] == ["# Overline", "## Equals", "### Tilde", "## Back to equals"]


def test_a_document_without_sections_has_no_heading_and_the_file_name_as_title() -> None:
    converted = convert("Just a paragraph.\n")
    assert converted.body == "Just a paragraph.\n"
    assert converted_article(PAGE, converted).title == "page"


def test_the_title_is_the_first_section_title() -> None:
    article = converted_article(PAGE, convert(".. _top:\n\nThe Title\n=========\n\nText.\n"))
    assert article.title == "The Title"


def test_heading_paths_and_anchors_are_those_of_markdown() -> None:
    converted = convert(
        """
        Guide
        =====

        The ``Session`` object
        ----------------------

        Text.
        """
    )
    chunks = MarkdownChunker().chunk(converted_article(PAGE, converted))
    assert [(c.heading_path, c.anchor) for c in chunks] == [
        (("Guide",), "guide"),
        (("Guide", "The Session object"), "the-session-object"),
    ]


def test_sphinx_file_wide_metadata_is_not_shown() -> None:
    assert body(":orphan:\n:tocdepth: 2\n\nTitle\n=====\n") == "# Title\n"


# --- paragraphs, inline markup, lists ---


def test_inline_markup_becomes_markdown() -> None:
    text = body("Some *emphasis*, **strong**, ``code`` and `default role`.\n")
    assert text == "Some *emphasis*, **strong**, `code` and `default role`.\n"


def test_markdown_characters_in_text_are_escaped() -> None:
    text = body("A * star, a [bracket], an _underscore and snake_case stays.\n\n# not a heading\n")
    tokens = MarkdownIt("commonmark").parse(text)
    assert [t.type for t in tokens if t.type.endswith("_open")] == ["paragraph_open"] * 2
    assert "snake_case" in text
    assert "\\*" in text


def test_lists_keep_their_numbers_and_nesting() -> None:
    text = body(
        """
        - one
        - two

          - nested

        3. three
        4. four
        """
    )
    assert text == "- one\n\n- two\n\n  - nested\n\n3. three\n4. four\n"  # loose: a nested list


def test_definition_and_field_lists_become_labelled_items() -> None:
    text = body(
        """
        term
            Its definition.

        :param engine: the engine.
        """
    )
    assert text == "- **term**: Its definition.\n\n- **param engine**: the engine.\n"


def test_links_keep_their_url() -> None:
    assert body("See `Python <https://python.org>`_.\n") == "See [Python](https://python.org).\n"


def test_block_quotes_and_line_blocks() -> None:
    text = body("Intro:\n\n    Quoted text.\n\n| line one\n| line two\n")
    assert text == "Intro:\n\n> Quoted text.\n\nline one\\\nline two\n"


def test_footnotes_are_kept_as_bracketed_labels() -> None:
    text = body("A claim [1]_.\n\n.. [1] The source.\n")
    assert text == "A claim \\[1\\].\n\n\\[1\\] The source.\n"


def test_images_point_at_the_repository_file() -> None:
    text = body(".. image:: ../img/flow.png\n   :alt: The flow\n")
    assert text == "![The flow](../img/flow.png)\n"
    assert converted_article(PAGE, convert(".. image:: ../img/flow.png\n")).images == (
        "doc/build/img/flow.png",
    )


# --- code ---


@pytest.mark.parametrize("directive", ["code-block", "sourcecode", "code"])
def test_code_directives_keep_their_language(directive: str) -> None:
    text = body(f".. {directive}:: python\n   :linenos:\n\n   x = 1\n")
    assert text == "```python\nx = 1\n```\n"


def test_a_literal_block_takes_the_highlight_language() -> None:
    text = body("Plain::\n\n    a = 1\n\n.. highlight:: sql\n\nThen::\n\n    SELECT 1\n")
    assert text == "Plain:\n\n```\na = 1\n```\n\nThen:\n\n```sql\nSELECT 1\n```\n"


def test_a_literal_block_takes_conf_py_highlight_language() -> None:
    files = {"doc/build/conf.py": 'highlight_language = "python3"\n'}
    assert body("Code::\n\n    x = 1\n", files) == "Code:\n\n```python3\nx = 1\n```\n"


def test_doctest_blocks_and_captions() -> None:
    text = body(
        """
        >>> 1 + 1
        2

        .. code-block:: console
           :caption: Run it

           $ run
        """
    )
    assert text == "```pycon\n>>> 1 + 1\n2\n```\n\n*Run it*\n\n```console\n$ run\n```\n"


def test_backticks_in_code_never_close_the_fence() -> None:
    text = body(".. code-block:: markdown\n\n   ```python\n   x\n   ```\n")
    assert text.startswith("````markdown\n")
    chunks = MarkdownChunker().chunk(converted_article(PAGE, convert(text)))
    assert chunks


def test_code_languages_reach_the_chunks() -> None:
    converted = convert("Title\n=====\n\n.. code-block:: python+sql\n\n   SELECT 1\n")
    (chunk,) = MarkdownChunker().chunk(converted_article(PAGE, converted))
    assert chunk.code_languages == ("python+sql",)


# --- tables ---


def test_grid_simple_and_list_tables_become_pipe_tables() -> None:
    text = body(
        """
        +---+---+
        | a | b |
        +===+===+
        | 1 | 2 |
        +---+---+

        ===  ===
        x    y
        ===  ===
        3    4|5
        ===  ===

        .. list-table:: Caption
           :header-rows: 1

           * - h
           * - ``v``
        """
    )
    assert text == (
        "| a | b |\n| --- | --- |\n| 1 | 2 |\n\n"
        "| x | y |\n| --- | --- |\n| 3 | 4\\|5 |\n\n"
        "**Caption**\n\n| h |\n| --- |\n| `v` |\n"
    )
    tokens = MarkdownIt("commonmark").enable("table").parse(text)
    assert sum(t.type == "table_open" for t in tokens) == 3


def test_spanned_cells_are_left_empty() -> None:
    text = body(
        """
        +-----+-----+
        | a   | b   |
        +=====+=====+
        | wide      |
        +-----+-----+
        """
    )
    assert text.splitlines()[-1] == "| wide |  |"


# --- admonitions ---


@pytest.mark.parametrize(
    ("directive", "alert"),
    [
        ("note", "NOTE"),
        ("tip", "TIP"),
        ("hint", "TIP"),
        ("important", "IMPORTANT"),
        ("warning", "WARNING"),
        ("caution", "CAUTION"),
        ("danger", "CAUTION"),
    ],
)
def test_admonitions_become_github_alerts(directive: str, alert: str) -> None:
    assert body(f".. {directive}:: Mind this.\n") == f"> [!{alert}]\n> Mind this.\n"


def test_sphinx_admonitions_get_their_title() -> None:
    text = body(
        """
        .. versionadded:: 2.1
           The ``x`` option.

        .. deprecated:: 2.0 Use ``y``.

        .. seealso::

           The tutorial.

        .. admonition:: Custom

           Body.
        """
    )
    assert text == (
        "> [!NOTE]\n> **Added in version 2.1**: The `x` option.\n\n"
        "> [!WARNING]\n> **Deprecated since version 2.0**: Use `y`.\n\n"
        "> [!NOTE]\n> **See also**: The tutorial.\n\n"
        "> [!NOTE]\n> **Custom**: Body.\n"
    )


def test_an_admonition_keeps_its_code_blocks() -> None:
    text = body(".. note::\n\n   Before.\n\n   .. code-block:: python\n\n      x = 1\n")
    assert text == "> [!NOTE]\n> Before.\n>\n> ```python\n> x = 1\n> ```\n"


# --- directives with nothing to read, object descriptions ---


def test_toctree_index_and_contents_are_not_indexed() -> None:
    text = body(
        """
        Title
        =====

        .. toctree::
           :maxdepth: 2

           install
           secret_entry

        .. index:: single: flush

        .. contents::

        .. only:: html

           Kept.
        """
    )
    assert text == "# Title\n\nKept.\n"


def test_object_descriptions_show_their_signature() -> None:
    text = body(
        """
        .. py:class:: Store(engine)

           The unit of work.

        .. autofunction:: acme.open_store
        """
    )
    assert text == ("**`class Store(engine)`**\n\nThe unit of work.\n\n**`acme.open_store`**\n")


# --- roles ---


@pytest.mark.parametrize(
    ("role", "shown"),
    [
        (":class:`acme.orm.Store`", "`acme.orm.Store`"),
        (":class:`~acme.orm.Store`", "`Store`"),
        (":class:`.Store`", "`Store`"),
        (":py:class:`!Store`", "`Store`"),
        (":func:`acme.open_store`", "`acme.open_store()`"),
        (":meth:`~.Store.flush`", "`flush()`"),
        (":attr:`.Store.autoflush`", "`Store.autoflush`"),
        (":exc:`StoreError`", "`StoreError`"),
        (":mod:`acme.orm`", "`acme.orm`"),
        (":class:`the store <acme.orm.Store>`", "`the store`"),
        (":term:`identity map`", "identity map"),
        (":abbr:`ORM (object relational mapper)`", "ORM"),
        (":kbd:`Ctrl+C`", "`Ctrl+C`"),
        (":envvar:`ACME_URL`", "`ACME_URL`"),
    ],
)
def test_object_and_text_roles_become_readable_text(role: str, shown: str) -> None:
    assert body(f"See {role}.\n") == f"See {shown}.\n"


def test_ref_to_a_label_in_the_file_is_a_link_to_its_section() -> None:
    text = body(
        """
        See :ref:`opening` and :ref:`the opening <opening>`.

        .. _opening:

        Opening a Store
        ===============
        """
    )
    assert text.splitlines()[0] == (
        "See [Opening a Store](#opening-a-store) and [the opening](#opening-a-store)."
    )


def test_ref_to_a_label_elsewhere_is_its_title_or_label_as_text() -> None:
    text = body("See :ref:`queryguide_toplevel` and :ref:`the guide <queryguide_toplevel>`.\n")
    assert text == "See queryguide_toplevel and the guide.\n"


def test_doc_links_to_the_rst_file() -> None:
    files = {"doc/build/conf.py": ""}  # `/x` starts at the source root
    text = body("Read :doc:`install` and :doc:`the API </api/index>`.\n", files)
    assert text == "Read [install](install.rst) and [the API](../api/index.rst).\n"


def test_substitutions_are_replaced() -> None:
    text = body(".. |product| replace:: Acme *Store*\n\nWelcome to |product|.\n")
    assert text == "Welcome to Acme *Store*.\n"


# --- unknown markup ---


def test_an_unknown_directive_keeps_its_text_and_is_a_problem() -> None:
    converted = convert(
        """
        .. tab-set::
           :sync-group: os

           .. tab-item:: Linux

              Use ``apt``.
        """
    )
    assert converted.body == "Linux\n\nUse `apt`.\n"
    assert converted.problems == (
        "reStructuredText: unknown directives kept as text: tab-set, tab-item",
    )


def test_an_unknown_role_is_shown_as_code_and_is_a_problem() -> None:
    converted = convert("Pass :paramref:`.Store.autoflush` or :pypi:`acme`.\n")
    assert converted.body == "Pass `Store.autoflush` or `acme`.\n"
    assert converted.problems == ("reStructuredText: unknown roles shown as code: paramref, pypi",)


def test_raw_html_is_not_imported() -> None:
    assert body("Text.\n\n.. raw:: html\n\n   <script>x()</script>\n") == "Text.\n"


def test_a_body_never_starts_with_front_matter() -> None:
    text = body("----------\n\nAfter a transition.\n\n----------\n\nMore.\n")
    assert not text.startswith("---")


def test_markup_docutils_cannot_parse_still_imports() -> None:
    converted = convert("Title\n=====\n\n.. note::\n\n  * a\n   * badly indented\n\n:bad:`x\n")
    assert converted.body.startswith("# Title")


# --- includes ---


def test_include_inserts_the_file_relative_to_the_article() -> None:
    files = {"doc/build/guide/_inc/part.rst": "Included *text*.\n"}
    assert body("Before.\n\n.. include:: _inc/part.rst\n\nAfter.\n", files) == (
        "Before.\n\nIncluded *text*.\n\nAfter.\n"
    )


def test_an_absolute_include_starts_at_the_source_root() -> None:
    files = {"doc/build/conf.py": "", "doc/build/_shared/note.rst": "Shared.\n"}
    assert body(".. include:: /_shared/note.rst\n", files) == "Shared.\n"


def test_include_options_cut_the_file_or_make_it_code() -> None:
    files = {"doc/build/guide/f.rst": "one\n.. start\ntwo\n.. end\nthree\n"}
    text = body(
        """
        .. include:: f.rst
           :start-after: .. start
           :end-before: .. end

        .. include:: f.rst
           :code: rst
           :start-line: 4
        """,
        files,
    )
    assert text == "two\n\n```rst\nthree\n```\n"


def test_literalinclude_reads_a_python_object_or_lines() -> None:
    code = "import a\n\n\n@deco\ndef f():\n    return 1\n\n\ndef g():\n    pass\n"
    files = {"doc/build/guide/ex.py": code}
    text = body(
        """
        .. literalinclude:: ex.py
           :pyobject: f

        .. literalinclude:: ex.py
           :lines: 1, 9-
           :language: python3
        """,
        files,
    )
    assert text == (
        "```python\n@deco\ndef f():\n    return 1\n```\n\n"
        "```python3\nimport a\ndef g():\n    pass\n```\n"
    )


def test_an_include_that_cannot_be_read_is_a_problem_not_a_failure() -> None:
    converted = convert(
        "Text.\n\n.. include:: missing.rst\n\n.. literalinclude:: ../../../../x.py\n"
    )
    assert converted.body == "Text.\n"
    assert converted.problems == (
        (
            "reStructuredText: include doc/build/guide/missing.rst: not among the imported files; "
            "literalinclude ../../../../x.py: not a path inside the repository"
        ),
    )


def test_an_include_of_itself_stops() -> None:
    files = {"doc/build/guide/a.rst": "Again.\n\n.. include:: a.rst\n"}
    converted = convert(".. include:: a.rst\n", files)
    assert converted.body == "Again.\n"
    assert "it includes itself" in converted.problems[0]


def test_includes_nest_at_most_max_include_depth() -> None:
    files = {
        f"doc/build/guide/{n}.rst": f"Level {n}.\n\n.. include:: {n + 1}.rst\n"
        for n in range(MAX_INCLUDE_DEPTH + 2)
    }
    converted = convert(".. include:: 0.rst\n", files)
    assert f"Level {MAX_INCLUDE_DEPTH - 1}." in converted.body
    assert f"Level {MAX_INCLUDE_DEPTH}." not in converted.body
    assert "levels deep" in converted.problems[0]


def test_the_source_root_is_looked_for_above_the_article_only() -> None:
    files = Files()
    RestructuredTextConverter().convert("a/b/c.rst", "Text.\n", files)
    assert files.asked == ["a/b/conf.py", "a/conf.py", "conf.py"]


# --- the fixture documentation ---


def test_the_fixture_session_guide() -> None:
    converted = fixture("doc/build/orm/session.rst")
    text = converted.body
    assert text.startswith("# Using a Store\n\nThe `Store` is where")
    assert "[Opening a Store](#opening-a-store)" in text
    assert '```python\nengine = create_engine("sqlite://")' in text  # `::` takes conf.py's
    assert "> [!WARNING]\n> Never share one `Store` between requests." in text
    assert "| deletes | children | parents \\| last |" in text
    assert "The pool keeps at most `pool_size` connections open." in text
    assert "def unrelated" not in text
    assert "toctree" not in text
    assert "single: Store" not in text
    chunks = MarkdownChunker().chunk(converted_article("doc/build/orm/session.rst", converted))
    assert "".join(c.content for c in chunks) == text


def test_the_fixture_tutorial_and_index() -> None:
    tutorial = fixture("doc/build/tutorial.rst").body
    assert "```gherkin\nFeature: checkout" in tutorial
    assert "[install the runner](index.rst)" in tutorial
    assert "- **Given**: Put the system in a known state." in tutorial
    index = fixture("doc/build/index.rst")
    assert index.problems == ()
    assert "toctreeonlyentry" not in index.body
    assert "[the session guide](orm/session.rst)" in index.body


# --- paths and keys ---


@pytest.mark.parametrize(
    ("include", "path", "selected"),
    [
        ((), "doc/a.rst", True),
        ((), "doc/a.RST", True),
        ((), "doc/a.txt", False),
        (("doc/",), "doc/a.rst", True),
        (("doc/",), "doc/a.txt", False),
        (("doc/**/*.txt",), "doc/x/a.txt", True),
        (("doc/a.txt",), "doc/a.txt", True),
        (("doc/", "doc/*.txt"), "doc/a.txt", True),
        (("doc/",), "doc/conf.py", False),
    ],
)
def test_rst_files_are_articles_and_txt_only_when_named(
    include: tuple[str, ...], path: str, selected: bool
) -> None:
    assert PathSelection.of(include).selects(path) is selected


def test_restructuredtext_paths() -> None:
    assert is_restructuredtext("a/b.rst")
    assert is_restructuredtext("a/B.TXT")
    assert not is_restructuredtext("a/b.md")


def test_the_key_changes_with_every_input() -> None:
    base = converted_key("a.rst", "text", [("b.rst", "x")], "v1")
    assert len(base) == 64
    assert base != converted_key("b.rst", "text", [("b.rst", "x")], "v1")
    assert base != converted_key("a.rst", "text", [("b.rst", "y")], "v1")
    assert base != converted_key("a.rst", "text", [("b.rst", "x")], "v2")
    assert base == converted_key("a.rst", "text", [("b.rst", "x")], "v1")
