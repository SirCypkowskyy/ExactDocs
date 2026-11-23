"""#479: a search across libraries with one library chosen ranks that library only.

The playground said "from 2 libraries" with one chosen. The ranking was scoped all along: the
results come from the chosen library only, while ``libraries`` and ``libraries_searched`` count
every readable library's matches (they are never narrowed). This pins both over REST.
"""

import hashlib
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import Settings
from exactdocs.catalog.dtos import ActivateManifestCommand, ArticleIn, StoreManifestCommand
from exactdocs.catalog.models import RefKind
from exactdocs.retrieval.dtos import ArticleChunksIn, ChunkIn, IndexManifestCommand

pytestmark = pytest.mark.usefixtures("demo_catalog")

PAYMENTS = "/acme/payments"
LEDGER = "/acme/ledger"
# Each demo library's default version: the highest stable tag, else the default branch.
DEFAULT = {PAYMENTS: ("v1.4.0", RefKind.TAG), LEDGER: ("main", RefKind.BRANCH)}
QUERY = "how do I retry failed calls"


@pytest.fixture
async def container() -> AsyncIterator[Container]:
    built = Container.build(Settings())
    async with built.running():
        for library in (PAYMENTS, LEDGER):
            await publish(built, library, f"Retry failed calls in {library} with a backoff.")
        yield built


@pytest.fixture
def client(container: Container, demo_catalog: dict[str, str]) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(container)),
        base_url="http://localhost",
        cookies=demo_catalog,
    )


async def publish(container: Container, library: str, content: str) -> None:
    """Store, index and activate one article in the library's default version, as an import does."""
    ref, kind = DEFAULT[library]
    blob = hashlib.sha1(library.encode(), usedforsecurity=False).hexdigest()
    stored = await container.catalog.store_manifest(
        StoreManifestCommand(
            library=library,
            ref=ref,
            kind=kind,
            commit_sha=blob,
            articles=[
                ArticleIn(
                    path="retry.md",
                    blob_sha=blob,
                    content_version=1,
                    title="Retry",
                    content=f"# Retry\n\n{content}",
                )
            ],
        )
    )
    await container.retrieval.index_manifest(
        IndexManifestCommand(
            manifest_id=stored.manifest_id,
            library=library,
            ref=ref,
            config_hash="c",
            articles=[
                ArticleChunksIn(
                    path="retry.md",
                    blob_sha=blob,
                    chunks=[
                        ChunkIn(
                            heading_path=["Retry"],
                            occurrence_index=0,
                            content=content,
                            content_hash=blob,
                            anchor="retry",
                            code_languages=[],
                        )
                    ],
                )
            ],
        )
    )
    await container.catalog.activate_manifest(
        ActivateManifestCommand(manifest_id=stored.manifest_id)
    )


async def search(client: httpx.AsyncClient, **params: str) -> dict[str, Any]:
    response = await client.get("/api/v1/search", params={"q": QUERY, **params})
    assert response.status_code == 200, response.text
    return response.json()


async def test_with_no_library_chosen_both_libraries_answer(client: httpx.AsyncClient) -> None:
    found = await search(client)

    assert {r["library"] for r in found["results"]} == {PAYMENTS, LEDGER}
    assert found["libraries_searched"] == 2


@pytest.mark.parametrize("chosen", [PAYMENTS, LEDGER])
async def test_one_chosen_library_is_the_only_one_ranked(
    client: httpx.AsyncClient, chosen: str
) -> None:
    found = await search(client, library=chosen)

    assert found["results"], "the chosen library matches"
    assert {r["library"] for r in found["results"]} == {chosen}
    # The counts are never narrowed: they span every readable library, the other one included.
    assert {f["library"] for f in found["libraries"]} == {PAYMENTS, LEDGER}
    assert found["libraries_searched"] == 2
