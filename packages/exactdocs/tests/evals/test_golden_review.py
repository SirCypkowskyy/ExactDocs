"""The golden set's review (#490): the sample, the verdicts' rules, the summary and the checks.

The checks run on a tiny local git repository standing in for an upstream project; the real review
file is checked against the real case files (no cache needed).
"""

import datetime as dt
import re
from pathlib import Path

import pytest
import yaml
from pydantic_evals import Case

from fixture_repo import git
from retrieval_eval.dataset import GOLDEN_KINDS, Answer, CaseInfo, Hit, Question
from retrieval_eval.golden import Corpus, GoldenCase, PinnedVersion, Project, fetch, load_cases
from retrieval_eval.golden_cli import main as golden_main
from retrieval_eval.golden_review import (
    KINDS,
    Review,
    ReviewEntry,
    SampleSpec,
    checks_markdown,
    copies,
    draw_sample,
    load_review,
    longest_run,
    near_duplicates,
    review_block,
    review_file_problems,
    review_problems,
    run_checks,
    stem,
    summarize,
    terms,
    wilson,
)
from retrieval_eval.golden_review_cli import main

GUIDE = """---
title: Guide
---

## Install

Run the installer with pip and restart the shell afterwards.

```sh
pip install demo
```

## Sessions

Changes to nested values are not tracked automatically, so assign the value back.

## Caching

Cached entries expire after five minutes of inactivity.
"""


def _case(
    name: str,
    kind: str,
    *,
    query: str | None = None,
    project: str = "demo",
    version: str = "v1",
    section: str = "Install",
) -> GoldenCase:
    unanswerable = kind == "unanswerable"
    hits = (
        []
        if unanswerable
        else [Hit(version=version, article="docs/guide.md", heading_path=[section])]
    )
    return Case(
        name=f"{project} {version}: {name}",
        inputs=Question(query=query or name, version=version, project=project),
        metadata=CaseInfo.model_validate({"kind": kind}),
        expected_output=Answer(
            hits=hits, reference="An answer.", facts=[] if unanswerable else ["a fact"]
        ),
    )


def _dumped(case: GoldenCase) -> dict[str, object]:
    assert case.metadata is not None
    assert case.expected_output is not None
    return {
        "name": case.name,
        "inputs": case.inputs.model_dump(mode="json", exclude_defaults=True),
        "metadata": {"kind": case.metadata.kind},
        "expected_output": case.expected_output.model_dump(mode="json", exclude_defaults=True),
    }


def _set(
    per_kind: int = 4, projects: tuple[str, ...] = ("demo", "other")
) -> list[tuple[str, GoldenCase]]:
    return [
        (project, _case(f"{kind} question {i}?", kind, project=project))
        for project in projects
        for kind in KINDS
        for i in range(per_kind)
    ]


def _entry(case: GoldenCase, project: str, **fields: object) -> ReviewEntry:
    values: dict[str, object] = {
        "case": case.name,
        "project": project,
        "kind": case.metadata.kind if case.metadata else "",
        "verdict": "correct",
        "reviewer": "independent review agent",
        "date": dt.date(2026, 11, 23),
    }
    return ReviewEntry.model_validate(values | fields)


def _review(sample: list[tuple[str, GoldenCase]], per_stratum: int = 1) -> Review:
    return Review(
        sample=SampleSpec(seed=1, per_stratum=per_stratum, drawn_from="sha256:x"),
        entries=[_entry(case, project) for project, case in sample],
    )


def test_the_sample_takes_the_same_number_of_every_kind_and_project_reproducibly() -> None:
    cases = _set()

    sample = draw_sample(cases, seed=490, per_stratum=3)

    assert len(sample) == 2 * len(GOLDEN_KINDS) * 3
    for project in ("demo", "other"):
        for kind in KINDS:
            drawn = [
                c for p, c in sample if p == project and c.metadata and c.metadata.kind == kind
            ]
            assert len(drawn) == 3
    assert [c.name for _, c in draw_sample(cases, seed=490, per_stratum=3)] == [
        c.name for _, c in sample
    ]
    assert [c.name for _, c in draw_sample(cases, seed=7, per_stratum=3)] != [
        c.name for _, c in sample
    ]


def test_a_stratum_smaller_than_the_draw_is_taken_whole() -> None:
    cases = _set(per_kind=2, projects=("demo",))

    assert len(draw_sample(cases, seed=1, per_stratum=3)) == len(cases)


def test_adding_a_case_leaves_the_other_strata_draws_unchanged() -> None:
    cases = _set()
    more = [*cases, ("demo", _case("an extra how-to?", "how-to"))]

    def drawn(of: list[tuple[str, GoldenCase]]) -> list[str | None]:
        return [
            c.name
            for p, c in draw_sample(of, seed=490, per_stratum=2)
            if (p, c.metadata.kind if c.metadata else "") != ("demo", "how-to")
        ]

    assert drawn(more) == drawn(cases)


@pytest.mark.parametrize(
    ("wrong", "n", "low", "high"),
    [(23, 90, 0.1768, 0.3544), (0, 15, 0.0, 0.2039), (15, 15, 0.7961, 1.0)],
)
def test_the_wilson_interval_bounds_a_proportion(
    wrong: int, n: int, low: float, high: float
) -> None:
    assert wilson(wrong, n) == (pytest.approx(low, abs=1e-4), pytest.approx(high, abs=1e-4))


def test_no_trials_give_the_widest_interval() -> None:
    assert wilson(0, 0) == (0.0, 1.0)


def test_a_complete_review_follows_the_rules() -> None:
    cases = _set()
    sample = draw_sample(cases, seed=1, per_stratum=1)

    assert review_problems(_review(sample), cases) == []


def test_broken_verdicts_are_reported() -> None:
    cases = _set()
    sample = draw_sample(cases, seed=1, per_stratum=1)
    (p0, c0), (p1, c1), (p2, c2), (p3, c3), (p4, c4) = sample[:5]
    review = _review(sample).model_copy(
        update={
            "entries": [
                _entry(c0, p0, verdict="removed", problems=["duplicate"], note="same as another"),
                _entry(c1, p1, verdict="fixed"),
                _entry(c2, p2, problems=["wrong-kind"]),
                _entry(c3, p3, verdict="fixed", problems=["wrong-kind"]),
                _entry(c4, "other" if p4 == "demo" else "demo"),
                _entry(c4, p4),
                *[_entry(c, p) for p, c in sample[5:]],
            ]
        }
    )

    problems = review_problems(review, cases)

    assert f"{c0.name}: is removed but still in the golden set" in problems
    assert f"{c1.name}: is fixed but names no problem" in problems
    assert f"{c1.name}: is fixed but has no note saying why" in problems
    assert f"{c2.name}: is correct but names problems" in problems
    assert f"{c3.name}: is fixed but has no note saying why" in problems
    assert f"{c4.name}: is not a case of {'other' if p4 == 'demo' else 'demo'}" in problems
    assert f"{c4.name}: reviewed twice" in problems


def test_a_removed_case_must_be_gone_and_a_stratum_must_be_complete() -> None:
    cases = _set()
    sample = draw_sample(cases, seed=1, per_stratum=1)
    (p0, c0) = sample[0]
    remaining = [(p, c) for p, c in cases if c.name != c0.name]
    removed = _entry(c0, p0, verdict="removed", problems=["duplicate"], note="same as another")
    review = _review(sample).model_copy(
        update={"entries": [removed, *[_entry(c, p) for p, c in sample[1:]]]}
    )

    assert review_problems(review, remaining) == []
    kind0 = c0.metadata.kind if c0.metadata else ""
    short = review.model_copy(update={"entries": review.entries[1:]})
    assert review_problems(short, remaining) == [f"{p0} {kind0}: 0 entries, not 1"]


def test_a_case_that_is_still_there_under_its_old_name_is_reported() -> None:
    cases = _set()
    sample = draw_sample(cases, seed=1, per_stratum=1)
    (p0, c0), (_, c1) = sample[:2]
    review = _review(sample)
    renamed = _entry(c0, p0, verdict="fixed", problems=["ambiguous"], note="reworded", was=c1.name)

    problems = review_problems(review.model_copy(update={"entries": [renamed]}), cases)

    assert f"{c0.name}: was renamed from {c1.name!r}, which is still in the set" in problems


def test_the_review_file_is_optional_and_must_load(tmp_path: Path) -> None:
    assert review_file_problems([], tmp_path / "review.yaml") == []
    (tmp_path / "review.yaml").write_text("sample: {seed: x}\n", encoding="utf-8")

    (problem,) = review_file_problems([], tmp_path / "review.yaml")

    assert problem.startswith("review.yaml: does not load:")


def test_the_summary_counts_verdicts_and_bounds_the_error_rate() -> None:
    cases = _set()
    sample = draw_sample(cases, seed=1, per_stratum=1)
    entries = [_entry(c, p) for p, c in sample]
    (p0, c0), (p1, c1) = sample[:2]
    entries[0] = _entry(c0, p0, verdict="fixed", problems=["missing-section"], note="n")
    entries[1] = _entry(
        c1, p1, verdict="fixed", problems=["wrong-kind", "missing-section"], note="n"
    )
    review = _review(sample).model_copy(update={"entries": entries})

    summary = summarize(review)
    block = review_block(review)

    assert (summary.size, summary.wrong) == (12, 2)
    assert summary.verdicts == {"correct": 10, "fixed": 2, "removed": 0}
    assert summary.problems["missing-section"] == 2
    assert summary.problems["wrong-kind"] == 1
    low, high = wilson(2, 12)
    assert f"2 of 12, 16.7% (95% Wilson interval {low * 100:.1f}% to {high * 100:.1f}%)" in block
    assert "| `missing-section` | 2 |" in block
    assert "`unsupported-fact`" not in block  # categories nobody found are left out
    assert "Reviewed by: independent review agent, 2026-11-23." in block


def test_words_are_stemmed_and_stop_words_left_out() -> None:
    assert stem("handlers") == "handler"
    assert stem("queries") == "query"
    assert stem("class") == "class"
    assert terms("How do I run the handlers?") == {"run", "handler"}


def test_a_copied_phrase_is_told_from_a_shared_name() -> None:
    copied = longest_run(
        "What does it mean that nested values are not tracked automatically?",
        "Changes to nested values are not tracked automatically.",
    )
    shared = longest_run("What is SessionMiddleware for?", "SessionMiddleware adds sessions.")

    assert copies(copied)
    assert not copies(shared)


def test_near_duplicates_are_paired_within_a_project() -> None:
    a = _case("How do I install the package with pip?", "how-to")
    b = _case("How do I install the package using pip?", "how-to", version="v2")
    c = _case("How do I install the package with pip?", "how-to", project="other")

    (pair,) = near_duplicates([("demo", a), ("demo", b), ("other", c)])

    assert (pair.a, pair.b, pair.same_version) == (a.name, b.name, False)


@pytest.fixture
def upstream(tmp_path: Path) -> tuple[Corpus, dict[str, Path]]:
    repo = tmp_path / "upstream"
    git("init", "-q", "-b", "main", "--template=", str(repo))
    (repo / "docs").mkdir()
    (repo / "docs" / "guide.md").write_text(GUIDE, encoding="utf-8")
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
    corpus = Corpus(projects=[project])
    return corpus, {"demo": fetch(project, tmp_path / "cache")}


def test_the_checks_measure_overlap_and_find_the_unanswerable_words(
    upstream: tuple[Corpus, dict[str, Path]],
) -> None:
    corpus, repos = upstream
    copied = _case(
        "What does it mean that nested values are not tracked automatically?",
        "conceptual",
        section="Sessions",
    )
    paraphrased = _case("What do I type to set it up?", "how-to", section="Install")
    answerable = _case("When do cached entries expire after inactivity?", "unanswerable")

    checks = run_checks(
        [("demo", copied), ("demo", paraphrased), ("demo", answerable)], corpus, repos
    )
    report = checks_markdown(checks)

    by_case = {o.case: o for o in checks.overlaps}
    first, second = by_case[copied.name or ""], by_case[paraphrased.name or ""]
    assert first.copied
    assert first.rank == 1
    assert first.expected > first.best_other
    assert not second.copied
    (vocabulary,) = checks.vocabulary
    assert vocabulary.flagged
    assert vocabulary.best[0][0] == "docs/guide.md [Caching]"
    assert "### Questions that copy their section (1)" in report
    assert f"- FLAG {answerable.name}." in report


def test_sample_writes_a_sheet_and_a_review_to_fill_in(
    upstream: tuple[Corpus, dict[str, Path]], tmp_path: Path
) -> None:
    corpus, _ = upstream
    corpus_file = tmp_path / "corpus.yaml"
    corpus_file.write_text(yaml.safe_dump(corpus.model_dump(mode="json")), encoding="utf-8")
    cases_dir = tmp_path / "cases"
    cases_dir.mkdir()
    cases = [_dumped(_case(f"{kind} question?", kind)) for kind in KINDS]
    (cases_dir / "demo.yaml").write_text(
        yaml.safe_dump({"name": "demo", "cases": cases}), encoding="utf-8"
    )
    out = tmp_path / "out"

    assert main([
        "sample", "--per-stratum", "1", "--offline", "--corpus", str(corpus_file),
        "--cases", str(cases_dir), "--cache-dir", str(tmp_path / "cache"), "--out", str(out),
    ]) == 0  # fmt: skip

    sheet = (out / "sheet.md").read_text(encoding="utf-8")
    draft = yaml.safe_load((out / "review-draft.yaml").read_text(encoding="utf-8"))
    assert len(re.findall(r"^## \d+\. demo v1: ", sheet, re.MULTILINE)) == len(KINDS)
    assert "````text\n## Install" in sheet  # a longer fence than the section's own
    assert "#### Expected: docs/guide.md [Install]" in sheet
    assert "/blob/" in sheet
    assert draft["sample"]["per_stratum"] == 1
    assert {e["kind"] for e in draft["entries"]} == set(KINDS)


def test_golden_validate_checks_the_review_beside_the_cases(
    upstream: tuple[Corpus, dict[str, Path]], tmp_path: Path
) -> None:
    corpus, _ = upstream
    corpus_file = tmp_path / "corpus.yaml"
    corpus_file.write_text(yaml.safe_dump(corpus.model_dump(mode="json")), encoding="utf-8")
    cases_dir = tmp_path / "cases"
    cases_dir.mkdir()
    case = _case("How do I install it?", "how-to")
    (cases_dir / "demo.yaml").write_text(
        yaml.safe_dump({"name": "demo", "cases": [_dumped(case)]}),
        encoding="utf-8",
    )
    entry = _entry(case, "demo", verdict="fixed").model_dump(mode="json")
    review = {"sample": {"seed": 1, "per_stratum": 1, "drawn_from": "x"}, "entries": [entry]}
    (tmp_path / "review.yaml").write_text(yaml.safe_dump(review), encoding="utf-8")
    args = ["validate", "--offline", "--corpus", str(corpus_file), "--cases", str(cases_dir)]

    assert golden_main([*args, "--cache-dir", str(tmp_path / "cache")]) == 1


def test_the_recorded_review_follows_the_rules() -> None:
    cases, problems = load_cases()

    assert problems == []
    assert review_problems(load_review(), cases) == []


def test_the_summary_command_prints_the_recorded_review(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["summary"]) == 0

    assert "95% Wilson interval" in capsys.readouterr().out
