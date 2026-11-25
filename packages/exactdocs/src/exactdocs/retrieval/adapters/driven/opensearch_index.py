"""OpenSearch as the search and vector backend (#354): ``exactdocs[opensearch]``.

The requests, mappings and answers are ``elastic_index``'s (shared with Elasticsearch); this
module adds the official client and the options: ``url``, ``index_prefix``, basic auth
(``username`` with ``password`` / ``password_file``: the security plugin's internal users, and
Amazon OpenSearch Service's fine-grained access control) or a bearer token (``token`` /
``token_file``: the security plugin's JWT), and TLS with a custom CA (``ca_certs``). Imported
only when ``EXACTDOCS_SEARCH_BACKEND`` or ``EXACTDOCS_VECTOR_BACKEND`` is ``opensearch``.

The client is the synchronous one (urllib3, thread-safe connection pools), each request run in
a worker thread: opensearch-py's async client is built on aiohttp with a connector option that
Python 3.14 deprecates, and the extra stays free of aiohttp.
"""

import asyncio
from collections.abc import Collection, Mapping
from dataclasses import dataclass, replace
from typing import Any

from opensearchpy import OpenSearch, RequestsHttpConnection, TransportError

from exactdocs.retrieval.adapters.driven.elastic_index import (
    Answer,
    ElasticOptions,
    ElasticSearchBackend,
    ElasticVectorBackend,
    error_reason,
    make_search_backend,
    make_vector_backend,
    parse_options,
)
from exactdocs.retrieval.constants import (
    ELASTIC_MAX_RETRIES,
    OPENSEARCH_BACKEND,
    OPENSEARCH_SECRETS,
)
from exactdocs.retrieval.errors import IndexBackendUnavailableError
from exactdocs_kernel import OutboundNetwork


@dataclass(frozen=True, slots=True, kw_only=True)
class _Client:
    """Implements ``elastic_index.Engine`` with ``OpenSearch``, in worker threads."""

    client: OpenSearch
    """The client."""

    async def request(
        self,
        method: str,
        path: str,
        *,
        body: object = None,
        params: Mapping[str, str] | None = None,
        ndjson: bool = False,
        allow: Collection[int] = (),
    ) -> Answer:
        """Send one request.

        Args:
            method: The method.
            path: The path.
            body: A JSON body, or ``_bulk`` text.
            params: The query string.
            ndjson: The body is ``_bulk`` text.
            allow: Error statuses answered instead of raised.

        Returns:
            The status and the JSON answer.

        Raises:
            IndexBackendUnavailableError: Unreachable, or an error status not in ``allow``.
        """
        headers = {"accept": "application/json"}
        if body is not None:
            headers["content-type"] = "application/x-ndjson" if ndjson else "application/json"
        try:
            data = await asyncio.to_thread(
                self.client.transport.perform_request,
                method,
                path,
                params=dict(params or {}),
                body=body,
                headers=headers,
            )
        except TransportError as error:
            status = error.status_code
            if isinstance(status, int) and status in allow:
                return Answer(status=status, body=_json(error.info))
            if isinstance(status, int):
                reason = error_reason(status, error.info)
            else:  # a connection error: no status
                reason = f"{type(error).__name__}: {error.error}"
            raise IndexBackendUnavailableError(OPENSEARCH_BACKEND, reason) from error
        if data is False:  # a HEAD answered 404
            return Answer(status=404, body={})
        return Answer(status=200, body=_json(data))

    async def close(self) -> None:
        """Close the client's connections."""
        await asyncio.to_thread(self.client.close)


def _json(body: object) -> dict[str, Any]:
    """Return an answer's JSON object (``{}`` for anything else, as a ``HEAD``'s).

    Args:
        body: The answer's body.

    Returns:
        The object.
    """
    return dict(body) if isinstance(body, Mapping) else {}


def _connect(options: ElasticOptions) -> _Client:
    """Build the client (it connects on its first request).

    Args:
        options: The checked options.

    Returns:
        The engine.
    """
    auth: dict[str, Any] = {}
    if options.token is not None:
        auth["headers"] = {"authorization": f"Bearer {options.token}"}
    elif options.username is not None:
        auth["http_auth"] = (options.username, options.password or "")
    # opensearch-py's urllib3 connection reads no proxy variable: through a proxy (#538), the
    # requests connection carries it, with that proxy given explicitly.
    proxy = options.network.proxy_for(options.urls[0])
    if proxy is not None:
        auth |= {
            "connection_class": RequestsHttpConnection,
            "proxies": {"http": proxy, "https": proxy},
        }
    client = OpenSearch(
        hosts=list(options.urls),
        ca_certs=options.ca_certs or options.network.ca_bundle,
        verify_certs=options.verify_certs,
        ssl_show_warn=options.verify_certs,
        timeout=options.request_timeout,
        max_retries=ELASTIC_MAX_RETRIES,
        retry_on_timeout=True,
        **auth,
    )
    return _Client(client=client)


def _options(options: Mapping[str, object]) -> ElasticOptions:
    """Check the ``[index_backends.opensearch]`` options.

    Args:
        options: The table.

    Returns:
        The options.

    Raises:
        ValueError: An option is invalid, or more than one way to sign in is given.
    """
    checked = parse_options(OPENSEARCH_BACKEND, options, OPENSEARCH_SECRETS)
    if checked.token is not None and checked.username is not None:
        message = "sign in one way: `token` or `username` with `password`"
        raise ValueError(message)
    return checked


def search_backend(
    options: Mapping[str, object], *, network: OutboundNetwork | None = None
) -> ElasticSearchBackend:
    """Build the search backend from its ``[index_backends.opensearch]`` options.

    Args:
        options: The options (``url`` at least).
        network: The outbound proxy, NO_PROXY and CA bundle (#538); none: direct, the
            system's trust.

    Returns:
        The backend; it connects when opened.
    """
    checked = replace(_options(options), network=network or OutboundNetwork())
    return make_search_backend(OPENSEARCH_BACKEND, OPENSEARCH_BACKEND, checked, _connect)


def vector_backend(
    options: Mapping[str, object], *, network: OutboundNetwork | None = None
) -> ElasticVectorBackend:
    """Build the vector backend from its ``[index_backends.opensearch]`` options.

    Args:
        options: The options (``url`` at least).
        network: The outbound proxy, NO_PROXY and CA bundle (#538); none: direct, the
            system's trust.

    Returns:
        The backend; it connects when opened.
    """
    checked = replace(_options(options), network=network or OutboundNetwork())
    return make_vector_backend(OPENSEARCH_BACKEND, OPENSEARCH_BACKEND, checked, _connect)
