"""Elasticsearch as the search and vector backend (#354): ``exactdocs[elasticsearch]``.

The requests, mappings and answers are ``elastic_index``'s (shared with OpenSearch); this module
adds the official client (8.x: it talks to Elasticsearch 8 and 9, the latter through its REST
compatibility with 8) over elastic-transport's httpx node, and the options: ``url``,
``index_prefix``, an API key (``api_key`` / ``api_key_file``), basic auth (``username`` with
``password`` / ``password_file``) or a bearer token (``token`` / ``token_file``), and TLS with a
custom CA (``ca_certs``). Imported only when ``EXACTDOCS_SEARCH_BACKEND`` or
``EXACTDOCS_VECTOR_BACKEND`` is ``elasticsearch``.
"""

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import Any

from elastic_transport import HttpxAsyncHttpNode
from elasticsearch import ApiError, AsyncElasticsearch, TransportError

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
    ELASTICSEARCH_BACKEND,
    ELASTICSEARCH_SECRETS,
)
from exactdocs.retrieval.errors import IndexBackendUnavailableError


@dataclass(frozen=True, slots=True, kw_only=True)
class _Client:
    """Implements ``elastic_index.Engine`` with ``AsyncElasticsearch``."""

    client: AsyncElasticsearch
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
            response = await self.client.perform_request(
                method, path, params=params, headers=headers, body=body
            )
        except ApiError as error:
            status = error.meta.status
            if status in allow:
                return Answer(status=status, body=_json(error.body))
            raise IndexBackendUnavailableError(
                ELASTICSEARCH_BACKEND, error_reason(status, error.body)
            ) from error
        except TransportError as error:
            reason = f"{type(error).__name__}: {error.message}"
            raise IndexBackendUnavailableError(ELASTICSEARCH_BACKEND, reason) from error
        return Answer(status=response.meta.status, body=_json(response.body))

    async def close(self) -> None:
        """Close the client's connections."""
        await self.client.close()


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
    auth: dict[str, Any] = {} if options.ca_certs is None else {"ca_certs": options.ca_certs}
    if options.api_key is not None:
        key_id, colon, key = options.api_key.partition(":")
        auth["api_key"] = (key_id, key) if colon else options.api_key
    elif options.token is not None:
        auth["bearer_auth"] = options.token
    elif options.username is not None:
        auth["basic_auth"] = (options.username, options.password or "")
    client = AsyncElasticsearch(
        list(options.urls),
        node_class=HttpxAsyncHttpNode,
        verify_certs=options.verify_certs,
        request_timeout=options.request_timeout,
        max_retries=ELASTIC_MAX_RETRIES,
        retry_on_timeout=True,
        **auth,
    )
    return _Client(client=client)


def _options(options: Mapping[str, object]) -> ElasticOptions:
    """Check the ``[index_backends.elasticsearch]`` options.

    Args:
        options: The table.

    Returns:
        The options.

    Raises:
        ValueError: An option is invalid, or more than one way to sign in is given.
    """
    checked = parse_options(ELASTICSEARCH_BACKEND, options, ELASTICSEARCH_SECRETS)
    ways = [checked.api_key, checked.token, checked.username]
    if sum(way is not None for way in ways) > 1:
        message = "sign in one way: `api_key`, `token` or `username` with `password`"
        raise ValueError(message)
    return checked


def search_backend(options: Mapping[str, object]) -> ElasticSearchBackend:
    """Build the search backend from its ``[index_backends.elasticsearch]`` options.

    Args:
        options: The options (``url`` at least).

    Returns:
        The backend; it connects when opened.
    """
    checked = _options(options)
    return make_search_backend(ELASTICSEARCH_BACKEND, ELASTICSEARCH_BACKEND, checked, _connect)


def vector_backend(options: Mapping[str, object]) -> ElasticVectorBackend:
    """Build the vector backend from its ``[index_backends.elasticsearch]`` options.

    Args:
        options: The options (``url`` at least).

    Returns:
        The backend; it connects when opened.
    """
    checked = _options(options)
    return make_vector_backend(ELASTICSEARCH_BACKEND, ELASTICSEARCH_BACKEND, checked, _connect)
