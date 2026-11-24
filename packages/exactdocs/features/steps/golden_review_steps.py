"""Steps for the golden set's review (packages/exactdocs/evals): run in-process, as
`just golden-review` and `just golden-validate` run it, on a tiny local repository standing in for
the golden corpus.
"""

import datetime as dt
import json
import shutil
import tempfile
from pathlib import Path

import yaml
from behave import given, then, when
from behave.runner import Context

from fixture_repo import git
from retrieval_eval.golden_cli import main as golden_main
from retrieval_eval.golden_review import KINDS, load_review, review_block
from retrieval_eval.golden_review_cli import main

GUIDE = """---
title: Guide
---

## Install

Run the installer with pip and restart the shell afterwards.

## Sessions

Changes to nested values are not tracked automatically, so assign the value back.

## Caching

Cached entries expire after five minutes of inactivity.
"""
QUESTIONS = {
    "identifier-lookup": ("Which command installs it?", "Install"),
    "how-to": ("How do I set it up from scratch?", "Install"),
    "conceptual": (
        "Why are nested values not tracked automatically, so assign the value back?",
        "Sessions",
    ),
    "version-change": ("Did the cache expiry change?", "Caching"),
    "cross-page": ("How do I install it and keep my sessions?", "Install"),
    "unanswerable": ("How do I uninstall it?", ""),
}


@given("a golden set with one case of every kind over a small pinned docs project")
def step_golden_set(context: Context) -> None:
    tmp = Path(tempfile.mkdtemp(prefix="exactdocs-golden-review-"))
    context.add_cleanup(shutil.rmtree, tmp, ignore_errors=True)
    repo = tmp / "upstream"
    git("init", "-q", "-b", "main", "--template=", str(repo))
    (repo / "docs").mkdir()
    (repo / "docs" / "guide.md").write_text(GUIDE, encoding="utf-8")
    (repo / "docs" / "faq.md").write_text("## Sessions\n\nSee the guide.\n", encoding="utf-8")
    git("add", "-A", cwd=repo)
    git(
        "commit", "-q", "--no-verify", "-m", "v1", cwd=repo,
        GIT_AUTHOR_NAME="A", GIT_AUTHOR_EMAIL="a@example.com",
        GIT_COMMITTER_NAME="A", GIT_COMMITTER_EMAIL="a@example.com",
    )  # fmt: skip
    context.review_commit = git("rev-parse", "HEAD", cwd=repo)
    project = {
        "id": "demo",
        "title": "Demo",
        "repository": str(repo),
        "include": ["docs/"],
        "licence": "MIT",
        "attribution": "Copyright (c) A",
        "versions": [{"name": "v1", "commit": context.review_commit}],
    }
    (tmp / "corpus.yaml").write_text(yaml.safe_dump({"projects": [project]}), encoding="utf-8")
    cases = []
    for kind, (query, section) in QUESTIONS.items():
        hits = [{"version": "v1", "article": "docs/guide.md", "heading_path": [section]}]
        if kind == "cross-page":
            hits.append({"version": "v1", "article": "docs/faq.md", "heading_path": ["Sessions"]})
        cases.append({
            "name": f"demo v1: {query}",
            "inputs": {"query": query, "version": "v1", "project": "demo"},
            "metadata": {"kind": kind},
            "expected_output": {
                "hits": [] if kind == "unanswerable" else hits,
                "reference": "An answer.",
                "facts": [] if kind == "unanswerable" else ["a fact"],
            },
        })  # fmt: skip
    (tmp / "cases").mkdir()
    dataset = yaml.safe_dump({"name": "demo", "cases": cases})
    (tmp / "cases" / "demo.yaml").write_text(dataset, encoding="utf-8")
    context.review_dir = tmp
    context.review_args = [
        "--corpus", str(tmp / "corpus.yaml"), "--cases", str(tmp / "cases"),
        "--cache-dir", str(tmp / "cache"), "--out", str(tmp / "out"),
    ]  # fmt: skip


@when("the review sample is drawn with one case per kind and project")
def step_draw(context: Context) -> None:
    assert main(["sample", "--per-stratum", "1", *context.review_args]) == 0
    out = context.review_dir / "out"
    context.review_sheet = (out / "sheet.md").read_text(encoding="utf-8")
    context.review_draft = yaml.safe_load((out / "review-draft.yaml").read_text(encoding="utf-8"))


@then("the review sheet shows every sampled case with links to its source at the pinned commit")
def step_sheet(context: Context) -> None:
    sheet = context.review_sheet
    for kind, (query, _) in QUESTIONS.items():
        assert f"demo v1: {query}" in sheet, query
        assert f"- Kind: `{kind}`" in sheet, kind
    assert f"/blob/{context.review_commit}/docs/guide.md#sessions" in sheet
    assert "#### Expected: docs/guide.md [Sessions]" in sheet  # the section's text is quoted


@then(
    "each sampled case is recorded as correct, fixed or removed, with the reviewer, the date "
    "and the reason"
)
def step_record(context: Context) -> None:
    draft = context.review_draft
    assert {e["kind"] for e in draft["entries"]} == set(KINDS)
    for entry in draft["entries"]:
        wrong = entry["kind"] == "cross-page"  # faq.md adds nothing: one article answers it
        entry |= {
            "verdict": "fixed" if wrong else "correct",
            "problems": ["wrong-kind"] if wrong else [],
            "reviewer": "independent review agent",
            "date": dt.date(2026, 11, 23),
            "note": "docs/guide.md states every fact" if wrong else "facts stated",
        }
    review_file = context.review_dir / "review.yaml"
    review_file.write_text(yaml.safe_dump(draft), encoding="utf-8")
    validate = ["validate", "--offline", *context.review_args[:6]]
    assert golden_main(validate) == 0
    broken = dict(draft, entries=[dict(e, note="") for e in draft["entries"]])
    review_file.write_text(yaml.safe_dump(broken), encoding="utf-8")
    assert golden_main(validate) == 1  # a fixed case must say why
    review_file.write_text(yaml.safe_dump(draft), encoding="utf-8")
    context.review = load_review(review_file)


@then(
    "the review summary states the share of wrong cases with a confidence interval and who "
    "reviewed them"
)
def step_summary(context: Context) -> None:
    block = review_block(context.review)
    assert "Wrong cases: 1 of 6, 16.7% (95% Wilson interval 3.0% to 56.4%)." in block, block
    assert "Reviewed by: independent review agent, 2026-11-23." in block
    assert "| `wrong-kind` | 1 |" in block


@when("the whole-set checks of the golden set run")
def step_checks(context: Context) -> None:
    assert main(["checks", *context.review_args]) == 0
    out = context.review_dir / "out"
    context.review_checks = json.loads((out / "checks.json").read_text(encoding="utf-8"))
    context.review_report = (out / "checks.md").read_text(encoding="utf-8")


@then(
    "they report how much each question's wording overlaps its expected section against the "
    "other sections"
)
def step_overlap(context: Context) -> None:
    overlaps = {o["case"]: o for o in context.review_checks["overlaps"]}
    assert len(overlaps) == len(QUESTIONS) - 1  # every answerable case
    for overlap in overlaps.values():
        assert {"expected", "best_other", "rank"} <= overlap.keys()
    assert "| all | 5 |" in context.review_report
    (vocabulary,) = context.review_checks["vocabulary"]  # the unanswerable case, searched for
    assert vocabulary["case"] == "demo v1: How do I uninstall it?"


@then("the cases whose question copies its section's wording are listed")
def step_copied(context: Context) -> None:
    query = QUESTIONS["conceptual"][0]
    assert "### Questions that copy their section (1)" in context.review_report
    assert f"- demo v1: {query} — “" in context.review_report
