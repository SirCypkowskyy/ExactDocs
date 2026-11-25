"""Context7 on the golden set: its responses, coverage, the report and the comparison (#493).

Context7 (Upstash) is a hosted documentation service: it serves a library's version only when
someone added it, and otherwise another release or the current docs, flagged in a ``version``
note. The run (``context7_cli``, ``just context7-bench``) asks its Public API's ``/v2/context``
for every golden question with the project's library and the pinned version, decides from the
note whether the version is served, and scores the text it returns with the text scorer (#491),
next to ExactDocs (#489's intervals and paired tests). Questions of a version it does not serve
are asked unpinned and reported apart, as "latest only". This module holds what needs no
network: reading a response, coverage, the budget, the report and the Markdown. See
docs/evals.md#context7.
"""

import json
from collections.abc import Sequence
from http import HTTPStatus
from operator import itemgetter
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict

from exactdocs.retrieval.constants import DEFAULT_QUERY_DOCS_TOKEN_BUDGET
from retrieval_eval.grounded_docs import Baseline, Paired, Recorded
from retrieval_eval.ingestion import tokens
from retrieval_eval.stats import Interval, StatsMethod
from retrieval_eval.text_bench import TextResult, TextRow

SCHEMA_VERSION: Final[int] = 1
"""The JSON report's layout; bumped when a field is renamed or removed."""
API_BASE: Final[str] = "https://context7.com/api"
"""Context7's REST API."""
API_VERSION: Final[str] = "2.0.0"
"""The Public API version measured (``info.version`` of https://context7.com/openapi.json)."""
CONTEXT_PATH: Final[str] = "/v2/context"
"""The documentation endpoint a question goes to (``type=json``)."""
API_KEY_VARIABLE: Final[str] = "CONTEXT7_API_KEY"
"""The environment variable holding the API key (a repository secret in the workflow)."""
TOKEN_BUDGET: Final[int] = DEFAULT_QUERY_DOCS_TOKEN_BUDGET
"""The most text, in estimated tokens, kept of one response: what ExactDocs' ``query-docs``
returns. Context7's API takes no budget, so its results are cut here, best first."""

Status = Literal["served", "unverified", "not served", "error"]
"""Whether Context7 serves a pinned version."""
SERVED: Final[Status] = "served"
"""Coverage: Context7 serves the pinned version (or a tag it verified as that version)."""
UNVERIFIED: Final[Status] = "unverified"
"""Coverage: Context7 serves another release in its place and flags it unverified."""
NOT_SERVED: Final[Status] = "not served"
"""Coverage: Context7 serves only the library's current documentation, or nothing."""
ERROR: Final[Status] = "error"
"""Coverage: the request failed, so nothing is known."""

PINNED: Final[str] = "pinned"
"""The group of served versions, asked with the pinned version."""
LATEST_ONLY: Final[str] = "latest only"
"""The group of versions Context7 does not serve, asked without a version."""
GROUPS: Final[dict[str, str]] = {
    PINNED: "versions Context7 serves, asked with the pinned version",
    UNVERIFIED: (
        "versions Context7 does not have, asked with the pinned version; it served another "
        "release and flagged it unverified"
    ),
    LATEST_ONLY: (
        "versions Context7 does not serve, asked without a version: what an agent gets there"
    ),
}
"""Every group of the report, in order, and what it is. Their numbers never mix."""
GROUP_OF: Final[dict[Status, str]] = {
    SERVED: PINNED,
    UNVERIFIED: UNVERIFIED,
    NOT_SERVED: LATEST_ONLY,
}
"""The group each coverage status's questions are scored in."""


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", use_attribute_docstrings=True)


class Fetched(_Model):
    """One raw ``/v2/context`` response, as the run caches it."""

    status: int
    """The HTTP status."""
    body: str
    """The body, as sent."""
    date: str
    """When it was received (UTC, ISO 8601)."""
    ms: float | None = None
    """How long the request took."""


def _json(fetched: Fetched) -> dict[str, Any] | None:
    """Read a successful response's body.

    Args:
        fetched: The response.

    Returns:
        The JSON object; None for a failed or unreadable response.
    """
    if fetched.status != HTTPStatus.OK:
        return None
    try:
        body = json.loads(fetched.body)
    except ValueError:
        return None
    return body if isinstance(body, dict) else None


def _code(snippet: dict[str, Any]) -> str:
    """A code snippet's text: its code blocks, fenced.

    Its title and description are left out: Context7 writes them, they are not the docs' text.

    Args:
        snippet: One ``codeSnippets`` entry.

    Returns:
        The text.
    """
    blocks = snippet.get("codeList") or []
    return "\n\n".join(f"```{b.get('language', '')}\n{b.get('code', '')}\n```" for b in blocks)


def results_of(fetched: Fetched) -> list[str]:
    """Read a response into its results' texts, in Context7's order (``rank``).

    Args:
        fetched: The response.

    Returns:
        One text per snippet, code and docs alike; none for a failed response.
    """
    body = _json(fetched)
    if body is None:
        return []
    ranked = [(s.get("rank", 0), _code(s)) for s in body.get("codeSnippets") or []]
    ranked += [(s.get("rank", 0), s.get("content", "")) for s in body.get("infoSnippets") or []]
    return [text for _, text in sorted(ranked, key=itemgetter(0)) if text]


def within_budget(texts: Sequence[str], budget: int = TOKEN_BUDGET) -> list[str]:
    """Keep the results that fit the budget, best first, as ``query-docs`` does.

    Args:
        texts: The results, best first.
        budget: The budget, in estimated tokens.

    Returns:
        The leading results whose text fits, in all.
    """
    kept, used = [], 0
    for text in texts:
        used += tokens(text)
        if used > budget:
            break
        kept.append(text)
    return kept


def coverage_of(fetched: Fetched, version: str) -> tuple[Status, str, str | None] | None:
    """Decide from a pinned request's response whether Context7 serves the version.

    Args:
        fetched: The response to ``/owner/repo/<version>``.
        version: The version asked.

    Returns:
        The status, the library ID that served it and the release served (None: the current
        docs or nothing); None when the request failed.
    """
    if fetched.status == HTTPStatus.NOT_FOUND:  # `version_not_found`
        return NOT_SERVED, "", None
    body = _json(fetched)
    if body is None:
        return None
    note = body.get("version")
    if not note:
        return SERVED, str(body.get("libraryId", "")), version
    resolved, served = str(note.get("libraryId", "")), note.get("served")
    if note.get("status") == "verified":
        return SERVED, resolved, served
    return (UNVERIFIED if served else NOT_SERVED), resolved, served


class Coverage(_Model):
    """Whether Context7 serves one pinned version."""

    project: str
    version: str
    requested_id: str
    """The library ID asked: ``/owner/repo/<version>``."""
    status: Status
    """``served``, ``unverified``, ``not served`` or ``error``."""
    resolved_id: str
    """The library ID Context7 says served it (moved libraries and matched tags included)."""
    served: str | None
    """The release served; None for the current docs."""
    date: str
    """When Context7 answered."""


class Group(_Model):
    """Context7's answers to the questions of the versions of one coverage group."""

    name: str
    """``pinned``, ``unverified`` or ``latest only``."""
    about: str
    """What it is."""
    versions: list[str]
    """``<project> <version>`` of each version in it."""
    result: TextResult
    """Context7's metrics on these cases, scored from the text."""
    context_tokens_interval: Interval | None
    """The 95% interval of the context tokens per question."""
    rows: list[TextRow]
    """Every case's row, by case name."""
    baseline: TextResult
    """ExactDocs' BM25 at ``default`` on the same cases, scored the same way."""
    versus: list[Paired]
    """Paired tests against ExactDocs on these cases."""


class Context7Report(_Model):
    """The run's JSON report (``context7.json``), documented in docs/evals.md."""

    schema_version: int = SCHEMA_VERSION
    golden: str
    """The golden set's fingerprint."""
    cases: int
    projects: list[str]
    corpus: list[dict[str, str]]
    """Every pinned version: ``project``, ``version``, ``commit``."""
    date: str
    """When the run ended (UTC, ISO 8601). Context7's index changes: compare no two dates."""
    tool: dict[str, str]
    """Context7: ``name``, ``api``, ``api_version``, ``endpoint``, ``token_budget``, ``client``."""
    environment: dict[str, str]
    """The ExactDocs commit, Python, platform and CPUs."""
    scorer: dict[str, Any]
    """The text scorer's settings."""
    statistics: StatsMethod
    """How the intervals and paired tests were computed."""
    coverage: list[Coverage]
    """Every pinned version."""
    baseline: Baseline
    """ExactDocs' BM25 at ``default`` on every case, scored from its text."""
    recorded: list[Recorded]
    """ExactDocs configurations of the recorded retrieval benchmark run, tested per group."""
    groups: list[Group]
    """One per coverage group with questions."""
    errors: list[str]
    """Questions whose request failed (scored as empty)."""


# ---------------------------------------------------------------- the summary


def _pct(value: float | None) -> str:
    return "-" if value is None else f"{value * 100:.1f}%"


def _rate(value: float | None, spread: Interval | None) -> str:
    """A rate with its interval, in percent.

    Args:
        value: The rate.
        spread: Its interval.

    Returns:
        ``81.7% (77.2-85.8)``, or the rate alone.
    """
    if value is None or spread is None:
        return _pct(value)
    return f"{_pct(value)} ({spread.low * 100:.1f}-{spread.high * 100:.1f})"


def _mean(value: float, spread: Interval | None) -> str:
    """A mean in [0, 1] with its interval.

    Args:
        value: The mean.
        spread: Its interval.

    Returns:
        ``0.734 (0.690-0.770)``, or the mean alone.
    """
    if spread is None:
        return f"{value:.3f}"
    return f"{value:.3f} ({spread.low:.3f}-{spread.high:.3f})"


def _line(name: str, result: TextResult, cases: int) -> str:
    """One line of a group's table.

    Args:
        name: What answered.
        result: Its metrics.
        cases: The cases in the group.

    Returns:
        The line.
    """
    m, spread = result.metrics.metrics, result.metrics.metrics.intervals
    return (
        f"| {name} | {cases} | {_rate(m.recall_at_1, spread.get('recall_at_1'))} "
        f"| {_rate(m.recall_at_5, spread.get('recall_at_5'))} "
        f"| {_rate(m.recall_at_10, spread.get('recall_at_10'))} "
        f"| {_mean(m.mrr, spread.get('mrr'))} | {_mean(m.ndcg_at_10, spread.get('ndcg_at_10'))} "
        f"| {_rate(m.wrong_version_rate, spread.get('wrong_version_rate'))} "
        f"| {_pct(result.metrics.version_neutral_share)} "
        f"| {result.metrics.context_tokens_per_question:,.0f} |"
    )


_TESTED: Final[tuple[str, ...]] = (
    "recall_at_1",
    "recall_at_5",
    "recall_at_10",
    "mrr",
    "ndcg_at_10",
)
"""The metrics the paired tests cover."""


def _tests(group: Group) -> list[str]:
    """A group's paired tests against ExactDocs.

    Args:
        group: The group.

    Returns:
        The lines: one per ExactDocs result, one column per metric.
    """
    lines = [
        "| against | " + " | ".join(name.replace("_at_", "@") for name in _TESTED) + " |",
        "|---|" + "---|" * len(_TESTED),
    ]
    for versus in group.versus:
        cells = []
        for name in _TESTED:
            test = versus.tests.get(name)
            if test is None:
                cells.append("-")
                continue
            scale = 100 if name.startswith("recall") else 1
            verdict = "significant" if test.significant else "not significant"
            cells.append(f"{test.difference * scale:+.3g}, p {test.p_value:.3g}, {verdict}")
        lines.append(f"| {versus.against} ({versus.scored_by}) | " + " | ".join(cells) + " |")
    return lines


def coverage_table(report: Context7Report) -> list[str]:
    """Every pinned version: whether Context7 serves it, what it resolved, and when.

    Args:
        report: The run.

    Returns:
        The lines.
    """
    lines = [
        "| Project | Version | Context7 | Library ID resolved | Release served | Date |",
        "|---|---|---|---|---|---|",
    ]
    lines.extend(
        f"| {c.project} | {c.version} | {c.status} | `{c.resolved_id or c.requested_id}` "
        f"| {c.served or 'current docs'} | {c.date} |"
        for c in report.coverage
    )
    return lines


def markdown(report: Context7Report) -> str:
    """Render the run as a Markdown summary.

    Args:
        report: The run.

    Returns:
        The summary.
    """
    tool, env = report.tool, report.environment
    lines = [
        "# Context7 on the golden set",
        "",
        (
            f"Context7 Public API {tool.get('api_version', '?')}, `{tool.get('endpoint', '?')}`, "
            f"run {report.date}; each response cut at {tool.get('token_budget', '?')} tokens, "
            "what ExactDocs' `query-docs` returns. Context7's index changes over time: these "
            "numbers hold for this date only. Golden set "
            f"{report.cases} cases (`{report.golden}`), ExactDocs commit "
            f"`{env.get('exactdocs_commit', '?')}`. Definitions: docs/evals.md#context7."
        ),
        "",
        "## Coverage of the pinned versions",
        "",
        *coverage_table(report),
    ]
    header = [
        (
            "| Tool | cases | recall@1 | recall@5 | recall@10 | MRR | nDCG@10 | wrong version "
            "| version-neutral | context tokens / q |"
        ),
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for group in report.groups:
        cases = len(group.rows)
        lines += [
            "",
            f"## {group.name.capitalize()}: {group.about}",
            "",
            f"Versions: {', '.join(group.versions)}.",
            "",
            *header,
            _line(group.baseline.tool, group.baseline, cases),
            _line(f"Context7 {group.name}", group.result, cases),
            "",
            "### Paired tests against ExactDocs",
            "",
            *_tests(group),
        ]
    if report.errors:
        lines += ["", "Questions whose request failed (scored as empty):", ""]
        lines += [f"- {e}" for e in report.errors]
    return "\n".join([*lines, ""])


def problems(report: Context7Report) -> list[str]:
    """Say what makes a run unfit to record: a failed request.

    Args:
        report: The run.

    Returns:
        The problems.
    """
    found = []
    if unknown := [f"{c.project} {c.version}" for c in report.coverage if c.status == ERROR]:
        found.append(f"coverage unknown for {', '.join(unknown)}")
    if report.errors:
        found.append(f"{len(report.errors)} question(s) failed")
    return found
