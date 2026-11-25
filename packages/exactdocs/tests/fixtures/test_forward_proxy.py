"""The stand-in Hub and the stand-in proxy keep a client's connection usable (#589).

A client that reuses its connection, as httpx does, sends the next request on it as soon as an
answer has arrived. The proxy used to close it after one request without saying so, and the next
request failed with "Server disconnected without sending a response".
"""

from collections.abc import Iterator

import httpx
import pytest

from fake_hub import FakeHub, fake_hub
from forward_proxy import forward_proxy

PAIRS = 20
"""How many times a test asks for an unknown path, then a known one."""


@pytest.fixture
def hub() -> Iterator[FakeHub]:
    with fake_hub() as running:
        yield running


def _ask(client: httpx.Client, base: str) -> tuple[list[int], set[object]]:
    """Ask for an unknown path, then a known one, ``PAIRS`` times on one client.

    Returns:
        The status of each answer, and the client side's address of each connection used.
    """
    statuses, connections = [], set()
    for _ in range(PAIRS):
        for path in ("/api/agent-harnesses", "/api/models/acme/model"):
            answer = client.get(f"{base}{path}")
            statuses.append(answer.status_code)
            connections.add(answer.extensions["network_stream"].get_extra_info("client_addr"))
    return statuses, connections


def test_the_hub_answers_an_unknown_path_with_404_on_a_connection_it_keeps(hub: FakeHub) -> None:
    with httpx.Client(trust_env=False) as client:
        statuses, connections = _ask(client, hub.url)

    assert statuses == [404, 200] * PAIRS
    assert len(connections) == 1
    assert len(hub.seen) == 2 * PAIRS


def test_the_proxy_keeps_a_plain_http_connection_open_from_one_request_to_the_next(
    hub: FakeHub,
) -> None:
    host, _, port = hub.url.removeprefix("http://").partition(":")
    with (
        forward_proxy({"hub.example.test:80": (host, int(port))}) as proxy,
        httpx.Client(proxy=proxy.url, trust_env=False) as client,
    ):
        statuses, connections = _ask(client, "http://hub.example.test")

    assert statuses == [404, 200] * PAIRS
    assert len(connections) == 1  # one connection to the proxy carried every request
    assert len(proxy.seen) == len(hub.seen) == 2 * PAIRS  # and the proxy saw each one


def test_the_proxy_says_it_closes_a_connection_after_refusing_a_host() -> None:
    with (
        forward_proxy() as proxy,
        httpx.Client(proxy=proxy.url, trust_env=False) as client,
    ):
        answers = [client.get("http://nowhere.example.test/") for _ in range(3)]

    assert [a.status_code for a in answers] == [403] * 3
    assert {a.headers.get("connection") for a in answers} == {"close"}
    assert len(proxy.seen) == 3
