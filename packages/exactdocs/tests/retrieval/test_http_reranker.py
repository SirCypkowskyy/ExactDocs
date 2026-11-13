"""The HTTP reranker adapter (#93): the Cohere-compatible and TEI dialects, limits and failures.

Each test answers through ``httpx2.MockTransport``: no endpoint is ever called.
"""

import json
from collections.abc import Callable
from typing import Any

import httpx2
import pytest

from exactdocs.retrieval.adapters.driven.http_reranker import HttpReranker, RerankDialect
from exactdocs.retrieval.constants import (
    COHERE_RERANK_BATCH,
    MAX_RERANK_DOCUMENT_CHARS,
    MAX_RERANK_QUERY_CHARS,
    TEI_RERANK_BATCH,
)
from exactdocs.retrieval.errors import RerankerError

KEY = "rr-secret-key"


def _reranker(
    answer: Callable[[dict[str, Any]], httpx2.Response],
    seen: list[httpx2.Request],
    *,
    dialect: RerankDialect = RerankDialect.COHERE,
    key: str | None = KEY,
    base_url: str = "https://rerank.example.com/v2/",
) -> HttpReranker:
    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return answer(json.loads(request.content))

    client = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    return HttpReranker(
        client=client, base_url=base_url, model="rerank-v3.5", key=key, dialect=dialect
    )


def _cohere(body: dict[str, Any]) -> httpx2.Response:
    """Cohere's shape: results best first, each with its index."""
    count = len(body["documents"])
    results = [{"index": i, "relevance_score": i / count} for i in reversed(range(count))]
    return httpx2.Response(200, json={"id": "x", "results": results, "meta": {}})


def _tei(body: dict[str, Any]) -> httpx2.Response:
    count = len(body["texts"])
    return httpx2.Response(200, json=[{"index": i, "score": -i} for i in range(count)])


async def test_the_cohere_dialect_sends_model_query_and_documents_and_reads_results() -> None:
    seen: list[httpx2.Request] = []
    reranker = _reranker(_cohere, seen)

    scores = await reranker.rerank("retry", ["a", "b", "c"])

    assert scores == [0.0, 1 / 3, 2 / 3]
    (request,) = seen
    assert str(request.url) == "https://rerank.example.com/v2/rerank"
    assert request.headers["authorization"] == f"Bearer {KEY}"
    assert json.loads(request.content) == {
        "model": "rerank-v3.5",
        "query": "retry",
        "documents": ["a", "b", "c"],
    }


async def test_voyage_answers_data_instead_of_results() -> None:
    def voyage(body: dict[str, Any]) -> httpx2.Response:
        data = [{"index": i, "relevance_score": 0.5 + i} for i in range(len(body["documents"]))]
        return httpx2.Response(200, json={"object": "list", "data": data})

    assert await _reranker(voyage, []).rerank("q", ["a", "b"]) == [0.5, 1.5]


async def test_the_tei_dialect_sends_texts_with_truncation_and_reads_a_list() -> None:
    seen: list[httpx2.Request] = []
    reranker = _reranker(
        _tei, seen, dialect=RerankDialect.TEI, key=None, base_url="http://tei:8080"
    )

    scores = await reranker.rerank("retry", ["a", "b"])

    assert scores == [0.0, -1.0]
    (request,) = seen
    assert str(request.url) == "http://tei:8080/rerank"
    assert "authorization" not in request.headers
    assert json.loads(request.content) == {"query": "retry", "texts": ["a", "b"], "truncate": True}


@pytest.mark.parametrize(
    ("dialect", "answer", "batch"),
    [
        (RerankDialect.COHERE, _cohere, COHERE_RERANK_BATCH),
        (RerankDialect.TEI, _tei, TEI_RERANK_BATCH),
    ],
)
async def test_documents_go_in_batches_the_endpoint_accepts(
    dialect: RerankDialect, answer: Callable[[dict[str, Any]], httpx2.Response], batch: int
) -> None:
    seen: list[httpx2.Request] = []
    field = "texts" if dialect is RerankDialect.TEI else "documents"

    scores = await _reranker(answer, seen, dialect=dialect).rerank("q", ["x"] * (batch + 3))

    assert [len(json.loads(r.content)[field]) for r in seen] == [batch, 3]
    assert len(scores) == batch + 3


async def test_long_texts_are_cut_to_the_document_and_query_limits() -> None:
    seen: list[httpx2.Request] = []

    await _reranker(_cohere, seen).rerank("q" * 5000, ["d" * 20_000])

    body = json.loads(seen[0].content)
    assert len(body["query"]) == MAX_RERANK_QUERY_CHARS
    assert len(body["documents"][0]) == MAX_RERANK_DOCUMENT_CHARS


async def test_no_documents_means_no_call() -> None:
    seen: list[httpx2.Request] = []

    assert await _reranker(_cohere, seen).rerank("q", []) == []
    assert not seen


def _two(index: object, score: object) -> Callable[[dict[str, Any]], httpx2.Response]:
    """An answer for two candidates whose first item has this index and score."""
    items = [{"index": index, "relevance_score": score}, {"index": 0, "relevance_score": 2}]
    return lambda _: httpx2.Response(200, json={"results": items})


@pytest.mark.parametrize(
    ("answer", "reason"),
    [
        (lambda _: httpx2.Response(503, json={"message": f"bad key {KEY}"}), "HTTP 503"),
        (lambda _: httpx2.Response(200, text="not json"), "not a rerank result"),
        (lambda _: httpx2.Response(200, json={"results": [{"index": 0}]}), "not a rerank result"),
        (
            lambda _: httpx2.Response(200, json={"results": [{"index": 5, "relevance_score": 1}]}),
            "not a rerank result",
        ),
        (
            lambda _: httpx2.Response(
                200,
                json={
                    "results": [
                        {"index": 0, "relevance_score": 1},
                        {"index": 0, "relevance_score": 2},
                    ]
                },
            ),
            "not a rerank result",
        ),
        (lambda _: httpx2.Response(200, json={"results": []}), "not a rerank result"),
        (lambda _: httpx2.Response(200, json=["nope"]), "not a rerank result"),
        (_two(True, 1), "not a rerank result"),
        (_two(1.0, 1), "not a rerank result"),
        (_two(1, "1"), "not a rerank result"),
    ],
    ids=[
        "http-error",
        "not-json",
        "no-score",
        "index-out-of-range",
        "repeated",
        "missing",
        "shape",
        "bool-index",
        "float-index",
        "text-score",
    ],
)
async def test_an_unusable_answer_is_a_reranker_error_without_secrets(
    answer: Callable[[dict[str, Any]], httpx2.Response], reason: str
) -> None:
    with pytest.raises(RerankerError, match=reason) as error:
        await _reranker(answer, []).rerank("secret query", ["a", "b"])

    assert KEY not in str(error.value)
    assert "secret query" not in str(error.value)


async def test_a_transport_failure_is_a_reranker_error_without_the_url() -> None:
    def refuse(request: httpx2.Request) -> httpx2.Response:
        message = f"cannot reach {request.url}"
        raise httpx2.ConnectError(message, request=request)

    client = httpx2.AsyncClient(transport=httpx2.MockTransport(refuse))
    reranker = HttpReranker(client=client, base_url="https://rerank.example.com/v2", model="m")

    with pytest.raises(RerankerError, match="ConnectError") as error:
        await reranker.rerank("q", ["a"])

    assert "rerank.example.com" not in str(error.value)


async def test_one_failed_batch_fails_the_call_with_a_reranker_error() -> None:
    def second_fails(body: dict[str, Any]) -> httpx2.Response:
        if body["documents"][0] == "late":
            return httpx2.Response(500)
        return _cohere(body)

    documents = ["early"] * COHERE_RERANK_BATCH + ["late"]

    with pytest.raises(RerankerError, match="HTTP 500"):
        await _reranker(second_fails, []).rerank("q", documents)


async def test_a_closed_client_is_a_reranker_error() -> None:
    client = httpx2.AsyncClient()
    await client.aclose()  # the profile's client, closed when the profile changed
    reranker = HttpReranker(client=client, base_url="https://rerank.example.com/v2", model="m")

    with pytest.raises(RerankerError, match="RuntimeError"):
        await reranker.rerank("q", ["a"] * (COHERE_RERANK_BATCH + 1))
