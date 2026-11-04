"""Steps for version manifests: stored through the catalog, read back over the REST API."""

import asyncio
import hashlib
from collections.abc import Awaitable, Callable

from behave import given, then, when
from behave.runner import Context

from exactdocs.bootstrap.container import Container
from exactdocs.catalog import CatalogModule
from exactdocs.catalog.dtos import (
    ActivateManifestCommand,
    ArticleIn,
    StoreManifestCommand,
)
from exactdocs.catalog.models import RefKind


def _run[T](context: Context, action: Callable[[CatalogModule], Awaitable[T]]) -> T:
    """Run `action` on the catalog of a second container over the scenario's data directory."""

    async def go() -> T:
        container = Container.build(context.settings)
        async with container.running():
            return await action(container.catalog)

    return asyncio.run(go())


def _git_blob_sha(content: str) -> str:
    data = content.encode()
    return hashlib.sha1(b"blob %d\0" % len(data) + data, usedforsecurity=False).hexdigest()


def _store(context: Context, library: str, ref: str, commit: str) -> str:
    articles = [
        ArticleIn(
            path=row["path"],
            blob_sha=_git_blob_sha(row["content"]),
            title=row["title"],
            content=row["content"],
        )
        for row in context.table or []
    ]
    command = StoreManifestCommand(
        library=library,
        ref=ref,
        kind=RefKind.TAG if ref.startswith("v") else RefKind.BRANCH,
        commit_sha=commit.ljust(40, "0"),
        articles=articles,
    )
    return _run(context, lambda catalog: catalog.store_manifest(command)).manifest_id


@given('"{library}" version "{ref}" has the active manifest at commit "{commit}":')
def step_active_manifest(context: Context, library: str, ref: str, commit: str) -> None:
    manifest_id = _store(context, library, ref, commit)
    command = ActivateManifestCommand(manifest_id=manifest_id)
    _run(context, lambda catalog: catalog.activate_manifest(command))


@given('"{library}" version "{ref}" has a pending manifest at commit "{commit}":')
def step_pending_manifest(context: Context, library: str, ref: str, commit: str) -> None:
    context.pending_manifest_id = _store(context, library, ref, commit)


@when("the pending manifest is activated")
def step_activate(context: Context) -> None:
    command = ActivateManifestCommand(manifest_id=context.pending_manifest_id)
    _run(context, lambda catalog: catalog.activate_manifest(command))


@when('I read the article "{path}" of "{library}" version "{ref}"')
def step_read(context: Context, path: str, library: str, ref: str) -> None:
    context.response = context.client.get(
        f"/api/v1/libraries{library}/article", params={"ref": ref, "path": path}
    )


@when('I read the article "{path}" of "{library}" without a ref')
def step_read_default(context: Context, path: str, library: str) -> None:
    context.response = context.client.get(
        f"/api/v1/libraries{library}/article", params={"path": path}
    )


@when('I list the articles of "{library}" version "{ref}"')
def step_list(context: Context, library: str, ref: str) -> None:
    context.response = context.client.get(
        f"/api/v1/libraries{library}/articles", params={"ref": ref}
    )


@when('I list the articles under "{prefix}" of "{library}" version "{ref}"')
def step_list_prefix(context: Context, prefix: str, library: str, ref: str) -> None:
    context.response = context.client.get(
        f"/api/v1/libraries{library}/articles", params={"ref": ref, "path_prefix": prefix}
    )


@when('I list {limit:d} articles of "{library}" version "{ref}"')
def step_list_limit(context: Context, limit: int, library: str, ref: str) -> None:
    context.response = context.client.get(
        f"/api/v1/libraries{library}/articles", params={"ref": ref, "limit": limit}
    )


@then('the article says "{content}" at commit "{commit}"')
def step_article(context: Context, content: str, commit: str) -> None:
    body = context.response.json()
    assert body["content"] == content, body
    assert body["commit_sha"] == commit.ljust(40, "0"), body


@then('the articles are "{paths}" at commit "{commit}"')
def step_articles(context: Context, paths: str, commit: str) -> None:
    body = context.response.json()
    assert [a["path"] for a in body["articles"]] == paths.split(", "), body
    assert body["commit_sha"] == commit.ljust(40, "0"), body


@then("there is a next page")
def step_next_page(context: Context) -> None:
    assert context.response.json()["next_cursor"]


@then('the commit of the version is "{commit}"')
def step_version_commit(context: Context, commit: str) -> None:
    assert context.response.json()["commit_sha"] == commit.ljust(40, "0")
