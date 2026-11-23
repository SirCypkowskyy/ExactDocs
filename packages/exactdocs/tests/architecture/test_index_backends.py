"""External index backends (#352) are optional extras behind one adapter module each.

Every entry of ``INDEX_BACKENDS`` names an adapter module in ``retrieval/adapters/driven`` that
defines its factories, and an extra that ``pyproject.toml`` declares; the extra's packages are
imported by that module alone (lazily, by ``bootstrap/index_backends.py``), so an install
without the extra, or with it and the backend not configured, never imports them.
"""

import ast
import tomllib
from pathlib import Path

import pytest

from exactdocs.bootstrap.constants import INDEX_BACKENDS
from exactdocs.bootstrap.index_kinds import IndexBackendKind

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
KINDS = list(INDEX_BACKENDS.values())


def _module_path(module: str) -> Path:
    return SRC / Path(*module.split(".")).with_suffix(".py")


def _imported(path: Path) -> set[str]:
    """The top-level packages a module imports (``import a.b`` and ``from a.b import c``: a)."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text("utf-8"))):
        if isinstance(node, ast.Import):
            names |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            names.add(node.module.split(".")[0])
    return names


def _importers(package: str) -> list[Path]:
    return sorted(p for p in SRC.rglob("*.py") if package in _imported(p))


def test_the_scanner_finds_importers() -> None:
    assert _module_path("exactdocs.bootstrap.database") in _importers("sqlalchemy")


@pytest.mark.parametrize("kind", KINDS, ids=[k.name for k in KINDS])
def test_a_backend_has_an_adapter_module_defining_its_factories(kind: IndexBackendKind) -> None:
    path = _module_path(kind.module)
    assert path.is_relative_to(SRC / "exactdocs" / "retrieval" / "adapters" / "driven"), path
    defined = {
        node.name
        for node in ast.parse(path.read_text("utf-8")).body
        if isinstance(node, ast.FunctionDef)
    }
    assert {f for f in (kind.search, kind.vectors) if f} <= defined


@pytest.mark.parametrize("kind", KINDS, ids=[k.name for k in KINDS])
def test_a_backends_extra_is_declared_and_imported_by_its_adapter_alone(
    kind: IndexBackendKind,
) -> None:
    if kind.extra is None:
        assert not kind.packages, "packages come from an extra"
        return
    project = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))["project"]
    assert kind.extra in project["optional-dependencies"], kind.extra
    for package in kind.packages:
        assert _importers(package) in ([], [_module_path(kind.module)]), package
