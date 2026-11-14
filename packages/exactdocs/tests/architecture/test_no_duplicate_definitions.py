"""No function or class name is defined twice in a module's or class's direct body.

Covers ``packages/*/src``. The later definition silently replaces the earlier one. Ruff's F811
only reports it when the first definition is unused before it is replaced, so a helper called
above its duplicate slips through (#339).

Only the direct body is scanned, so definitions inside ``if``/``try`` blocks or function bodies
are not checked; that keeps ``TYPE_CHECKING``/``else`` and ``try``/``except ImportError``
fallbacks green. ``@overload`` stubs and ``@<name>.setter``/``.getter``/``.deleter`` on the
same name are legitimate repeats. Repeated ``@<f>.register def _(...)`` singledispatch
implementations are not handled and would be reported as ``<scope>._``.
"""

import ast
from collections import Counter
from pathlib import Path

import pytest

PACKAGES = Path(__file__).resolve().parents[3]
# The built web bundle is generated, not written by hand. The hand-written Alembic revisions
# under ``migrations/`` are scanned: each defines ``upgrade``/``downgrade`` once per file.
EXCLUDED_PARTS = {"_web"}
PROPERTY_ACCESSORS = {"setter", "getter", "deleter"}


def _repeatable(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> bool:
    """Tell whether a decorator marks the definition as a deliberate repeat of its name.

    Args:
        node: The function or class definition.

    Returns:
        True for ``@overload``/``@typing.overload`` and for ``@<name>.setter``/``.getter``/
        ``.deleter`` where ``<name>`` is the definition's own name.
    """
    for d in node.decorator_list:
        if isinstance(d, ast.Name) and d.id == "overload":
            return True
        if isinstance(d, ast.Attribute) and d.attr == "overload":
            return True
        if (
            isinstance(d, ast.Attribute)
            and d.attr in PROPERTY_ACCESSORS
            and isinstance(d.value, ast.Name)
            and d.value.id == node.name
        ):
            return True
    return False


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
            and not _repeatable(node)
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


def test_checker_reports_lookalike_overload_and_foreign_setter() -> None:
    """``@my_overload`` is not ``overload``, and ``@q.setter`` does not make ``p`` a repeat."""
    source = (
        "@my_overload\ndef f(): ...\n@my_overload\ndef f(): ...\n"
        "class C:\n    @property\n    def p(self): ...\n    @q.setter\n    def p(self, v): ...\n"
    )
    assert duplicates(source) == ["<module>.f", "C.p"]


def test_checker_accepts_overloads_and_property_accessors() -> None:
    """``@overload`` stubs and a property's own setter/getter repeat a name on purpose."""
    source = (
        "import typing\nfrom typing import overload\n"
        "@overload\ndef f(x: int) -> int: ...\n@typing.overload\ndef f(x: str) -> str: ...\n"
        "def f(x): return x\n"
        "class C:\n    @property\n    def p(self): ...\n    @p.setter\n    def p(self, v): ...\n"
        "    @p.getter\n    def p(self): ...\n"
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
