"""One ranking suite for every search engine: ``expected-queries.yaml`` through ``SearchDocs``.

Each entry of the table says which section must rank first for a query in a version (see the
fixture README for the format). The cases run end to end: the fixture repository is imported by
the real importer, then searched through the retrieval use case.
"""

from pathlib import Path
from typing import Any

import pytest
import yaml

from exactdocs.retrieval.dtos import SearchDocsQuery
from exactdocs.retrieval.models import TagMatch
from exactdocs.retrieval.ports.driving import SearchDocs
from fixture_repo import DocsRepo, git

from .conftest import LIBRARY  # ty: ignore[unresolved-import]

TABLE = Path(__file__).parents[2] / "fixtures" / "docs-repo" / "expected-queries.yaml"
TOP = 5  # how many hits a failure prints


def load_cases() -> list[Any]:
    """``(entry, version, expected)`` per asserted version; ``xfail: <reason>`` marks a known gap."""
    cases = []
    for entry in yaml.safe_load(TABLE.read_text(encoding="utf-8"))["queries"]:
        for version, expected in entry["expected"].items():
            marks = [pytest.mark.xfail(reason=entry["xfail"])] if "xfail" in entry else []
            cases.append(pytest.param(entry, version, expected, marks=marks, id=_id(entry, version)))
    return cases


def _id(entry: dict[str, Any], version: str) -> str:
    tags = f"[{','.join(entry['tags'])}]" if "tags" in entry else ""
    return f"{version}:{entry['query']}{tags}"


@pytest.mark.parametrize(("entry", "version", "expected"), load_cases())
async def test_expected_section_ranks_first(
    search_docs: SearchDocs,
    docs_repo: DocsRepo,
    entry: dict[str, Any],
    version: str,
    expected: dict[str, Any] | None,
) -> None:
    result = await search_docs(
        SearchDocsQuery(
            library=LIBRARY,
            ref=version,
            query=entry["query"],
            tags=entry.get("tags", []),
            tags_match=TagMatch(entry.get("tags_match", "any")),
            limit=TOP,
        )
    )
    top = [f"{h.article_path} > {' > '.join(h.heading_path)} ({h.score:.2f})" for h in result.results]
    context = f"\n{entry['query']!r} in {version}; top {TOP}:\n  " + "\n  ".join(top or ["(none)"])

    assert result.version == version
    commit = git("rev-parse", f"{version}^{{commit}}", cwd=docs_repo.path)
    assert {h.commit_sha for h in result.results} <= {commit}, "answered from another version"
    if expected is None:
        assert not result.results, context
        return
    wanted = (expected["article"], expected["heading_path"])
    ranked = [(h.article_path, h.heading_path) for h in result.results]
    assert wanted in ranked[: entry.get("top_n", 1)], f"expected {wanted} first{context}"
