"""The golden set (#345): its schema rules, the section check, fetching and importing.

Everything runs on a tiny local git repository standing in for an upstream project, so no test
needs the network. The real corpus is checked offline when it is already in the local cache
(``just golden-validate`` fetches it); CI has no cache and skips that test.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic_evals import Case

from fixture_repo import git
from retrieval_eval.dataset import Answer, CaseInfo, Hit, Question
from retrieval_eval.fixture import model_free_container
from retrieval_eval.golden import (
    CASES_DIR,
    Corpus,
    GoldenCase,
    PinnedVersion,
    Project,
    default_cache_dir,
    fetch,
    has_commit,
    load_cases,
    load_corpus,
    load_golden,
    schema_problems,
    section_problems,
)
from retrieval_eval.golden_cli import import_corpus, main

GUIDE_V1 = """---
title: Guide
---
# Guide

Intro.

## Install

Run it.

```sh
## not a heading
```
"""
GUIDE_V2 = GUIDE_V1.replace("## Install", "## Setup")


def _commit(repo: Path, tag: str, files: dict[str, str], delete: tuple[str, ...] = ()) -> str:
    for path, text in files.items():
        (repo / path).parent.mkdir(parents=True, exist_ok=True)
        (repo / path).write_text(text, encoding="utf-8")
    for path in delete:
        (repo / path).unlink()
    git("add", "-A", cwd=repo)
    git(
        "commit", "-q", "--no-verify", "-m", tag, cwd=repo,
        GIT_AUTHOR_NAME="A", GIT_AUTHOR_EMAIL="a@example.com",
        GIT_COMMITTER_NAME="A", GIT_COMMITTER_EMAIL="a@example.com",
    )  # fmt: skip
    git("tag", tag, cwd=repo)
    return git("rev-parse", "HEAD", cwd=repo)


@pytest.fixture(scope="module")
def upstream(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict[str, str]]:
    """A project whose guide moves (docs/guide.md -> docs/start.md) and renames a section."""
    repo = tmp_path_factory.mktemp("upstream")
    git("init", "-q", "-b", "main", "--template=", str(repo))
    v1 = _commit(repo, "v1", {"docs/guide.md": GUIDE_V1, "README.md": "# Readme\n"})
    v2 = _commit(repo, "v2", {"docs/start.md": GUIDE_V2}, delete=("docs/guide.md",))
    return repo, {"v1": v1, "v2": v2}


@pytest.fixture
def corpus(upstream: tuple[Path, dict[str, str]]) -> Corpus:
    repo, shas = upstream
    return Corpus(
        projects=[
            Project(
                id="demo",
                title="Demo",
                repository=str(repo),
                include=["docs/"],
                licence="MIT",
                attribution="Copyright (c) A",
                versions=[PinnedVersion(name=v, commit=sha) for v, sha in shas.items()],
            )
        ]
    )


@pytest.fixture
def repos(corpus: Corpus, tmp_path: Path) -> dict[str, Path]:
    return {"demo": fetch(corpus.projects[0], tmp_path / "cache")}


def _case(
    *,
    name: str = "demo v1: How do I install it?",
    kind: str = "how-to",
    project: str | None = "demo",
    version: str = "v1",
    hits: list[tuple[str, str, list[str]]] | None = None,
    reference: str | None = "Run it.",
    facts: list[str] | None = None,
) -> GoldenCase:
    found = [("v1", "docs/guide.md", ["Guide", "Install"])] if hits is None else hits
    return Case(
        name=name,
        inputs=Question(query="How do I install it?", version=version, project=project),
        metadata=CaseInfo.model_validate({"kind": kind}),
        expected_output=Answer(
            hits=[Hit(version=v, article=a, heading_path=p) for v, a, p in found],
            reference=reference,
            facts=["run it"] if facts is None else facts,
        ),
    )


def _unanswerable(
    *,
    name: str = "demo v1: How do I install it?",
    hits: list[tuple[str, str, list[str]]] | None = None,
    facts: list[str] | None = None,
) -> GoldenCase:
    return _case(name=name, kind="unanswerable", hits=hits or [], facts=facts or [])


def test_a_valid_case_and_a_valid_unanswerable_case_have_no_problem(corpus: Corpus) -> None:
    cases = [("demo", _case()), ("demo", _unanswerable(name="demo v1: other"))]

    assert schema_problems(cases, corpus) == []


@pytest.mark.parametrize(
    ("make", "problem"),
    [
        (lambda: _case(kind="question"), "kind is 'question', not one of conceptual, cross-page"),
        (lambda: _case(project=None), "project is None, but it is in demo.yaml"),
        (
            lambda: _case(version="v9", hits=[("v9", "docs/guide.md", ["Guide"])]),
            "demo has no pinned version 'v9'",
        ),
        (lambda: _case(reference=" "), "has no reference answer"),
        (lambda: _unanswerable(hits=[("v1", "docs/guide.md", ["Guide"])]), "but expects sections"),
        (lambda: _unanswerable(facts=["x"]), "is unanswerable but lists facts"),
        (lambda: _case(hits=[]), "expects no section: name them, or make it unanswerable"),
        (lambda: _case(facts=[" "]), "lists no facts a correct answer must contain"),
        (
            lambda: _case(hits=[("v2", "docs/start.md", ["Guide", "Setup"])]),
            "expects a section of v2, not of its version v1",
        ),
        (
            lambda: _case(
                kind="cross-page",
                hits=[
                    ("v1", "docs/guide.md", ["Guide"]),
                    ("v1", "docs/guide.md", ["Guide", "Install"]),
                ],
            ),
            "is cross-page but expects sections of fewer than two articles",
        ),
    ],
)
def test_a_case_that_breaks_a_rule_is_reported(
    corpus: Corpus, make: Callable[[], GoldenCase], problem: str
) -> None:
    problems = schema_problems([("demo", make())], corpus)

    assert len(problems) == 1
    assert problems[0].startswith("demo v1: How do I install it?: ")
    assert problem in problems[0]


def test_a_duplicate_name_and_an_unknown_project_are_reported(corpus: Corpus) -> None:
    problems = schema_problems(
        [("demo", _case()), ("demo", _case()), ("other", _case(name="x", project="other"))], corpus
    )

    assert problems == [
        "demo v1: How do I install it?: the name is used by another case",
        "x: the corpus has no project 'other'",
    ]


def test_sections_that_exist_at_their_pinned_commit_pass(
    corpus: Corpus, repos: dict[str, Path]
) -> None:
    cases = [
        ("demo", _case()),
        ("demo", _case(name="b", version="v2", hits=[("v2", "docs/start.md", ["Guide", "Setup"])])),
        ("demo", _case(name="c", hits=[("v1", "docs/guide.md", ["Guide"])])),
    ]

    assert section_problems(cases, corpus, repos) == []


@pytest.mark.parametrize(
    ("hit", "problem"),
    [
        (
            ("v2", "docs/guide.md", ["Guide", "Install"]),
            "v2:docs/guide.md does not exist at the pinned",
        ),
        (
            ("v1", "docs/guide.md", ["Guide", "Instal"]),
            "v1:docs/guide.md has no section [Guide > Instal]; closest: [Guide > Install]",
        ),
        (
            ("v2", "docs/start.md", ["Guide", "Install"]),
            "v2:docs/start.md has no section [Guide > Install]; closest: [Guide > Setup]",
        ),
        (
            ("v1", "docs/guide.md", ["Guide", "not a heading"]),
            "has no section [Guide > not a heading]",
        ),
        (
            ("v1", "README.md", ["Readme"]),
            "README.md is not a .md/.mdx file under the project's include",
        ),
    ],
)
def test_a_section_missing_at_the_pinned_commit_is_reported(
    corpus: Corpus, repos: dict[str, Path], hit: tuple[str, str, list[str]], problem: str
) -> None:
    version = hit[0]
    case = _case(name="broken", version=version, hits=[hit])

    problems = section_problems([("demo", case)], corpus, repos)

    assert len(problems) == 1
    assert problems[0].startswith(f"broken: {version}:")
    assert problem in problems[0]


def test_fetch_keeps_every_pinned_commit_and_offline_needs_them(
    corpus: Corpus, tmp_path: Path, upstream: tuple[Path, dict[str, str]]
) -> None:
    project = corpus.projects[0]
    with pytest.raises(RuntimeError, match="not cached"):
        fetch(project, tmp_path / "empty", offline=True)

    repo = fetch(project, tmp_path / "cache")

    _, shas = upstream
    assert all(has_commit(repo, sha) for sha in shas.values())
    assert git("rev-parse", "v2^{commit}", cwd=repo) == shas["v2"]
    assert fetch(project, tmp_path / "cache", offline=True) == repo


async def test_import_takes_each_version_at_its_pinned_commit(
    corpus: Corpus, repos: dict[str, Path], tmp_path: Path
) -> None:
    container = model_free_container(tmp_path / "data")
    async with container.running(jobs=False):
        records = await import_corpus(container, corpus.projects, repos)

    pinned = {v.name: v.commit for v in corpus.projects[0].versions}
    assert [(r.version, r.imported_commit, r.files) for r in records] == [
        ("v1", pinned["v1"], 1),
        ("v2", pinned["v2"], 1),
    ]
    assert all(r.library.endswith("upstream0") and not r.problems for r in records)


def _write(tmp_path: Path, corpus: Corpus, cases: list[dict[str, Any]]) -> list[str]:
    corpus_file = tmp_path / "corpus.yaml"
    corpus_file.write_text(yaml.safe_dump(corpus.model_dump(mode="json")), encoding="utf-8")
    cases_dir = tmp_path / "cases"
    cases_dir.mkdir()
    dataset = {"name": "demo", "cases": cases}
    (cases_dir / "demo.yaml").write_text(yaml.safe_dump(dataset), encoding="utf-8")
    cache = str(tmp_path / "cache")
    return [
        "validate",
        "--corpus",
        str(corpus_file),
        "--cases",
        str(cases_dir),
        "--cache-dir",
        cache,
    ]


def test_validate_lists_the_broken_cases_and_fails(
    corpus: Corpus, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    good, bad = _case(), _case(name="bad", hits=[("v1", "docs/guide.md", ["Guide", "Setup"])])
    cases = [_dumped(good), _dumped(bad)]

    assert main(_write(tmp_path, corpus, cases)) == 1

    err = capsys.readouterr().err
    assert "1 problem(s) in the golden set:" in err
    assert "  - bad: v1:docs/guide.md has no section [Guide > Setup]" in err


def test_validate_passes_a_valid_golden_set(
    corpus: Corpus, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(_write(tmp_path, corpus, [_dumped(_case())])) == 0
    assert "golden set: 1 cases in 1 files, every section exists" in capsys.readouterr().out


def _dumped(case: GoldenCase) -> dict[str, Any]:
    assert case.metadata
    assert case.expected_output
    return {
        "name": case.name,
        "inputs": case.inputs.model_dump(mode="json", exclude_defaults=True),
        "metadata": case.metadata.model_dump(mode="json"),
        "expected_output": case.expected_output.model_dump(
            mode="json", include={"hits", "reference", "facts"}
        ),
    }


def test_the_golden_case_files_follow_the_rules() -> None:
    cases, problems = load_cases()
    corpus = load_corpus()

    assert problems + schema_problems(cases, corpus) == []
    assert {project for project, _ in cases} == {p.id for p in corpus.projects}
    assert {path.stem for path in CASES_DIR.glob("*.yaml")} == {p.id for p in corpus.projects}
    assert [c.name for c in load_golden().cases] == [c.name for _, c in cases]


def test_the_golden_sections_exist_at_the_pinned_commits() -> None:
    corpus, cache = load_corpus(), default_cache_dir()
    if not all(
        (cache / f"{p.id}.git" / "HEAD").exists()
        and all(has_commit(cache / f"{p.id}.git", v.commit) for v in p.versions)
        for p in corpus.projects
    ):
        pytest.skip("the corpus is not in the local cache: run `just golden-validate` first")
    repos = {p.id: cache / f"{p.id}.git" for p in corpus.projects}
    cases, _ = load_cases()

    assert section_problems(cases, corpus, repos) == []
