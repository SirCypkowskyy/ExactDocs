"""Steps for the counts on a library's versions (#513).

The expected counts come from other endpoints: a version's articles from its article listing,
its chunks from the embedding progress (every chunk of every version, once embedded).
"""

from http import HTTPStatus

from behave import then, when
from behave.runner import Context

from steps.search_steps import LIBRARY


def _articles(context: Context, ref: str) -> int:
    """Count a version's articles as its article listing does.

    Args:
        context: The behave context.
        ref: The version.

    Returns:
        The listing's total.
    """
    response = context.client.get(
        f"/api/v1/libraries{LIBRARY}/articles", params={"ref": ref, "limit": 1}
    )
    assert response.status_code == HTTPStatus.OK, response.text
    return response.json()["total"]


@when("the client lists the library's versions")
def step_list_versions(context: Context) -> None:
    response = context.client.get(f"/api/v1/libraries{LIBRARY}/versions")
    assert response.status_code == HTTPStatus.OK, response.text
    context.versions = response.json()["versions"]


def _check_counts(context: Context) -> list[dict]:
    """Check every version's article count and that it has chunks.

    Args:
        context: The behave context.

    Returns:
        The listed versions.
    """
    versions = context.versions
    assert [v["ref"] for v in versions] == ["v1.3.0", "v1.4.0"], versions
    for version in versions:
        assert version["articles"] == _articles(context, version["ref"]) > 0, version
        assert version["chunks"] >= version["articles"], version
    return versions


@then("each version carries its article and chunk counts, every chunk embedded")
def step_every_chunk_embedded(context: Context) -> None:
    versions = _check_counts(context)
    assert all(v["embedded_chunks"] == v["chunks"] for v in versions), versions
    response = context.client.get("/api/v1/ai/embedding")
    assert response.status_code == HTTPStatus.OK, response.text
    (space,) = response.json()["spaces"]
    assert space["chunks"] == sum(v["chunks"] for v in versions), (space, versions)


@then("each version carries its article and chunk counts, no chunk embedded")
def step_no_chunk_embedded(context: Context) -> None:
    versions = _check_counts(context)
    assert all(v["embedded_chunks"] == 0 for v in versions), versions


@then("the library carries the article count of its default version")
def step_library_articles(context: Context) -> None:
    response = context.client.get("/api/v1/libraries")
    assert response.status_code == HTTPStatus.OK, response.text
    (library,) = [lib for lib in response.json()["libraries"] if lib["id"] == LIBRARY]
    (default,) = [v for v in context.versions if v["is_default"]]
    assert library["article_count"] == default["articles"], (library, default)
