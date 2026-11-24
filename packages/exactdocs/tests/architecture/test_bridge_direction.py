"""Bridges in `bootstrap/bridges.py` point one way: see docs/architecture.md, *Bridges are one-way*.

A bridge class implements the consumer's driven port (it imports the consumer's `models` or
`ports.driven`) by calling the provider's driving port (it imports the provider's `ports.driving`
or `dtos`). The allowed edges, consumer -> provider, follow the dependency order
catalog < retrieval < ingestion, which also rules out cycles.
"""

import ast
from graphlib import TopologicalSorter
from pathlib import Path

import pytest

BRIDGES = Path(__file__).resolve().parents[2] / "src" / "exactdocs" / "bootstrap" / "bridges.py"
ALLOWED = {
    ("retrieval", "catalog"),
    ("ingestion", "catalog"),
    ("ingestion", "retrieval"),
    # Library roles (E12-05): identity provides, and has no dependency of its own.
    ("catalog", "identity"),
    ("retrieval", "identity"),
    ("ingestion", "identity"),
    # Usage counts (#510): who opted in to the people leaderboard, and library roles.
    ("usage", "identity"),
}
CONSUMER_MODULES = {"models", "ports.driven"}
PROVIDER_MODULES = {"ports.driving", "dtos"}


def bridge_edges(source: str) -> dict[str, set[tuple[str, str]]]:
    """Map each class in `source` to its (consumer, provider) edges, read from its imports."""
    tree = ast.parse(source)
    imported: dict[str, tuple[str, str]] = {}  # name -> (domain, module inside the domain)
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("exactdocs."):
            domain, _, module = (node.module or "").removeprefix("exactdocs.").partition(".")
            imported.update({alias.asname or alias.name: (domain, module) for alias in node.names})
    edges: dict[str, set[tuple[str, str]]] = {}
    for cls in (n for n in tree.body if isinstance(n, ast.ClassDef)):
        used = {
            imported[n.id] for n in ast.walk(cls) if isinstance(n, ast.Name) and n.id in imported
        }
        consumers = {domain for domain, module in used if module in CONSUMER_MODULES}
        providers = {domain for domain, module in used if module in PROVIDER_MODULES}
        edges[cls.name] = {(c, p) for c in consumers for p in providers}
    return edges


def test_every_bridge_points_from_a_consumer_to_a_provider_that_is_allowed() -> None:
    edges = bridge_edges(BRIDGES.read_text())

    assert edges, "bridges.py has no bridge"
    for name, found in edges.items():
        assert found, f"{name} does not connect a consumer's port to a provider's use case"
        assert found <= ALLOWED, (
            f"{name} goes against the bridge direction: {sorted(found - ALLOWED)}"
        )


def test_the_allowed_edges_have_no_cycle() -> None:
    graph: dict[str, set[str]] = {}
    for consumer, provider in ALLOWED:
        graph.setdefault(consumer, set()).add(provider)

    TopologicalSorter(graph).prepare()  # raises CycleError on any cycle, however long


def test_the_catalog_bridge_is_read_as_retrieval_to_catalog() -> None:
    assert bridge_edges(BRIDGES.read_text())["CatalogSearchableVersions"] == {
        ("retrieval", "catalog")
    }


@pytest.mark.parametrize(
    ("consumer", "provider"),
    [("catalog", "retrieval"), ("retrieval", "ingestion"), ("catalog", "ingestion")],
)
def test_a_bridge_against_the_direction_is_caught(consumer: str, provider: str) -> None:
    source = (
        f"from exactdocs.{consumer}.models import Wanted\n"
        f"from exactdocs.{provider}.ports.driving import Offered\n\n"
        "class Bridge:\n    wanted: Wanted\n    offered: Offered\n"
    )

    (found,) = bridge_edges(source).values()

    assert found == {(consumer, provider)}
    assert not found <= ALLOWED
