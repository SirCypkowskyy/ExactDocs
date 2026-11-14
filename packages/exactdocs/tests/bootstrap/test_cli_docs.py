"""``library`` and ``docs``: requests, output safety, the notice, exit codes."""

import json

import httpx2
import pytest

from exactdocs.bootstrap.cli_library import UsageError, exit_code, find_library, query_docs
from exactdocs.bootstrap.client import ApiClient, ApiError, ClientError
from exactdocs.bootstrap.constants import EXIT_NOT_FOUND, EXIT_USAGE
from exactdocs_kernel import NOTICE

BIDI = chr(0x202E)
HOSTILE = f"\x1b[2J\x1b]0;pwned\x07evil\r\n{BIDI}line two\tcell\x00\n"
LIBRARY = {
    "id": "/acme/docs",
    "title": "Acme\x1b[31m Docs\nSecond line",
    "description": "d\x07esc",
    "defaultVersion": "v1",
    "articles": 3,
    "totalSnippets": 9,
    "versions": ["v1", "v0"],
    "sourceUrl": "https://example.test/acme/docs",
}


def client(handler: httpx2.MockTransport) -> ApiClient:
    return ApiClient("http://localhost", "t", transport=handler)


async def test_docs_text_keeps_the_notice_and_line_breaks_but_drops_controls(
    capsys: pytest.CaptureFixture[str],
) -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, text=f"{NOTICE}\n\n### T\n\n{HOSTILE}")

    async with client(httpx2.MockTransport(handler)) as api:
        await query_docs(api, "/acme/docs@v1", "retry policy", language="go", as_json=False)

    out = capsys.readouterr().out
    assert out.startswith(NOTICE + "\n\n### T\n\n")
    assert "\x1b" not in out
    assert "\r" not in out
    assert "\x07" not in out
    assert "\x00" not in out
    assert BIDI not in out
    assert "evil\nline two\tcell\n" in out
    assert out.endswith("\n")
    assert dict(seen[0].url.params) == {
        "libraryId": "/acme/docs@v1",
        "query": "retry policy",
        "type": "txt",
        "language": "go",
    }


async def test_docs_json_is_the_response_with_its_notice(
    capsys: pytest.CaptureFixture[str],
) -> None:
    body = {"notice": NOTICE, "infoSnippets": [{"content": HOSTILE}], "codeSnippets": []}

    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.params["type"] == "json"
        return httpx2.Response(200, json=body)

    async with client(httpx2.MockTransport(handler)) as api:
        await query_docs(api, "/acme/docs", "q", as_json=True)

    out = capsys.readouterr().out
    assert json.loads(out) == body
    assert "\x1b" not in out  # json.dumps escapes it


@pytest.mark.parametrize("library_id", ["acme/docs", "/acme", "/", "react"])
async def test_a_malformed_library_id_is_refused_before_any_request(library_id: str) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise AssertionError(request)

    async with client(httpx2.MockTransport(handler)) as api:
        with pytest.raises(UsageError, match="invalid library ID") as raised:
            await query_docs(api, library_id, "q", as_json=False)
    assert exit_code(raised.value) == EXIT_USAGE


async def test_an_unknown_library_is_exit_3_and_prints_nothing_on_stdout(
    capsys: pytest.CaptureFixture[str],
) -> None:
    def handler(_: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            404, json={"error": "not_found", "detail": "no such library", "message": "no such"}
        )

    async with client(httpx2.MockTransport(handler)) as api:
        with pytest.raises(ApiError) as raised:
            await query_docs(api, "/a/b", "q", as_json=False)
    assert exit_code(raised.value) == EXIT_NOT_FOUND
    assert not capsys.readouterr().out


async def test_library_lists_results_safely_with_the_notice_first(
    capsys: pytest.CaptureFixture[str],
) -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json={"notice": NOTICE, "results": [LIBRARY]})

    async with client(httpx2.MockTransport(handler)) as api:
        await find_library(api, "acme", None)

    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == NOTICE
    assert "1. Title: Acme[31m Docs Second line" in lines
    assert "   Context7-compatible library ID: /acme/docs" in lines
    assert "   Versions: v1, v0" in lines
    assert not any("\x1b" in line or "\x07" in line for line in lines)
    assert dict(seen[0].url.params) == {"libraryName": "acme", "query": "acme"}


async def test_library_json_is_the_bare_list_and_the_notice_goes_to_stderr(
    capsys: pytest.CaptureFixture[str],
) -> None:
    def handler(_: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json={"notice": NOTICE, "results": [LIBRARY]})

    async with client(httpx2.MockTransport(handler)) as api:
        await find_library(api, "acme", "q", as_json=True)

    out, err = capsys.readouterr()
    assert json.loads(out) == [LIBRARY]
    assert err.strip() == NOTICE


async def test_a_success_that_is_not_text_says_a_text_body_was_expected() -> None:
    def handler(_: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json={"notice": NOTICE})  # an older server ignoring type=txt

    async with client(httpx2.MockTransport(handler)) as api:
        with pytest.raises(ClientError, match="expected a text body") as raised:
            await api.request_text("GET", "/c7/docs")
    assert not isinstance(raised.value, ApiError)
