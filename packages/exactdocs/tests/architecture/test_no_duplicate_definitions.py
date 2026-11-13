"""No module or class defines the same function or class name twice in ``packages/*/src``.

The later definition silently replaces the earlier one. Ruff's F811 only reports it when the
first definition is unused before it is replaced, so a helper called above its duplicate slips
through (#339). ``@overload`` stubs and ``@<name>.setter``/``.deleter`` are legitimate repeats.
"""

import ast
from collections import Counter
from pathlib import Path

import pytest

PACKAGES = Path(__file__).resolve().parents[3]
# Generated or vendored code that is not written by hand.
EXCLUDED_PARTS = {"_web", "migrations"}
REPEATABLE_DECORATORS = ("overload", ".setter", ".deleter")


def duplicates(source: str) -> list[str]:
    """Return ``<scope>.<name>`` for each name defined more than once in one scope.

    Args:
        source: A module's source code.

    Returns:
        The duplicated names, prefixed with their scope (``<module>`` or the class name).
    """
    tree = ast.parse(source)
    scopes: list[ast.Module | ast.ClassDef] = [tree]
    scopes += [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
    found = []
    for scope in scopes:
        names = Counter(
            node.name
            for node in scope.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and not any(ast.unparse(d).endswith(REPEATABLE_DECORATORS) for d in node.decorator_list)
        )
        label = scope.name if isinstance(scope, ast.ClassDef) else "<module>"
        found += [f"{label}.{name}" for name, count in names.items() if count > 1]
    return found


def test_checker_reports_a_redefined_function_used_before_it_is_replaced() -> None:
    """The case F811 misses: the first definition is called before the second replaces it."""
    source = (
        "def f(): ...\nX = f()\ndef f(): ...\n"
        "class C:\n    def m(self): ...\n    def m(self): ...\n"
    )
    assert duplicates(source) == ["<module>.f", "C.m"]


def test_checker_accepts_overloads_and_property_setters() -> None:
    """``@overload`` stubs and property setters repeat a name on purpose."""
    source = (
        "from typing import overload\n"
        "@overload\ndef f(x: int) -> int: ...\n@overload\ndef f(x: str) -> str: ...\n"
        "def f(x): return x\n"
        "class C:\n    @property\n    def p(self): ...\n    @p.setter\n    def p(self, v): ...\n"
    )
    assert duplicates(source) == []


def _sources() -> list[Path]:
    """List the hand-written source files of every package.

    Returns:
        The ``.py`` files under ``packages/*/src``, generated folders excluded.
    """
    return sorted(
        path
        for path in PACKAGES.glob("*/src/**/*.py")
        if not EXCLUDED_PARTS.intersection(path.parts)
    )


@pytest.mark.parametrize("path", _sources(), ids=lambda p: p.relative_to(PACKAGES).as_posix())
def test_no_duplicate_definitions(path: Path) -> None:
    """Each function and class name is defined once per module or class body.

    Args:
        path: The source file to check.
    """
    assert duplicates(path.read_text(encoding="utf-8")) == []
