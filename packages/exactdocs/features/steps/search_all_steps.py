"""Steps for searching across libraries, over REST."""

from behave import then, when
from behave.runner import Context

DEFAULTS = {"/fixture/docs-repo": "v1.4.0", "/other/guide": "v1.3.0"}


def _search_all(context: Context, query: str, **params: object) -> None:
    context.response = context.client.get("/api/v1/search", params={"q": query, **params})


@when('a user searches all libraries for "{query}"')
def step_search_all(context: Context, query: str) -> None:
    _search_all(context, query)


@when('a user searches "{query}" across libraries, narrowed to "{library}"')
def step_search_all_narrowed(context: Context, query: str, library: str) -> None:
    _search_all(context, query, library=library)


@when('a user searches "{query}" across libraries with all of tags "{tags}"')
def step_search_all_tags(context: Context, query: str, tags: str) -> None:
    _search_all(context, query, tags=tags.split(", "), tags_match="all")


@then("results come from each library's default version")
def step_defaults(context: Context) -> None:
    body = context.response.json()
    assert {(r["library"], r["version"]) for r in body["results"]} == set(DEFAULTS.items()), body


@then("each result names its library and version, with counts per library")
def step_facets(context: Context) -> None:
    body = context.response.json()
    for result in body["results"]:
        assert DEFAULTS[result["library"]] == result["version"], result
        assert result["commit_sha"] == context.commits[result["version"]], result
    facets = {f["library"]: f for f in body["libraries"]}
    assert set(facets) == set(DEFAULTS), body
    for library, version in DEFAULTS.items():
        assert facets[library]["version"] == version, body
        assert facets[library]["matches"] >= 1, body
    assert body["libraries_searched"] >= len(DEFAULTS), body


@then('every result comes from "{library}" at "{ref}"')
def step_only_library(context: Context, library: str, ref: str) -> None:
    results = context.response.json()["results"]
    assert results, context.response.text
    assert {(r["library"], r["version"]) for r in results} == {(library, ref)}, results


@then("the counts per library still cover both libraries")
def step_global_counts(context: Context) -> None:
    libraries = {f["library"] for f in context.response.json()["libraries"]}
    assert libraries == set(DEFAULTS), libraries


@then('no result is from version "{ref}" of "{library}"')
def step_not_version(context: Context, ref: str, library: str) -> None:
    body = context.response.json()
    assert body["results"], body
    other = [r for r in body["results"] if r["library"] == library]
    assert not [r for r in other if r["version"] == ref or r["commit_sha"] == context.commits[ref]]
