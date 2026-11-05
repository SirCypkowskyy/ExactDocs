"""Steps for tags users set by hand on an article path of a library."""

from http import HTTPStatus

from behave import given, then, when
from behave.runner import Context

from steps.import_steps import LIBRARY


def _tag(context: Context, path: str, tags: list[str]) -> None:
    context.response = context.client.put(
        f"/api/v1/libraries{LIBRARY}/tags", params={"path": path}, json={"tags": tags}
    )


def _article(context: Context, path: str, ref: str) -> dict:
    response = context.client.get(
        f"/api/v1/libraries{LIBRARY}/article", params={"ref": ref, "path": path}
    )
    assert response.status_code == HTTPStatus.OK, response.text
    return response.json()


def _search(context: Context, ref: str, query: str, tag: str) -> set[str]:
    response = context.client.get(
        f"/api/v1/libraries{LIBRARY}/search", params={"q": query, "ref": ref, "tags": [tag]}
    )
    assert response.status_code == HTTPStatus.OK, response.text
    return {r["article_path"] for r in response.json()["results"]}


@given('the user tagged "{path}" with "{tag}"')
def step_tagged_before(context: Context, path: str, tag: str) -> None:
    _tag(context, path, [tag])
    assert context.response.status_code == HTTPStatus.OK, context.response.text
    assert context.response.json()["tags"] == [tag], context.response.text


@when('the user tags "{path}" with "{tag}"')
def step_tag(context: Context, path: str, tag: str) -> None:
    _tag(context, path, [tag])


@given('the user adds the version "{ref}"')
def step_add_version(context: Context, ref: str) -> None:
    context.execute_steps(f'When the user adds the version "{ref}"')


@when('the user removes the manual tags of "{path}"')
def step_untag(context: Context, path: str) -> None:
    context.response = context.client.delete(
        f"/api/v1/libraries{LIBRARY}/tags", params={"path": path}
    )
    assert context.response.status_code == HTTPStatus.NO_CONTENT, context.response.text


@then('"{path}" in "{ref}" is tagged "{tag}"')
def step_tagged(context: Context, path: str, ref: str, tag: str) -> None:
    assert tag in _article(context, path, ref)["tags"]


@then('"{path}" in "{ref}" is not tagged "{tag}"')
def step_not_tagged(context: Context, path: str, ref: str, tag: str) -> None:
    assert tag not in _article(context, path, ref)["tags"]


@then('"{path}" in "{ref}" carries exactly the tags "{tags}"')
def step_tagged_exactly(context: Context, path: str, ref: str, tags: str) -> None:
    found = _article(context, path, ref)["tags"]
    assert sorted(found) == sorted(tags.split(", ")), found


@then('"{path}" in "{ref}" has no manual tags')
def step_no_manual(context: Context, path: str, ref: str) -> None:
    assert _article(context, path, ref)["manual_tags"] == []


@then('"{path}" in "{ref}" shows "{tag}" as a manual tag')
def step_manual(context: Context, path: str, ref: str, tag: str) -> None:
    assert _article(context, path, ref)["manual_tags"] == [tag]


@then('listing "{ref}" by the tag "{tag}" gives only "{path}"')
def step_listed(context: Context, ref: str, tag: str, path: str) -> None:
    response = context.client.get(
        f"/api/v1/libraries{LIBRARY}/articles", params={"ref": ref, "tags": tag}
    )
    assert response.status_code == HTTPStatus.OK, response.text
    assert [a["path"] for a in response.json()["articles"]] == [path], response.text


@then('searching "{ref}" for "{query}" with the tag "{tag}" finds only "{path}"')
def step_search_finds(context: Context, ref: str, query: str, tag: str, path: str) -> None:
    assert _search(context, ref, query, tag) == {path}


@then('searching "{ref}" for "{query}" with the tag "{tag}" finds nothing')
def step_search_nothing(context: Context, ref: str, query: str, tag: str) -> None:
    assert _search(context, ref, query, tag) == set()


@then("the tag is refused as invalid")
def step_refused(context: Context) -> None:
    response = context.response
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY, response.text
