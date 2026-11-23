"""Azure AI Search backends for the contract suites (#353): on the in-process fake, or a service.

The fake (``azure_search_fake.py``) is plugged in as the azure-core transport and always runs,
so CI runs every contract case without Azure. With ``EXACTDOCS_TEST_AZURE_SEARCH_URL`` (the
service's endpoint) the same cases also run against a real service: the API key from
``EXACTDOCS_TEST_AZURE_SEARCH_KEY``, or Entra ID (``DefaultAzureCredential``: the manual workflow
signs in with ``azure/login``) when it is unset. Each case writes to indexes of its own
(``exactdocs-test-<random>``) and deletes them afterwards.
"""

import os
import secrets
from collections.abc import AsyncGenerator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any

from azure_search_fake import API_KEY, ENDPOINT, FakeSearchService
from exactdocs.retrieval.adapters.driven.azure_search_index import (
    AzureHybridVectorBackend,
    AzureSearchBackend,
    AzureVectorBackend,
    search_backend,
    vector_backend,
)
from exactdocs.retrieval.ports import SearchBackend, VectorBackend

URL_VARIABLE = "EXACTDOCS_TEST_AZURE_SEARCH_URL"
KEY_VARIABLE = "EXACTDOCS_TEST_AZURE_SEARCH_KEY"
REQUIRE_VARIABLE = "EXACTDOCS_REQUIRE_AZURE_SEARCH"

type Factory[T] = Callable[[], AbstractAsyncContextManager[T]]


def fake_options(service: FakeSearchService | None = None, **more: Any) -> dict[str, Any]:
    """The options an operator writes for the fake service."""
    key = service.api_key if service is not None else API_KEY
    return {"endpoint": ENDPOINT, "api_key": key, "index": "exactdocs"} | more


def real_url() -> str | None:
    """The real service's endpoint, or ``None`` (its cases are left out)."""
    url = os.environ.get(URL_VARIABLE) or None
    if url is None and os.environ.get(REQUIRE_VARIABLE) == "1":
        message = f"{REQUIRE_VARIABLE}=1 but {URL_VARIABLE} names no service"
        raise RuntimeError(message)
    return url


def real_options(**more: Any) -> dict[str, Any]:
    """The options of the real service, with indexes of this test's own."""
    url = real_url()
    assert url is not None
    options: dict[str, Any] = {"endpoint": url, "index": f"exactdocs-test-{secrets.token_hex(4)}"}
    key = os.environ.get(KEY_VARIABLE)
    if key:
        options["api_key"] = key
    return options | more


async def _drop_everything(backend: AzureSearchBackend | AzureVectorBackend) -> None:
    """Delete every index the backend's ``index`` option names (the search one and spaces')."""
    service = backend.service
    prefix = service.connection.index
    for name in await service.index_names():
        if name == prefix or name.startswith(prefix + "-space"):
            await service.drop(name)


def _search_case(options: Callable[[], dict[str, Any]], *, fake: bool) -> Factory[SearchBackend]:
    @asynccontextmanager
    async def case() -> AsyncGenerator[SearchBackend]:
        service = FakeSearchService() if fake else None
        transport = service.transport if service is not None else None
        backend = search_backend(options(), transport=transport)
        await backend.open()
        try:
            yield backend
        finally:
            try:
                if not fake:
                    await _drop_everything(backend)
            finally:
                await backend.close()

    return case


def _vector_case(
    options: Callable[[], dict[str, Any]], *, fake: bool, hybrid: bool
) -> Factory[VectorBackend]:
    @asynccontextmanager
    async def case() -> AsyncGenerator[VectorBackend]:
        service = FakeSearchService() if fake else None
        transport = service.transport if service is not None else None
        backend = vector_backend(options() | {"hybrid": hybrid}, transport=transport)
        await backend.open()
        try:
            yield backend
        finally:
            try:
                if not fake:
                    inner = (
                        backend.vectors
                        if isinstance(backend, AzureHybridVectorBackend)
                        else backend
                    )
                    await _drop_everything(inner)
            finally:
                await backend.close()

    return case


def cases() -> list[tuple[str, Factory[SearchBackend] | None, Factory[VectorBackend]]]:
    """``(name, search, vectors)`` of every Azure AI Search case: the fake's, a service's."""
    found: list[tuple[str, Factory[SearchBackend] | None, Factory[VectorBackend]]] = [
        (
            "azure_search_fake",
            _search_case(fake_options, fake=True),
            _vector_case(fake_options, fake=True, hybrid=True),
        ),
        ("azure_search_fake_plain", None, _vector_case(fake_options, fake=True, hybrid=False)),
    ]
    if real_url() is not None:
        found += [
            (
                "azure_search",
                _search_case(real_options, fake=False),
                _vector_case(real_options, fake=False, hybrid=True),
            ),
            ("azure_search_plain", None, _vector_case(real_options, fake=False, hybrid=False)),
        ]
    return found
