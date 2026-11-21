"""Guarantees every ``Chunker`` adapter must keep, checked on fixture articles and random ones."""

import hashlib
import itertools
import json
import random
import re
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import markdown_it
import pytest
from markdown_it import MarkdownIt

from exactdocs.ingestion import models
from exactdocs.ingestion.adapters.driven.markdown_chunker import MarkdownChunker
from exactdocs.ingestion.errors import InvalidChunkingConfigError
from exactdocs.ingestion.models import ArticleChunk, ChunkingConfig, parse_article
from exactdocs.ingestion.ports import Chunker
from exactdocs.retrieval.models import Chunk, ChunkSet, article_chunk_rows

ADAPTERS: list[Callable[[ChunkingConfig], Chunker]] = [MarkdownChunker]
# Every kind of setting a library can choose (LIB-09): the guarantees hold for each of them.
CONFIGS = [
    ChunkingConfig(),
    *(ChunkingConfig(split_depth=level) for level in range(1, models.MAX_HEADING_LEVEL)),
    ChunkingConfig(min_chars=200),
    ChunkingConfig(max_chars=300),
    ChunkingConfig(max_chars=1),
    ChunkingConfig(min_chars=100, max_chars=400),
    ChunkingConfig(split_depth=1, max_chars=200),
    ChunkingConfig(split_depth=2, min_chars=50, max_chars=120),
    ChunkingConfig(min_chars=models.MAX_CHUNK_CHARS),
    ChunkingConfig(max_section_chars=None),
    ChunkingConfig(max_section_chars=1),
    ChunkingConfig(max_section_chars=120),
    ChunkingConfig(min_chars=100, max_section_chars=150),
    ChunkingConfig(min_chars=30, max_section_chars=60),
    ChunkingConfig(split_depth=2, max_chars=300, max_section_chars=200),
]
CONFIG_IDS = [
    f"h{c.split_depth}-min{c.min_chars}-max{c.max_chars}-section{c.max_section_chars}-{c.chunker}"
    for c in CONFIGS
]
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


@pytest.fixture(params=CONFIGS, ids=CONFIG_IDS)
def any_chunker(chunker: Chunker, request: pytest.FixtureRequest) -> Chunker:
    """The adapter configured with each supported setting in turn."""
    return chunker.configured(request.param)


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
    any_chunker: Chunker, path: Path
) -> None:
    _check_never_split(any_chunker, _parse(path).body)


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


@pytest.mark.parametrize(
    ("info", "languages"),
    [
        (" ", ()),
        ("\t", ()),
        (" \t ", ()),
        ("  python  ", ("python",)),
        ("python {.class}", ("python",)),
        ("\tbash\ttitle=x", ("bash",)),
        ("{}", ()),
    ],
    ids=["space", "tab", "spaces-and-tab", "padded", "attributes", "tab-separated", "no-word"],
)
def test_a_fence_info_of_only_whitespace_names_no_language(
    chunker: Chunker, info: str, languages: tuple[str, ...]
) -> None:
    """Issue #430: ```` ``` ```` then blanks gave a non-empty info whose ``split()`` was empty."""
    for fence in ("```", "~~~"):
        body = f"# A\n\n{fence}{info}\nx = 1\n{fence}\n\nAfter.\n"

        (chunk,) = chunker.chunk(parse_article("a.md", body))

        assert chunk.code_languages == languages
        assert chunk.content == body


def test_config_hash_covers_the_markdown_engine_version(monkeypatch: pytest.MonkeyPatch) -> None:
    default = MarkdownChunker().config_hash
    monkeypatch.setattr(markdown_it, "__version__", "0.0.1")

    assert MarkdownChunker().config_hash != default


def test_split_depth_out_of_range_is_a_domain_error() -> None:
    with pytest.raises(InvalidChunkingConfigError):
        ChunkingConfig(split_depth=7)


_ANCHOR_VECTORS = json.loads((TESTS / "fixtures" / "heading_anchors.json").read_text("utf-8"))[
    "cases"
]


@pytest.mark.parametrize("case", _ANCHOR_VECTORS, ids=[c["name"] for c in _ANCHOR_VECTORS])
def test_anchors_match_the_shared_vectors(case: dict, chunker: Chunker) -> None:
    """The web renderer (anchors.test.ts) reads the same table, so search links land on headings."""
    chunks = chunker.chunk(parse_article("a.md", case["markdown"]))
    assert [c.anchor for c in chunks if c.heading_path] == case["anchors"]


def test_the_web_copy_of_the_anchor_vectors_is_identical() -> None:
    """The web build sees only ``web/``, so its test reads a copy (Biome formats it): same data."""
    copy = TESTS.parents[2] / "web/src/features/browse/render/fixtures/heading_anchors.json"
    original = json.loads((TESTS / "fixtures" / "heading_anchors.json").read_text("utf-8"))
    assert json.loads(copy.read_text("utf-8")) == original, (
        "cp packages/exactdocs/tests/fixtures/heading_anchors.json "
        "web/src/features/browse/render/fixtures/ && (cd web && pnpm format)"
    )


# ------------------------------------------------------------------ every supported setting

INSTALL = TESTS / "fixtures/docs-repo/commits/v1.4.0/docs/guide/install.md"


def _real_paths(body: str) -> set[tuple[str, ...]]:
    """The full heading path of every top-level heading, whatever the split level."""
    chunks = MarkdownChunker().chunk(parse_article("a.md", body))
    return {c.heading_path for c in chunks}


def test_every_setting_names_the_docker_section_within_its_heading_path(
    any_chunker: Chunker,
) -> None:
    chunks = any_chunker.chunk(parse_article("guide/install.md", INSTALL.read_text()))

    docker = next(c for c in chunks if "\n### Docker\n" in f"\n{c.content}")
    assert docker.heading_path == ("Guide", "Install", "Docker")[: len(docker.heading_path)]
    assert docker.heading_path  # never the text before the first heading
    assert {c.heading_path for c in chunks} <= _real_paths(INSTALL.read_text())


def test_every_setting_keeps_the_text_before_the_first_heading_apart(
    any_chunker: Chunker,
) -> None:
    chunks = any_chunker.chunk(parse_article("a.md", "Intro text.\n\n# One\n\nBody\n"))

    assert (chunks[0].heading_path, chunks[0].content) == ((), "Intro text.\n\n")


def test_every_setting_keeps_every_invariant_of_small_documents(any_chunker: Chunker) -> None:
    kinds = ("heading", "text", "fence", "table")
    for size in range(1, 5):
        for combination in itertools.product(kinds, repeat=size):
            body, _ = _document(combination)
            _check_never_split(any_chunker, body)
            chunks = any_chunker.chunk(parse_article("a.md", body))
            assert {c.heading_path for c in chunks} <= _real_paths(body) | {()}, body
            assert [c.position for c in chunks] == list(range(len(chunks)))
            _check_identities(chunks, body)


def _check_identities(chunks: Sequence[ArticleChunk], body: str) -> None:
    """Occurrences count sections per heading path; parts count up within a section."""
    seen: dict[tuple[str, ...], int] = {}
    before: ArticleChunk | None = None
    for chunk in chunks:
        if chunk.part:  # a later part of the section the chunk before started or continued
            assert before is not None, body
            assert (chunk.heading_path, chunk.occurrence_index, chunk.part) == (
                before.heading_path,
                before.occurrence_index,
                before.part + 1,
            ), body
        else:
            assert chunk.occurrence_index == seen.get(chunk.heading_path, 0), body
            seen[chunk.heading_path] = chunk.occurrence_index + 1
        before = chunk
    keys = [(c.heading_path, c.occurrence_index, c.part) for c in chunks]
    assert len(set(keys)) == len(keys), body


TINY = "# A\n\na\n\n## B\n\nb\n\n## C\n\n" + "c" * 60 + "\n\n## D\n\nd\n"


def _cut(config: ChunkingConfig, body: str) -> list[tuple[tuple[str, ...], int]]:
    chunks = MarkdownChunker(config).chunk(parse_article("a.md", body))
    return [(c.heading_path, len(c.content)) for c in chunks]


def test_sections_shorter_than_min_chars_merge_into_the_next_and_the_last_into_the_one_before():
    cut = _cut(ChunkingConfig(min_chars=20), TINY)

    # A + B are still under 20 characters, so C joins them; D is too short and has no next.
    assert [path for path, _ in cut] == [("A",)]
    assert [path for path, _ in _cut(ChunkingConfig(min_chars=10), TINY)] == [
        ("A",),  # A + B
        ("A", "C"),  # C + D: D is the last and too short
    ]


def test_merging_never_makes_a_chunk_longer_than_max_chars() -> None:
    cut = _cut(ChunkingConfig(min_chars=20, max_chars=40), TINY)

    assert [path for path, _ in cut] == [("A",), ("A", "C"), ("A", "D")]
    assert all(size <= 40 or path == ("A", "C") for path, size in cut)  # C alone is longer


def test_the_text_before_the_first_heading_is_never_merged() -> None:
    cut = _cut(ChunkingConfig(min_chars=500), "Intro.\n\n# A\n\na\n\n## B\n\nb\n")

    assert [path for path, _ in cut] == [(), ("A",)]


def test_a_chunk_longer_than_max_chars_is_cut_again_at_its_deeper_headings() -> None:
    body = "# A\n\n" + "a" * 50 + "\n\n## B\n\n" + "b" * 50 + "\n\n## C\n\nc\n"

    assert [path for path, _ in _cut(ChunkingConfig(split_depth=1), body)] == [("A",)]
    assert [path for path, _ in _cut(ChunkingConfig(split_depth=1, max_chars=80), body)] == [
        ("A",),
        ("A", "B"),  # B and C fit together
    ]


def test_a_long_section_without_deeper_headings_stays_whole() -> None:
    body = "# A\n\n```\n" + "x\n" * 100 + "```\n"

    assert _cut(ChunkingConfig(max_chars=10), body) == [(("A",), len(body))]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"min_chars": -1},
        {"max_chars": 0},
        {"min_chars": 10, "max_chars": 9},
        {"max_chars": models.MAX_CHUNK_CHARS + 1},
        {"max_section_chars": 0},
        {"max_section_chars": models.MAX_CHUNK_CHARS + 1},
        {"chunker": "chonkie"},
    ],
)
def test_chunking_settings_out_of_range_are_a_domain_error(kwargs: dict[str, Any]) -> None:
    with pytest.raises(InvalidChunkingConfigError):
        ChunkingConfig(**kwargs)


@pytest.mark.parametrize("kwargs", [{"max_chars": 101}, {"min_chars": 101}, {"min_chars": 200}])
def test_sizes_above_the_section_bound_are_refused_as_new_settings(kwargs: dict[str, Any]) -> None:
    config = ChunkingConfig(max_section_chars=100, **kwargs)  # one stored before still loads

    with pytest.raises(InvalidChunkingConfigError, match="must be at most 100"):
        config.refuse_sizes_above_section_bound()


@pytest.mark.parametrize(
    "config",
    [
        ChunkingConfig(max_section_chars=100, min_chars=100, max_chars=100),
        ChunkingConfig(max_section_chars=None, min_chars=50_000, max_chars=90_000),
        ChunkingConfig(),
    ],
)
def test_sizes_within_the_section_bound_are_accepted(config: ChunkingConfig) -> None:
    config.refuse_sizes_above_section_bound()


def _hash(*fields: object) -> str:
    """The config hash of a payload that starts with the parser and chunker versions."""
    payload = json.dumps(
        [models.PARSER_VERSION, models.CHUNKER_VERSION, *fields], separators=(",", ":")
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:32]


def test_without_a_section_bound_the_default_config_keeps_the_hash_from_before_sizes_existed():
    engine = f"markdown-it-py {markdown_it.__version__}"
    unbounded = MarkdownChunker(ChunkingConfig(max_section_chars=None))

    assert unbounded.config_hash == _hash(6, engine)


def test_the_default_config_hash_names_the_default_section_bound() -> None:
    engine = f"markdown-it-py {markdown_it.__version__}"
    default = f"sections-{models.DEFAULT_MAX_SECTION_CHARS}"

    assert MarkdownChunker().config_hash == _hash(6, engine, default)


@pytest.mark.parametrize(
    "config",
    [
        ChunkingConfig(min_chars=1),
        ChunkingConfig(max_chars=500),
        ChunkingConfig(split_depth=3),
        ChunkingConfig(max_section_chars=4000),
        ChunkingConfig(max_section_chars=None),
    ],
)
def test_every_setting_changes_the_config_hash(config: ChunkingConfig) -> None:
    assert MarkdownChunker().configured(config).config_hash != MarkdownChunker().config_hash


def test_a_chunker_this_adapter_does_not_provide_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(models, "CHUNKERS", frozenset({"markdown", "other"}))

    with pytest.raises(InvalidChunkingConfigError):
        MarkdownChunker().configured(ChunkingConfig(chunker="other"))


def _records(chunks: Sequence[ArticleChunk]) -> list[list[tuple[tuple[str, ...], str, bool]]]:
    """Each chunk's heading records as ``(heading path, anchor, starts chunk)``."""
    return [[(h.heading_path, h.anchor, h.starts_chunk) for h in c.headings or ()] for c in chunks]


def test_a_chunk_of_the_default_setting_records_the_one_heading_that_starts_it(
    chunker: Chunker,
) -> None:
    chunks = chunker.chunk(parse_article("guide/install.md", INSTALL.read_text()))

    assert _records(chunks) == [[(c.heading_path, c.anchor, True)] for c in chunks]


def test_merged_sections_record_every_heading_they_hold_in_order() -> None:
    chunks = MarkdownChunker(ChunkingConfig(min_chars=10)).chunk(parse_article("a.md", TINY))

    assert _records(chunks) == [
        [(("A",), "a", True), (("A", "B"), "b", False)],
        [(("A", "C"), "c", True), (("A", "D"), "d", False)],
    ]


def test_headings_below_the_split_level_are_recorded_with_their_own_anchors() -> None:
    body = "# A\n\n## Foo\n\n### Deep\n\n#### Deeper\n\n## Foo\n\n### Deep\n"
    chunks = MarkdownChunker(ChunkingConfig(split_depth=2)).chunk(parse_article("a.md", body))

    assert _records(chunks) == [
        [(("A",), "a", True)],
        [
            (("A", "Foo"), "foo", True),
            (("A", "Foo", "Deep"), "deep", False),
            (("A", "Foo", "Deep", "Deeper"), "deeper", False),
        ],
        [(("A", "Foo"), "foo-1", True), (("A", "Foo", "Deep"), "deep-1", False)],
    ]


def test_a_heading_merged_into_the_text_before_the_first_heading_does_not_start_it() -> None:
    body = "Intro.\n\n### Deep\n\nx\n\n# A\n\na\n"
    chunks = MarkdownChunker(ChunkingConfig(split_depth=2)).chunk(parse_article("a.md", body))

    assert [c.heading_path for c in chunks] == [(), ("A",)]
    assert _records(chunks) == [[(("Deep",), "deep", False)], [(("A",), "a", True)]]


def test_the_text_before_the_first_heading_records_no_heading(chunker: Chunker) -> None:
    chunks = chunker.chunk(parse_article("a.md", "Intro.\n\n# A\n\na\n"))

    assert _records(chunks) == [[], [(("A",), "a", True)]]
    assert all(c.headings is not None for c in chunks)


@pytest.mark.parametrize("path", ARTICLES, ids=lambda p: str(p.relative_to(TESTS)))
def test_every_setting_records_every_heading_the_default_one_cuts_at(
    any_chunker: Chunker, path: Path
) -> None:
    article = _parse(path)
    default = MarkdownChunker().chunk(article)
    chunks = any_chunker.chunk(article)

    every = [(c.heading_path, c.anchor) for c in default if c.heading_path]
    assert [(h[0], h[1]) for r in _records(chunks) for h in r] == every
    earlier: set[tuple[tuple[str, ...], str]] = set()  # headings recorded by the chunks so far
    for chunk, records in zip(chunks, _records(chunks), strict=True):
        starting = [(p, a) for p, a, starts in records if starts]
        if chunk.heading_path and not starting:  # a part after the first of a split section
            assert (chunk.heading_path, chunk.anchor) in earlier, records
        else:
            expected = [(chunk.heading_path, chunk.anchor)] if chunk.heading_path else []
            assert starting == expected, records
            assert not records or records[0][2] == bool(chunk.heading_path)
        earlier |= {(p, a) for p, a, _ in records}


def test_a_setting_that_can_merge_headings_changes_the_hash_it_had_before_heading_records() -> None:
    engine = f"markdown-it-py {markdown_it.__version__}"
    config = ChunkingConfig(min_chars=400)
    before = json.dumps(
        [models.PARSER_VERSION, models.CHUNKER_VERSION, 6, engine, 400, None, "markdown"],
        separators=(",", ":"),
    )

    hashed = MarkdownChunker().configured(config).config_hash
    assert hashed != hashlib.sha256(before.encode()).hexdigest()[:32]


@pytest.mark.parametrize("max_chars", [1, 50, 500])
def test_a_setting_that_cannot_merge_headings_keeps_the_hash_it_had_before_heading_records(
    max_chars: int,
) -> None:
    engine = f"markdown-it-py {markdown_it.__version__}"
    config = ChunkingConfig(max_chars=max_chars, max_section_chars=None)

    hashed = MarkdownChunker().configured(config).config_hash
    assert hashed == _hash(6, engine, 0, max_chars, "markdown")


@pytest.mark.parametrize("max_chars", [1, 50, 500])
@pytest.mark.parametrize("path", ARTICLES, ids=lambda p: str(p.relative_to(TESTS)))
def test_max_chars_alone_never_merges_headings(path: Path, max_chars: int) -> None:
    chunks = MarkdownChunker(ChunkingConfig(max_chars=max_chars)).chunk(_parse(path))

    assert all(h.starts_chunk for c in chunks for h in c.headings or ())


# ------------------------------------------------------------------ sections split at blocks (#141)


def _paragraphs(count: int, width: int = 40) -> str:
    """``count`` numbered paragraphs of ``width`` characters each, plus their blank line."""
    return "".join(f"{i:04d} {'p' * (width - 6)}\n\n" for i in range(count))


def _chunks(config: ChunkingConfig, body: str) -> Sequence[ArticleChunk]:
    return MarkdownChunker(config).chunk(parse_article("a.md", body))


def test_a_section_longer_than_the_bound_is_split_at_its_blocks_within_it() -> None:
    body = "# A\n\n" + _paragraphs(10) + "# B\n\nb\n"
    chunks = _chunks(ChunkingConfig(max_section_chars=100), body)
    parts = [c for c in chunks if c.heading_path == ("A",)]

    assert len(parts) > 1
    assert all(len(c.content) <= 100 for c in parts)
    assert "".join(c.content for c in parts) == "# A\n\n" + _paragraphs(10)
    assert all(c.content.startswith(("# A\n", "0")) for c in parts)  # each starts with a block
    assert [c.occurrence_index for c in parts] == [0] * len(parts)  # one section
    assert [c.part for c in parts] == list(range(len(parts)))
    assert {c.anchor for c in parts} == {"a"}
    assert chunks[-1].heading_path == ("B",)
    assert (chunks[-1].occurrence_index, chunks[-1].part, chunks[-1].content) == (
        0,
        0,
        "# B\n\nb\n",
    )
    _check_never_split(MarkdownChunker(ChunkingConfig(max_section_chars=100)), body)


def test_parts_fill_up_to_the_bound() -> None:
    body = "# A\n\n" + _paragraphs(9)  # the heading block is 5 characters, each paragraph 41
    chunks = _chunks(ChunkingConfig(max_section_chars=100), body)

    assert [len(c.content) for c in chunks] == [5 + 41 * 2, 41 * 2, 41 * 2, 41 * 2, 41]


def test_a_code_fence_longer_than_the_bound_is_never_split() -> None:
    fence = "```python\n" + "".join(f"line_{i} = {i}\n\n" for i in range(50)) + "```\n"
    body = "# A\n\nBefore.\n\n" + fence + "\nAfter.\n"
    chunks = _chunks(ChunkingConfig(max_section_chars=60), body)

    holding = [c for c in chunks if "```" in c.content]
    assert len(holding) == 1
    assert holding[0].content == fence + "\n"  # the block alone, longer than the bound
    assert holding[0].code_languages == ("python",)
    assert holding[0].heading_path == ("A",)
    assert [c.code_languages for c in chunks if c is not holding[0]] == [(), ()]
    assert "".join(c.content for c in chunks) == body


def test_a_table_longer_than_the_bound_is_never_split() -> None:
    table = "| key | value |\n|-----|-------|\n" + "".join(f"| k{i} | v{i} |\n" for i in range(40))
    body = "# A\n\nIntro.\n\n" + table + "\nOutro.\n"
    chunks = _chunks(ChunkingConfig(max_section_chars=50), body)

    (holding,) = [c for c in chunks if "| key |" in c.content]
    assert table in holding.content
    assert holding.content.count("|-----|") == 1
    assert "| k39 | v39 |" in holding.content
    _check_never_split(MarkdownChunker(ChunkingConfig(max_section_chars=50)), body)


def test_a_single_block_longer_than_the_bound_stays_whole() -> None:
    body = "# A\n\nShort.\n\n" + "word " * 500 + "\n"
    chunks = _chunks(ChunkingConfig(max_section_chars=100), body)

    assert [c.content for c in chunks] == ["# A\n\nShort.\n\n", "word " * 500 + "\n"]
    assert [(c.occurrence_index, c.part) for c in chunks] == [(0, 0), (0, 1)]


@pytest.mark.parametrize(
    "block",
    [
        "```python\n" + "".join(f"x_{i} = {i}\n\n" for i in range(40)) + "```\n",
        "| key | value |\n|-----|-------|\n" + "".join(f"| k{i} | v{i} |\n" for i in range(40)),
        "word " * 500 + "\n",
    ],
    ids=["fence", "table", "paragraph"],
)
def test_a_heading_is_never_left_alone_before_a_block_longer_than_the_bound(block: str) -> None:
    body = "## Reference\n\n" + block + "\nAfter.\n"
    chunks = _chunks(ChunkingConfig(max_section_chars=100), body)

    assert chunks[0].content == "## Reference\n\n" + block + "\n"  # heading and block together
    assert _records(chunks)[0] == [(("Reference",), "reference", True)]
    assert [c.content for c in chunks[1:]] == ["After.\n"]
    assert "".join(c.content for c in chunks) == body


def test_nested_blocks_split_only_between_top_level_ones() -> None:
    items = "".join(f"- item {i}\n\n  more of item {i}\n\n" for i in range(20))
    quote = "".join(f"> quoted {i}\n>\n" for i in range(20))
    body = "# A\n\n" + items + "Between.\n\n" + quote
    chunks = _chunks(ChunkingConfig(max_section_chars=40), body)

    assert chunks[0].content == "# A\n\n" + items  # the list is one block, after the heading
    assert any(c.content.startswith("> quoted 0") and "> quoted 19" in c.content for c in chunks)


def test_only_the_first_part_records_the_heading() -> None:
    body = "# A\n\n" + _paragraphs(10) + "## B\n\nb\n"
    chunks = _chunks(ChunkingConfig(max_section_chars=100), body)

    records = _records(chunks)
    assert records[0] == [(("A",), "a", True)]
    assert all(r == [] for r in records[1:-1])
    assert records[-1] == [(("A", "B"), "b", True)]


def test_the_ids_of_parts_are_unique_and_the_same_on_every_run() -> None:
    body = "# A\n\n" + _paragraphs(30) + "# A\n\n" + _paragraphs(30) + "# A\n\nlast\n"
    config = ChunkingConfig(max_section_chars=200)

    def identities() -> list[tuple[tuple[str, ...], int, int, str]]:
        """What a chunk ID is made of, for each chunk."""
        return [
            (c.heading_path, c.occurrence_index, c.part, c.content_hash)
            for c in _chunks(config, body)
        ]

    first = identities()
    assert first == identities()
    assert len({(path, occurrence, part) for path, occurrence, part, _ in first}) == len(first)
    # Each repeated heading is the next occurrence, however many parts the one before has.
    chunks = _chunks(config, body)
    assert [c.occurrence_index for c in chunks if c.content.startswith("# A\n")] == [0, 1, 2]
    assert all(c.part == 0 for c in chunks if c.content.startswith("# A\n"))
    assert max(c.part for c in chunks) > 1
    _check_identities(chunks, body)


def test_splitting_a_section_changes_no_later_section_with_the_same_heading() -> None:
    second = "## Example\n\nB\n"
    small = "## Example\n\nA\n\n" + second
    large = "## Example\n\n" + _paragraphs(10) + second
    config = ChunkingConfig(max_section_chars=100)

    before = _chunks(config, small)[-1]
    after = _chunks(config, large)[-1]
    assert len(_chunks(config, large)) > 2  # the first section was split
    assert (before.heading_path, before.occurrence_index, before.part, before.content_hash) == (
        after.heading_path,
        after.occurrence_index,
        after.part,
        after.content_hash,
    )


def test_the_text_before_the_first_heading_is_split_but_never_merged() -> None:
    body = "\n\n" + _paragraphs(10) + "# A\n\na\n"
    chunks = _chunks(ChunkingConfig(min_chars=90, max_section_chars=100), body)

    preamble = [c for c in chunks if not c.heading_path]
    assert len(preamble) > 1
    assert preamble[0].content.startswith("\n\n0000 ")  # the blank lines ride with the first
    assert [(c.occurrence_index, c.part) for c in preamble] == [
        (0, i) for i in range(len(preamble))
    ]
    assert "".join(c.content for c in preamble) == "\n\n" + _paragraphs(10)
    assert chunks[-1].heading_path == ("A",)


def test_deeper_headings_cut_a_group_longer_than_the_bound_before_its_blocks_do() -> None:
    body = "# A\n\n" + _paragraphs(2) + "## B\n\n" + _paragraphs(2) + "## C\n\nc\n"
    chunks = _chunks(ChunkingConfig(split_depth=1, max_section_chars=100), body)

    assert [c.heading_path for c in chunks] == [("A",), ("A", "B")]
    assert all(
        h.starts_chunk == (h.heading_path == c.heading_path)
        for c in chunks
        for h in c.headings or ()
    )


def test_merging_never_makes_a_chunk_longer_than_the_section_bound() -> None:
    chunks = _chunks(ChunkingConfig(min_chars=20, max_section_chars=40), TINY)

    assert [c.heading_path for c in chunks] == [("A",), ("A", "C"), ("A", "D")]
    assert all(len(c.content) <= 40 or c.heading_path == ("A", "C") for c in chunks)


def test_the_default_bound_splits_a_huge_section_and_none_keeps_it_whole() -> None:
    body = "# A\n\n" + _paragraphs(1000, width=200)  # about 200,000 characters

    default = _chunks(ChunkingConfig(), body)
    assert len(default) > 1
    assert all(len(c.content) <= models.DEFAULT_MAX_SECTION_CHARS for c in default)
    assert {c.heading_path for c in default} == {("A",)}
    assert [c.content for c in _chunks(ChunkingConfig(max_section_chars=None), body)] == [body]


def test_a_section_within_the_bound_is_not_split() -> None:
    body = "# A\n\n" + _paragraphs(3)

    assert [c.content for c in _chunks(ChunkingConfig(max_section_chars=len(body)), body)] == [body]


MDX_TABS = """<Tabs>
<TabItem value="npm">

```bash
npm install acme
```

Then run it.

</TabItem>
<TabItem value="yarn">

```bash
yarn add acme
```

</TabItem>
</Tabs>
"""


def test_an_mdx_component_holding_blank_lines_is_never_split() -> None:
    body = "## Install\n\nIntro.\n\n" + MDX_TABS + "\nAfter.\n\nMore after.\n"
    chunks = _chunks(ChunkingConfig(max_section_chars=15), body)

    (holding,) = [c for c in chunks if "<Tabs>" in c.content]
    assert MDX_TABS in holding.content
    assert "".join(c.content for c in chunks) == body
    assert chunks[-1].content == "More after.\n"  # cuts come back once the component closes
    _check_identities(chunks, body)


def test_a_closing_tag_inside_a_paragraph_still_closes_the_component() -> None:
    component = "<Note>\n\nFirst paragraph.\n\nSecond paragraph.\n</Note>\n"
    body = "## A\n\nIntro.\n\n" + component + "\nAfter.\n"
    chunks = _chunks(ChunkingConfig(max_section_chars=20), body)

    assert [c.content for c in chunks] == ["## A\n\nIntro.\n\n", component + "\n", "After.\n"]


def test_block_html_holding_blank_lines_is_never_split_but_inline_and_void_tags_do_not_count():
    details = "<details>\n<summary>More</summary>\n\nHidden text.\n\nMore hidden.\n\n</details>\n"
    inline = "A <span>word</span> and an image <img src='x.png'> and <br/>.\n"
    body = "## A\n\n" + inline + "\n" + details + "\n<Tab />\n\nEnd paragraph here.\n"
    chunks = _chunks(ChunkingConfig(max_section_chars=20), body)

    (holding,) = [c for c in chunks if "<details>" in c.content]
    assert details in holding.content
    assert chunks[-1].content == "End paragraph here.\n"
    assert "".join(c.content for c in chunks) == body


def test_a_component_never_closed_keeps_only_the_rest_of_its_section_whole() -> None:
    body = "## A\n\n<Tabs>\n\n" + _paragraphs(5) + "## B\n\n" + _paragraphs(5)
    chunks = _chunks(ChunkingConfig(max_section_chars=100), body)

    assert len([c for c in chunks if c.heading_path == ("A",)]) == 1
    assert len([c for c in chunks if c.heading_path == ("B",)]) > 1


def test_a_tag_in_an_html_comment_does_not_count() -> None:
    body = "## A\n\n<!-- <Tabs>\n\nnot open -->\n\n" + _paragraphs(5)
    chunks = _chunks(ChunkingConfig(max_section_chars=100), body)

    assert len(chunks) > 1


def test_inline_html_in_running_text_does_not_stop_the_split() -> None:
    for opening in (
        "The method returns a Promise<Response> object.\n\n",
        "Wrap it in <Note> tags.\n\n",
        "A <details> block follows.\n\n",
        "Returns a\nPromise<Response> or <Note> when\nit fails.\n\n",  # mid-line, not first
    ):
        body = "## A\n\n" + opening + _paragraphs(40)
        chunks = _chunks(ChunkingConfig(max_section_chars=1000), body)

        assert len(chunks) > 1, opening
        assert all(len(c.content) <= 1000 for c in chunks), opening
        assert "".join(c.content for c in chunks) == body


def test_a_tag_that_starts_a_line_of_a_paragraph_still_opens_a_component() -> None:
    body = "## A\n\nIntro.\n<Note>\n\n" + _paragraphs(5) + "Closing words.\n</Note>\n\nAfter.\n"
    chunks = _chunks(ChunkingConfig(max_section_chars=60), body)

    (holding,) = [c for c in chunks if "<Note>" in c.content]
    assert "</Note>" in holding.content
    assert chunks[-1].content == "After.\n"


def _rows(chunks: Sequence[ArticleChunk]) -> None:
    """Index the chunks as one article of a manifest; raises when two get the same ID."""
    chunk_set = ChunkSet(
        blob_sha="b",
        config_hash="h",
        chunks=tuple(
            Chunk(
                heading_path=c.heading_path,
                occurrence_index=c.occurrence_index,
                part=c.part,
                content=c.content,
                content_hash=c.content_hash,
                anchor=c.anchor,
            )
            for c in chunks
        ),
    )
    article_chunk_rows("/o/r/main", "a.md", chunk_set, ())


FENCE_60 = "```\n" + "c\n" * 40 + "```\n\n"


def test_the_first_part_of_a_split_section_is_never_merged_into_the_chunk_before() -> None:
    body = "# A\n\nshort\n\n# B\n\nb\n\n" + FENCE_60 + "# B\n\nb2\n\n" + FENCE_60
    chunks = _chunks(ChunkingConfig(max_section_chars=60, min_chars=30), body)

    assert [(c.heading_path, c.occurrence_index, c.part, c.content) for c in chunks] == [
        (("A",), 0, 0, "# A\n\nshort\n\n"),
        (("B",), 0, 0, "# B\n\nb\n\n"),
        (("B",), 0, 1, FENCE_60),
        (("B",), 1, 0, "# B\n\nb2\n\n"),
        (("B",), 1, 1, FENCE_60),
    ]
    _check_identities(chunks, body)
    _rows(chunks)  # no DuplicateChunkError: the two fences are two chunk IDs


def test_a_repeated_heading_after_a_merge_takes_the_next_occurrence_for_every_part() -> None:
    body = "# A\n\nshort\n\n# A\n\nshort2\n\n" + FENCE_60
    chunks = _chunks(ChunkingConfig(max_section_chars=60, min_chars=30), body)

    assert [(c.heading_path, c.occurrence_index, c.part) for c in chunks] == [
        (("A",), 0, 0),
        (("A",), 1, 0),
        (("A",), 1, 1),
    ]
    _check_identities(chunks, body)


_RANDOM_BLOCKS: list[Callable[[random.Random], str]] = [
    lambda r: "word " * r.randint(1, 30) + "\n\n",
    lambda r: "```py\n" + "x = 1\n\n" * r.randint(1, 20) + "```\n\n",
    lambda r: "| a |\n|---|\n" + "| b |\n" * r.randint(1, 10) + "\n",
    lambda _: "- a\n\n  more\n\n- b\n\n",
    lambda r: "<Tabs>\n<TabItem>\n\n" + "word " * r.randint(1, 20) + "\n\n</TabItem>\n</Tabs>\n\n",
    lambda _: "Returns Promise<Response> here.\n\n",
    lambda r: f"{'#' * r.randint(1, 3)} {r.choice('AB')}\n\n",
    lambda r: f"{'#' * r.randint(1, 3)} {r.choice('AB')}\n\n",
]


def test_random_documents_keep_every_invariant_whatever_min_chars_merges() -> None:
    rng = random.Random(141)  # ruff: ignore[suspicious-non-cryptographic-random-usage]
    for _ in range(400):
        body = "".join(rng.choice(_RANDOM_BLOCKS)(rng) for _ in range(rng.randint(1, 25)))
        config = ChunkingConfig(
            max_section_chars=rng.randint(1, 400),
            min_chars=rng.randint(1, 100),
            split_depth=rng.randint(1, 6),
        )
        chunker = MarkdownChunker(config)
        _check_never_split(chunker, body)
        chunks = chunker.chunk(parse_article("a.md", body))
        _check_identities(chunks, f"{config}\n{body}")
        _rows(chunks)
