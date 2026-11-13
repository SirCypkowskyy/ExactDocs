"""The benchmark pages (#349): their generated tables match the recorded runs."""

from retrieval_eval.bench_pages import PAGES, blocks, main, render


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
