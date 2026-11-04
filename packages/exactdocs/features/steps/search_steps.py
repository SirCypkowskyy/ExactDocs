"""Steps for search: the fixture docs repository is imported through the driving ports."""

import asyncio
import fnmatch
import hashlib
from itertools import starmap
from urllib.parse import quote

from behave import given, then, when
from behave.runner import Context

from exactdocs.bootstrap.container import Container
from exactdocs.catalog.adapters.driven.sqlite import SqliteLibraryRepository
from exactdocs.catalog.dtos import ActivateManifestCommand, ArticleIn, StoreManifestCommand
from exactdocs.catalog.models import HostKind, Library, LibraryId, RefKind, VersionRef
from exactdocs.ingestion.adapters.driven.markdown_chunker import MarkdownChunker
from exactdocs.ingestion.models import parse_article
from exactdocs.retrieval.dtos import ArticleChunksIn, ChunkIn, IndexManifestCommand
from steps.http_steps import step_running

LIBRARY = "/fixture/docs-repo"
REPOSITORY = "https://github.com/fixture/docs-repo"
SKIPPED_DIRECTORIES = (
    "docs/reference/oversized.md",
    "docs/legacy/",
    "docs/archive/",
    "docs/assets/",
)
# What the library's tag rules would add on import (the fixture's front matter has no `api`).
TAG_RULES = {"docs/api/**": "api"}
LOCATION_FIELDS = [
    "chunk_id",
    "article_path",
    "heading_path",
    "position",
    "total",
    "prev_chunk_id",
    "next_chunk_id",
    "commit_sha",
    "source_url",
    "anchor",
]


def _git_blob_sha(content: str) -> str:
    data = content.encode()
    return hashlib.sha1(b"blob %d\0" % len(data) + data, usedforsecurity=False).hexdigest()


def _read_version(context: Context, ref: str) -> tuple[str, list[tuple[str, str]]]:
    """Return the commit and the (path, text) of every article the importer would take."""
    repo, git = context.fixture_repo.path, context.fixture_git
    commit = git("rev-parse", ref, cwd=repo)
    articles = []
    for path in git("ls-tree", "-r", "--name-only", ref, "--", "docs", cwd=repo).splitlines():
        if not path.endswith((".md", ".mdx")) or path.startswith(SKIPPED_DIRECTORIES):
            continue
        try:
            text = git("show", f"{ref}:{path}", cwd=repo)
        except UnicodeDecodeError:
            continue
        articles.append((path, text))
    return commit, articles


async def _import(context: Context, refs: list[str]) -> None:
    container = Container.build(context.settings)
    chunker = MarkdownChunker()
    async with container.running():
        await SqliteLibraryRepository(container.engine).save(
            Library(
                id=LibraryId(LIBRARY),
                title="Docs repo",
                source_url=REPOSITORY,
                host=HostKind.GITHUB,
                default_branch=VersionRef("main"),
            )
        )
        for ref in refs:
            commit, files = _read_version(context, ref)
            parsed = list(starmap(parse_article, files))
            stored = await container.catalog.store_manifest(
                StoreManifestCommand(
                    library=LIBRARY,
                    ref=ref,
                    kind=RefKind.TAG,
                    commit_sha=commit,
                    articles=[
                        ArticleIn(
                            path=a.path,
                            blob_sha=_git_blob_sha(text),
                            content_version=1,
                            title=a.title,
                            tags=_tags(a.path, a.tags),
                            content=a.body,
                        )
                        for a, (_, text) in zip(parsed, files, strict=True)
                    ],
                )
            )
            await container.retrieval.index_manifest(
                IndexManifestCommand(
                    manifest_id=stored.manifest_id,
                    library=LIBRARY,
                    ref=ref,
                    config_hash=chunker.config_hash,
                    articles=[
                        ArticleChunksIn(
                            path=a.path,
                            blob_sha=_git_blob_sha(text),
                            tags=_tags(a.path, a.tags),
                            chunks=[
                                ChunkIn(
                                    heading_path=list(c.heading_path),
                                    occurrence_index=c.occurrence_index,
                                    content=c.content,
                                    content_hash=c.content_hash,
                                    anchor=c.anchor,
                                    code_languages=list(c.code_languages),
                                )
                                for c in chunker.chunk(a)
                            ],
                        )
                        for a, (_, text) in zip(parsed, files, strict=True)
                    ],
                )
            )
            await container.catalog.activate_manifest(
                ActivateManifestCommand(manifest_id=stored.manifest_id)
            )
            context.commits = getattr(context, "commits", {}) | {ref: commit}


def _tags(path: str, declared: tuple[str, ...]) -> list[str]:
    ruled = [tag for pattern, tag in TAG_RULES.items() if fnmatch.fnmatch(path, pattern)]
    return sorted({*declared, *ruled})


@given('ExactDocs is running with the fixture docs repository imported at "{first}" and "{second}"')
def step_imported(context: Context, first: str, second: str) -> None:
    step_running(context)
    asyncio.run(_import(context, [first, second]))


def _search(context: Context, target: str, params: dict[str, object]) -> None:
    owner, repo, *ref = target.removeprefix("/").split("/", 2)
    if ref:
        params = {"ref": ref[0], **params}
    path = f"/api/v1/libraries/{owner}/{repo}/search"
    context.response = context.client.get(path, params={"q": params.pop("q"), **params})
    context.searched = target


@when('a user searches "{target}" for "{query}"')
def step_search(context: Context, target: str, query: str) -> None:
    _search(context, target, {"q": query})


@when('a user searches "{query}" in "{target}" with all of tags "{tags}"')
def step_search_tags(context: Context, query: str, target: str, tags: str) -> None:
    wanted = tags.split(", ")
    _search(context, target, {"q": query, "tags": wanted, "tags_match": "all"})
    context.wanted_tags = wanted


@then('the result is explicitly empty for version "{ref}"')
def step_empty(context: Context, ref: str) -> None:
    body = context.response.json()
    assert (body["version"], body["results"]) == (ref, []), body
    assert body["coverage"]["complete"], body


@then('no result from "{ref}" is returned')
def step_no_other_version(context: Context, ref: str) -> None:
    body = context.response.json()
    assert body["version"] != ref
    assert not [r for r in body["results"] if r["commit_sha"] == context.commits[ref]]


@then(
    "each result has chunk ID, article path, heading path, position of total, previous and next "
    "chunk IDs, commit SHA and a source link to the section anchor"
)
def step_location(context: Context) -> None:
    body = context.response.json()
    assert body["results"], body
    commit = context.commits[body["version"]]
    for result in body["results"]:
        missing = [f for f in LOCATION_FIELDS if f not in result]
        assert not missing, missing
        assert result["heading_path"], result
        assert result["article_path"].startswith("docs/"), result
        assert 0 <= result["position"] < result["total"], result
        assert (result["position"] == 0) == (result["prev_chunk_id"] is None), result
        assert (result["position"] == result["total"] - 1) == (result["next_chunk_id"] is None)
        assert result["commit_sha"] == commit, result
        expected = f"{REPOSITORY}/blob/{commit}/{quote(result['article_path'])}#{result['anchor']}"
        assert result["source_url"] == expected, result


@then('the response says it searched version "{ref}"')
def step_searched(context: Context, ref: str) -> None:
    assert context.response.json()["version"] == ref, context.response.text


@then('the response states retrieval mode "{mode}", not reranked, and its coverage')
def step_mode(context: Context, mode: str) -> None:
    body = context.response.json()
    assert (body["retrieval_mode"], body["reranked"]) == (mode, False), body
    assert body["fallback_reason"] is None, body
    coverage = body["coverage"]
    assert coverage["candidates"] >= len(body["results"]), coverage
    assert coverage["reranked"] == 0, coverage
    assert isinstance(coverage["complete"], bool), coverage


@then('every result is tagged "{first}" and "{second}"')
def step_tagged(context: Context, first: str, second: str) -> None:
    results = context.response.json()["results"]
    assert results, context.response.text
    for result in results:
        assert {first, second} <= set(result["tags"]), result
