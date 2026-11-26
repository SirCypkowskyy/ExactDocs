"""Steps for search: the fixture docs repository is imported through the driving ports."""

import asyncio
import fnmatch
import hashlib
from itertools import starmap
from pathlib import Path
from urllib.parse import quote

import yaml
from behave import given, then, when
from behave.runner import Context

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.index_backends import IndexBackends
from exactdocs.catalog.adapters.driven.sqlite import SqliteLibraryRepository
from exactdocs.catalog.dtos import ActivateManifestCommand, ArticleIn, StoreManifestCommand
from exactdocs.catalog.models import HostKind, Library, LibraryId, RefKind, VersionRef
from exactdocs.ingestion.adapters.driven.markdown_chunker import MarkdownChunker
from exactdocs.ingestion.models import parse_article
from exactdocs.retrieval.dtos import ArticleChunksIn, ChunkHeadingIn, ChunkIn, IndexManifestCommand
from exactdocs_kernel import respelled_note
from fixture_repo import git_bytes
from steps.http_steps import step_running

LIBRARY = "/fixture/docs-repo"
REPOSITORY = "https://github.com/fixture/docs-repo"
SKIPPED_DIRECTORIES = (
    "docs/reference/oversized.md",
    "docs/legacy/binary.md",
    "docs/legacy/undecodable.md",
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


def git_blob_sha(content: str) -> str:
    data = content.encode()
    return hashlib.sha1(b"blob %d\0" % len(data) + data, usedforsecurity=False).hexdigest()


def read_version(context: Context, ref: str) -> tuple[str, list[tuple[str, str]]]:
    """Return the commit and the (path, text) of every article the importer would take."""
    repo, git = context.fixture_repo.path, context.fixture_git
    commit = git("rev-parse", ref, cwd=repo)
    articles = []
    for path in git("ls-tree", "-r", "--name-only", ref, "--", "docs", cwd=repo).splitlines():
        if not path.endswith((".md", ".mdx")) or path.startswith(SKIPPED_DIRECTORIES):
            continue
        data = git_bytes("show", f"{ref}:{path}", cwd=repo)
        try:
            text = data.decode()
        except UnicodeDecodeError:
            text = data.decode("cp1252")  # the Latin-1 article, as the importer reads it
        articles.append((path, text))
    return commit, articles


async def import_versions(
    context: Context,
    refs: list[str],
    library: str = LIBRARY,
    title: str = "Docs repo",
    *,
    index_backends: IndexBackends | None = None,
) -> None:
    container = Container.build(context.settings, index_backends=index_backends)
    chunker = MarkdownChunker()
    async with container.running(jobs=False):
        await SqliteLibraryRepository(engine=container.engine).save(
            Library(
                id=LibraryId(library),
                title=title,
                source_url=REPOSITORY,
                host=HostKind.GITHUB,
                default_branch=VersionRef("main"),
            )
        )
        for ref in refs:
            commit, files = read_version(context, ref)
            parsed = list(starmap(parse_article, files))
            stored = await container.catalog.store_manifest(
                StoreManifestCommand(
                    library=library,
                    ref=ref,
                    kind=RefKind.TAG,
                    commit_sha=commit,
                    articles=[
                        ArticleIn(
                            path=a.path,
                            blob_sha=git_blob_sha(text),
                            content_version=1,
                            title=a.title,
                            tags=_tags(a.path, a.tags),
                            front_matter=a.front_matter,
                            content=a.body,
                        )
                        for a, (_, text) in zip(parsed, files, strict=True)
                    ],
                )
            )
            await container.retrieval.index_manifest(
                IndexManifestCommand(
                    manifest_id=stored.manifest_id,
                    library=library,
                    ref=ref,
                    config_hash=chunker.config_hash,
                    articles=[
                        ArticleChunksIn(
                            path=a.path,
                            blob_sha=git_blob_sha(text),
                            tags=_tags(a.path, a.tags),
                            chunks=[
                                ChunkIn(
                                    heading_path=list(c.heading_path),
                                    occurrence_index=c.occurrence_index,
                                    content=c.content,
                                    content_hash=c.content_hash,
                                    anchor=c.anchor,
                                    code_languages=list(c.code_languages),
                                    headings=None
                                    if c.headings is None
                                    else [
                                        ChunkHeadingIn(
                                            heading_path=list(h.heading_path),
                                            anchor=h.anchor,
                                            starts_chunk=h.starts_chunk,
                                        )
                                        for h in c.headings
                                    ],
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
    asyncio.run(import_versions(context, [first, second]))


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


@when('a user searches "{target}" for "{query}" grouped by article')
def step_search_grouped(context: Context, target: str, query: str) -> None:
    context.ranked_results = context.response.json()["results"]
    _search(context, target, {"q": query, "group_by": "article", "limit": 10})


@then("the results are best first and none names a group")
def step_best_first(context: Context) -> None:
    results = context.response.json()["results"]
    assert results, context.response.text
    scores = [r["score"] for r in results]
    assert scores == sorted(scores, reverse=True), scores
    assert all(r["group"] is None for r in results), results


@then("the same results come grouped by article, as the MCP search returns them")
def step_grouped(context: Context) -> None:
    grouped = context.response.json()["results"]
    ranked = context.ranked_results
    assert {r["chunk_id"] for r in grouped} >= {r["chunk_id"] for r in ranked}
    order = list(dict.fromkeys(r["article_path"] for r in grouped))
    assert [r["group"] for r in grouped] == [order.index(r["article_path"]) + 1 for r in grouped]
    assert grouped[0]["chunk_id"] == ranked[0]["chunk_id"]


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


@then('the response notes that ref "{asked}" was read as "{used}"')
def step_ref_noted(context: Context, asked: str, used: str) -> None:
    assert context.response.json()["notes"] == [respelled_note(asked, used)], context.response.text


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


TABLE = Path(__file__).parents[2] / "tests" / "fixtures" / "docs-repo" / "expected-queries.yaml"


@when("each query of the expected-queries table is searched in its version")
def step_search_table(context: Context) -> None:
    """Search the table over HTTP.

    This scenario mirrors the importer's rules (``SKIPPED_DIRECTORIES``, ``TAG_RULES``) by hand;
    the pytest suite in ``tests/retrieval/ranking`` is the check on the real importer. Only the
    imported versions are asked (not ``next``), and entries marked ``xfail`` are skipped.
    """
    context.ranked = []
    for entry in yaml.safe_load(TABLE.read_text(encoding="utf-8"))["queries"]:
        if "xfail" in entry:  # a known gap, tracked in the ranking suite
            continue
        for version, expected in entry["expected"].items():
            if version not in context.commits:  # only the imported versions are asked
                continue
            _search(
                context,
                f"{LIBRARY}/{version}",
                {
                    "q": entry["query"],
                    "tags": entry.get("tags", []),
                    "tags_match": entry.get("tags_match", "any"),
                },
            )
            context.ranked.append((entry["query"], version, expected, context.response.json()))


@then("its expected section is the top result")
def step_table_ranked(context: Context) -> None:
    assert context.ranked
    wrong = []
    for query, version, expected, body in context.ranked:
        top = [(r["article_path"], r["heading_path"]) for r in body["results"]]
        want = None if expected is None else (expected["article"], expected["heading_path"])
        if (top[0] if top else None) != want:
            wrong.append(f"{query!r} in {version}: wanted {want}, top 5 {top[:5]}")
    assert not wrong, "\n".join(wrong)
