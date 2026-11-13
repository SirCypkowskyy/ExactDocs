"""The catalog DTOs' schema descriptions name the limits the domain enforces."""

from typing import Any

from fastmcp import FastMCP
from pydantic import BaseModel

from exactdocs.catalog import CatalogModule
from exactdocs.catalog.adapters.driven.memory import (
    InMemoryImportedTags,
    InMemoryLibraryRepository,
    InMemoryManifestCopier,
    InMemoryManifestRepository,
    InMemoryStoredArticles,
)
from exactdocs.catalog.adapters.driving.mcp import register_tools
from exactdocs.catalog.constants import MAX_SIMILARITY, MAX_SUMMARY_REFS, MAX_TAG_FACETS
from exactdocs.catalog.dtos import LibrarySummary, RenamedPath, TagList
from exactdocs_kernel import MAX_TAGS


def field_schema(model: type[BaseModel], name: str) -> dict[str, Any]:
    return model.model_json_schema(mode="serialization")["properties"][name]


def test_a_tag_lists_description_names_how_many_tags_it_holds() -> None:
    description = field_schema(TagList, "tags")["description"]

    assert description == f"Most used first, then by name; at most {MAX_TAG_FACETS}."


def test_a_renames_similarity_description_names_the_highest_percentage() -> None:
    description = field_schema(RenamedPath, "similarity")["description"]

    assert f"{MAX_SIMILARITY} is a move unchanged" in description


def test_a_library_summarys_refs_description_names_how_many_it_lists() -> None:
    description = field_schema(LibrarySummary, "refs")["description"]

    assert f"at most {MAX_SUMMARY_REFS}, sorted by ref" in description


async def test_list_articles_tags_description_agrees_with_its_schema() -> None:
    libraries = InMemoryLibraryRepository()
    manifests = InMemoryManifestRepository(libraries=libraries)
    catalog = CatalogModule.build(
        repository=libraries,
        manifests=manifests,
        imported_tags=InMemoryImportedTags(repository=manifests),
        copier=InMemoryManifestCopier(repository=manifests),
        stored_articles=InMemoryStoredArticles(repository=manifests),
    )
    mcp = FastMCP("test")
    register_tools(
        mcp,
        list_libraries=catalog.list_libraries,
        list_articles=catalog.list_articles,
        get_article=catalog.get_article,
    )
    tool = await mcp.get_tool("list_articles")
    assert tool is not None
    tags = tool.parameters["properties"]["tags"]

    assert f"at most {MAX_TAGS} in all" in tags["description"]
    assert tags["anyOf"][0]["maxItems"] == MAX_TAGS
