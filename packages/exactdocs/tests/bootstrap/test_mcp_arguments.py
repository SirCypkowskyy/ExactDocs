"""The MCP tools accept the arguments agents actually send (#573), through the real server.

Each case is one of the tool errors gpt-oss:120b hit in the agent benchmark's recorded run (PR
#572): an empty optional argument, a limit above the maximum, `path_prefix` on `search_docs`, a
library's name where its ID goes, a path the version does not have, and an argument the tool does
not have (still refused, but the error names the real ones). And from the run for #575 (#606): a
ref written with a `v` for a version imported without one, and a ref the library does not have.
"""

import hashlib
from typing import Any

import pytest
from fastmcp import Client

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.mcp import build_mcp
from exactdocs.bootstrap.settings import Settings
from exactdocs.catalog.dtos import ActivateManifestCommand, ArticleIn, StoreManifestCommand
from exactdocs.catalog.models import RefKind
from exactdocs.retrieval.dtos import ArticleChunksIn, ChunkIn, IndexManifestCommand

pytestmark = pytest.mark.usefixtures("demo_catalog")

LIB = "/acme/payments"
LEDGER = "/acme/ledger"
ARTICLES = {
    "docs/api/client.md": "The client retries payments with retry_policy.",
    "docs/api/server.md": "The server checks every retry_policy it gets.",
    "docs/guide/install.md": "Install the SDK; retry_policy defaults to three tries.",
    "docs/usage/models.md": "Models describe a payment.",
}


async def publish(
    container: Container,
    articles: dict[str, str],
    *,
    library: str = LIB,
    ref: str = "v1.4.0",
) -> dict[str, list[str]]:
    """Store, index and activate a version of one chunk per article; return chunk IDs by path."""
    stored = await container.catalog.store_manifest(
        StoreManifestCommand(
            library=library,
            ref=ref,
            kind=RefKind.TAG,
            commit_sha="b" * 40,
            articles=[
                ArticleIn(
                    path=path,
                    blob_sha=_blob(path, body),
                    content_version=1,
                    title=path,
                    content=f"# {path}\n\n{body}",
                )
                for path, body in articles.items()
            ],
        )
    )
    indexed = await container.retrieval.index_manifest(
        IndexManifestCommand(
            manifest_id=stored.manifest_id,
            library=library,
            ref=ref,
            config_hash="cfg",
            articles=[
                ArticleChunksIn(
                    path=path,
                    blob_sha=_blob(path, body),
                    chunks=[
                        ChunkIn(
                            heading_path=[path],
                            occurrence_index=0,
                            content=f"# {path}\n\n{body}",
                            content_hash=hashlib.sha256(body.encode()).hexdigest(),
                            anchor="a",
                        )
                    ],
                )
                for path, body in articles.items()
            ],
        )
    )
    await container.catalog.activate_manifest(
        ActivateManifestCommand(manifest_id=stored.manifest_id)
    )
    return indexed.chunk_ids


def _blob(path: str, body: str) -> str:
    return hashlib.sha1(f"# {path}\n\n{body}".encode(), usedforsecurity=False).hexdigest()


@pytest.fixture
def container() -> Container:
    return Container.build(Settings())


async def call(container: Container, tool: str, arguments: dict[str, Any]) -> Any:
    async with container.running(), Client(build_mcp(container)) as mcp:
        return await mcp.call_tool(tool, arguments, raise_on_error=False)


def text_of(result: Any) -> str:
    return "\n".join(getattr(c, "text", "") for c in result.content)


# ---------------------------------------------------------------- empty optional arguments
async def test_resolve_library_id_answers_an_empty_query_as_no_query(
    container: Container,
) -> None:
    async with container.running():
        await publish(container, ARTICLES)
    empty = await call(container, "resolve-library-id", {"libraryName": "payments", "query": ""})
    blank = await call(container, "resolve-library-id", {"libraryName": "payments", "query": " "})

    assert not empty.is_error, text_of(empty)
    assert "Context7-compatible library ID: /acme/payments" in empty.content[1].text
    assert empty.content[1].text == blank.content[1].text
    assert len(empty.content) == 2  # nothing was changed in the arguments: no notes


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("search_docs", {"library": LIB, "query": "retry_policy", "ref": "", "mode": ""}),
        ("search_docs", {"library": LIB, "query": "retry_policy", "path_prefix": "", "tags": None}),
        ("search_docs", {"library": LIB, "query": "retry_policy", "tags_match": None}),
        ("view_search", {"library": LIB, "query": "retry_policy", "ref": "", "path_prefix": ""}),
        ("search_all_docs", {"query": "retry_policy", "library": "", "path_prefix": ""}),
        ("list_articles", {"library": LIB, "ref": "", "cursor": "", "tags_match": ""}),
        ("list_libraries", {"cursor": "", "limit": None}),
        ("read_article", {"library": LIB, "path": "docs/guide/install.md", "ref": ""}),
        ("view_article", {"library": LIB, "path": "docs/guide/install.md", "ref": "  "}),
        ("article_outline", {"library": LIB, "path": "docs/guide/install.md", "ref": ""}),
        ("query-docs", {"libraryId": LIB, "query": "retry_policy", "language": ""}),
    ],
)
async def test_an_empty_optional_argument_counts_as_not_given_in_every_tool(
    container: Container, tool: str, arguments: dict[str, Any]
) -> None:
    async with container.running():
        await publish(container, ARTICLES)
    result = await call(container, tool, arguments)

    assert not result.is_error, text_of(result)


async def test_an_empty_required_argument_is_still_refused(container: Container) -> None:
    result = await call(container, "search_docs", {"library": LIB, "query": ""})

    assert result.is_error


# ---------------------------------------------------------------- limits
async def test_a_limit_above_the_maximum_is_clamped_and_the_result_says_so(
    container: Container,
) -> None:
    async with container.running():
        await publish(container, {f"docs/a{i:03}.md": "x" for i in range(205)})
    result = await call(container, "list_articles", {"library": LIB, "limit": 1000})

    assert not result.is_error, text_of(result)
    data = result.structured_content
    assert len(data["articles"]) == 200
    assert data["next_cursor"] is not None
    assert data["notes"] == ["limit 1000 is above the maximum of 200: 200 was used."]
    assert result.content[-1].text == "Notes: limit 1000 is above the maximum of 200: 200 was used."


@pytest.mark.parametrize(
    ("tool", "arguments", "note"),
    [
        (
            "search_docs",
            {"library": LIB, "query": "retry_policy", "limit": 500},
            "limit 500 is above the maximum of 50: 50 was used.",
        ),
        (
            "search_docs",
            {"library": LIB, "query": "retry_policy", "limit": 0},
            "limit 0 is below the minimum of 1: 1 was used.",
        ),
        (
            "search_all_docs",
            {"query": "retry_policy", "limit": "-3"},
            "limit -3 is below the minimum of 1: 1 was used.",
        ),
        (
            "list_libraries",
            {"limit": 1e4},
            "limit 10000 is above the maximum of 200: 200 was used.",
        ),
    ],
)
async def test_every_limit_out_of_range_is_clamped(
    container: Container, tool: str, arguments: dict[str, Any], note: str
) -> None:
    async with container.running():
        await publish(container, ARTICLES)
    result = await call(container, tool, arguments)

    assert not result.is_error, text_of(result)
    assert result.structured_content["notes"] == [note]
    if arguments.get("limit") == 0:
        assert len(result.structured_content["results"]) == 1


async def test_a_limit_in_range_adds_no_notes(container: Container) -> None:
    async with container.running():
        await publish(container, ARTICLES)
    result = await call(container, "search_docs", {"library": LIB, "query": "x", "limit": "3"})

    assert not result.is_error, text_of(result)
    assert "notes" not in result.structured_content


async def test_a_limit_that_is_no_number_is_still_refused(container: Container) -> None:
    result = await call(container, "list_articles", {"library": LIB, "limit": "all"})

    assert result.is_error


# ---------------------------------------------------------------- path_prefix
async def test_search_docs_keeps_the_hits_under_the_path_prefix(container: Container) -> None:
    async with container.running():
        await publish(container, ARTICLES)
    everywhere = await call(container, "search_docs", {"library": LIB, "query": "retry_policy"})
    api = await call(
        container,
        "search_docs",
        {"library": LIB, "query": "retry_policy", "path_prefix": "docs/api/"},
    )

    assert {r["article_path"] for r in everywhere.structured_content["results"]} == {
        "docs/api/client.md",
        "docs/api/server.md",
        "docs/guide/install.md",
    }
    found = api.structured_content
    assert {r["article_path"] for r in found["results"]} == {
        "docs/api/client.md",
        "docs/api/server.md",
    }
    assert found["coverage"] == {"candidates": 2, "reranked": 0, "complete": True}


async def test_a_path_prefix_is_a_directory_matched_literally(container: Container) -> None:
    async with container.running():
        await publish(container, ARTICLES | {"docs/api-old/legacy.md": "retry_policy was"})
    result = await call(
        container,
        "search_docs",
        {"library": LIB, "query": "retry_policy", "path_prefix": "docs/api"},
    )
    escape = await call(
        container, "search_docs", {"library": LIB, "query": "x", "path_prefix": "../docs"}
    )

    paths = {r["article_path"] for r in result.structured_content["results"]}
    assert paths == {"docs/api/client.md", "docs/api/server.md"}  # not docs/api-old
    assert escape.is_error


async def test_a_path_prefix_cuts_to_the_limit_and_says_more_exist(container: Container) -> None:
    async with container.running():
        await publish(container, ARTICLES)
    result = await call(
        container,
        "search_docs",
        {"library": LIB, "query": "retry_policy", "path_prefix": "docs/api", "limit": 1},
    )

    found = result.structured_content
    assert found["results"][0]["article_path"].startswith("docs/api/")
    assert len(found["results"]) == 1
    assert found["coverage"]["complete"] is False


async def test_view_search_and_search_all_docs_take_the_path_prefix(container: Container) -> None:
    async with container.running():
        await publish(container, ARTICLES)
        await publish(container, {"docs/api/ledger.md": "retry_policy"}, library=LEDGER, ref="main")
    view = await call(
        container,
        "view_search",
        {"library": LIB, "query": "retry_policy", "path_prefix": "docs/guide"},
    )
    across = await call(
        container, "search_all_docs", {"query": "retry_policy", "path_prefix": "docs/api"}
    )

    assert "docs/guide/install.md" in view.content[1].text
    assert "docs/api/client.md" not in view.content[1].text
    results = across.structured_content["results"]
    assert {(r["library"], r["article_path"]) for r in results} == {
        (LIB, "docs/api/client.md"),
        (LIB, "docs/api/server.md"),
        (LEDGER, "docs/api/ledger.md"),
    }
    assert across.structured_content["coverage"]["candidates"] == 3


# ---------------------------------------------------------------- library names
@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("search_docs", {"library": "Payments", "query": "retry_policy"}),
        ("search_all_docs", {"library": "payments", "query": "retry_policy"}),
        ("list_articles", {"library": "acme/payments"}),
        ("read_article", {"library": "PAYMENTS", "path": "docs/guide/install.md"}),
        ("article_outline", {"library": "payments", "path": "docs/guide/install.md"}),
        ("query-docs", {"libraryId": "Payments", "query": "retry_policy"}),
    ],
)
async def test_a_library_name_that_matches_one_library_is_resolved(
    container: Container, tool: str, arguments: dict[str, Any]
) -> None:
    async with container.running():
        await publish(container, ARTICLES)
        await publish(container, {"a.md": "retry_policy"}, library=LEDGER, ref="main")
    result = await call(container, tool, arguments)

    assert not result.is_error, text_of(result)
    name = arguments.get("library", arguments.get("libraryId"))
    assert "is a name, not an ID: resolved to '/acme/payments'." in text_of(result)
    assert repr(name) in text_of(result)
    if tool == "search_all_docs":
        assert {r["library"] for r in result.structured_content["results"]} == {LIB}


async def test_a_name_matching_several_libraries_lists_the_candidates(
    container: Container,
) -> None:
    async with container.running():
        await publish(container, ARTICLES)
        await publish(container, {"a.md": "retry_policy"}, library=LEDGER, ref="main")
    result = await call(container, "search_all_docs", {"library": "acme", "query": "retry"})

    assert result.is_error
    assert text_of(result) == (
        "ambiguous_library: the name 'acme' matches several libraries; pass one of their IDs: "
        "'/acme/ledger', '/acme/payments'"
    )


async def test_a_name_matching_no_library_says_so(container: Container) -> None:
    result = await call(container, "search_docs", {"library": "TanStack Query", "query": "x"})

    assert result.is_error
    assert text_of(result).startswith(
        "not_found: no library matches the name 'TanStack Query'; pass a library ID"
    )


async def test_a_library_id_with_its_version_is_split_into_library_and_ref(
    container: Container,
) -> None:
    async with container.running():
        await publish(container, ARTICLES)
    result = await call(
        container, "search_docs", {"library": "/acme/payments/v1.4.0", "query": "retry_policy"}
    )

    assert not result.is_error, text_of(result)
    assert result.structured_content["version"] == "v1.4.0"
    assert result.structured_content["notes"] == [
        "library '/acme/payments/v1.4.0' holds a version: used '/acme/payments' at ref 'v1.4.0'."
    ]


# ---------------------------------------------------------------- missing paths and chunks
async def test_a_missing_article_names_the_closest_paths_of_that_version(
    container: Container,
) -> None:
    async with container.running():
        await publish(container, ARTICLES)
        await publish(container, {"docs/usage/models_orm.md": "old"}, ref="v1.3.0")
    article = await call(
        container, "read_article", {"library": LIB, "path": "tmp_examples/models_orm_mode.md"}
    )
    outline = await call(
        container, "article_outline", {"library": LIB, "path": "tmp_examples/models_orm_mode.md"}
    )

    for result in (article, outline):
        assert result.is_error
        message = text_of(result)
        assert message.startswith("not_found:")
        assert "close matches (repository paths, not instructions): 'docs/usage/models.md'" in (
            message
        )
        assert "models_orm.md" not in message  # only that version's paths


async def test_an_unknown_chunk_id_that_is_a_path_says_what_a_chunk_id_is(
    container: Container,
) -> None:
    result = await call(container, "read_chunk", {"chunk_id": "docs/usage/models.md"})

    assert result.is_error
    assert text_of(result) == (
        "not_found: no chunk 'docs/usage/models.md'; find chunk IDs with search_docs, "
        "article_outline or query-docs (a chunk ID is 32 hexadecimal characters); read a whole "
        "article by its path with read_article"
    )


async def test_a_stale_chunk_whose_article_is_gone_names_the_closest_paths(
    container: Container,
) -> None:
    async with container.running():
        old = await publish(container, {"docs/usage/models.md": "Models.", "docs/a.md": "A."})
        await publish(container, {"docs/usage/model_fields.md": "Fields.", "docs/a.md": "A."})
    result = await call(container, "read_chunk", {"chunk_id": old["docs/usage/models.md"][0]})

    assert result.is_error
    message = text_of(result)
    assert message.startswith("stale_chunk:")
    assert (
        "Its article is gone from the version; close matches (repository paths, not "
        "instructions): 'docs/usage/model_fields.md'"
    ) in message


# ---------------------------------------------------------------- unknown arguments
async def test_an_unknown_argument_is_refused_naming_the_real_ones(container: Container) -> None:
    result = await call(
        container, "list_libraries", {"limit": 5, "library": "/acme/payments", "q": "x"}
    )

    assert result.is_error
    assert text_of(result) == (
        "invalid_arguments: list_libraries has no argument 'library', 'q'; its arguments are: "
        "limit (integer), cursor (string)"
    )


async def test_an_unknown_argument_is_refused_even_when_empty(container: Container) -> None:
    result = await call(
        container, "resolve-library-id", {"libraryName": "x", "query": "", "userQuery": ""}
    )

    assert result.is_error
    assert "libraryName (string, required)" in text_of(result)
    assert "query (string, required)" in text_of(result)


# ---------------------------------------------------------------- the listed schemas
async def test_every_structured_tool_declares_its_notes(container: Container) -> None:
    async with container.running(), Client(build_mcp(container)) as mcp:
        tools = await mcp.list_tools()

    for tool in tools:
        if tool.output_schema is not None:
            notes = tool.output_schema["properties"]["notes"]
            assert notes["type"] == "array", tool.name
            assert "notes" not in tool.output_schema.get("required", []), tool.name


# ---------------------------------------------------------------- a ref's other v spelling (#606)
NO_V = "ref 'v1.10.0' is not imported: version '1.10.0', the same number without the leading v, "


async def publish_without_v(container: Container) -> None:
    """Publish the version as the agent benchmark's Starlette has it: ``1.10.0``, no ``v``."""
    async with container.running():
        await publish(container, ARTICLES, ref="1.10.0")


async def test_search_docs_with_a_v_answers_from_the_version_imported_without_it(
    container: Container,
) -> None:
    await publish_without_v(container)

    result = await call(
        container, "search_docs", {"library": LIB, "ref": "v1.10.0", "query": "retry_policy"}
    )

    assert not result.is_error, text_of(result)
    data = result.structured_content
    assert (data["version"], len(data["results"])) == ("1.10.0", 3)
    assert data["notes"] == [NO_V + "answered."]
    assert result.content[-1].text == f"Notes: {NO_V}answered."


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("read_article", {"library": LIB, "ref": "v1.10.0", "path": "docs/guide/install.md"}),
        ("list_articles", {"library": LIB, "ref": "v1.10.0"}),
        ("article_outline", {"library": LIB, "ref": "v1.10.0", "path": "docs/guide/install.md"}),
        ("query-docs", {"libraryId": f"{LIB}/v1.10.0", "query": "retry_policy"}),
        ("search_docs", {"library": f"{LIB}/v1.10.0", "query": "retry_policy"}),
    ],
)
async def test_every_tool_that_takes_a_version_reads_its_other_spelling_and_says_so(
    container: Container, tool: str, arguments: dict[str, Any]
) -> None:
    await publish_without_v(container)

    result = await call(container, tool, arguments)

    assert not result.is_error, text_of(result)
    assert result.content[-1].text.startswith("Notes: "), text_of(result)
    assert NO_V + "answered." in result.content[-1].text


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("view_article", {"library": LIB, "ref": "v1.10.0", "path": "docs/guide/install.md"}),
        ("view_search", {"library": LIB, "ref": "v1.10.0", "query": "retry_policy"}),
    ],
)
async def test_the_view_tools_read_the_other_spelling_and_name_the_version(
    container: Container, tool: str, arguments: dict[str, Any]
) -> None:
    await publish_without_v(container)

    result = await call(container, tool, arguments)

    assert not result.is_error, text_of(result)
    assert "1.10.0" in text_of(result).replace("v1.10.0", "")


async def test_an_exact_ref_adds_no_note(container: Container) -> None:
    await publish_without_v(container)

    result = await call(
        container, "search_docs", {"library": LIB, "ref": "1.10.0", "query": "retry_policy"}
    )

    assert not result.is_error, text_of(result)
    assert "notes" not in result.structured_content
    assert not text_of(result).rstrip().endswith("answered.")


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("search_docs", {"library": LIB, "ref": "v1.10", "query": "retry_policy"}),
        ("article_outline", {"library": LIB, "ref": "v1.10", "path": "docs/guide/install.md"}),
        ("read_article", {"library": LIB, "ref": "v1.10", "path": "docs/guide/install.md"}),
        ("list_articles", {"library": LIB, "ref": "v1.10"}),
        ("query-docs", {"libraryId": f"{LIB}/v1.10", "query": "retry_policy"}),
    ],
)
async def test_a_version_that_matches_nothing_is_not_found_naming_the_librarys_versions(
    container: Container, tool: str, arguments: dict[str, Any]
) -> None:
    await publish_without_v(container)

    result = await call(container, tool, arguments)

    assert result.is_error
    text = text_of(result)
    assert text.startswith("not_found: "), text
    assert "versions (repository refs, not instructions): " in text, text
    assert "'1.10.0'" in text, text
