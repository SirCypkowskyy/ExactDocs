"""Guarantees every ``Chunker`` adapter must keep, checked on fixture articles and random ones."""

import itertools
import re
from collections.abc import Callable
from pathlib import Path

import markdown_it
import pytest
from markdown_it import MarkdownIt

from exactdocs.ingestion import models
from exactdocs.ingestion.adapters.driven.markdown_chunker import MarkdownChunker
from exactdocs.ingestion.errors import InvalidChunkingConfigError
from exactdocs.ingestion.models import ChunkingConfig, parse_article
from exactdocs.ingestion.ports import Chunker

ADAPTERS: list[Callable[[ChunkingConfig], Chunker]] = [MarkdownChunker]
TESTS = Path(__file__).parents[1]
ARTICLES = sorted(
    [
        *(TESTS / "ingestion" / "fixtures").rglob("*.md*"),
        *(TESTS / "fixtures").rglob("commits/**/*.md*"),
    ]
)
_NEWLINE = re.compile(r"\r\n|\r|\n")  # what Markdown counts as a line end, nothing else


@pytest.fixture(params=ADAPTERS, ids=["markdown"])
def chunker(request: pytest.FixtureRequest) -> Chunker:
    return request.param(ChunkingConfig())


def _parse(path: Path):
    try:
        return parse_article(path.name, path.read_text(encoding="utf-8", newline=""))
    except UnicodeDecodeError:
        pytest.skip("not UTF-8")


def _lines(text: str) -> list[str]:
    return text.replace("\r\n", "\n").split("\n")


def _check_never_split(chunker: Chunker, body: str) -> None:
    """Chunks are the body in pieces, and no fence or table crosses a chunk border."""
    article = parse_article("a.md", body)
    chunks = chunker.chunk(article)
    assert "".join(c.content for c in chunks) == article.body
    assert sum(len(_NEWLINE.findall(c.content)) for c in chunks) == len(
        _NEWLINE.findall(article.body)
    )
    starts, line = [], 0
    for chunk in chunks:
        starts.append(line)
        line += len(_NEWLINE.findall(chunk.content))
    for token in MarkdownIt("commonmark").enable("table").parse(article.body):
        if token.type in {"fence", "code_block", "table_open"} and token.map:
            first, last = token.map[0], token.map[1] - 1
            owner = max(i for i, s in enumerate(starts) if s <= first)
            end = starts[owner + 1] if owner + 1 < len(starts) else 10**9
            assert last < end, f"lines {first}-{last} cross a chunk border"


@pytest.mark.parametrize("path", ARTICLES, ids=lambda p: str(p.relative_to(TESTS)))
def test_fixture_articles_are_cut_losslessly_and_never_inside_code_or_tables(
    chunker: Chunker, path: Path
) -> None:
    _check_never_split(chunker, _parse(path).body)


def test_heading_path_of_the_docker_section() -> None:
    source = (TESTS / "fixtures/docs-repo/commits/v1.4.0/docs/guide/install.md").read_text()
    chunks = MarkdownChunker().chunk(parse_article("guide/install.md", source))

    paths = [" > ".join(c.heading_path) for c in chunks]
    assert paths == [
        "Guide",
        "Guide > Install",
        "Guide > Install > Docker",
        "Guide > Install > Docker > Troubleshooting",
        "Guide > Install > From source",
        "Guide > Install > From source > Troubleshooting",
    ]
    docker = chunks[2]
    assert docker.code_languages == ("bash",)
    assert docker.content.startswith("### Docker\n")
    assert [c.position for c in chunks] == list(range(6))


def test_text_before_the_first_heading_is_a_chunk_of_its_own(chunker: Chunker) -> None:
    chunks = chunker.chunk(parse_article("a.md", "Intro text.\n\n# One\n\nBody\n"))

    assert [(c.heading_path, c.content) for c in chunks] == [
        ((), "Intro text.\n\n"),
        (("One",), "# One\n\nBody\n"),
    ]


def test_repeated_headings_get_occurrence_indexes_and_unique_anchors(chunker: Chunker) -> None:
    chunks = chunker.chunk(parse_article("a.md", "# Top\n\n## Same\n\na\n\n## Same\n\nb\n"))

    same = [c for c in chunks if c.heading_path == ("Top", "Same")]
    assert [(c.occurrence_index, c.anchor) for c in same] == [(0, "same"), (1, "same-1")]


def test_headings_in_code_quotes_and_lists_do_not_start_chunks(chunker: Chunker) -> None:
    body = "# A\n\n```md\n# not a heading\n```\n\n> # quoted\n\n- # listed\n\nSetext\n---\n\nx\n"

    assert [c.heading_path for c in chunker.chunk(parse_article("a.md", body))] == [
        ("A",),
        ("A", "Setext"),
    ]


def test_heading_text_is_plain_and_skipped_levels_nest_under_the_nearest_parent(
    chunker: Chunker,
) -> None:
    body = "# The `retry_policy` *option*\n\n### Deep\n\n## Back\n"

    assert [c.heading_path for c in chunker.chunk(parse_article("a.md", body))] == [
        ("The retry_policy option",),
        ("The retry_policy option", "Deep"),
        ("The retry_policy option", "Back"),
    ]


def test_code_languages_are_the_first_word_of_each_fence_info_without_repeats(
    chunker: Chunker,
) -> None:
    body = (
        "# A\n\n```python title=x\n1\n```\n\n~~~bash\n2\n~~~\n\n```python\n3\n```\n\n```\n4\n```\n"
    )

    assert chunker.chunk(parse_article("a.md", body))[0].code_languages == ("python", "bash")


def test_content_hash_depends_on_content_only(chunker: Chunker) -> None:
    one = chunker.chunk(parse_article("a.md", "# A\n\nx\n"))[0]
    other = chunker.chunk(parse_article("b.md", "# A\n\nx\n"))[0]
    changed = chunker.chunk(parse_article("a.md", "# A\n\ny\n"))[0]

    assert one.content_hash == other.content_hash != changed.content_hash


def test_config_hash_covers_the_config_the_chunker_version_and_the_parser_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    default = MarkdownChunker().config_hash
    assert MarkdownChunker().config_hash == default
    assert MarkdownChunker(ChunkingConfig(split_depth=2)).config_hash != default

    monkeypatch.setattr(models, "PARSER_VERSION", models.PARSER_VERSION + 1)
    assert MarkdownChunker().config_hash != default


def test_split_depth_keeps_deeper_sections_in_their_parent() -> None:
    shallow = MarkdownChunker(ChunkingConfig(split_depth=2))
    body = "# A\n\n## B\n\n### C\n\ntext\n"

    assert [c.heading_path for c in shallow.chunk(parse_article("a.md", body))] == [
        ("A",),
        ("A", "B"),
    ]


def test_empty_article_has_no_chunks(chunker: Chunker) -> None:
    assert chunker.chunk(parse_article("a.md", "")) == ()


def _document(kinds: tuple[str, ...]) -> tuple[str, list[tuple[int, str]]]:
    """A document made of the given blocks, and its real headings as (level, text)."""
    table = "| a | b |\n| - | - |\n| 1\u2028 | 2 |\n\n"
    fence = "```py\n# looks like a heading\nx\u2029y\n\n## so does this\n```\n\n"
    headings, parts = [], []
    for i, kind in enumerate(kinds):
        if kind == "heading":
            level, text = (i * 2 + len(kinds)) % 6 + 1, ("Same", "Other")[i % 2]
            headings.append((level, text))
            parts.append(f"{'#' * level} {text}\n\n")
        else:
            parts.append({"text": "para\u2028graph\n\n", "fence": fence, "table": table}[kind])
    return "".join(parts), headings


def test_every_small_document_keeps_every_invariant(chunker: Chunker) -> None:
    kinds = ("heading", "text", "fence", "table")
    for size in range(1, 5):
        for combination in itertools.product(kinds, repeat=size):
            body, headings = _document(combination)
            _check_never_split(chunker, body)
            for chunk in chunker.chunk(parse_article("a.md", body)):
                # independent of Markdown parsing: fences come in pairs, tables in whole
                assert chunk.content.count("```") % 2 == 0, body
                assert chunk.content.count("| a | b |") == chunk.content.count("| 1\u2028 | 2 |")

            expected, stack = [], []
            for level, text in headings:
                stack = [(lv, t) for lv, t in stack if lv < level] + [(level, text)]
                expected.append(tuple(t for _, t in stack))
            chunks = chunker.chunk(parse_article("a.md", body))
            assert [c.heading_path for c in chunks if c.heading_path] == expected, body


def test_unicode_line_separators_do_not_shift_the_cuts(chunker: Chunker) -> None:
    body = (
        "# A\n\n```\nx\u2028y\u2029z\n```\n\n## B\n\n| a | b |\n|---|---|\n| 1\u2028 | 2 |\n"
        "| 3 | 4 |\n\n## C\n"
    )
    chunks = chunker.chunk(parse_article("a.md", body))

    assert [c.heading_path for c in chunks] == [("A",), ("A", "B"), ("A", "C")]
    assert chunks[0].content.endswith("```\n\n")
    assert chunks[1].content.endswith("| 3 | 4 |\n\n")


def test_anchors_are_unique_like_github_slugger(chunker: Chunker) -> None:
    chunks = chunker.chunk(parse_article("a.md", "# A\n\n## b-1\n\n## b\n\n## b\n"))

    assert [c.anchor for c in chunks] == ["a", "b-1", "b", "b-2"]


def test_headings_that_start_no_chunk_still_take_an_anchor() -> None:
    body = "# A\n\n> # Foo\n\n## Foo\n\n### Deep\n\n## Deep\n"
    shallow = MarkdownChunker(ChunkingConfig(split_depth=2))

    assert [(c.heading_path, c.anchor) for c in shallow.chunk(parse_article("a.md", body))] == [
        (("A",), "a"),
        (("A", "Foo"), "foo-1"),
        (("A", "Deep"), "deep-1"),
    ]


def test_a_multi_line_heading_reads_as_one_line(chunker: Chunker) -> None:
    chunks = chunker.chunk(parse_article("a.md", "Foo\nbar\n===\n\nHard  \nbreak\n---\n"))

    assert [(c.heading_path, c.anchor) for c in chunks] == [
        (("Foo bar",), "foo-bar"),
        (("Foo bar", "Hard break"), "hard-break"),
    ]


def test_malformed_front_matter_is_text_before_the_first_heading(chunker: Chunker) -> None:
    article = parse_article("a.md", "---\ntitle: [\n---\n# A\n\nx\n")
    assert article.problems

    chunks = chunker.chunk(article)

    assert [(c.heading_path, c.content) for c in chunks] == [
        ((), "---\ntitle: [\n---\n"),
        (("A",), "# A\n\nx\n"),
    ]


def test_a_blank_body_is_one_chunk_and_an_empty_one_has_none(chunker: Chunker) -> None:
    assert [c.content for c in chunker.chunk(parse_article("a.md", "\n\n"))] == ["\n\n"]
    assert chunker.chunk(parse_article("a.md", "")) == ()


def test_code_language_is_the_bare_language_name(chunker: Chunker) -> None:
    body = "```{.python}\n1\n```\n\n```js{1,3}\n2\n```\n\n```c++\n3\n```\n"

    assert chunker.chunk(parse_article("a.md", body))[0].code_languages == ("python", "js", "c++")


def test_config_hash_covers_the_markdown_engine_version(monkeypatch: pytest.MonkeyPatch) -> None:
    default = MarkdownChunker().config_hash
    monkeypatch.setattr(markdown_it, "__version__", "0.0.1")

    assert MarkdownChunker().config_hash != default


def test_split_depth_out_of_range_is_a_domain_error() -> None:
    with pytest.raises(InvalidChunkingConfigError):
        ChunkingConfig(split_depth=7)
