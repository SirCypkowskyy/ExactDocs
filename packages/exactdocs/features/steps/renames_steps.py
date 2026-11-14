"""Steps for the rename map git gives each imported version."""

import asyncio
import hashlib
from collections.abc import Awaitable, Callable
from http import HTTPStatus

from behave import given, then, when
from behave.runner import Context

from exactdocs.bootstrap.container import Container
from exactdocs.catalog import CatalogModule
from exactdocs.catalog.dtos import (
    ActivateManifestCommand,
    ArticleIn,
    RenameIn,
    StoreManifestCommand,
)
from exactdocs.catalog.models import RefKind
from steps.import_steps import LIBRARY

GIT_MIN_SIMILARITY, FULL_SIMILARITY = 50, 100  # git reports renames from 50 percent


def _renamed_path(context: Context, ref: str, path: str, direction: str = "forward"):
    return context.client.get(
        f"/api/v1/libraries{LIBRARY}/renamed-path",
        params={"ref": ref, "path": path, "direction": direction},
    )


@given("git cannot compare two commits")
def step_git_cannot(context: Context) -> None:
    context.renames.failing = True


@then('the rename map of "{ref}" maps "{old}" to "{new}"')
def step_maps(context: Context, ref: str, old: str, new: str) -> None:
    response = _renamed_path(context, ref, old)
    assert response.status_code == HTTPStatus.OK, response.text
    found = response.json()["renamed"]
    assert found is not None, f"{ref} has no rename of {old}"
    assert (found["old_path"], found["new_path"], found["ref"]) == (old, new, ref), found
    assert found["from_ref"] == "v1.3.0", found
    assert GIT_MIN_SIMILARITY <= found["similarity"] <= FULL_SIMILARITY, found


@then('the rename map of "{ref}" has nothing for "{old}"')
def step_nothing(context: Context, ref: str, old: str) -> None:
    response = _renamed_path(context, ref, old)
    assert response.status_code == HTTPStatus.OK, response.text
    assert response.json() == {"renamed": None}, response.text


@then('"{new}" of "{ref}" came from "{old}"')
def step_back(context: Context, new: str, ref: str, old: str) -> None:
    response = _renamed_path(context, ref, new, "back")
    assert response.status_code == HTTPStatus.OK, response.text
    assert response.json()["renamed"]["old_path"] == old, response.text


@then('the rename map of "{ref}" is not found')
def step_unknown(context: Context, ref: str) -> None:
    assert _renamed_path(context, ref, "docs/a.md").status_code == HTTPStatus.NOT_FOUND


# ---------------------------------------------------------------- across several versions (#201)


@given('"{library}" has the versions "{first}", "{second}" and "{third}", imported in that order')
def step_versions(context: Context, library: str, first: str, second: str, third: str) -> None:
    context.chain_library = library
    context.chain = [first, second, third]
    context.chain_renames = {}


@given('"{ref}" renamed "{old}" of "{from_ref}" to "{new}"')
def step_chain_rename(context: Context, ref: str, old: str, from_ref: str, new: str) -> None:
    context.chain_renames[ref] = (from_ref, old, new)


def _on_catalog[T](context: Context, action: Callable[[CatalogModule], Awaitable[T]]) -> T:
    """Run `action` on the catalog of a second container over the scenario's data directory."""

    async def go() -> T:
        container = Container.build(context.settings)
        async with container.running(jobs=False):
            return await action(container.catalog)

    return asyncio.run(go())


def _sha(text: str) -> str:
    return hashlib.sha1(text.encode(), usedforsecurity=False).hexdigest()


def _import_chain(context: Context) -> None:
    """Store and activate each version, linked to the one before it, with its articles."""
    paths = ["guide/setup.md", "guide/auth.md"]
    previous: str | None = None
    for ref in context.chain:
        renames = []
        if ref in context.chain_renames:
            from_ref, old, new = context.chain_renames[ref]
            assert from_ref == previous, (ref, from_ref, previous)
            paths = [new if p == old else p for p in paths]
            renames = [RenameIn(from_ref=from_ref, old_path=old, new_path=new, similarity=90)]
        command = StoreManifestCommand(
            library=context.chain_library,
            ref=ref,
            kind=RefKind.TAG,
            commit_sha=_sha(ref),
            articles=[
                ArticleIn(
                    path=p,
                    blob_sha=_sha(f"{ref} {p}"),
                    content_version=1,
                    title=p,
                    content=f"{p} in {ref}",
                )
                for p in paths
            ],
            renames=renames,
            renamed_from=previous,
        )
        stored = _on_catalog(context, lambda catalog, c=command: catalog.store_manifest(c))
        activate = ActivateManifestCommand(manifest_id=stored.manifest_id)
        _on_catalog(context, lambda catalog, a=activate: catalog.activate_manifest(a))
        previous = ref


@when('I ask where "{path}" of "{from_ref}" is in "{ref}"')
def step_ask_across(context: Context, path: str, from_ref: str, ref: str) -> None:
    _import_chain(context)
    context.response = context.client.get(
        f"/api/v1/libraries{context.chain_library}/renamed-path",
        params={"ref": ref, "from": from_ref, "path": path},
    )


@then('the answer is "{path}"')
def step_answer(context: Context, path: str) -> None:
    assert context.response.status_code == HTTPStatus.OK, context.response.text
    found = context.response.json()["renamed"]
    assert found is not None, context.response.text
    assert found["new_path"] == path, found


@then("the answer is that it did not move")
def step_did_not_move(context: Context) -> None:
    assert context.response.status_code == HTTPStatus.OK, context.response.text
    assert context.response.json() == {"renamed": None}, context.response.text
