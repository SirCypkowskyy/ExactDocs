"""#245: the default local models, for real, with sockets blocked.

Runs when ``EXACTDOCS_TEST_MODELS_DIR`` names a directory that ``exactdocs models pull`` filled
with the defaults (CI's *Retrieval eval (local models)* job, which caches it); the 158 MB of
models are not fetched by the test suite. ``test_local_models.py`` runs the same path on tiny
models everywhere.
"""

import os
from pathlib import Path

import pytest

from socket_guard import run_guarded

MODELS = os.environ.get("EXACTDOCS_TEST_MODELS_DIR", "")

pytestmark = pytest.mark.skipif(
    not MODELS, reason="EXACTDOCS_TEST_MODELS_DIR (the pulled default models) is not set"
)

DEFAULTS = """
import asyncio
from pathlib import Path
from exactdocs.bootstrap.local_models import LocalModels
from exactdocs.retrieval.adapters.driven.local_models import LocalEmbeddingModels
from exactdocs.retrieval.models import ModelRole, ProfileOrigin, ProviderKind, ProviderProfile

async def main():
    local = LocalModels(models_dir=Path(os.environ["EXACTDOCS_TEST_MODELS_DIR"]))
    profile = ProviderProfile(
        name="local", kind=ProviderKind.LOCAL, origin=ProfileOrigin.CONFIGURATION
    )
    handle = await local.embedder(profile, "BAAI/bge-small-en-v1.5")
    embeddings = LocalEmbeddingModels().bind(
        handle, name="local:BAAI/bge-small-en-v1.5", dimensions=None, batch_size=16
    )
    documents = [
        "Retry policy: failed calls are repeated up to three times with exponential backoff.",
        "Rotating tokens: create a new API key, deploy it, then revoke the old one.",
    ]
    vectors = (await embeddings.embed_documents(documents)).vectors
    query = (await embeddings.embed_query("how do I retry failed calls")).vectors[0]
    similarity = [sum(a * b for a, b in zip(query, v)) for v in vectors]
    reranker = await local.reranker(profile, "Xenova/ms-marco-MiniLM-L-6-v2")
    scores = await reranker.rerank("how do I retry failed calls", documents)
    return len(vectors[0]), similarity, list(scores)

dimensions, similarity, scores = asyncio.run(main())
print(json.dumps({
    "blocked": blocked,
    "dimensions": dimensions,
    "similarity": similarity,
    "scores": scores,
}))
"""


def test_the_default_models_embed_and_rerank_with_sockets_blocked(tmp_path: Path) -> None:
    seen = run_guarded(tmp_path, DEFAULTS)

    assert seen["blocked"] == []
    assert seen["dimensions"] == 384
    retry, tokens = seen["similarity"]
    assert retry > tokens
    assert seen["scores"][0] > seen["scores"][1]
