"""RET-02 (#93) end to end on each SQL backend: the container, an import, a profile, the adapter.

A fake gateway on loopback stands in for the rerank endpoint (it scores in the reverse of the order
it was sent), so no provider is called. On PostgreSQL the chunks, the library settings and the
search index are PostgreSQL's.
"""

import pytest

from databases import SQL_BACKENDS
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.settings import AiSettings, Settings
from exactdocs.retrieval.dtos import SearchDocsQuery, SetLibraryRetrievalCommand
from exactdocs.retrieval.models import FallbackReason, ResultGrouping
from fake_llm import gateway
from fixture_import import LIBRARY, import_fixture
from fixture_repo import DocsRepo

QUERY = "how do I retry failed calls"
RANKED = ResultGrouping.CHUNK  # the reranked order itself, not grouped by article (#575)


@pytest.mark.parametrize("backend", SQL_BACKENDS)
async def test_a_search_is_reranked_and_a_slow_reranker_keeps_the_order(
    backend: str, docs_repo: DocsRepo, request: pytest.FixtureRequest
) -> None:
    if backend == "postgres":
        request.getfixturevalue("on_postgres")
    with gateway() as fake:
        ai = AiSettings.model_validate(
            {
                "providers": {
                    "rr": {"kind": "openai-compatible", "base_url": f"{fake.url}/v2"},
                    "slow": {"kind": "openai-compatible", "base_url": f"{fake.url}/slow/v2"},
                },
                "reranker": {"model": "rr:rerank-v3.5", "timeout": 0.5},
            }
        )
        container = Container.build(Settings(ai=ai))
        async with container.running(jobs=False):
            await import_fixture(container, docs_repo)
            retrieval = container.retrieval
            await retrieval.set_library_retrieval(
                SetLibraryRetrievalCommand(library=LIBRARY, rerank_top_n=3)
            )
            reranked = await retrieval.search_docs(
                SearchDocsQuery(
                    library=LIBRARY, ref="v1.4.0", query=QUERY, limit=5, group_by=RANKED
                )
            )
            await retrieval.set_library_retrieval(
                SetLibraryRetrievalCommand(
                    library=LIBRARY, reranker="slow:rerank-v3.5", rerank_top_n=3
                )
            )
            kept = await retrieval.search_docs(
                SearchDocsQuery(
                    library=LIBRARY, ref="v1.4.0", query=QUERY, limit=5, group_by=RANKED
                )
            )

    assert (reranked.reranked, reranked.coverage.reranked) == (True, 3)
    head = [r.chunk_id for r in kept.results[:3]]
    assert [r.chunk_id for r in reranked.results[:3]] == head[::-1]
    assert [r.chunk_id for r in reranked.results[3:]] == [r.chunk_id for r in kept.results[3:]]
    assert (kept.reranked, kept.fallback_reason) == (False, FallbackReason.RERANKER_TIMEOUT)
    rerank_calls = [s for s in fake.seen if s.path.endswith("/rerank")]
    assert [len(s.body["documents"]) for s in rerank_calls] == [3, 3]
