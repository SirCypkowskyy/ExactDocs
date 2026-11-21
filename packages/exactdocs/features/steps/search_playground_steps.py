"""Steps for the search playground's modes across libraries (#428), over REST.

The embedding model is the fake gateway of ``hybrid_search_steps`` (it hashes terms); every
version is embedded by the background ``embed`` jobs.
"""

import time
from http import HTTPStatus
from typing import Any

from behave import given, then, when
from behave.runner import Context

from steps.search_all_steps import DEFAULTS

EMBEDDING_SECONDS = 60.0


@given("every library is embedded")
def step_every_library_embedded(context: Context) -> None:
    deadline = time.monotonic() + EMBEDDING_SECONDS
    left = None
    while time.monotonic() < deadline:
        estimate = context.client.get("/api/v1/ai/embedding/estimate")
        assert estimate.status_code == HTTPStatus.OK, estimate.text
        left = estimate.json()["chunks"]
        if left == 0:
            return
        time.sleep(0.05)
    assert left == 0, f"{left} chunks are still to embed"


def _libraries(spec: str) -> list[str]:
    """Read the libraries a step names: ``all libraries`` or quoted IDs joined by ``and``.

    Args:
        spec: The step's text.

    Returns:
        The library IDs; empty for all libraries.
    """
    if spec == "all libraries":
        return []
    return [part.strip().strip('"') for part in spec.split(" and ")]


@when('a user searches "{query}" in mode "{mode}" across {libraries}')
def step_search_across(context: Context, query: str, mode: str, libraries: str) -> None:
    context.chosen = _libraries(libraries)
    params: dict[str, Any] = {"q": query, "mode": mode, "limit": 10}
    if context.chosen:
        params["library"] = context.chosen
    context.response = context.client.get("/api/v1/search", params=params)


@when('a user searches version "{target}" for "{query}" in mode "{mode}"')
def step_search_version(context: Context, target: str, query: str, mode: str) -> None:
    owner, repo, ref = target.removeprefix("/").split("/", 2)
    context.response = context.client.get(
        f"/api/v1/libraries/{owner}/{repo}/search", params={"q": query, "ref": ref, "mode": mode}
    )


def _body(context: Context) -> dict[str, Any]:
    assert context.response.status_code == HTTPStatus.OK, context.response.text
    return context.response.json()


@then('mode "{mode}" answered without a fallback')
def step_answered(context: Context, mode: str) -> None:
    body = _body(context)
    assert (body["retrieval_mode"], body["fallback_reason"]) == (mode, None), body
    assert body["results"], body


@then("every result is from a chosen library's default version, with its {ranks}")
def step_chosen_with_ranks(context: Context, ranks: str) -> None:
    body = _body(context)
    chosen = set(context.chosen or DEFAULTS)
    for result in body["results"]:
        assert result["library"] in chosen, result
        assert result["version"] == DEFAULTS[result["library"]], result
        assert result["commit_sha"] == context.commits[result["version"]], result
        bm25, vector = result["bm25_rank"], result["vector_rank"]
        match ranks:
            case "BM25 rank":
                assert bm25 is not None, result
                assert vector is None, result
            case "vector rank":
                assert vector is not None, result
                assert bm25 is None, result
            case _:
                assert bm25 is not None or vector is not None, result
    if ranks == "BM25 rank":
        assert [r["bm25_rank"] for r in body["results"]] == list(
            range(1, len(body["results"]) + 1)
        ), body
    if ranks == "vector rank":
        assert [r["vector_rank"] for r in body["results"]] == list(
            range(1, len(body["results"]) + 1)
        ), body


@then('every result is from "{ref}"')
def step_every_from(context: Context, ref: str) -> None:
    body = _body(context)
    assert body["version"] == ref, body
    for result in body["results"]:
        assert result["commit_sha"] == context.commits[ref], result


@then('BM25 answered across the libraries with fallback reason "{reason}"')
def step_bm25_fallback(context: Context, reason: str) -> None:
    body = _body(context)
    assert (body["retrieval_mode"], body["fallback_reason"]) == ("bm25", reason), body
    assert body["results"], body
    for result in body["results"]:
        assert result["vector_rank"] is None, result
