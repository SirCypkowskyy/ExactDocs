"""The benchmark pages (#349): their generated tables match the recorded runs."""

import pytest

from agent_bench.report import BenchReport
from retrieval_eval.bench_pages import PAGES, RESULTS, agent_blocks, blocks, main, render


def test_the_committed_pages_match_the_recorded_runs() -> None:
    assert main(["--check"]) == 0, "run `just bench-pages` and commit docs/benchmark/"


def test_every_generated_block_is_on_a_page() -> None:
    pages = "".join(p.read_text("utf-8") for p in PAGES.glob("*.md"))
    for name in blocks():
        assert f"<!-- bench:{name} -->" in pages


def test_a_block_is_refilled_and_the_text_around_it_kept() -> None:
    a, b, end = "<!-- bench:a -->\n", "<!-- bench:b -->\n", "<!-- /bench -->\n"
    page = f"intro\n{a}old\n{end}middle\n{b}{end}"
    assert render(page, {"a": "A", "b": "B"}) == f"intro\n{a}A\n{end}middle\n{b}B\n{end}"


def test_a_recorded_agent_run_with_the_context7_arm_is_not_published() -> None:
    report = BenchReport.model_validate_json((RESULTS / "agent.json").read_text("utf-8"))
    arms = [*report.meta.arms, "context7"]
    with_context7 = report.model_copy(
        update={"meta": report.meta.model_copy(update={"arms": arms})}
    )

    with pytest.raises(ValueError, match="Context7's terms forbid publishing it"):
        agent_blocks(with_context7)
