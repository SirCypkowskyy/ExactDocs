"""The agent benchmark (#348): recording, grounding, pricing, the judge, the report, agreement.

The unit tests run in CI. The end-to-end test (marked ``eval``) starts ExactDocs as shipped,
``exactdocs serve --stdio``, over a tiny two-version corpus imported for real, and runs the stand-in
agents and judge through it under two retrieval configurations.
"""

from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic_evals import Case

from agent_bench.agreement import LABELLING_HEADER, agreement, answer_id, sample
from agent_bench.cli import main, run_bench
from agent_bench.harness import (
    AgentRun,
    BenchInfo,
    Recorder,
    RetrievalConfig,
    Section,
    ToolCall,
    bench_dataset,
    grounded,
    read_other_versions,
    usd,
)
from agent_bench.judge import AnswerJudge, judge_agent
from agent_bench.offline import OFFLINE_AGENTS, OFFLINE_JUDGE, offline_judge, offline_verdict
from agent_bench.report import (
    BenchReport,
    QuestionResult,
    RunMeta,
    accurate,
    against_reference,
    markdown,
    results_of,
    summarize,
)
from fixture_repo import git
from retrieval_eval.dataset import Answer, CaseInfo, Hit, Question
from retrieval_eval.golden import Corpus, GoldenCase, PinnedVersion, Project, fetch
from retrieval_eval.stats import StatsMethod

LIBRARY = "/acme/demo"


def _info(**changes: Any) -> BenchInfo:
    values: dict[str, Any] = {
        "kind": "how-to",
        "project": "demo",
        "title": "Demo",
        "library": LIBRARY,
        "reference": "Use pip install demo.",
        "facts": ["install it with pip install demo"],
        "hits": [Hit(version="v1", article="docs/guide.md", heading_path=["Guide", "Install"])],
    }
    return BenchInfo(**(values | changes))


def _chunk(
    version: str = "v1",
    article: str = "docs/guide.md",
    path: tuple[str, ...] = ("Guide", "Install"),
) -> dict[str, Any]:
    return {
        "library": LIBRARY,
        "version": version,
        "article_path": article,
        "heading_path": list(path),
        "chunk_id": f"{version}-{article}-{len(path)}",
        "content": "Install the package with pip install demo.",
    }


# ------------------------------------------------------------------- retrieval configurations


def test_a_retrieval_configuration_names_ai_settings() -> None:
    config = RetrievalConfig.parse(
        "hybrid:mode=hybrid, embedding.model=eval:text-embedding-3-small"
    )
    assert config.name == "hybrid"
    assert config.env == {
        "EXACTDOCS_AI__MODE": "hybrid",
        "EXACTDOCS_AI__EMBEDDING__MODEL": "eval:text-embedding-3-small",
    }
    assert RetrievalConfig.parse("env").env == {}


@pytest.mark.parametrize("text", [":mode=bm25", "bm25:mode", "bm25:=x"])
def test_a_malformed_retrieval_configuration_is_refused(text: str) -> None:
    with pytest.raises(ValueError, match="retrieval configuration"):
        RetrievalConfig.parse(text)


# ------------------------------------------------------------------------------- recording


async def test_the_recorder_keeps_full_reads_and_search_modes_only() -> None:
    recorder = Recorder()
    resolved: list[str] = []

    async def call_tool(
        name: str, args: dict[str, Any], *, metadata: dict[str, Any] | None = None
    ) -> Any:
        assert name == "read_chunk"
        del metadata
        resolved.append(args["chunk_id"])
        return _chunk("v2", "docs/start.md", ("Guide", "Setup")) | {"chunk_id": args["chunk_id"]}

    await recorder.take("read_chunk", _chunk(), call_tool)
    await recorder.take(
        "read_article", {"library": LIBRARY, "ref": "v1", "path": "docs/a.md"}, call_tool
    )
    await recorder.take(
        "query-docs", ["notice", "### Setup\n\nSource: x\n\nChunk: c-9\n\ntext"], call_tool
    )
    await recorder.take(
        "search_docs",
        {
            "retrieval_mode": "bm25",
            "fallback_reason": "mode_unavailable",
            "results": [{"chunk_id": "s"}],
        },
        call_tool,
    )
    await recorder.take(
        "search_docs", {"retrieval_mode": "bm25", "fallback_reason": None}, call_tool
    )
    await recorder.take("list_libraries", {"libraries": []}, call_tool)

    assert resolved == ["c-9"]
    assert [
        (s.version, s.article, s.heading_path, s.chunk_id, s.whole_article) for s in recorder.read
    ] == [
        ("v1", "docs/guide.md", ["Guide", "Install"], "v1-docs/guide.md-2", False),
        ("v1", "docs/a.md", [], "", True),
        ("v2", "docs/start.md", ["Guide", "Setup"], "c-9", False),
    ]
    assert recorder.modes == ["bm25 (mode_unavailable)", "bm25"]


# ------------------------------------------------------------------------------- grounding


def _read(*sections: Section) -> AgentRun:
    return AgentRun(answer="a", read=list(sections))


def test_an_answer_is_grounded_when_every_answering_section_was_read() -> None:
    install = Section(
        library=LIBRARY, version="v1", article="docs/guide.md", heading_path=["Guide", "Install"]
    )
    article = Section(library=LIBRARY, version="v1", article="docs/guide.md", whole_article=True)
    other_version = install.model_copy(update={"version": "v2"})
    other_library = install.model_copy(update={"library": "/acme/other"})
    other_section = install.model_copy(update={"heading_path": ["Guide"]})

    assert grounded(_info(), _read(install)) is True
    assert grounded(_info(), _read(article)) is True
    for wrong in (other_version, other_library, other_section):
        assert grounded(_info(), _read(wrong)) is False
    cross = _info(hits=[*_info().hits, Hit(version="v1", article="docs/b.md", heading_path=[])])
    assert grounded(cross, _read(install)) is False
    either = Hit(version="v1", article="docs/b.md", heading_path=[], alternative=True)
    assert grounded(_info(hits=[*_info().hits, either]), _read(install)) is True  # #501
    assert grounded(_info(kind="unanswerable", facts=[], hits=[]), _read(install)) is None


def test_reads_of_another_version_of_the_library_are_listed() -> None:
    question = Question(query="q", version="v1", project="demo")
    run = _read(
        Section(library=LIBRARY, version="v1", article="docs/guide.md"),
        Section(library=LIBRARY, version="v2", article="docs/start.md"),
        Section(library="/acme/other", version="v9", article="x.md"),
    )
    assert read_other_versions(question, _info(), run) == ["v2:docs/start.md"]


# --------------------------------------------------------------------------------- pricing


def test_a_known_model_is_priced_and_a_stand_in_is_not() -> None:
    priced = usd("openai:gpt-4o", 1_000_000, 0)
    assert priced is not None
    assert priced > 0
    assert usd("openai:gpt-4o", 0, 1_000_000) > priced  # ty: ignore[unsupported-operator]
    assert usd("offline:read", 1000, 1000) is None
    assert usd("test", 1000, 1000) is None
    assert usd("openai:no-such-model-xyz", 1000, 1000) is None


# ----------------------------------------------------------------------------------- judge


@pytest.mark.parametrize(
    ("answer", "facts", "grade"),
    [
        (
            "Install the package with pip install demo.",
            ["install it with pip install demo"],
            "correct",
        ),
        (
            "Run pip install demo.",
            ["install it with pip install demo", "settings live in demo.toml"],
            "partially_correct",
        ),
        ("Use conda.", ["install it with pip install demo"], "wrong"),
        (
            "The documentation of v1 does not cover this.",
            ["install it with pip install demo"],
            "refused",
        ),
        ("The documentation of v1 does not cover this.", [], "refused"),
        ("Install the package with pip install demo.", [], "wrong"),
    ],
)
def test_the_stand_in_judge_grades_by_fact_overlap(
    answer: str, facts: list[str], grade: str
) -> None:
    assert offline_verdict({"answer": answer, "facts": facts}).grade == grade


def _golden(name: str, version: str, kind: str, hits: list[Hit], facts: list[str]) -> GoldenCase:
    return Case(
        name=name,
        inputs=Question(query=name.split(": ", 1)[1], version=version, project="demo"),
        metadata=CaseInfo(kind=kind),  # ty: ignore[invalid-argument-type]
        expected_output=Answer(hits=hits, reference=f"reference of {name}", facts=facts),
    )


def _corpus(repository: str = "https://example.com/acme/demo", **commits: str) -> Corpus:
    versions = [PinnedVersion(name=v, commit=sha) for v, sha in commits.items()]
    return Corpus(
        projects=[
            Project(
                id="demo",
                title="Demo",
                repository=repository,
                include=["docs/"],
                licence="MIT",
                attribution="Copyright (c) A",
                versions=versions or [PinnedVersion(name="v1", commit="0" * 40)],
            )
        ]
    )


INSTALL = Hit(version="v1", article="docs/guide.md", heading_path=["Guide", "Install"])
CASES = [
    _golden(
        "demo v1: How do I install the package?",
        "v1",
        "how-to",
        [INSTALL],
        ["install it with pip install demo"],
    ),
    _golden("demo v1: How do I uninstall the package?", "v1", "unanswerable", [], []),
    _golden(
        "demo v1: What is the config file?",
        "v1",
        "conceptual",
        [INSTALL],
        ["settings live in demo.toml"],
    ),
]


async def test_the_judge_labels_answers_and_a_failed_run_is_wrong_unjudged() -> None:
    dataset = bench_dataset([("demo", c) for c in CASES], _corpus())
    dataset.add_evaluator(AnswerJudge(judge=judge_agent(offline_judge())))
    runs = {
        CASES[0].inputs.query: AgentRun(
            answer="Install the package with pip install demo.",
            read=[
                Section(
                    library=LIBRARY,
                    version="v1",
                    article="docs/guide.md",
                    heading_path=["Guide", "Install"],
                    chunk_id="c1",
                )
            ],
            tool_calls=[
                ToolCall(name="search_docs", args="{}", seconds=0.1),
                ToolCall(name="read_chunk", args="{}", seconds=0.1),
            ],
            input_tokens=100,
            output_tokens=20,
            usd=0.002,
            seconds=1.5,
        ),
        CASES[1].inputs.query: AgentRun(
            answer="The documentation of v1 does not cover this.", usd=0.001, seconds=0.5
        ),
        CASES[2].inputs.query: AgentRun(
            answer="", error="UsageLimitExceeded: request limit", usd=0.003, seconds=3.0
        ),
    }

    async def task(question: Question) -> AgentRun:
        return runs[question.query]

    evaluated = await dataset.evaluate(task, progress=False)
    rows = results_of(evaluated, "offline:read", "bm25")

    by_case = {r.case: r for r in rows}
    assert [by_case[c.name or ""].grade for c in CASES] == ["correct", "refused", "wrong"]
    assert by_case[CASES[2].name or ""].judge_reason.startswith("no answer: UsageLimitExceeded")
    first = by_case[CASES[0].name or ""]
    assert first.grounded is True
    assert first.chunks_read == ["c1@v1"]
    assert first.question == "How do I install the package?"
    assert first.facts == ["install it with pip install demo"]
    assert by_case[CASES[1].name or ""].grounded is None

    cell = summarize("offline:read", "bm25", rows)
    assert cell.questions == 3
    assert cell.grades == {
        "correct": 1,
        "partially_correct": 0,
        "wrong": 1,
        "refused": 1,
        "error": 0,
    }
    measured = (cell.accuracy, cell.grounded_share, cell.tool_calls_per_question)
    assert measured == pytest.approx((0.667, 0.5, 0.667))
    spent = (cell.tokens_per_question, cell.usd_per_question, cell.seconds_p50)
    assert spent == pytest.approx((40.0, 0.002, 1.5))
    kinds = cell.by_kind
    assert (kinds["unanswerable"].accuracy, kinds["conceptual"].accuracy) == pytest.approx((1, 0))
    assert cell.by_project["demo"].questions == 3


def test_refused_is_accurate_for_an_unanswerable_case_only() -> None:
    rows = [
        _row("answerable refused", grade="refused"),
        _row("unanswerable refused", grade="refused", kind="unanswerable"),
        _row("unanswerable correct", grade="correct", kind="unanswerable"),
        _row("unanswerable answered anyway", grade="wrong", kind="unanswerable"),
    ]
    assert [accurate(r) for r in rows] == [False, True, True, False]

    cell = summarize("m", "r", rows)
    assert cell.accuracy == pytest.approx(0.5)
    assert cell.grades["refused"] == 2  # the raw grades stay as the judge gave them
    assert cell.by_kind["how-to"].correct == 0
    assert cell.by_kind["unanswerable"].correct == 2


def test_a_cell_with_an_unpriced_run_has_no_usd_and_an_empty_cell_is_zero() -> None:
    rows = [_row("a", usd=0.1), _row("b", usd=None)]
    assert summarize("m", "r", rows).usd_per_question is None
    empty = summarize("m", "r", [])
    assert (empty.questions, empty.accuracy, empty.grounded_share) == (0, 0.0, None)


# ---------------------------------------------------------------------- report and agreement


def _row(
    case: str,
    *,
    grade: str = "correct",
    wrong_version: bool = False,
    usd: float | None = 0.01,
    agent: str = "m1",
    kind: str = "how-to",
) -> QuestionResult:
    return QuestionResult(
        agent_model=agent,
        retrieval="bm25",
        case=case,
        project="demo",
        kind=kind,
        version="v1",
        question=f"question {case}",
        reference="ref",
        facts=["fact"],
        grade=grade,
        wrong_version=wrong_version,
        usd=usd,
        answer=f"answer {case}",
    )


def _report(rows: list[QuestionResult]) -> BenchReport:
    meta = RunMeta(
        started_at="2026-11-13T00:00:00+00:00",
        exactdocs_version="0.0.0",
        git_commit="abc",
        agent_models=sorted({r.agent_model for r in rows}),
        judge_model="offline",
        retrieval={"bm25": {"EXACTDOCS_AI__MODE": "bm25"}},
        max_requests=20,
        concurrency=1,
        cases=len(rows),
        agent_instructions="i",
        prompt="p",
        corpus=[],
    )
    cells = [
        summarize(a, "bm25", [r for r in rows if r.agent_model == a]) for a in meta.agent_models
    ]
    return BenchReport(meta=meta, cells=cells, questions=rows)


def test_the_markdown_report_shows_each_cell_and_the_breakdowns() -> None:
    text = markdown(_report([_row("a"), _row("b", grade="wrong", wrong_version=True, agent="m2")]))
    assert "| `m1` | bm25 | 100.0 % [100.0, 100.0] |" in text
    assert "| `m2` | bm25 | 0.0 % [0.0, 0.0] | 0 | 1 | 0 | 0 | 1 |" in text
    assert "## Accuracy per kind" in text
    assert "## Accuracy per project" in text
    assert "`EXACTDOCS_AI__MODE=bm25`; searches answered by no search" in text


# ---------------------------------------------------------------------- intervals, tests (#489)


def test_a_cell_gives_its_rates_and_means_an_interval() -> None:
    grades = ["correct" if i % 4 else "wrong" for i in range(40)]
    rows = [_row(str(i), grade=g, kind="a" if i < 20 else "b") for i, g in enumerate(grades)]

    cell = summarize("m", "bm25", rows)

    accuracy = cell.intervals["accuracy"]
    assert cell.accuracy == pytest.approx(0.75)
    assert accuracy.low < cell.accuracy < accuracy.high
    assert {"accuracy", "tool_calls_per_question", "tokens_per_question"} <= set(cell.intervals)
    assert "grounded_share" not in cell.intervals  # no question names its sections here
    usd = cell.intervals["usd_per_question"]  # every question cost the same
    assert (usd.low, usd.high) == pytest.approx((0.01, 0.01))
    kind = cell.by_kind["b"]
    assert kind.interval is not None
    assert kind.interval.high - kind.interval.low > accuracy.high - accuracy.low  # fewer cases


def _against(grades: dict[str, list[str]]) -> list[QuestionResult]:
    return [
        _row(f"case {i}", grade=grade).model_copy(update={"retrieval": retrieval})
        for retrieval, given in grades.items()
        for i, grade in enumerate(given)
    ]


def test_each_configuration_is_tested_against_the_first_one() -> None:
    same = ["correct", "wrong"] * 20
    better = ["correct"] * 40  # every question the first got wrong, now right
    rows = _against({"none": same, "bm25": same, "hybrid": better})
    names = ("none", "bm25", "hybrid")
    cells = [summarize("m1", name, [q for q in rows if q.retrieval == name]) for name in names]

    first, bm25, hybrid = against_reference(cells, rows)

    assert (first.reference, first.versus_reference) == (None, None)
    assert bm25.reference == "none"
    assert bm25.versus_reference is not None
    assert (bm25.versus_reference.p_value, bm25.versus_reference.significant) == (1, False)
    assert hybrid.versus_reference is not None
    assert hybrid.versus_reference.significant
    assert (hybrid.versus_reference.gained, hybrid.versus_reference.lost) == (20, 0)
    report = _report(rows).model_copy(
        update={"cells": [first, bm25, hybrid], "statistics": StatsMethod()}
    )
    text = markdown(report)
    assert "## Against the first retrieval configuration" in text
    assert "| `m1` | hybrid | none | **+50.0** [" in text
    assert "10,000 resamples, seed 489" in text


def test_a_labelling_sample_is_reproducible_has_blank_labels_and_no_judge_grade() -> None:
    report = _report([_row(str(i)) for i in range(80)])
    first = sample(report, 50, seed=1)
    assert len(first) == 50
    assert first == sample(report, 50, seed=1)
    assert first != sample(report, 50, seed=2)
    assert len(sample(report, 500, seed=1)) == 80
    entry = first[0]
    assert (entry["grade"], entry["wrong_version"]) == ("", "")
    assert {"question", "reference", "facts", "answer", "version"} <= entry.keys()
    assert "judge_reason" not in entry


def test_agreement_compares_the_labelled_answers_with_the_judge() -> None:
    rows = [_row("a"), _row("b", grade="wrong", wrong_version=True), _row("c"), _row("d")]
    report = _report(rows)
    labels = [
        {"id": answer_id(rows[0]), "grade": "correct", "wrong_version": False},
        {"id": answer_id(rows[1]), "grade": "partially_correct", "wrong_version": True},
        {"id": answer_id(rows[2]), "grade": "correct", "wrong_version": ""},
        {"id": answer_id(rows[3]), "grade": "", "wrong_version": ""},
    ]
    result = agreement(report, labels)
    assert (result.labelled, result.agreed, result.rate) == (3, 2, 0.667)
    assert (result.wrong_version_labelled, result.wrong_version_agreed) == (2, 2)
    assert result.confusion == {"correct": {"correct": 2}, "partially_correct": {"wrong": 1}}
    assert agreement(report, []).rate is None
    with pytest.raises(ValueError, match="not in the report"):
        agreement(report, [{"id": "nope", "grade": "correct"}])
    with pytest.raises(ValueError, match="is not one of"):
        agreement(report, [{"id": answer_id(rows[0]), "grade": "great"}])


def test_the_cli_exports_a_sample_and_reads_the_labels_back(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rows = [_row("a"), _row("b", grade="wrong")]
    report, labels = tmp_path / "report.json", tmp_path / "labels.yaml"
    report.write_text(_report(rows).model_dump_json(), encoding="utf-8")

    assert main(["sample", "--report", str(report), "--out", str(labels)]) == 0
    assert labels.read_text(encoding="utf-8").startswith(LABELLING_HEADER)
    assert "is\n# `refused`, not `correct`" in LABELLING_HEADER
    entries = yaml.safe_load(labels.read_text(encoding="utf-8"))
    assert len(entries) == 2
    for entry in entries:
        entry["grade"] = "correct"
    labels.write_text(yaml.safe_dump(entries), encoding="utf-8")
    capsys.readouterr()

    assert main(["agreement", "--report", str(report), "--labels", str(labels)]) == 0
    assert '"rate": 0.5' in capsys.readouterr().out


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["run"], "give --agent-model and --judge-model, or --offline"),
        (["run", "--agent-model", "m"], "give --agent-model and --judge-model, or --offline"),
        (["run", "--offline", "--retrieval", "bm25:mode"], "is not key=value"),
        (["run", "--offline", "--projects", "nope"], "no case matches"),
    ],
)
def test_the_cli_refuses_an_incomplete_run(
    args: list[str], message: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(args) == 2
    assert message in capsys.readouterr().err


# ---------------------------------------------------------------------- end to end (eval)

GUIDE_V1 = """# Guide

Intro to demo.

## Install

Install the package with `pip install demo`, then import it.

## Configure

Settings live in demo.toml next to the project.
"""
START_V2 = """# Guide

## Setup

Install the package with `uv add demo`; pip is no longer documented.
"""


def _commit(repo: Path, tag: str, files: dict[str, str], delete: tuple[str, ...] = ()) -> str:
    for path, text in files.items():
        (repo / path).parent.mkdir(parents=True, exist_ok=True)
        (repo / path).write_text(text, encoding="utf-8")
    for path in delete:
        (repo / path).unlink()
    git("add", "-A", cwd=repo)
    git(
        "commit",
        "-q",
        "--no-verify",
        "-m",
        tag,
        cwd=repo,
        GIT_AUTHOR_NAME="A",
        GIT_AUTHOR_EMAIL="a@example.com",
        GIT_COMMITTER_NAME="A",
        GIT_COMMITTER_EMAIL="a@example.com",
    )
    git("tag", tag, cwd=repo)
    return git("rev-parse", "HEAD", cwd=repo)


@pytest.mark.eval
async def test_stand_in_agents_answer_through_exactdocs_as_shipped(tmp_path: Path) -> None:
    upstream = tmp_path / "acme" / "demo"
    upstream.mkdir(parents=True)
    git("init", "-q", "-b", "main", "--template=", str(upstream))
    v1 = _commit(upstream, "v1", {"docs/guide.md": GUIDE_V1})
    v2 = _commit(upstream, "v2", {"docs/start.md": START_V2}, delete=("docs/guide.md",))
    corpus = _corpus(str(upstream), v1=v1, v2=v2)
    repos = {"demo": fetch(corpus.projects[0], tmp_path / "cache")}
    setup = Hit(version="v2", article="docs/start.md", heading_path=["Guide", "Setup"])
    cases = [
        _golden(
            "demo v1: How do I install the package?",
            "v1",
            "how-to",
            [INSTALL],
            ["install the package with pip install demo"],
        ),
        _golden(
            "demo v2: How do I install the package?",
            "v2",
            "version-change",
            [setup],
            ["install the package with uv add demo"],
        ),
        _golden("demo v2: Which file holds the settings?", "v2", "unanswerable", [], []),
    ]

    report = await run_bench(
        [("demo", c) for c in cases],
        corpus,
        repos,
        agent_models=OFFLINE_AGENTS,
        judge_model=OFFLINE_JUDGE,
        retrieval=[
            RetrievalConfig.parse("bm25:mode=bm25"),
            RetrievalConfig.parse("hybrid:mode=hybrid"),
        ],
        work_dir=tmp_path / "work",
    )

    assert [(c.agent_model, c.retrieval) for c in report.cells] == [
        ("offline:search", "bm25"),
        ("offline:read", "bm25"),
        ("offline:search", "hybrid"),
        ("offline:read", "hybrid"),
    ]
    assert all(c.questions == 3 and c.grades["error"] == 0 for c in report.cells)
    assert {c.retrieval: c.retrieval_modes for c in report.cells} == {
        "bm25": {"bm25": 3},
        "hybrid": {"bm25 (mode_unavailable)": 3},  # no embedding model: the server falls back
    }
    assert [(c.project, c.version, c.imported_commit) for c in report.meta.corpus] == [
        ("demo", "v1", v1),
        ("demo", "v2", v2),
    ]
    assert report.meta.retrieval["hybrid"] == {"EXACTDOCS_AI__MODE": "hybrid"}
    for row in report.questions:
        names = [call.name for call in row.tool_calls]
        assert names[:2] == ["list_libraries", "search_docs"], row
        assert row.input_tokens > 0
        assert row.usd is None  # stand-ins are not in the price list
        assert row.other_versions_read == []
        assert row.retrieval_modes == [
            "bm25" if row.retrieval == "bm25" else "bm25 (mode_unavailable)"
        ]
        assert all(chunk.endswith(f"@{row.version}") for chunk in row.chunks_read)
        if row.agent_model == "offline:read":
            assert names == ["list_libraries", "search_docs", "read_chunk"]
            if row.kind != "unanswerable":
                assert row.grounded is True, row
                assert row.grade == "correct", row
        else:
            assert row.chunks_read == []
            assert row.grounded in {False, None}
    unanswerable = [r for r in report.questions if r.kind == "unanswerable"]
    assert {r.grade for r in unanswerable} == {"wrong"}  # the stand-ins answer anyway
    # each agent model's hybrid cell is tested against its bm25 cell, the first configuration
    assert report.statistics is not None
    assert [c.reference for c in report.cells] == [None, None, "bm25", "bm25"]
    assert all(c.versus_reference.cases == 3 for c in report.cells[2:] if c.versus_reference)
    assert "# Agent benchmark" in markdown(report)
