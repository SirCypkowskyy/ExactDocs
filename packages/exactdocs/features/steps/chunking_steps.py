"""Steps for the heading-based chunker, run on articles of the fixture docs repository."""

from unittest.mock import patch

from behave import given, then, when
from behave.runner import Context

from exactdocs.ingestion import models
from exactdocs.ingestion.adapters.driven.markdown_chunker import MarkdownChunker
from exactdocs.ingestion.models import ArticleChunk, parse_article


def _find(context: Context, path: str) -> ArticleChunk:
    wanted = tuple(path.split(" > "))
    (chunk,) = [c for c in context.chunks if c.heading_path == wanted]
    return chunk


@when('I chunk "{path}" of version "{version}"')
def step_chunk(context: Context, path: str, version: str) -> None:
    source = context.fixture_git("show", f"{version}:{path}", cwd=context.fixture_repo.path)
    context.chunks = MarkdownChunker().chunk(parse_article(path, source))


@then('there is a chunk with the heading path "{path}"')
def step_has_path(context: Context, path: str) -> None:
    context.chunk = _find(context, path)


@then('that chunk keeps its fenced "{language}" block whole')
def step_fence(context: Context, language: str) -> None:
    text = context.chunk.content
    assert context.chunk.code_languages == (language,)
    fences = text.count("```")
    assert fences % 2 == 0, text  # every opening fence is closed in the same chunk


@then('the chunk "{path}" holds the whole platform table')
def step_table(context: Context, path: str) -> None:
    text = _find(context, path).content
    assert "| Platform " in text
    assert "| Windows  | partial   | use WSL" in text


@then('the chunks "{first}" and "{second}" have anchors "{a}" and "{b}"')
def step_anchors(context: Context, first: str, second: str, a: str, b: str) -> None:
    assert (_find(context, first).anchor, _find(context, second).anchor) == (a, b)


@given("the parser version is bumped")
def step_bump(context: Context) -> None:
    context.before = MarkdownChunker().config_hash
    patcher = patch.object(models, "PARSER_VERSION", models.PARSER_VERSION + 1)
    patcher.start()
    context.add_cleanup(patcher.stop)


@then("the chunking-config hash differs from before")
def step_differs(context: Context) -> None:
    assert MarkdownChunker().config_hash != context.before


# Issue #430: the Azure storage docs open fences so; the import failed with an IndexError.
BLANK_FENCES = "# Storage\n\n```   \naz storage account list\n```\n\n~~~\t\necho x\n~~~\n"


@given('the article "{path}" has code fences with only spaces or a tab after the backticks')
def step_blank_fences(context: Context, path: str) -> None:
    context.article = parse_article(path, BLANK_FENCES)


@when('I chunk the article "{path}"')
def step_chunk_article(context: Context, path: str) -> None:
    assert context.article.path == path
    context.chunks = MarkdownChunker().chunk(context.article)


@then("its only chunk holds every fence and names no code language")
def step_no_language(context: Context) -> None:
    (chunk,) = context.chunks
    assert chunk.content == BLANK_FENCES, chunk.content
    assert chunk.code_languages == ()


# Issue #562: MkDocs (attr_list) and Docusaurus set heading ids so; they stayed in the heading text.
ATTRIBUTE_LISTS = "# Async Tests { #async-tests }\n\nIntro.\n\n## HTTPX { #httpx }\n\nUse it.\n"


@given('the article "{path}" sets its heading ids with attribute lists')
def step_attribute_lists(context: Context, path: str) -> None:
    context.article = parse_article(path, ATTRIBUTE_LISTS)


@then('that chunk has the anchor "{anchor}"')
def step_chunk_anchor(context: Context, anchor: str) -> None:
    assert context.chunk.anchor == anchor, context.chunk.anchor


@then("that chunk still holds its heading as written")
def step_verbatim_heading(context: Context) -> None:
    assert context.chunk.content.startswith("## HTTPX { #httpx }\n"), context.chunk.content
