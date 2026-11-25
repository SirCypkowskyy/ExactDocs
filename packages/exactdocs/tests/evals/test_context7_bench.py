"""Context7 on the golden set (#493): its responses, coverage, the budget, the cache and the run.

Context7 is ``context7_stand_in``; nothing here reaches the network. The real run is
``just context7-bench`` (docs/evals/context7.md).
"""

import json
from pathlib import Path

import httpx
import pytest

from context7_stand_in import DATE, INSTALL_CODE, INSTALL_TEXT, StandInContext7
from retrieval_bench_stand_ins import tiny_corpus
from retrieval_eval.context7 import (
    API_KEY_VARIABLE,
    LATEST_ONLY,
    NOT_SERVED,
    PINNED,
    SERVED,
    TOKEN_BUDGET,
    UNVERIFIED,
    Context7Report,
    Fetched,
    coverage_of,
    problems,
    results_of,
    within_budget,
)
from retrieval_eval.context7_cli import CachedContext7, HttpContext7, main


def _ok(body: dict) -> Fetched:
    return Fetched(status=200, body=json.dumps(body), date=DATE)


# ---------------------------------------------------------------- reading /v2/context


def test_results_come_in_context7s_rank_across_code_and_docs() -> None:
    body = {
        "codeSnippets": [
            {"codeTitle": "T", "codeDescription": "D", "rank": 1, "codeList": [
                {"language": "py", "code": "a = 1"}, {"language": "py", "code": "b = 2"},
            ]},
        ],
        "infoSnippets": [
            {"content": "Second.", "breadcrumb": "A > B", "rank": 2},
            {"content": "Third.", "rank": 3},
        ],
    }  # fmt: skip

    texts = results_of(_ok(body))

    assert texts == ["```py\na = 1\n```\n\n```py\nb = 2\n```", "Second.", "Third."]


def test_a_failed_or_unreadable_response_has_no_result() -> None:
    assert results_of(Fetched(status=404, body="{}", date=DATE)) == []
    assert results_of(Fetched(status=200, body="not json", date=DATE)) == []


def test_results_are_cut_at_the_query_docs_budget_best_first() -> None:
    big = "x" * (TOKEN_BUDGET * 4 - 40)  # TOKEN_BUDGET - 10 tokens

    assert within_budget([big, "y" * 40, "z" * 4]) == [big, "y" * 40]
    assert within_budget(["z" * 4, "x" * (TOKEN_BUDGET * 4 + 4)]) == ["z" * 4]


# ---------------------------------------------------------------- coverage


def test_a_version_without_a_version_note_is_served() -> None:
    assert coverage_of(_ok({"libraryId": "/a/b@v1"}), "v1") == (SERVED, "/a/b@v1", "v1")


def test_a_verified_match_is_served_as_the_tag_context7_matched() -> None:
    version = {"libraryId": "/a/b/v1.2.3", "requested": "v1.2", "served": "v1.2.3",
               "status": "verified"}  # fmt: skip

    assert coverage_of(_ok({"version": version}), "v1.2") == (SERVED, "/a/b/v1.2.3", "v1.2.3")


def test_another_release_is_unverified_and_current_docs_are_not_served() -> None:
    other = {"libraryId": "/a/b/v2", "requested": "v1", "served": "v2", "status": "unverified"}
    current = {"libraryId": "/a/b", "requested": "v1", "served": None, "status": "unverified"}

    assert coverage_of(_ok({"version": other}), "v1") == (UNVERIFIED, "/a/b/v2", "v2")
    assert coverage_of(_ok({"version": current}), "v1") == (NOT_SERVED, "/a/b", None)
    assert coverage_of(Fetched(status=404, body="{}", date=DATE), "v1") == (NOT_SERVED, "", None)


def test_an_error_decides_nothing() -> None:
    assert coverage_of(Fetched(status=429, body="{}", date=DATE), "v1") is None


# ---------------------------------------------------------------- the client and its cache


async def test_the_client_sends_the_pinned_api_with_the_key() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"codeSnippets": [], "infoSnippets": []})

    client = HttpContext7("secret", transport=httpx.MockTransport(handler))

    fetched = await client.context("/a/b/v1", "how?")

    (request,) = seen
    assert request.url.path == "/api/v2/context"
    assert dict(request.url.params) == {"libraryId": "/a/b/v1", "query": "how?", "type": "json"}
    assert request.headers["authorization"] == "Bearer secret"
    assert fetched.status == 200
    assert fetched.ms is not None


async def test_the_client_waits_out_a_rate_limit() -> None:
    answers = iter([httpx.Response(429, headers={"Retry-After": "0"}), httpx.Response(200)])
    client = HttpContext7("k", transport=httpx.MockTransport(lambda _r: next(answers)))

    assert (await client.context("/a/b", "q")).status == 200


async def test_a_cached_response_is_not_asked_again(tmp_path: Path) -> None:
    inner = StandInContext7()
    cached = CachedContext7(tmp_path, inner)

    first = await cached.context("/a/b/v1", "install demo package pip")
    again = await CachedContext7(tmp_path, None).context("/a/b/v1", "install demo package pip")

    assert first == again
    assert len(inner.calls) == 1


async def test_from_cache_a_missing_response_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="not in the cache"):
        await CachedContext7(tmp_path, None).context("/a/b", "q")


async def test_a_failed_response_is_not_cached(tmp_path: Path) -> None:
    inner = StandInContext7(serves="error")
    await CachedContext7(tmp_path, inner).context("/a/b", "q")

    with pytest.raises(RuntimeError, match="not in the cache"):
        await CachedContext7(tmp_path, None).context("/a/b", "q")


# ---------------------------------------------------------------- the run


def _args(tmp_path: Path) -> list[str]:
    tiny_corpus(tmp_path)
    return [
        "--corpus", str(tmp_path / "corpus.yaml"), "--cases", str(tmp_path / "cases"),
        "--cache-dir", str(tmp_path / "cache"), "--responses", str(tmp_path / "responses"),
        "--out", str(tmp_path / "out"), "--recorded", str(tmp_path / "none.json"),
    ]  # fmt: skip


def _report(tmp_path: Path) -> Context7Report:
    return Context7Report.model_validate_json((tmp_path / "out" / "context7.json").read_text())


def test_the_run_refuses_to_call_context7_without_a_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(API_KEY_VARIABLE, raising=False)

    assert main(_args(tmp_path)) == 2


def test_a_served_version_is_scored_pinned(tmp_path: Path) -> None:
    tool = StandInContext7()

    assert main(_args(tmp_path), tool=lambda: tool) == 0

    report = _report(tmp_path)
    assert [c.status for c in report.coverage] == [SERVED]
    (group,) = report.groups
    assert group.name == PINNED
    assert group.versions == ["demo v1"]
    answerable = next(r for r in group.rows if r.row.answerable)
    assert answerable.row.rank == 1
    assert report.tool["token_budget"] == str(TOKEN_BUDGET)
    assert len(tool.calls) == 2  # the first question resolves the version and is reused


def test_latest_only_never_mixes_with_pinned(tmp_path: Path) -> None:
    tool = StandInContext7(serves="current only")

    assert main(_args(tmp_path), tool=lambda: tool) == 0

    (group,) = _report(tmp_path).groups
    assert group.name == LATEST_ONLY
    assert all(len(lib.split("/")) == 3 for lib, _ in tool.calls[1:])  # /owner/repo, no version


def test_a_failed_question_is_a_problem(tmp_path: Path) -> None:
    assert main(_args(tmp_path), tool=lambda: StandInContext7(serves="error")) == 1

    report = _report(tmp_path)
    assert report.coverage[0].status == "error"
    assert problems(report)


async def test_the_text_scored_is_the_docs_own() -> None:
    fetched = await StandInContext7().context("/a/b/v1", "install demo package pip")

    assert results_of(fetched) == [INSTALL_TEXT, f"```sh\n{INSTALL_CODE}\n```"]
