"""Grounded Docs on the golden set (#492): its responses, the run, the report and the install.

The run's tests use ``grounded_docs_stand_in``: Grounded Docs 3.4.1's real ``search_docs``
responses, recorded on the retrieval benchmark's tiny corpus, replayed. Nothing here starts Node.js
or reaches the network; the real run is ``just grounded-bench`` (docs/evals/grounded-docs.md).
"""

import contextlib
import json
import shutil
import sqlite3
from pathlib import Path

import pytest
import yaml

from fixture_repo import git
from grounded_docs_stand_in import (
    EMBEDDING,
    FULL_TEXT,
    ReplayingGroundedDocs,
    recorded,
    stand_in_embedding,
)
from retrieval_bench_stand_ins import tiny_corpus
from retrieval_eval.golden import PinnedVersion, Project
from retrieval_eval.grounded_docs import (
    INTEGRITY,
    PACKAGE,
    TEXT_BASELINE,
    TOP_K,
    VERSION,
    GroundedDocsReport,
    VersionIndex,
    cases_not_indexed,
    markdown,
    page_blocks,
    paired,
    problems,
    split_results,
)
from retrieval_eval.grounded_docs_cli import (
    REQUEST_TIMEOUT_MS,
    install,
    limits,
    main,
    materialize,
    read_store,
    write_config,
)
from retrieval_eval.retrieval_bench import Row
from retrieval_eval.text_bench import TextRow

INSTALL_QUERY = "install demo package pip"
"""The tiny corpus' answerable question."""
OTHER_QUERY = "kubernetes operator crd"
"""Its unanswerable one."""


# ---------------------------------------------------------------- reading search_docs


def test_a_response_is_split_into_its_results_in_order() -> None:
    (text,) = recorded()["multi"].values()

    found = split_results(text)

    assert [f.url for f in found] == [
        "file:///corpus/multi/1.0.0/docs/timeouts.md",
        "file:///corpus/multi/1.0.0/docs/pool.md",
        "file:///corpus/multi/1.0.0/docs/retries.md",
    ]
    assert found[0].content.startswith("# Timeouts\nEvery request has a connect timeout")
    assert found[1].content.endswith("## Size\nThe pool holds ten connections by default.")
    assert "------" not in "".join(f.content for f in found)


def test_no_results_is_no_result() -> None:
    assert split_results(recorded()[FULL_TEXT][OTHER_QUERY]) == []
    assert split_results("") == []


def test_a_rule_inside_a_result_is_not_a_new_result() -> None:
    rule = "\n" + "-" * 60 + "\n"
    text = f"{rule}Result 1: file:///a.md\n\nA table:{rule}Result 7: not a result\n\nstill A\n"

    (found,) = split_results(text)

    assert found.url == "file:///a.md"
    assert found.content.endswith("Result 7: not a result\n\nstill A")


# ---------------------------------------------------------------- the corpus folder


def _project(tmp_path: Path) -> tuple[Path, Project]:
    repo = tmp_path / "upstream"
    git("init", "-q", "-b", "main", "--template=", str(repo))
    files = {
        "docs/guide.md": "---\ntitle: Guide\n---\n# Guide\n\nText.\n",
        "docs/api/deep/er/page.mdx": "# Page\n",
        "docs/logo.png": "not markdown",
        "src/code.md": "# Not under docs\n",
    }
    for path, text in files.items():
        (repo / path).parent.mkdir(parents=True, exist_ok=True)
        (repo / path).write_text(text, encoding="utf-8")
    (repo / "docs" / "same.md").symlink_to("guide.md")
    git("add", "-A", cwd=repo)
    git(
        "commit", "-q", "--no-verify", "-m", "v1", cwd=repo,
        GIT_AUTHOR_NAME="A", GIT_AUTHOR_EMAIL="a@example.com",
        GIT_COMMITTER_NAME="A", GIT_COMMITTER_EMAIL="a@example.com",
    )  # fmt: skip
    project = Project(
        id="demo",
        title="Demo",
        repository=str(repo),
        include=["docs/"],
        licence="MIT",
        attribution="Copyright (c) A",
        versions=[PinnedVersion(name="v1", commit=git("rev-parse", "HEAD", cwd=repo))],
    )
    return repo, project


def test_the_folder_holds_the_importers_files_byte_for_byte(tmp_path: Path) -> None:
    repo, project = _project(tmp_path)
    folder = tmp_path / "corpus" / "demo" / "v1"
    (folder / "stale.md").parent.mkdir(parents=True)
    (folder / "stale.md").write_text("left from another run", encoding="utf-8")

    written = materialize(repo, project.versions[0].commit, project, folder)

    assert written == ["docs/api/deep/er/page.mdx", "docs/guide.md", "docs/same.md"]
    assert sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()) == (
        written
    )
    front_matter = "---\ntitle: Guide\n---\n# Guide\n\nText.\n"
    assert (folder / "docs" / "guide.md").read_text(encoding="utf-8") == front_matter
    assert (folder / "docs" / "same.md").read_text(encoding="utf-8") == front_matter


def test_the_crawl_limits_are_its_defaults_unless_a_folder_needs_more() -> None:
    assert limits(["docs/a.md", "docs/b/c.md"], (3, 1000)) == (3, 1000)
    deep = ["docs/framework/react/guides/a.md"]
    assert limits(deep, (3, 1000)) == (5, 1000)
    many = [f"docs/{i}.md" for i in range(1200)]
    assert limits(many, (3, 1000)) == (3, 1200 + 2)  # files, docs/ and the folder itself


def test_the_config_file_turns_telemetry_off_and_reads_only_the_corpus(tmp_path: Path) -> None:
    write_config(tmp_path / "config.yaml", tmp_path / "corpus")

    config = yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8"))

    assert config == {
        "app": {"telemetryEnabled": False},
        "scraper": {"security": {"fileAccess": {"allowedRoots": [str(tmp_path / "corpus")]}}},
        "embeddings": {"requestTimeoutMs": REQUEST_TIMEOUT_MS},
    }


def test_the_store_is_read_per_library_version(tmp_path: Path) -> None:
    store = tmp_path / "store"
    store.mkdir()
    with contextlib.closing(sqlite3.connect(store / "documents.db")) as db:
        db.executescript(
            """
            CREATE TABLE libraries (id INTEGER PRIMARY KEY, name TEXT);
            CREATE TABLE versions (id INTEGER PRIMARY KEY, library_id INTEGER, name TEXT);
            CREATE TABLE pages (id INTEGER PRIMARY KEY, version_id INTEGER, url TEXT);
            CREATE TABLE documents (id INTEGER PRIMARY KEY, page_id INTEGER, embedding BLOB);
            INSERT INTO libraries VALUES (1, 'demo');
            INSERT INTO versions VALUES (1, 1, 'v1'), (2, 1, 'v2');
            INSERT INTO pages VALUES (1, 1, 'file:///a.md'), (2, 1, 'file:///b.md'),
                                     (3, 2, 'file:///a.md');
            INSERT INTO documents VALUES (1, 1, x'00'), (2, 1, NULL), (3, 2, x'00'), (4, 3, NULL);
            """
        )
        db.commit()

    held = read_store(store)

    assert held["demo", "v1"].pages == {"file:///a.md", "file:///b.md"}
    assert (held["demo", "v1"].chunks, held["demo", "v1"].embedded) == (3, 2)
    assert (held["demo", "v2"].chunks, held["demo", "v2"].embedded) == (1, 0)
    assert read_store(tmp_path / "nothing") == {}


# ---------------------------------------------------------------- the run


@pytest.fixture
def corpus_args(tmp_path: Path) -> list[str]:
    """The tiny corpus on disk; returns the CLI's corpus, cases and cache arguments."""
    return tiny_corpus(tmp_path / "corpus")[:6]


def _run(
    tmp_path: Path, args: list[str], tool: ReplayingGroundedDocs, *extra: str
) -> tuple[int, GroundedDocsReport | None]:
    out = tmp_path / "out"
    code = main(
        [
            *args,
            "--home", str(tmp_path / "home"),
            "--out", str(out),
            "--recorded", str(tmp_path / "no-recorded-run.json"),
            *extra,
        ],
        tool=lambda _home, _offline: tool,
        embedder=stand_in_embedding,
    )  # fmt: skip
    path = out / "grounded-docs.json"
    report = (
        GroundedDocsReport.model_validate_json(path.read_text("utf-8")) if path.exists() else None
    )
    return code, report


def test_a_run_indexes_every_version_asks_every_question_and_scores_it(
    tmp_path: Path, corpus_args: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    tool = ReplayingGroundedDocs()

    code, report = _run(tmp_path, corpus_args, tool)

    assert code == 0
    assert report is not None
    assert tool.indexed == [("demo", "v1", (3, 1000))] * 2  # once per configuration
    assert report.tool | {"node": "?"} == {
        "name": "Grounded Docs",
        "package": PACKAGE,
        "version": VERSION,
        "integrity": INTEGRITY,
        "search": "search_docs",
        "top_k": str(TOP_K),
        "node": "?",
    }
    assert report.date
    assert [run.configuration for run in report.runs] == [FULL_TEXT, EMBEDDING]
    for run in report.runs:
        (version,) = run.indexing
        assert (version.project, version.version, version.offered, version.indexed) == (
            "demo",
            "v1",
            1,
            1,
        )
        assert version.not_indexed == []
        assert run.index_bytes > 0
        assert len(run.rows) == 2
        assert run.result.metrics.metrics.recall_at_1 == 1  # the guide holds Install
        assert set(run.result.metrics.metrics.intervals) >= {"recall_at_5", "mrr", "ndcg_at_10"}
        assert run.context_tokens_interval is not None
        (versus,) = run.versus
        assert (versus.against, versus.scored_by) == (TEXT_BASELINE, "text")
        assert set(versus.tests) == {
            "recall_at_1",
            "recall_at_5",
            "recall_at_10",
            "mrr",
            "ndcg_at_10",
            "recall_at_1k_tokens",  # both scored from their text: the context is known (#575)
            "recall_at_2k_tokens",
            "recall_at_4k_tokens",
            "recall_at_1k_tokens_cut",  # and the text can be cut at the budget
            "recall_at_2k_tokens_cut",
            "recall_at_4k_tokens_cut",
        }
        m = run.result.metrics.metrics
        assert m.context_tokens_per_question == run.result.metrics.context_tokens_per_question
        assert m.recall_at_4k_tokens == 1  # the tiny guide is far under 4,000 tokens
        assert run.errors == []
    full_text, vector = report.runs
    assert full_text.embedding is None
    assert full_text.variables == {}
    assert full_text.result.metrics.metrics.no_answer_rate == 1  # "No results found"
    assert vector.result.metrics.metrics.no_answer_rate == 0
    assert vector.variables == {
        "OPENAI_API_KEY": "local",
        "OPENAI_API_BASE": "<endpoint>/v1",
        "DOCS_MCP_EMBEDDING_MODEL": "BAAI/bge-small-en-v1.5",
    }
    assert vector.embedding is not None
    assert vector.embedding.indexing.texts == 1  # the guide, through the endpoint
    assert vector.embedding.questions.texts == 2
    assert vector.indexing[0].embedded == vector.indexing[0].chunks == 1
    assert full_text.settings["app"]["storePath"] == "<store>"
    assert report.baseline.name == TEXT_BASELINE
    assert report.baseline.result.metrics.metrics.recall_at_1 == 1
    assert report.recorded == []
    summary = (tmp_path / "out" / "grounded-docs.md").read_text("utf-8")
    assert summary in capsys.readouterr().out
    assert "| Grounded Docs full-text | text | 100.0% |" in summary
    assert f"| {TEXT_BASELINE} | text | 100.0% |" in summary


def test_an_article_left_out_is_named_with_the_cases_that_expected_it(
    tmp_path: Path, corpus_args: list[str]
) -> None:
    tool = ReplayingGroundedDocs(leave_out=frozenset({"docs/guide.md"}))

    code, report = _run(tmp_path, corpus_args, tool, "--configs", FULL_TEXT)

    assert report is not None
    (run,) = report.runs
    assert run.indexing[0].not_indexed == ["docs/guide.md"]
    assert run.cases_not_indexed == ["demo v1: How do I install the demo package?"]
    assert run.result.metrics.metrics.recall_at_10 == 0
    assert problems(report) == [f"{FULL_TEXT}: nothing indexed for demo v1"]
    assert code == 1
    assert "`docs/guide.md`" in markdown(report)


def test_a_part_and_its_alternative_count_once_as_the_text_scorer_counts_them(
    tmp_path: Path,
) -> None:
    guide = {"version": "v1", "article": "docs/guide.md"}
    install = guide | {"heading_path": ["Guide", "Install"]}
    configure = guide | {"heading_path": ["Guide", "Configure"]}

    def case(name: str, hits: list[dict]) -> dict:
        return {
            "name": f"demo v1: {name}",
            "inputs": {"query": INSTALL_QUERY, "version": "v1", "project": "demo"},
            "metadata": {"kind": "how-to"},
            "expected_output": {"hits": hits, "reference": "pip.", "facts": ["pip"]},
        }

    cases = [
        case("either section", [install, configure | {"alternative": True}]),
        case("both sections", [install, configure]),
    ]
    args = tiny_corpus(tmp_path / "corpus", cases=cases)[:6]

    _, report = _run(tmp_path, args, ReplayingGroundedDocs(), "--configs", FULL_TEXT)

    assert report is not None
    rows = {r.case: r.row for r in report.runs[0].rows}
    either, both = rows["demo v1: either section"], rows["demo v1: both sections"]
    assert (either.rank, either.sections, either.section_ranks, either.ndcg) == (1, 1, (1,), 1.0)
    assert (both.rank, both.sections, both.section_ranks) == (1, 2, (1,))  # one result, one part
    assert both.ndcg < 1


def test_a_case_with_an_article_still_indexed_is_not_out_of_reach() -> None:
    def row(case: str) -> TextRow:
        return TextRow(
            case=case,
            row=Row(
                case=case, kind="version-change", project="demo", answerable=True, rank=None,
                ndcg=0.0, sections=1, section_ranks=(), wrong_version=False, empty=False,
                search_ms=1.0, tokens=0, usd=0.0,
            ),
            results=0, neutral=0, unmatched=0, context_tokens=0, tokens_to_hit=None, facts=0,
            facts_found=0,
        )  # fmt: skip

    indexing = [
        VersionIndex(
            project="demo", version="v1", commit="c", library="demo", seconds=1.0, offered=3,
            indexed=2, chunks=2, embedded=0, max_depth=3, max_pages=1000,
            not_indexed=["docs/changelog.md"],
        )
    ]  # fmt: skip
    articles = {
        "only the changelog": {("v1", "docs/changelog.md")},
        "an alternative or a part in the guide": {
            ("v1", "docs/changelog.md"),
            ("v1", "docs/guide.md"),
        },
        "another version's changelog": {("v2", "docs/changelog.md")},
    }

    found = cases_not_indexed([row(name) for name in articles], articles, indexing)

    assert found == ["only the changelog"]  # recall counts a hit on any section a case lists


def test_a_failed_search_is_scored_empty_and_fails_the_run(
    tmp_path: Path, corpus_args: list[str]
) -> None:
    tool = ReplayingGroundedDocs(fail=frozenset({INSTALL_QUERY}))

    code, report = _run(tmp_path, corpus_args, tool, "--configs", FULL_TEXT)

    assert code == 1
    assert report is not None
    (run,) = report.runs
    (error,) = run.errors
    assert INSTALL_QUERY in error
    assert run.result.metrics.metrics.recall_at_10 == 0


def test_resume_keeps_the_versions_already_indexed(tmp_path: Path, corpus_args: list[str]) -> None:
    first = ReplayingGroundedDocs()
    _, before = _run(tmp_path, corpus_args, first, "--configs", FULL_TEXT)
    again = ReplayingGroundedDocs(stores=first.stores)

    code, after = _run(tmp_path, corpus_args, again, "--configs", FULL_TEXT, "--resume")

    assert code == 0
    assert before is not None
    assert after is not None
    assert again.indexed == []
    assert after.runs[0].indexing == before.runs[0].indexing
    assert [r.row.rank for r in after.runs[0].rows] == [r.row.rank for r in before.runs[0].rows]


def test_without_resume_every_version_is_indexed_again(
    tmp_path: Path, corpus_args: list[str]
) -> None:
    first = ReplayingGroundedDocs()
    _run(tmp_path, corpus_args, first, "--configs", FULL_TEXT)
    again = ReplayingGroundedDocs()

    _run(tmp_path, corpus_args, again, "--configs", FULL_TEXT)

    assert again.indexed == [("demo", "v1", (3, 1000))]


def test_an_unknown_configuration_is_refused(tmp_path: Path, corpus_args: list[str]) -> None:
    assert _run(tmp_path, corpus_args, ReplayingGroundedDocs(), "--configs", "colbert")[0] == 2


def test_paired_tests_compare_case_by_case() -> None:
    def row(case: str, rank: int | None) -> Row:
        return Row(
            case=case, kind="how-to", project="demo", answerable=True, rank=rank,
            ndcg=1.0 if rank == 1 else 0.0, sections=1, section_ranks=(rank,) if rank else (),
            wrong_version=False, empty=False, search_ms=1.0, tokens=0, usd=0.0,
        )  # fmt: skip

    theirs = [row(f"c{i}", 1 if i < 5 else None) for i in range(20)]
    mine = [row(f"c{i}", 1) for i in range(20)]

    result = paired(TEXT_BASELINE, "text", theirs, mine)

    test = result.tests["recall_at_1"]
    assert (test.gained, test.lost, test.difference) == (15, 0, 0.75)
    assert test.significant


def test_the_page_blocks_come_from_the_report(tmp_path: Path, corpus_args: list[str]) -> None:
    _, report = _run(tmp_path, corpus_args, ReplayingGroundedDocs())
    assert report is not None

    blocks = page_blocks(report)

    assert set(blocks) == {"grounded-docs-run", "grounded-docs"}
    assert f"Grounded Docs {VERSION}" in blocks["grounded-docs-run"]
    assert "### Paired tests against ExactDocs" in blocks["grounded-docs"]


# ---------------------------------------------------------------- the install


def test_the_install_is_refused_offline_when_it_is_not_there(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="not installed"):
        install(tmp_path, offline=True)


def _installed(home: Path, integrity: str) -> Path:
    prefix = home / VERSION
    entry = prefix / "node_modules" / PACKAGE / "dist" / "index.js"
    entry.parent.mkdir(parents=True)
    entry.write_text("", encoding="utf-8")
    lock = {"packages": {f"node_modules/{PACKAGE}": {"version": VERSION, "integrity": integrity}}}
    (prefix / "package-lock.json").write_text(json.dumps(lock), encoding="utf-8")
    return entry


def test_an_install_of_another_release_is_refused(tmp_path: Path) -> None:
    _installed(tmp_path, "sha512-x")

    with pytest.raises(RuntimeError, match=r"not 3\.4\.1"):
        install(tmp_path, offline=True)


def test_the_pinned_install_is_accepted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    entry = _installed(tmp_path, INTEGRITY)
    monkeypatch.setattr(shutil, "which", lambda name: f"/opt/bin/{name}")

    tool = install(tmp_path, offline=True)

    assert (tool.entry, tool.config, tool.node) == (
        entry,
        tmp_path / "config.yaml",
        Path("/opt/bin/node"),
    )


def test_the_install_needs_node(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _installed(tmp_path, INTEGRITY)
    monkeypatch.setattr(shutil, "which", lambda _name: None)

    with pytest.raises(RuntimeError, match=r"Node\.js 22"):
        install(tmp_path, offline=True)
