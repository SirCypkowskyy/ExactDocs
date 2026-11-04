"""Steps for query-docs, over the fixture repository imported in search_steps."""

import re

from behave import given, then, when
from behave.runner import Context

from exactdocs.retrieval.adapters.driving.mcp import SECTION_SEPARATOR
from exactdocs_kernel import NOTICE
from fixture_repo import git_bytes
from steps.mcp_steps import call_tool

TWO_BLOCKS = 2
BROAD_QUERY = "the a to is of retry token install client docs guide"


def _only_in(context: Context, ref: str) -> list[str]:
    """Lines of ``ref``'s docs that no other imported version has."""
    git, repo = context.fixture_git, context.fixture_repo.path
    others = {r for r in ("v1.3.0", "v1.4.0") if r != ref}

    def lines(version: str) -> set[str]:
        files = git("ls-tree", "-r", "--name-only", version, "--", "docs", cwd=repo).splitlines()
        return {
            line.strip()
            for f in files
            if f.endswith((".md", ".mdx"))
            for line in git_bytes("show", f"{version}:{f}", cwd=repo)
            .decode(errors="ignore")
            .splitlines()
            if len(line.strip()) > 20  # ruff: ignore[magic-value-comparison] - skip short lines like fences
        }

    return sorted(lines(ref).difference(*(lines(o) for o in others)))


def _payload(context: Context) -> str:
    return context.mcp_result.content[1].text


@given("the size budget is {tokens:d} tokens")
def step_budget(context: Context, tokens: int) -> None:
    context.settings = context.settings.model_copy(update={"query_docs_token_budget": tokens})


@when('an agent calls "query-docs" with libraryId "{library}" and query "{query}"')
def step_query(context: Context, library: str, query: str) -> None:
    call_tool(context, "query-docs", {"libraryId": library, "query": query}, raise_on_error=False)


@when(
    'an agent calls "query-docs" with libraryId "{library}", query "{query}" and language "{lang}"'
)
def step_query_language(context: Context, library: str, query: str, lang: str) -> None:
    call_tool(
        context,
        "query-docs",
        {"libraryId": library, "query": query, "language": lang},
        raise_on_error=False,
    )


@when('an agent calls "query-docs" with a broad query')
def step_broad(context: Context) -> None:
    step_query(context, "/fixture/docs-repo", BROAD_QUERY)


@then('no text that exists only in "{ref}" is returned')
def step_no_text(context: Context, ref: str) -> None:
    assert not context.mcp_result.is_error, context.mcp_result
    only = _only_in(context, ref)
    assert only, "the fixture has nothing unique to " + ref
    leaked = [line for line in only if line in _payload(context)]
    assert not leaked, leaked


@then('the payload contains text that exists only in "{ref}"')
def step_has_text(context: Context, ref: str) -> None:
    only = _only_in(context, ref)
    assert any(line in _payload(context) for line in only), _payload(context)


@then('the call fails with "{code}"')
def step_fails(context: Context, code: str) -> None:
    assert context.mcp_result.is_error
    assert context.mcp_result.content[0].text.startswith(f"{code}:"), context.mcp_result.content


@then("the payload is at most {limit:d} characters")
def step_limit(context: Context, limit: int) -> None:
    assert _payload(context).strip(), "an empty payload proves nothing"
    # Everything the agent receives: the notice block and the documentation block.
    total = sum(len(block.text) for block in context.mcp_result.content)
    assert total <= limit, total


@then("the payload holds whole chunks only")
def step_whole(context: Context) -> None:
    *blocks, last = _payload(context).split(SECTION_SEPARATOR)
    # The last part is either a block or the line saying how many matches were left out.
    if not last.endswith("did not fit the size budget; narrow the query."):
        blocks.append(last)
    assert blocks
    for block in blocks:
        assert block.startswith("### "), block[:80]
        assert "\n\nChunk: " in block, block[:200]
        assert block.count("```") % 2 == 0, block  # no code fence was cut in half


@then("the first block has a python code block")
def step_first_python(context: Context) -> None:
    first = _payload(context).split(SECTION_SEPARATOR)[0]
    assert re.search(r"^```python", first, re.MULTILINE), first


@then("the result has two text blocks: the notice, then the documentation")
def step_two(context: Context) -> None:
    content = context.mcp_result.content
    assert len(content) == TWO_BLOCKS, content
    assert content[0].text == NOTICE
    assert context.mcp_data is None
