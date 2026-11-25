"""The benchmark's report: one row per question, a summary per agent model, arm and retrieval setup.

Each cell gives quality (accuracy, answers true of another version only, refusals, tool calls) and
cost (wall time, input tokens, output tokens with the thinking, thinking tokens on their own, USD),
each rate and mean with its 95% interval (#489), and each cost as mean, p50 and p95. Every arm is
compared with ``none`` and with ``exactdocs`` on the same cases (#495): accuracy by McNemar's test,
time and tokens by a paired permutation test. A question the provider failed on (``error``) is
left out of every rate, mean and test; one the agent never answered (``no_answer``) is a miss.
"""

import statistics
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Sequence
from typing import Final

from pydantic import BaseModel, ConfigDict, Field
from pydantic_evals.reporting import EvaluationReport

from agent_bench.arms import ARMS, BASELINES, EXACTDOCS
from agent_bench.harness import (
    AgentRun,
    BenchInfo,
    ToolCall,
    grounded,
    read_other_versions,
)
from agent_bench.judge import ERROR, GRADE, GRADES, NO_ANSWER, WRONG_VERSION
from agent_bench.redact import scrub
from retrieval_eval.dataset import Question
from retrieval_eval.stats import DEFAULT as DEFAULT_STATS
from retrieval_eval.stats import (
    Interval,
    PairedTest,
    StatsMethod,
    interval,
    paired_binary,
    paired_mean,
)
from retrieval_eval.suite import percentile

CORRECT: Final[str] = "correct"
"""The grade that counts as accurate."""
REFUSED: Final[str] = "refused"
"""The grade of an answer that says the documentation does not cover the question, or that the
agent does not know."""
UNANSWERABLE: Final[str] = "unanswerable"
"""The kind of a case its version does not answer: there a refusal is the right answer."""
P95: Final[float] = 0.95
"""The high percentile of each cost."""
FAILURES_SHOWN: Final[int] = 30
"""Runs without an answer listed in the Markdown (all are in the JSON)."""


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class QuestionResult(_Model):
    """One question asked of one agent model with one arm (and retrieval configuration)."""

    agent_model: str
    """The agent's model."""
    arm: str = EXACTDOCS
    """The documentation arm (``arms.ARMS``)."""
    retrieval: str
    """The retrieval configuration's name; empty for an arm without one (``none``)."""
    case: str
    """The golden case's name."""
    project: str
    """The golden project."""
    kind: str
    """The golden kind."""
    version: str
    """The version asked about."""
    question: str
    """The question."""
    reference: str = ""
    """The case's reference answer."""
    facts: list[str] = Field(default_factory=list)
    """The facts a correct answer must contain."""
    grade: str
    """One of ``judge.GRADES``, ``no_answer`` (the agent never answered) or ``error`` (the
    provider or the judge failed)."""
    wrong_version: bool = False
    """The judge found something true of another version only."""
    grounded: bool | None = None
    """The agent read every answering section; ``None`` when the case has none."""
    other_versions_read: list[str] = Field(default_factory=list)
    """``<version>:<article>`` the agent read of the asked library at another version."""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    """The agent's tool calls."""
    chunks_read: list[str] = Field(default_factory=list)
    """``<chunk ID>@<version>`` of each chunk read in full (``<article>@<version>`` for a whole
    article)."""
    retrieval_modes: list[str] = Field(default_factory=list)
    """How each search was answered."""
    input_tokens: int = 0
    """The agent's input tokens."""
    output_tokens: int = 0
    """The agent's output tokens, thinking included."""
    thinking_tokens: int | None = None
    """The agent's thinking tokens; ``None`` when none was returned or reported."""
    thinking_estimated: bool = False
    """``thinking_tokens`` is estimated from the thinking text."""
    usd: float | None = None
    """What the agent's tokens cost; ``None`` when unpriced."""
    seconds: float = 0.0
    """The run's wall time, retries included."""
    provider_retries: int = 0
    """Model requests that failed and were retried."""
    retry_seconds: float = 0.0
    """Of ``seconds``, the time lost to those retries."""
    answer: str = ""
    """The agent's answer, as it gave it (the judge read it with the arms' names removed)."""
    judge_reason: str = ""
    """The judge's reason (or what failed)."""

    @property
    def net_seconds(self) -> float:
        """The wall time without the time lost to provider retries.

        Returns:
            Seconds.
        """
        return max(self.seconds - self.retry_seconds, 0.0)


class Breakdown(_Model):
    """Accuracy over a subset of questions (one kind, one project)."""

    questions: int
    """Questions in the subset (those the provider failed on left out)."""
    correct: int
    """Graded correct."""
    accuracy: float
    """``correct / questions``."""
    interval: Interval | None = None
    """The 95% interval of ``accuracy`` (#489); wide on a few dozen questions."""


class Spread(_Model):
    """One cost per question: mean with its 95% interval, median and 95th percentile."""

    questions: int
    """Questions measured."""
    mean: float
    """The mean."""
    interval: Interval | None
    """The 95% bootstrap interval of the mean."""
    p50: float
    """The median."""
    p95: float
    """The 95th percentile (nearest rank, as the retrieval suite's latencies)."""


class ArmComparison(_Model):
    """A cell against a baseline arm's cell for the same agent model, on the same cases (#495)."""

    against: str
    """The baseline arm (``none`` or ``exactdocs``)."""
    against_retrieval: str = ""
    """The baseline cell's retrieval configuration (its arm's first)."""
    cases: int
    """Cases both answered without a provider failure."""
    accuracy: PairedTest | None
    """McNemar's test (mid-p) of accuracy: this cell minus the baseline, as a share."""
    seconds: PairedTest | None
    """Paired permutation test of the wall time per question (retries left out), in seconds."""
    input_tokens: PairedTest | None
    """Paired permutation test of the input tokens per question."""
    output_tokens: PairedTest | None
    """Paired permutation test of the output tokens per question, thinking included."""
    seconds_ratio: float | None
    """This cell's mean wall time over the baseline's, on these cases."""
    output_tokens_ratio: float | None
    """This cell's mean output tokens over the baseline's, on these cases."""


class CellSummary(_Model):
    """One agent model with one arm (and retrieval configuration)."""

    agent_model: str
    """The agent's model."""
    arm: str = EXACTDOCS
    """The documentation arm."""
    retrieval: str
    """The retrieval configuration; empty for an arm without one."""
    questions: int
    """Questions asked."""
    answered: int = 0
    """Questions with a result: ``questions`` without those the provider failed on. Every rate
    and mean is over these."""
    grades: dict[str, int]
    """How many questions got each grade (``no_answer`` and ``error`` included)."""
    accuracy: float
    """Share graded correct (``refused`` on an unanswerable case counts)."""
    wrong_version: int
    """Answers the judge found wrong for the version (true of another version only)."""
    wrong_version_share: float | None = None
    """``wrong_version`` over the answered questions."""
    refused_answerable: int = 0
    """Answerable questions the agent refused (said not covered or not known): misses."""
    refused_answerable_share: float | None = None
    """Of the answered answerable questions, the share refused."""
    correct_refusals: int = 0
    """Unanswerable questions the agent refused: the right answer there."""
    correct_refusal_share: float | None = None
    """Of the answered unanswerable questions, the share refused."""
    grounded_share: float | None
    """Of the answerable questions, the share where the agent read every answering section."""
    read_other_versions: int
    """Questions where the agent read something of the asked library at another version."""
    tool_calls_per_question: float
    """Mean tool calls."""
    tool_errors: int = 0
    """Tool calls that failed (an argument refused, a path not found...), over the answered
    questions (#573): each costs the agent a turn, and a tool that fails twice ends the run."""
    runs_with_tool_errors: int = 0
    """Answered questions where at least one tool call failed."""
    tool_errors_by_tool: dict[str, int] = Field(default_factory=dict)
    """``tool_errors`` per tool."""
    tokens_per_question: float
    """Mean input plus output tokens."""
    usd_per_question: float | None
    """Mean USD; ``None`` when a run was unpriced."""
    seconds_p50: float
    """Median wall time per question (retries left out)."""
    seconds: Spread | None = None
    """Wall time per question, without the time lost to provider retries."""
    input_tokens: Spread | None = None
    """Input tokens per question."""
    output_tokens: Spread | None = None
    """Output tokens per question, thinking included."""
    thinking_tokens: Spread | None = None
    """Thinking tokens per question, over the questions that returned or reported thinking;
    ``None`` when none did (not 0)."""
    thinking_returned: int = 0
    """Questions with thinking tokens (reported or estimated)."""
    thinking_estimated: bool = False
    """Some of ``thinking_tokens`` are estimated from the thinking text."""
    usd: Spread | None = None
    """USD per question; ``None`` when a run was unpriced (never 0 for unpriced)."""
    tool_calls: Spread | None = None
    """Tool calls per question."""
    provider_retries: int = 0
    """Model requests that failed and were retried, over the cell."""
    retry_seconds: float = 0.0
    """The time those retries took, over the cell."""
    retrieval_modes: dict[str, int]
    """How the searches were answered (``<mode>`` or ``<mode> (<fallback reason>)``), counted."""
    by_kind: dict[str, Breakdown]
    """Accuracy per golden kind."""
    by_project: dict[str, Breakdown]
    """Accuracy per golden project."""
    intervals: dict[str, Interval] = Field(default_factory=dict)
    """The 95% interval of ``accuracy``, ``grounded_share``, the other shares and the means per
    question (#489): a percentile bootstrap over the questions."""
    reference: str | None = None
    """The retrieval configuration this cell is tested against: its arm's first, for the same
    agent model (#489). None for that configuration itself."""
    versus_reference: PairedTest | None = None
    """McNemar's test (mid-p) of this cell's accuracy against ``reference``'s, on the questions
    both answered."""
    versus: list[ArmComparison] = Field(default_factory=list)
    """This cell against ``none`` and ``exactdocs`` (when it is neither, and they ran)."""


class CorpusCommit(_Model):
    """One imported version: the commit the manifest pins and the one the catalog recorded."""

    project: str
    """The golden project."""
    version: str
    """The version."""
    pinned_commit: str
    """From ``corpus.yaml``."""
    imported_commit: str
    """What the import recorded."""


class RunMeta(_Model):
    """What a run needs to be reproduced.

    It never holds a key: settings that name one are recorded as ``<redacted>``, and base URLs
    without user, password or query.
    """

    started_at: str
    """When it started (UTC, ISO 8601)."""
    exactdocs_version: str
    """The installed ExactDocs."""
    git_commit: str
    """The repository's commit the benchmark ran from."""
    agent_models: list[str]
    """The agent models."""
    judge_model: str
    """The judge's model."""
    arms: list[str] = Field(default_factory=lambda: [EXACTDOCS])
    """The documentation arms, in order."""
    retrieval: dict[str, dict[str, str]]
    """Each retrieval configuration's settings (``EXACTDOCS_AI__...``), secrets redacted."""
    max_requests: int
    """The model-request limit per question, the same for every arm."""
    concurrency: int
    """Questions asked at once."""
    cases: int
    """Questions per agent model and arm."""
    selection: str = "all"
    """How the cases were picked (all, a stratified sample, a filter)."""
    thinking: str = "model default"
    """The agents' thinking setting (pydantic-ai ``thinking``), or the model's default."""
    max_retries: int = 0
    """Retries of a failed provider request."""
    providers: dict[str, str] = Field(default_factory=dict)
    """Where the models are served: provider to base URL, never a key."""
    agent_instructions: dict[str, str]
    """Each arm's instructions."""
    prompt: str
    """The user prompt's template."""
    corpus: list[CorpusCommit]
    """Every imported version and its commit."""
    servers: dict[str, dict[str, str]] = Field(default_factory=dict)
    """What each setup's documentation server was (``servers.ArmServers.described``): the
    server and its release, its integrity hash, its configuration and the tools the agent got;
    empty for stand-ins."""
    resumed: int = 0
    """Questions kept from an earlier run of the same command (``--resume``), not asked again:
    they ran at that run's commit and time."""


class BenchReport(_Model):
    """The whole run."""

    meta: RunMeta
    """How it ran."""
    cells: list[CellSummary]
    """One summary per agent model, arm and retrieval configuration."""
    questions: list[QuestionResult]
    """Every question's record."""
    statistics: StatsMethod | None = None
    """How the intervals and tests were computed: seed, resamples, confidence and level (#489)."""


def results_of(
    report: EvaluationReport[Question, AgentRun, BenchInfo],
    agent_model: str,
    retrieval: str,
    *,
    arm: str = EXACTDOCS,
) -> list[QuestionResult]:
    """Flatten one evaluation into question records.

    Args:
        report: The evaluated cases of one agent model, arm and configuration.
        agent_model: The agent's model.
        retrieval: The configuration's name (empty for an arm without one).
        arm: The arm.

    Returns:
        One record per case; a case whose task or judge failed is graded ``error``.
    """
    rows = []
    for case in report.cases:
        run, info = case.output, case.metadata
        if info is None:
            continue
        label = case.labels.get(GRADE)
        wrong = case.assertions.get(WRONG_VERSION)
        failures = "; ".join(f"{f.name}: {f.error_message}" for f in case.evaluator_failures)
        rows.append(
            QuestionResult(
                agent_model=agent_model,
                arm=arm,
                retrieval=retrieval,
                case=case.name,
                project=info.project,
                kind=info.kind,
                version=case.inputs.version,
                question=case.inputs.query,
                reference=info.reference,
                facts=info.facts,
                grade=label.value if label else ERROR,
                wrong_version=bool(wrong and wrong.value),
                grounded=grounded(info, run) if traced(arm) else None,
                other_versions_read=read_other_versions(case.inputs, info, run),
                tool_calls=run.tool_calls,
                chunks_read=[
                    f"{s.article if s.whole_article else s.chunk_id}@{s.version}" for s in run.read
                ],
                retrieval_modes=run.retrieval_modes,
                input_tokens=run.input_tokens,
                output_tokens=run.output_tokens,
                thinking_tokens=run.thinking_tokens,
                thinking_estimated=run.thinking_estimated,
                usd=run.usd,
                seconds=run.seconds,
                provider_retries=run.provider_retries,
                retry_seconds=run.retry_seconds,
                answer=run.answer,
                judge_reason=scrub((label.reason or "") if label else failures),
            )
        )
    for failure in report.failures:
        info = failure.metadata
        rows.append(
            QuestionResult(
                agent_model=agent_model,
                arm=arm,
                retrieval=retrieval,
                case=failure.name,
                project=info.project if info else "",
                kind=info.kind if info else "",
                version=failure.inputs.version,
                question=failure.inputs.query,
                reference=info.reference if info else "",
                facts=info.facts if info else [],
                grade=ERROR,
                judge_reason=scrub(f"the task failed: {failure.error_message}"),
            )
        )
    return rows


def traced(arm: str) -> bool:
    """Tell whether an arm's reads can be traced to the golden set's sections (``Arm.traced``).

    Args:
        arm: The arm's name.

    Returns:
        False for an arm whose text comes from an index of sources the run does not know.
    """
    known = ARMS.get(arm)
    return known is None or known.traced


def accurate(row: QuestionResult) -> bool:
    """Tell whether a question counts as answered right.

    ``correct`` always does. ``refused`` (the documentation does not cover it, or the agent does
    not know) does only for an ``unanswerable`` case, where it is the right answer; for any other
    kind it is a miss, as is ``no_answer``.

    Args:
        row: The question, with its raw grade.

    Returns:
        True when it counts towards accuracy.
    """
    return row.grade == CORRECT or (row.kind == UNANSWERABLE and row.grade == REFUSED)


def counted(row: QuestionResult) -> bool:
    """Tell whether a question counts in the rates: everything but a provider or judge failure.

    Args:
        row: The question.

    Returns:
        False for ``error``.
    """
    return row.grade != ERROR


def _breakdown(rows: Sequence[QuestionResult], key: Callable[[QuestionResult], str]) -> dict:
    """Accuracy per value of ``key``, over the counted questions.

    Args:
        rows: The questions.
        key: What to group by.

    Returns:
        Group to its breakdown, sorted by group.
    """
    groups: defaultdict[str, list[QuestionResult]] = defaultdict(list)
    for row in rows:
        if counted(row):
            groups[key(row)].append(row)
    return {
        name: Breakdown(
            questions=len(group),
            correct=(correct := sum(accurate(r) for r in group)),
            accuracy=round(correct / len(group), 3),
            interval=interval([float(accurate(r)) for r in _ordered(group)], digits=3),
        )
        for name, group in sorted(groups.items())
    }


def _mean(values: Iterable[float]) -> float:
    """The mean, 0 for nothing.

    Args:
        values: The numbers.

    Returns:
        Their mean, rounded to 3 places.
    """
    values = list(values)
    return round(statistics.fmean(values), 3) if values else 0.0


def _share(part: int, whole: int) -> float | None:
    """A share, ``None`` over nothing.

    Args:
        part: The count.
        whole: Out of.

    Returns:
        ``part / whole`` rounded to 3 places.
    """
    return round(part / whole, 3) if whole else None


def _ordered(rows: Iterable[QuestionResult]) -> list[QuestionResult]:
    """Put questions in case order, so cells of the same questions share the bootstrap's draws.

    Args:
        rows: The questions.

    Returns:
        Them, by case name.
    """
    return sorted(rows, key=lambda r: r.case)


def spread(values: Sequence[float], *, digits: int = 3) -> Spread | None:
    """Mean with its interval, median and 95th percentile of one cost.

    Args:
        values: One value per question, in case order.
        digits: Decimals kept.

    Returns:
        The spread; ``None`` for no value.
    """
    if not values:
        return None
    return Spread(
        questions=len(values),
        mean=round(statistics.fmean(values), digits),
        interval=interval(values, digits=digits),
        p50=round(percentile(values, 0.5), digits),
        p95=round(percentile(values, P95), digits),
    )


def _intervals(rows: Sequence[QuestionResult]) -> dict[str, Interval]:
    """The 95% interval of each rate and mean per question of a cell.

    Args:
        rows: Its counted questions.

    Returns:
        By ``CellSummary`` field; a rate over no question, or USD of an unpriced run, has none.
    """
    rows = _ordered(rows)
    priced = [r.usd for r in rows if r.usd is not None]
    answerable = [r for r in rows if r.kind != UNANSWERABLE]
    columns = {
        "accuracy": [float(accurate(r)) for r in rows],
        "grounded_share": [float(r.grounded) for r in rows if r.grounded is not None],
        "wrong_version_share": [float(r.wrong_version) for r in rows],
        "refused_answerable_share": [float(r.grade == REFUSED) for r in answerable],
        "correct_refusal_share": [
            float(r.grade == REFUSED) for r in rows if r.kind == UNANSWERABLE
        ],
        "tool_calls_per_question": [float(len(r.tool_calls)) for r in rows],
        "tokens_per_question": [float(r.input_tokens + r.output_tokens) for r in rows],
        "usd_per_question": priced if len(priced) == len(rows) else [],
    }
    digits = {"usd_per_question": 6}
    return {
        name: found
        for name, values in columns.items()
        if (found := interval(values, digits=digits.get(name, 3))) is not None
    }


def summarize(
    agent_model: str, retrieval: str, rows: Sequence[QuestionResult], *, arm: str = EXACTDOCS
) -> CellSummary:
    """Aggregate one agent model with one arm and configuration.

    Args:
        agent_model: The agent's model.
        retrieval: The configuration's name (empty for an arm without one).
        rows: Its questions.
        arm: The arm.

    Returns:
        The summary; every rate and mean is over the questions without a provider failure.
    """
    counts = Counter(r.grade for r in rows)
    kept = _ordered(r for r in rows if counted(r))
    answerable = [r for r in kept if r.grounded is not None]
    priced = [r.usd for r in kept if r.usd is not None]
    asked = [r for r in kept if r.kind != UNANSWERABLE]
    unanswerable = [r for r in kept if r.kind == UNANSWERABLE]
    refused = sum(r.grade == REFUSED for r in asked)
    right_refusals = sum(r.grade == REFUSED for r in unanswerable)
    thought = [r for r in kept if r.thinking_tokens is not None]
    seconds = [r.net_seconds for r in kept]
    return CellSummary(
        agent_model=agent_model,
        arm=arm,
        retrieval=retrieval,
        questions=len(rows),
        answered=len(kept),
        grades={grade: counts[grade] for grade in (*GRADES, NO_ANSWER, ERROR)},
        accuracy=round(sum(accurate(r) for r in kept) / len(kept), 3) if kept else 0.0,
        wrong_version=sum(r.wrong_version for r in kept),
        wrong_version_share=_share(sum(r.wrong_version for r in kept), len(kept)),
        refused_answerable=refused,
        refused_answerable_share=_share(refused, len(asked)),
        correct_refusals=right_refusals,
        correct_refusal_share=_share(right_refusals, len(unanswerable)),
        grounded_share=_share(sum(r.grounded is True for r in answerable), len(answerable)),
        read_other_versions=sum(bool(r.other_versions_read) for r in kept),
        tool_calls_per_question=_mean(len(r.tool_calls) for r in kept),
        tool_errors=sum(1 for r in kept for call in r.tool_calls if call.error),
        runs_with_tool_errors=sum(any(call.error for call in r.tool_calls) for r in kept),
        tool_errors_by_tool=dict(
            sorted(Counter(call.name for r in kept for call in r.tool_calls if call.error).items())
        ),
        tokens_per_question=_mean(r.input_tokens + r.output_tokens for r in kept),
        usd_per_question=round(statistics.fmean(priced), 6)
        if kept and len(priced) == len(kept)
        else None,
        seconds_p50=round(statistics.median(seconds), 3) if seconds else 0.0,
        seconds=spread(seconds),
        input_tokens=spread([float(r.input_tokens) for r in kept], digits=1),
        output_tokens=spread([float(r.output_tokens) for r in kept], digits=1),
        thinking_tokens=spread([float(r.thinking_tokens or 0) for r in thought], digits=1),
        thinking_returned=len(thought),
        thinking_estimated=any(r.thinking_estimated for r in thought),
        usd=spread(priced, digits=6) if len(priced) == len(kept) else None,
        tool_calls=spread([float(len(r.tool_calls)) for r in kept]),
        provider_retries=sum(r.provider_retries for r in rows),
        retry_seconds=round(sum(r.retry_seconds for r in rows), 3),
        retrieval_modes=dict(Counter(m for r in kept for m in r.retrieval_modes)),
        by_kind=_breakdown(rows, lambda r: r.kind),
        by_project=_breakdown(rows, lambda r: r.project),
        intervals=_intervals(kept),
    )


type CellKey = tuple[str, str, str]
"""``(agent model, arm, retrieval)``."""


def _by_cell(rows: Sequence[QuestionResult]) -> dict[CellKey, dict[str, QuestionResult]]:
    """Index the counted questions by cell and case.

    Args:
        rows: Every question.

    Returns:
        Cell to case to its record.
    """
    cells: defaultdict[CellKey, dict[str, QuestionResult]] = defaultdict(dict)
    for row in rows:
        if counted(row):
            cells[row.agent_model, row.arm, row.retrieval][row.case] = row
    return cells


def against_reference(
    cells: Sequence[CellSummary],
    rows: Sequence[QuestionResult],
    method: StatsMethod = DEFAULT_STATS,
) -> list[CellSummary]:
    """Test each cell's accuracy against its arm's first retrieval configuration, per agent model.

    Args:
        cells: Every cell; for each agent model and arm, the reference configuration's first.
        rows: Every question.
        method: The seed, resamples, confidence and significance level.

    Returns:
        The cells, each but the references with ``reference`` and ``versus_reference``.
    """
    first: dict[tuple[str, str], str] = {}
    for cell in cells:
        first.setdefault((cell.agent_model, cell.arm), cell.retrieval)
    outcomes = _by_cell(rows)
    tested = []
    for cell in cells:
        reference = first[cell.agent_model, cell.arm]
        if cell.retrieval == reference:
            tested.append(cell)
            continue
        theirs = outcomes[cell.agent_model, cell.arm, reference]
        mine = outcomes[cell.agent_model, cell.arm, cell.retrieval]
        common = sorted(theirs.keys() & mine.keys())
        test = paired_binary(
            [accurate(theirs[c]) for c in common], [accurate(mine[c]) for c in common], method
        )
        tested.append(cell.model_copy(update={"reference": reference, "versus_reference": test}))
    return tested


def _ratio(mine: Sequence[float], theirs: Sequence[float]) -> float | None:
    """The ratio of two means.

    Args:
        mine: This cell's values.
        theirs: The baseline's, on the same cases.

    Returns:
        ``mean(mine) / mean(theirs)``, rounded to 2 places; ``None`` when undefined.
    """
    if not mine or not statistics.fmean(theirs):
        return None
    return round(statistics.fmean(mine) / statistics.fmean(theirs), 2)


def compare(
    mine: dict[str, QuestionResult],
    theirs: dict[str, QuestionResult],
    against: CellKey,
    method: StatsMethod = DEFAULT_STATS,
) -> ArmComparison:
    """Compare a cell with a baseline cell on the cases both answered.

    Args:
        mine: This cell's counted questions by case.
        theirs: The baseline's.
        against: The baseline cell.
        method: The seed, resamples, confidence and significance level.

    Returns:
        The paired tests of accuracy, wall time and tokens, and the ratios of the means.
    """
    common = sorted(mine.keys() & theirs.keys())
    a, b = [theirs[c] for c in common], [mine[c] for c in common]
    seconds_a, seconds_b = [r.net_seconds for r in a], [r.net_seconds for r in b]
    output_a, output_b = [float(r.output_tokens) for r in a], [float(r.output_tokens) for r in b]
    return ArmComparison(
        against=against[1],
        against_retrieval=against[2],
        cases=len(common),
        accuracy=paired_binary([accurate(r) for r in a], [accurate(r) for r in b], method),
        seconds=paired_mean(seconds_a, seconds_b, method),
        input_tokens=paired_mean(
            [float(r.input_tokens) for r in a], [float(r.input_tokens) for r in b], method
        ),
        output_tokens=paired_mean(output_a, output_b, method),
        seconds_ratio=_ratio(seconds_b, seconds_a),
        output_tokens_ratio=_ratio(output_b, output_a),
    )


def against_arms(
    cells: Sequence[CellSummary],
    rows: Sequence[QuestionResult],
    method: StatsMethod = DEFAULT_STATS,
) -> list[CellSummary]:
    """Compare each cell with the ``none`` and ``exactdocs`` cells of its agent model (#495).

    A baseline arm's cell is its first retrieval configuration's. A cell is compared with the
    baselines before its own arm in ``BASELINES`` (``exactdocs`` with ``none``; ``context7`` with
    both), so no pair is shown twice; within an arm, ``against_reference`` compares the retrieval
    configurations.

    Args:
        cells: Every cell.
        rows: Every question.
        method: The seed, resamples, confidence and significance level.

    Returns:
        The cells, with ``versus``.
    """
    baselines: dict[tuple[str, str], CellKey] = {}
    for cell in cells:
        if cell.arm in BASELINES:
            baselines.setdefault(
                (cell.agent_model, cell.arm), (cell.agent_model, cell.arm, cell.retrieval)
            )
    outcomes = _by_cell(rows)
    compared = []
    for cell in cells:
        mine = outcomes[cell.agent_model, cell.arm, cell.retrieval]
        before = BASELINES[: BASELINES.index(cell.arm)] if cell.arm in BASELINES else BASELINES
        versus = [
            compare(mine, outcomes[key], key, method)
            for arm in before
            if (key := baselines.get((cell.agent_model, arm)))
        ]
        compared.append(cell.model_copy(update={"versus": versus}))
    return compared


# ------------------------------------------------------------------------------------ Markdown


def _pct(value: float | None) -> str:
    """Show a share as a percentage.

    Args:
        value: A share, or ``None``.

    Returns:
        ``87.5 %`` or ``n/a``.
    """
    return "n/a" if value is None else f"{value * 100:.1f} %"


def _ci(spread_: Interval | None) -> str:
    """Show a share's interval after it.

    Args:
        spread_: The interval, or ``None``.

    Returns:
        `` [80.1, 93.0]``, or nothing.
    """
    return "" if spread_ is None else f" [{spread_.low * 100:.1f}, {spread_.high * 100:.1f}]"


def _number(value: float, digits: int) -> str:
    """Show a number with thousands separators.

    Args:
        value: The number.
        digits: Decimals.

    Returns:
        E.g. ``1,234.5``.
    """
    return f"{value:,.{digits}f}"


def _cost(cost: Spread | None, digits: int = 1, missing: str = "n/a") -> str:
    """Show one cost: mean [interval], p50, p95.

    Args:
        cost: The spread, or ``None``.
        digits: Decimals.
        missing: What to show without one.

    Returns:
        E.g. ``12.3 [10.1, 14.8]; p50 9.8; p95 31.0``.
    """
    if cost is None:
        return missing
    ci = (
        ""
        if cost.interval is None
        else f" [{_number(cost.interval.low, digits)}, {_number(cost.interval.high, digits)}]"
    )
    return (
        f"{_number(cost.mean, digits)}{ci}; p50 {_number(cost.p50, digits)}; "
        f"p95 {_number(cost.p95, digits)}"
    )


def arm_label(cell: CellSummary) -> str:
    """Name a cell's arm in a table.

    Args:
        cell: The cell.

    Returns:
        ``none``, or ``exactdocs (bm25)`` for an arm with a retrieval configuration.
    """
    return f"{cell.arm} ({cell.retrieval})" if cell.retrieval else cell.arm


def _count_share(count: int, share: float | None, spread_: Interval | None) -> str:
    """Show a count with its share and interval.

    Args:
        count: The count.
        share: Its share.
        spread_: The share's interval.

    Returns:
        E.g. ``4 (13.3 % [3.3, 26.7])``.
    """
    return f"{count} ({_pct(share)}{_ci(spread_)})" if share is not None else str(count)


def _quality(report: BenchReport) -> list[str]:
    """The quality table.

    Args:
        report: The run.

    Returns:
        Its lines.
    """
    lines = [
        "## Quality",
        "",
        (
            "| Agent model | Arm | Accuracy | Correct | Partial | Wrong | Refused | No answer "
            "| Errors | Wrong for the version | Refused, answerable "
            "| Correct refusals, unanswerable | Read the answer | Read another version "
            "| Tool calls/q |"
        ),
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for c in report.cells:
        shares = c.intervals
        accuracy = _pct(c.accuracy) + _ci(shares.get("accuracy"))
        arm = ARMS.get(c.arm)
        other = str(c.read_other_versions)
        if arm is not None and arm.tool is None:
            read = "n/a (no tools)"
        elif not traced(c.arm):
            read, other = "n/a (its own index)", "n/a"
        else:
            read = _pct(c.grounded_share) + _ci(shares.get("grounded_share"))
        wrong = _count_share(
            c.wrong_version, c.wrong_version_share, shares.get("wrong_version_share")
        )
        refused = _count_share(
            c.refused_answerable, c.refused_answerable_share, shares.get("refused_answerable_share")
        )
        right = _count_share(
            c.correct_refusals, c.correct_refusal_share, shares.get("correct_refusal_share")
        )
        calls = f"{c.tool_calls_per_question}"
        if (tool_ci := shares.get("tool_calls_per_question")) is not None:
            calls += f" [{tool_ci.low}, {tool_ci.high}]"
        lines.append(
            f"| `{c.agent_model}` | {arm_label(c)} | {accuracy} | {c.grades['correct']} "
            f"| {c.grades['partially_correct']} | {c.grades['wrong']} | {c.grades['refused']} "
            f"| {c.grades[NO_ANSWER]} | {c.grades[ERROR]} | {wrong} | {refused} | {right} "
            f"| {read} | {other} | {calls} |"
        )
    return lines


def _tool_errors(report: BenchReport) -> list[str]:
    """The failed tool calls of each arm with tools (#573).

    Args:
        report: The run.

    Returns:
        The lines; none for a run whose arms have no tools.
    """
    cells = [c for c in report.cells if (arm := ARMS.get(c.arm)) is None or arm.tool is not None]
    if not cells:
        return []
    lines = [
        "",
        "## Tool errors",
        "",
        (
            "Tool calls the server refused or could not answer (an argument it does not take, a "
            "path the version lacks...), over the answered questions. Each costs the agent a turn, "
            "and the harness ends a run whose tool fails twice."
        ),
        "",
        "| Agent model | Arm | Runs with a tool error | Tool errors | By tool |",
        "|---|---|---|---|---|",
    ]
    for c in cells:
        by_tool = ", ".join(f"`{tool}` {n}" for tool, n in c.tool_errors_by_tool.items()) or "-"
        lines.append(
            f"| `{c.agent_model}` | {arm_label(c)} | {c.runs_with_tool_errors} of {c.answered} "
            f"| {c.tool_errors} | {by_tool} |"
        )
    return lines


def _thinking(c: CellSummary) -> str:
    """Show a cell's thinking tokens.

    Args:
        c: The cell.

    Returns:
        The spread, marked estimated where it is, or ``not returned``.
    """
    if c.thinking_tokens is None:
        return "not returned"
    shown = _cost(c.thinking_tokens, 0)
    if c.thinking_returned < c.answered:
        shown += f" ({c.thinking_returned} of {c.answered} questions)"
    return f"{shown} (estimated)" if c.thinking_estimated else shown


def _costs(report: BenchReport) -> list[str]:
    """The cost table.

    Args:
        report: The run.

    Returns:
        Its lines.
    """
    lines = [
        "## Cost per question",
        "",
        (
            "Each: mean [95% interval of the mean]; median; 95th percentile, over the questions "
            "without a provider failure. Wall time leaves out the time lost to provider retries."
        ),
        "",
        (
            "| Agent model | Arm | Wall time (s) | Input tokens | Output tokens, thinking included "
            "| Thinking tokens | USD | Retried requests |"
        ),
        "|---|---|---|---|---|---|---|---|",
    ]
    for c in report.cells:
        retried = f"{c.provider_retries} ({c.retry_seconds:,.0f} s)" if c.provider_retries else "0"
        lines.append(
            f"| `{c.agent_model}` | {arm_label(c)} | {_cost(c.seconds, 1)} "
            f"| {_cost(c.input_tokens, 0)} | {_cost(c.output_tokens, 0)} | {_thinking(c)} "
            f"| {_cost(c.usd, 5, 'unpriced')} | {retried} |"
        )
    return lines


def _paired(test: PairedTest | None, scale: float, digits: int, unit: str = "") -> str:
    """Show a paired test's difference, interval and p-value; bold when significant.

    Args:
        test: The test, or ``None``.
        scale: What the difference is multiplied by (100 for points).
        digits: Decimals.
        unit: Appended to the difference.

    Returns:
        E.g. ``**+12.3** [+5.0, +20.0]; p 0.003``.
    """
    if test is None:
        return "n/a"
    shown = f"{test.difference * scale:+,.{digits}f}{unit}"
    shown = f"**{shown}**" if test.significant else shown
    low, high = test.interval.low * scale, test.interval.high * scale
    return f"{shown} [{low:+,.{digits}f}, {high:+,.{digits}f}]; p {test.p_value:.2g}"


def _versus_arms(report: BenchReport) -> list[str]:
    """Each cell against ``none`` and ``exactdocs``, on the same cases.

    Args:
        report: The run.

    Returns:
        The lines; none when no cell has a comparison.
    """
    compared = [(c, v) for c in report.cells for v in c.versus]
    if not compared:
        return []
    alpha = report.statistics.alpha if report.statistics else 0.05
    lines = [
        "",
        "## Against the other arms, on the same cases",
        "",
        (
            "Each arm against `none` (and `exactdocs`), for the same agent model and the cases "
            "both answered without a provider failure: the difference (this arm minus the other), "
            "its paired bootstrap interval and the p-value; accuracy by McNemar's test (mid-p), "
            "time and tokens by a paired sign-flip permutation test. The ratio is this arm's mean "
            f"over the other's. **Bold**: significant at {alpha:.0%}."
        ),
        "",
        (
            "| Agent model | Arm | Against | Cases | Accuracy (points) | Gained / lost "
            "| Wall time (s) | Time ratio | Output tokens | Output ratio | Input tokens |"
        ),
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for c, v in compared:
        against = f"{v.against} ({v.against_retrieval})" if v.against_retrieval else v.against
        accuracy = v.accuracy
        gained = f"{accuracy.gained} / {accuracy.lost}" if accuracy else "n/a"
        time_ratio = "n/a" if v.seconds_ratio is None else f"{v.seconds_ratio}x"
        output_ratio = "n/a" if v.output_tokens_ratio is None else f"{v.output_tokens_ratio}x"
        lines.append(
            f"| `{c.agent_model}` | {arm_label(c)} | {against} | {v.cases} "
            f"| {_paired(v.accuracy, 100, 1)} | {gained} | {_paired(v.seconds, 1, 1)} "
            f"| {time_ratio} | {_paired(v.output_tokens, 1, 0)} | {output_ratio} "
            f"| {_paired(v.input_tokens, 1, 0)} |"
        )
    return lines


def _versus_reference(report: BenchReport) -> list[str]:
    """How the intervals were computed, and each cell's test against its arm's reference.

    Args:
        report: The run.

    Returns:
        The lines; none for a report without intervals.
    """
    method = report.statistics
    if method is None:
        return []
    lines = [
        "",
        (
            f"In brackets: the {method.confidence:.0%} interval, a percentile bootstrap over the "
            f"questions ({method.resamples:,} resamples, seed {method.seed}); with a few dozen "
            "questions per kind or project, theirs are wide."
        ),
    ]
    tested = [c for c in report.cells if c.versus_reference is not None]
    if not tested:
        return lines
    lines += [
        "",
        "## Against the first retrieval configuration",
        "",
        (
            "Accuracy against the arm's first retrieval configuration, for the same agent model "
            "and the questions both answered: the difference in points, its paired bootstrap "
            "interval and the p-value of McNemar's test (mid-p). "
            f"**Bold**: significant at {method.alpha:.0%}."
        ),
        "",
        "| Agent model | Arm | Against | Accuracy difference | Gained / lost | p |",
        "|---|---|---|---|---|---|",
    ]
    for c in tested:
        test = c.versus_reference
        if test is None:
            continue
        shown = f"{test.difference * 100:+.1f}"
        shown = f"**{shown}**" if test.significant else shown
        lines.append(
            f"| `{c.agent_model}` | {arm_label(c)} | {c.reference} "
            f"| {shown} [{test.interval.low * 100:+.1f}, {test.interval.high * 100:+.1f}] "
            f"| {test.gained} / {test.lost} | {test.p_value:.2g} |"
        )
    return lines


def _without_answer(report: BenchReport) -> list[str]:
    """The runs that ended without an answer, and why.

    Args:
        report: The run.

    Returns:
        The lines; none when every run answered.
    """
    failed = [q for q in report.questions if q.grade in {NO_ANSWER, ERROR}]
    if not failed:
        return []
    lines = [
        "",
        "## Runs without an answer",
        "",
        (
            f"{len(failed)} runs: `no_answer` is the agent's (a miss, counted), `error` the "
            "provider's or the judge's (left out of every rate and test)."
        ),
        "",
        "| Agent model | Arm | Case | Grade | Why |",
        "|---|---|---|---|---|",
    ]
    for q in failed[:FAILURES_SHOWN]:
        arm = f"{q.arm} ({q.retrieval})" if q.retrieval else q.arm
        why = q.judge_reason.replace("|", "\\|").replace("\n", " ")[:160]
        lines.append(f"| `{q.agent_model}` | {arm} | {q.case} | {q.grade} | {why} |")
    if len(failed) > FAILURES_SHOWN:
        lines.append(f"\n{len(failed) - FAILURES_SHOWN} more in the JSON report.")
    return lines


def _servers(report: BenchReport) -> list[str]:
    """What each arm's documentation server was.

    Args:
        report: The run.

    Returns:
        The lines; none for a run on stand-ins.
    """
    if not report.meta.servers:
        return []
    lines = ["", "## Documentation servers", ""]
    for name, about in report.meta.servers.items():
        shown = "; ".join(
            f"{k}: `{v}`" if k == "integrity" else f"{k}: {v}" for k, v in about.items()
        )
        lines.append(f"- **{name}**: {shown}")
    return lines


def markdown(report: BenchReport) -> str:
    """Render the report for a person (and ``$GITHUB_STEP_SUMMARY``).

    Args:
        report: The run.

    Returns:
        Markdown: the run's setup, quality and cost per agent model and arm, the comparisons
        between arms, accuracy per kind and per project.
    """
    meta = report.meta
    lines = [
        "# Agent benchmark",
        "",
        (
            f"{meta.cases} golden questions ({meta.selection}) per agent model and arm "
            f"({', '.join(meta.arms)}); judge `{meta.judge_model}`; ExactDocs "
            f"{meta.exactdocs_version} at `{meta.git_commit[:12]}`; at most {meta.max_requests} "
            f"model requests per question; thinking: {meta.thinking}."
            + (
                f" {meta.resumed} of the answers were kept from an earlier run (`--resume`)."
                if meta.resumed
                else ""
            )
        ),
        "",
        *_quality(report),
        *_tool_errors(report),
        "",
        *_costs(report),
    ]
    lines += _versus_arms(report)
    lines += _versus_reference(report)
    for title, field in (("kind", "by_kind"), ("project", "by_project")):
        groups = sorted({g for c in report.cells for g in getattr(c, field)})
        lines += ["", f"## Accuracy per {title}", ""]
        lines.append("| Agent model | Arm | " + " | ".join(groups) + " |")
        lines.append("|---|---|" + "---|" * len(groups))
        for c in report.cells:
            cells = getattr(c, field)
            shown = [
                f"{_pct(cells[g].accuracy)}{_ci(cells[g].interval)} ({cells[g].questions})"
                if g in cells
                else ""
                for g in groups
            ]
            lines.append(f"| `{c.agent_model}` | {arm_label(c)} | " + " | ".join(shown) + " |")
    lines += _without_answer(report)
    lines += _servers(report)
    if meta.retrieval:
        lines += ["", "## Retrieval configurations", ""]
    for name, env in meta.retrieval.items():
        settings = ", ".join(f"`{k}={v}`" for k, v in env.items()) or "the environment's"
        modes = Counter[str]()
        for c in report.cells:
            if c.retrieval == name:
                modes.update(c.retrieval_modes)
        answered = ", ".join(f"{mode}: {n}" for mode, n in sorted(modes.items())) or "no search"
        lines.append(f"- **{name}**: {settings}; searches answered by {answered}")
    return "\n".join(lines) + "\n"
