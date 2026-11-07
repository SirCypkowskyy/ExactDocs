"""Python conventions that ruff cannot check, enforced with an AST walk over ``packages/*/src``.

See *Python conventions* in docs/architecture.md. Each rule has a "bad code" fixture in
``fixtures/conventions/`` that the checker must report and a "good code" one it must accept.

Rules (the name is printed in every failure, next to ``file:line``):

``constant-outside-constants``
    A module-level constant (an ``UPPER_CASE`` name, or anything annotated ``Final``) is defined
    outside a ``constants.py`` module or a ``constants/`` package.
``constant-not-final``
    A constant is not annotated ``Final[<type>]``.
``constant-without-docstring``
    A constant is not followed by an attribute docstring.
``function-without-docstring``
    A function, method or nested function, public or private, has no docstring.
``docstring-missing-args``
    The docstring does not list every parameter (``self``/``cls`` excluded) under ``Args:``.
``docstring-missing-returns``
    The function returns a value, but its docstring has no ``Returns:`` (``Yields:`` for a
    generator) section. Properties describe the attribute instead and are exempt.
``field-without-docstring``
    A dataclass or pydantic model field is not followed by an attribute docstring.
``model-without-attribute-docstrings``
    A pydantic model does not set ``use_attribute_docstrings=True`` (itself or through a base).
``dataclass-flags``
    A ``@dataclass`` lacks ``frozen=True``, ``slots=True`` or ``kw_only=True`` and its decorator
    carries no ``# conventions: allow-mutable-dataclass|allow-dict|allow-positional -- <reason>``.
``exception-marker-without-reason``
    An exception marker has no reason after ``--``.
"""

import ast
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import NotRequired, TypedDict

import pytest

PACKAGES = Path(__file__).resolve().parents[3]
FIXTURES = Path(__file__).parent / "fixtures" / "conventions"
# Generated or vendored code that is not written by hand.
EXCLUDED_PARTS = {"_web", "migrations"}

CONSTANT_NAME = re.compile(r"^_*[A-Z][A-Z0-9_]*$")
# `# conventions: allow-dict, allow-positional -- reason`; a later `# ...` comment ends the reason.
MARKER = re.compile(
    r"#\s*conventions:\s*(?P<names>[\w\s,-]+?)\s*(?:--\s*(?P<reason>[^#]*))?(?:#.*)?$"
)
# What each missing dataclass flag needs as an exception marker.
FLAG_MARKERS = {
    "frozen": "allow-mutable-dataclass",
    "slots": "allow-dict",
    "kw_only": "allow-positional",
}
DATACLASS_MODULES = {"dataclasses", "pydantic.dataclasses"}
MODEL_BASES = {"BaseModel", "BaseSettings", "RootModel"}
PROPERTY_DECORATORS = {"property", "cached_property", "computed_field"}
NO_VALUE = {"None", "NoReturn", "Never"}
SECTION = re.compile(r"^(?P<indent>\s*)(?P<name>[A-Z][A-Za-z ]*):\s*$")
ARGS_SECTIONS = {"Args", "Arguments"}
RETURNS_SECTIONS = {"Returns", "Return"}
YIELDS_SECTIONS = {"Yields", "Yield"}


@dataclass(frozen=True, slots=True, kw_only=True)
class Violation:
    """One broken rule at one place."""

    path: str
    """File, as given to the checker."""
    line: int
    """1-based line of the offending definition."""
    rule: str
    """Rule name, as listed in the module docstring."""
    message: str
    """What is wrong and how to fix it."""
    subject: str = ""
    """Qualified name of what is wrong (``Class.method``, ``Class.field``); the baseline key."""

    def __str__(self) -> str:
        """Render as ``path:line: rule: message``.

        Returns:
            The violation on one line, the way compilers and linters print them.
        """
        return f"{self.path}:{self.line}: {self.rule}: {self.message}"


class _Where(TypedDict):
    """Where a violation is, as keyword arguments of ``Violation``."""

    path: str
    """File, as given to the checker."""
    line: int
    """1-based line."""
    subject: NotRequired[str]
    """Qualified name of the offending definition."""


def _is_constants_module(path: PurePosixPath) -> bool:
    """Tell whether constants may be defined in ``path``.

    Args:
        path: The module's path.

    Returns:
        True for ``constants.py`` and for any module inside a ``constants/`` package.
    """
    return path.name == "constants.py" or "constants" in path.parts[:-1]


def _name(node: ast.expr) -> str:
    """Last dotted component of a name, attribute or subscripted generic.

    Args:
        node: An annotation, base class or decorator expression.

    Returns:
        ``Final`` for ``typing.Final[int]``, ``BaseModel`` for ``pydantic.BaseModel`` and so on;
        an empty string for anything else.
    """
    match node:
        case ast.Name(id=name) | ast.Attribute(attr=name):
            return name
        case ast.Subscript(value=value) | ast.Call(func=value):
            return _name(value)
        case _:
            return ""


def _is_docstring(node: ast.stmt | None) -> bool:
    """Tell whether a statement is a bare string literal (an attribute docstring).

    Args:
        node: The statement after an assignment, or None at the end of a body.

    Returns:
        True when ``node`` is a string expression statement.
    """
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    )


def _followed_by_docstring(body: list[ast.stmt]) -> Iterator[tuple[ast.stmt, bool]]:
    """Pair each statement of a body with whether the next one is a docstring.

    Args:
        body: A module or class body.

    Yields:
        Each statement and True when an attribute docstring follows it.
    """
    for index, node in enumerate(body):
        following = body[index + 1] if index + 1 < len(body) else None
        yield node, _is_docstring(following)


def _module_bodies(body: list[ast.stmt]) -> Iterator[list[ast.stmt]]:
    """The module body and the bodies of its top-level ``if``/``try``/``with`` blocks.

    Args:
        body: A module body (or a block's body, for the recursion).

    Yields:
        Each statement list whose assignments define module-level names.
    """
    yield body
    for node in body:
        blocks: list[list[ast.stmt]] = []
        match node:
            case ast.If(body=then, orelse=orelse):
                blocks = [then, orelse]
            case ast.Try(body=tried, orelse=orelse, finalbody=final, handlers=handlers):
                blocks = [tried, orelse, final, *(handler.body for handler in handlers)]
            case ast.With(body=inner):
                blocks = [inner]
        for block in blocks:
            yield from _module_bodies(block)


def _assignments(tree: ast.Module) -> Iterator[tuple[ast.stmt, bool, str, bool, bool]]:
    """Module-level assignments to names, one per assigned name.

    ``A, B = 1, 2`` and ``A = B = 1`` yield both names (as untyped), and assignments inside
    top-level ``if``/``try``/``with`` blocks count. Type definitions (``NewType``, ``TypeVar``)
    are not values and are skipped.

    Args:
        tree: The parsed module.

    Yields:
        The statement, whether a docstring follows it, the name, whether it is annotated
        ``Final`` and whether that annotation names the type (``Final[int]``).
    """
    for body in _module_bodies(tree.body):
        for node, documented in _followed_by_docstring(body):
            match node:
                case ast.AnnAssign(target=ast.Name(id=name), annotation=annotation):
                    final = _name(annotation) == "Final"
                    typed = final and isinstance(annotation, ast.Subscript)
                    yield node, documented, name, final, typed
                case ast.Assign(value=ast.Call(func=func)) if _name(func) in {"NewType", "TypeVar"}:
                    continue
                case ast.Assign(targets=targets):
                    for target in targets:
                        names = target.elts if isinstance(target, ast.Tuple) else [target]
                        for each in names:
                            if isinstance(each, ast.Name):
                                yield node, documented, each.id, False, False


def _check_constants(path: PurePosixPath, tree: ast.Module) -> Iterator[Violation]:
    """Constants live in constants modules, are ``Final[...]`` and have a docstring.

    Args:
        path: The module's path.
        tree: The parsed module.

    Yields:
        Every broken constants rule.
    """
    in_constants = _is_constants_module(path)
    for node, documented, name, final, typed in _assignments(tree):
        if name == "__all__" or not (final or in_constants or CONSTANT_NAME.match(name)):
            continue
        where: _Where = {"path": str(path), "line": node.lineno}
        if not in_constants:
            yield Violation(
                **where,
                rule="constant-outside-constants",
                message=f"move `{name}` to the package's `constants.py` (or `constants/`)",
            )
        if not typed:
            yield Violation(
                **where,
                rule="constant-not-final",
                message=f"annotate `{name}` as `Final[<type>]`",
            )
        if not documented:
            yield Violation(
                **where,
                rule="constant-without-docstring",
                message=f'add a """docstring""" on the line after `{name}`',
            )


def _decorators(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> set[str]:
    """Names of a definition's decorators.

    Args:
        node: A function or class definition.

    Returns:
        ``{"property", "setter", ...}``: the last dotted component of each decorator.
    """
    return {_name(decorator) for decorator in node.decorator_list}


def _sections(docstring: str) -> dict[str, list[str]]:
    """Split a Google-style docstring into its sections.

    Args:
        docstring: The cleaned docstring (``ast.get_docstring``).

    Returns:
        Section name (``Args``, ``Returns``...) to the lines under it.
    """
    sections: dict[str, list[str]] = {}
    current: list[str] | None = None
    for line in docstring.splitlines():
        header = SECTION.match(line)
        if header and not header["indent"]:
            current = sections.setdefault(header["name"], [])
        elif current is not None and line and not line[0].isspace():
            current = None  # free text after the sections
        elif current is not None:
            current.append(line)
    return sections


def _documented_args(lines: list[str]) -> set[str]:
    """Parameter names listed in an ``Args:`` section.

    Args:
        lines: The section's lines, still indented.

    Returns:
        The names at the section's first indentation level, without ``*``/``**``.
    """
    entries = [line for line in lines if line.strip()]
    if not entries:
        return set()
    indent = min(len(line) - len(line.lstrip()) for line in entries)
    names = set()
    for line in entries:
        if len(line) - len(line.lstrip()) == indent:
            entry = re.match(r"\**(\w+)\s*(\([^)]*\))?\s*:", line.strip())
            if entry:
                names.add(entry[1])
    return names


def _own_nodes(function: ast.FunctionDef | ast.AsyncFunctionDef) -> Iterator[ast.AST]:
    """Walk a function body without descending into nested functions, classes or lambdas.

    Args:
        function: The function to walk.

    Yields:
        Every node that belongs to this function's own code.
    """
    stack: list[ast.AST] = list(function.body)
    while stack:
        node = stack.pop()
        yield node
        stack.extend(
            child
            for child in ast.iter_child_nodes(node)
            if not isinstance(
                child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
            )
        )


def _returns_value(function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Tell whether a function hands a value back to its caller.

    Args:
        function: The function definition.

    Returns:
        False for a ``-> None``/``NoReturn``/``Never`` annotation; with no annotation, whether
        a ``return`` statement carries a value.
    """
    if function.returns is not None:
        annotation = function.returns
        if isinstance(annotation, ast.Constant) and annotation.value is None:
            return False
        if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
            return annotation.value.strip() not in NO_VALUE  # a string annotation, `-> "None"`
        return _name(annotation) not in NO_VALUE
    return any(
        isinstance(node, ast.Return) and node.value is not None for node in _own_nodes(function)
    )


def _is_generator(function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Tell whether a function is a generator.

    Args:
        function: The function definition.

    Returns:
        True when its own body contains ``yield`` or ``yield from``.
    """
    return any(isinstance(node, (ast.Yield, ast.YieldFrom)) for node in _own_nodes(function))


def _parameters(function: ast.FunctionDef | ast.AsyncFunctionDef, *, method: bool) -> list[str]:
    """Parameters a docstring must document.

    Args:
        function: The function definition.
        method: Whether it is defined directly in a class body.

    Returns:
        Every parameter name, without ``self``/``cls`` of a method and the ``_`` placeholder.
    """
    arguments = function.args
    positional = [*arguments.posonlyargs, *arguments.args]
    if method and "staticmethod" not in _decorators(function) and positional:
        positional = positional[1:]
    every = [*positional, arguments.vararg, *arguments.kwonlyargs, arguments.kwarg]
    return [arg.arg for arg in every if arg is not None and arg.arg != "_"]


def _check_function(
    path: PurePosixPath,
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    method: bool,
    qualname: str,
) -> Iterator[Violation]:
    """A function has a docstring that documents its parameters and its result.

    Args:
        path: The module's path.
        function: The function definition.
        method: Whether it is defined directly in a class body.
        qualname: Its qualified name in the module (``Class.method``, ``outer.inner``).

    Yields:
        Every broken docstring rule.
    """
    decorators = _decorators(function)
    if "overload" in decorators:
        return
    where: _Where = {"path": str(path), "line": function.lineno, "subject": qualname}
    docstring = ast.get_docstring(function)
    if docstring is None:
        yield Violation(
            **where,
            rule="function-without-docstring",
            message=f"document `{function.name}` (Google style; private functions too)",
        )
        return
    sections = _sections(docstring)
    expected = _parameters(function, method=method)
    documented = set().union(*(_documented_args(sections.get(s, [])) for s in ARGS_SECTIONS))
    missing = [name for name in expected if name not in documented]
    if missing:
        yield Violation(
            **where,
            rule="docstring-missing-args",
            message=f"`{function.name}`: list {', '.join(missing)} under `Args:`",
        )
    if decorators & PROPERTY_DECORATORS or decorators & {"setter", "deleter"}:
        return
    if not _returns_value(function):
        return
    generator = _is_generator(function)
    wanted = YIELDS_SECTIONS if generator else RETURNS_SECTIONS
    if not wanted & sections.keys():
        yield Violation(
            **where,
            rule="docstring-missing-returns",
            message=(
                f"`{function.name}`: describe the result under "
                f"`{'Yields' if generator else 'Returns'}:`"
            ),
        )


def _dataclass_names(tree: ast.Module) -> set[str]:
    """Names a module uses for ``dataclass``, aliases included.

    Args:
        tree: The parsed module.

    Returns:
        ``dataclass`` and every ``from dataclasses import dataclass as <alias>`` (pydantic's too).
    """
    return {"dataclass"} | {
        alias.asname
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module in DATACLASS_MODULES
        for alias in node.names
        if alias.name == "dataclass" and alias.asname
    }


def _dataclass_decorator(node: ast.ClassDef, names: set[str]) -> ast.expr | None:
    """Find a class's ``@dataclass`` decorator.

    Args:
        node: The class definition.
        names: What the module calls ``dataclass`` (see ``_dataclass_names``).

    Returns:
        The decorator expression, or None for a class that is not a dataclass.
    """
    return next((d for d in node.decorator_list if _name(d) in names), None)


def _markers(lines: list[str], decorator: ast.expr) -> dict[str, str]:
    """Exception markers in the comments of a decorator's lines.

    Args:
        lines: The module's source lines.
        decorator: The decorator expression (may span several lines).

    Returns:
        Marker name (``allow-dict``...) to its reason (empty when missing).
    """
    found: dict[str, str] = {}
    end = decorator.end_lineno or decorator.lineno
    for line in lines[decorator.lineno - 1 : end]:
        if "#" not in line:
            continue
        marker = MARKER.search(line[line.index("#") :])
        if marker:
            reason = (marker["reason"] or "").strip()
            for name in marker["names"].split(","):
                found[name.strip()] = reason
    return found


def _check_dataclass(
    path: PurePosixPath, lines: list[str], node: ast.ClassDef, decorator: ast.expr
) -> Iterator[Violation]:
    """A dataclass is frozen, slotted and keyword-only, or says why not.

    Args:
        path: The module's path.
        lines: The module's source lines.
        node: The class definition.
        decorator: Its ``@dataclass`` decorator.

    Yields:
        Every broken dataclass rule.
    """
    flags = {
        keyword.arg: isinstance(keyword.value, ast.Constant) and keyword.value.value is True
        for keyword in (decorator.keywords if isinstance(decorator, ast.Call) else [])
    }
    markers = _markers(lines, decorator)
    where: _Where = {"path": str(path), "line": decorator.lineno}
    for name, reason in markers.items():
        if not reason:
            yield Violation(
                **where,
                rule="exception-marker-without-reason",
                message=f"`{name}` on `{node.name}` needs a reason: `# conventions: {name} -- why`",
            )
    missing = [
        f"{flag}=True"
        for flag, marker in FLAG_MARKERS.items()
        if not flags.get(flag) and marker not in markers
    ]
    if missing:
        yield Violation(
            **where,
            rule="dataclass-flags",
            message=(
                f"`{node.name}`: add {', '.join(missing)}, or mark the decorator line with "
                "`# conventions: allow-mutable-dataclass|allow-dict|allow-positional -- <reason>`"
            ),
        )


def _sets_attribute_docstrings(node: ast.ClassDef) -> bool:
    """Tell whether a pydantic model's own ``model_config`` sets ``use_attribute_docstrings``.

    Args:
        node: The class definition.

    Returns:
        True when ``model_config = ConfigDict(..., use_attribute_docstrings=True)`` is in the body.
    """
    for statement in node.body:
        match statement:
            case ast.Assign(targets=[ast.Name(id="model_config")], value=ast.Call() as config) | (
                ast.AnnAssign(target=ast.Name(id="model_config"), value=ast.Call() as config)
            ):
                return any(
                    keyword.arg == "use_attribute_docstrings"
                    and isinstance(keyword.value, ast.Constant)
                    and keyword.value.value is True
                    for keyword in config.keywords
                )
    return False


def _check_fields(path: PurePosixPath, node: ast.ClassDef, qualname: str) -> Iterator[Violation]:
    """Every field of a dataclass or pydantic model has an attribute docstring.

    Args:
        path: The module's path.
        node: The class definition.
        qualname: The class's qualified name in the module.

    Yields:
        One violation per undocumented field.
    """
    for statement, documented in _followed_by_docstring(node.body):
        match statement:
            case ast.AnnAssign(target=ast.Name(id=name), annotation=annotation):
                if name == "model_config" or _name(annotation) == "ClassVar" or documented:
                    continue
                yield Violation(
                    path=str(path),
                    line=statement.lineno,
                    rule="field-without-docstring",
                    message=f'`{node.name}.{name}`: add a """docstring""" on the line after it',
                    subject=f"{qualname}.{name}",
                )


@dataclass(frozen=True, slots=True, kw_only=True)
class _Module:
    """A parsed source file."""

    path: PurePosixPath
    """Path printed in violations."""
    source: str
    """The file's text."""
    tree: ast.Module
    """The parsed file."""


def _dotted(path: PurePosixPath) -> str:
    """Import name of a module from its path.

    Args:
        path: ``packages/<dist>/src/<package>/.../<module>.py``, or a bare fixture file name.

    Returns:
        ``exactdocs.catalog.dtos`` for ``.../src/exactdocs/catalog/dtos.py``; a package's
        ``__init__.py`` is the package itself.
    """
    parts = list(path.with_suffix("").parts)
    if "src" in parts:
        parts = parts[parts.index("src") + 1 :]
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


type _ClassKey = tuple[str, str]
"""A class by module import name and class name."""


def _index(
    modules: list[_Module],
) -> tuple[dict[_ClassKey, ast.ClassDef], dict[_ClassKey, _ClassKey]]:
    """Index the classes of a code base and the names its modules import.

    Args:
        modules: Every parsed module of the code base.

    Returns:
        Every class by key, and every ``from x import y [as z]`` as ``(module, z) -> (x, y)``.
    """
    classes: dict[_ClassKey, ast.ClassDef] = {}
    imported: dict[_ClassKey, _ClassKey] = {}
    for module in modules:
        name = _dotted(module.path)
        for node in ast.walk(module.tree):
            if isinstance(node, ast.ClassDef):
                classes.setdefault((name, node.name), node)
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                for alias in node.names:
                    imported[name, alias.asname or alias.name] = (node.module, alias.name)
    return classes, imported


def _resolve(
    key: _ClassKey, classes: dict[_ClassKey, ast.ClassDef], imported: dict[_ClassKey, _ClassKey]
) -> _ClassKey:
    """Follow imports (and re-exports) to where a name is defined.

    Args:
        key: A name as seen from a module.
        classes: Every class of the code base.
        imported: Every imported name of the code base.

    Returns:
        The key of the defining module, or the last key reached when it is not a known class.
    """
    seen = set()
    while key in imported and key not in classes and key not in seen:
        seen.add(key)
        key = imported[key]
    return key


def _models(modules: list[_Module]) -> tuple[set[_ClassKey], set[_ClassKey]]:
    """Find the pydantic models of a code base, following bases through imports.

    A base resolves to a class of the same module or to the class an ``import from`` names
    (through re-exports in ``__init__.py``); ``BaseModel``, ``BaseSettings`` and ``RootModel``
    are the roots.

    Args:
        modules: Every parsed module of the code base.

    Returns:
        The models, and those that get ``use_attribute_docstrings`` from their own config or a
        base.
    """
    classes, imported = _index(modules)
    bases = {
        key: [
            (_name(base), _resolve((key[0], _name(base)), classes, imported)) for base in node.bases
        ]
        for key, node in classes.items()
    }
    models: set[_ClassKey] = set()
    configured: set[_ClassKey] = set()
    changed = True
    while changed:
        changed = False
        for key, node in classes.items():
            parents = {target for _, target in bases[key]}
            is_root = any(
                name in MODEL_BASES and target not in classes for name, target in bases[key]
            )
            if key not in models and (is_root or parents & models):
                models.add(key)
                changed = True
            if (
                key in models
                and key not in configured
                and (_sets_attribute_docstrings(node) or parents & configured)
            ):
                configured.add(key)
                changed = True
    return models, configured


def check(modules: list[_Module]) -> list[Violation]:
    """Run every rule over a code base.

    Args:
        modules: Every parsed module of the code base (pydantic models are resolved across them).

    Returns:
        The violations, ordered by path and line.
    """
    models, configured = _models(modules)
    found: list[Violation] = []
    for module in modules:
        lines = module.source.splitlines()
        found.extend(_check_constants(module.path, module.tree))
        dataclass_names = _dataclass_names(module.tree)
        for function, method, qualname in _functions(module.tree, in_class=False, prefix=""):
            found.extend(_check_function(module.path, function, method=method, qualname=qualname))
        dotted = _dotted(module.path)
        for node, qualname in _classes(module.tree, prefix=""):
            key = (dotted, node.name)
            decorator = _dataclass_decorator(node, dataclass_names)
            if decorator is not None:
                found.extend(_check_dataclass(module.path, lines, node, decorator))
            if decorator is not None or key in models:
                found.extend(_check_fields(module.path, node, qualname))
            if key in models and key not in configured:
                found.append(
                    Violation(
                        path=str(module.path),
                        line=node.lineno,
                        rule="model-without-attribute-docstrings",
                        message=(
                            f"`{node.name}`: set `use_attribute_docstrings=True` in its "
                            "`model_config` (or inherit it) so field docstrings reach the schemas"
                        ),
                    )
                )
    return sorted(found, key=lambda v: (v.path, v.line, v.rule))


def _functions(
    node: ast.AST, *, in_class: bool, prefix: str
) -> Iterator[tuple[ast.FunctionDef | ast.AsyncFunctionDef, bool, str]]:
    """Every function defined under a node, at any depth.

    Args:
        node: A module, class, function or statement.
        in_class: Whether ``node`` is (inside the statements of) a class body.
        prefix: Qualified name of ``node``'s scope plus ``.`` (empty for the module).

    Yields:
        Each function, whether it is a method (defined in a class body) and its qualified name.
    """
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield child, in_class, prefix + child.name
            yield from _functions(child, in_class=False, prefix=f"{prefix}{child.name}.")
        elif isinstance(child, ast.ClassDef):
            yield from _functions(child, in_class=True, prefix=f"{prefix}{child.name}.")
        else:
            yield from _functions(child, in_class=in_class, prefix=prefix)


def _classes(node: ast.AST, *, prefix: str) -> Iterator[tuple[ast.ClassDef, str]]:
    """Every class defined under a node, at any depth.

    Args:
        node: A module, class, function or statement.
        prefix: Qualified name of ``node``'s scope plus ``.`` (empty for the module).

    Yields:
        Each class and its qualified name.
    """
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.ClassDef):
            yield child, prefix + child.name
            yield from _classes(child, prefix=f"{prefix}{child.name}.")
        elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield from _classes(child, prefix=f"{prefix}{child.name}.")
        else:
            yield from _classes(child, prefix=prefix)


def parse(path: PurePosixPath, source: str) -> _Module:
    """Parse one file for ``check``.

    Args:
        path: The path printed in violations; it also decides whether it is a constants module.
        source: The file's text.

    Returns:
        The parsed module.
    """
    return _Module(path=path, source=source, tree=ast.parse(source, filename=str(path)))


def _sources() -> Iterable[Path]:
    """Every hand-written Python file under ``packages/*/src``.

    Returns:
        The files, sorted.
    """
    return sorted(
        file
        for file in PACKAGES.glob("*/src/**/*.py")
        if not EXCLUDED_PARTS & set(file.relative_to(PACKAGES).parts)
    )


# ---------------------------------------------------------------- the code base


# Docstrings that existing code still lacks, one `<path> <qualified name> <rule>` per line. New
# code gets no entry: the list only shrinks (an entry that no longer fails must be deleted), and
# only the docstring rules may appear in it. Emptying it is tracked in its own issue.
BASELINE = Path(__file__).parent / "conventions_baseline.txt"
# The most entries the baseline may hold. Lower it when you delete lines; never raise it.
BASELINE_CEILING = 3362
BASELINE_RULES = {
    "function-without-docstring",
    "docstring-missing-args",
    "docstring-missing-returns",
    "field-without-docstring",
}


def _key(violation: Violation) -> str:
    """Baseline key of a violation: independent of line numbers.

    Args:
        violation: The violation.

    Returns:
        ``<path> <qualified name> <rule>``.
    """
    return f"{violation.path} {violation.subject} {violation.rule}"


def _baseline() -> set[str]:
    """Read the baseline.

    Returns:
        Its keys (comments and blank lines skipped).
    """
    lines = BASELINE.read_text().splitlines() if BASELINE.exists() else []
    return {line.strip() for line in lines if line.strip() and not line.startswith("#")}


def _code_base() -> list[Violation]:
    """Check every source file under ``packages/*/src``.

    Returns:
        The violations.
    """
    modules = [
        parse(PurePosixPath(file.relative_to(PACKAGES.parent).as_posix()), file.read_text())
        for file in _sources()
    ]
    assert len(modules) > 50, "the checker found no sources; is PACKAGES right?"
    return check(modules)


def test_the_code_base_follows_the_conventions() -> None:
    known = _baseline()
    violations = [v for v in _code_base() if _key(v) not in known]
    assert not violations, (
        f"{len(violations)} convention violation(s) (docs/architecture.md, Python conventions):\n"
        + "\n".join(map(str, violations))
    )


def test_the_baseline_only_shrinks() -> None:
    known = _baseline()
    assert {key.rsplit(" ", 1)[-1] for key in known} <= BASELINE_RULES
    assert len(known) <= BASELINE_CEILING, "new code must follow the conventions, not the baseline"
    stale = known - {_key(v) for v in _code_base()}
    assert not stale, f"fixed, now remove them from {BASELINE.name}: {sorted(stale)}"


# ---------------------------------------------------------------- each rule, on fixtures


def _check_fixture(name: str, *, as_path: str | None = None) -> list[str]:
    """Check one fixture file, optionally as if it lived at another path.

    Args:
        name: File name in ``fixtures/conventions/``.
        as_path: Path to check it as (e.g. ``pkg/constants.py``); the file name by default.

    Returns:
        ``rule@line`` for every violation.
    """
    source = (FIXTURES / name).read_text()
    module = parse(PurePosixPath(as_path or name), source)
    return [f"{v.rule}@{v.line}" for v in check([module])]


def _lines_marked(name: str, rule: str) -> list[str]:
    """Lines a fixture marks as expected violations with ``# expect: <rule>``.

    Args:
        name: File name in ``fixtures/conventions/``.
        rule: The rule name.

    Returns:
        ``rule@line`` for every line carrying the marker. A marker on a docstring-less ``def``
        line points at the definition itself.
    """
    lines = (FIXTURES / name).read_text().splitlines()
    return [
        f"{rule}@{number}"
        for number, line in enumerate(lines, start=1)
        if re.search(rf"#.*\bexpect: [\w, -]*\b{re.escape(rule)}\b", line)
    ]


BAD = [
    ("constant_outside_constants.py", None, "constant-outside-constants"),
    ("constant_not_final.py", "pkg/constants.py", "constant-not-final"),
    ("constant_without_docstring.py", "pkg/constants/_limits.py", "constant-without-docstring"),
    ("function_without_docstring.py", None, "function-without-docstring"),
    ("docstring_missing_args.py", None, "docstring-missing-args"),
    ("docstring_missing_returns.py", None, "docstring-missing-returns"),
    ("field_without_docstring.py", None, "field-without-docstring"),
    ("model_without_attribute_docstrings.py", None, "model-without-attribute-docstrings"),
    ("dataclass_flags.py", None, "dataclass-flags"),
    ("marker_without_reason.py", None, "exception-marker-without-reason"),
]


@pytest.mark.parametrize(("name", "as_path", "rule"), BAD, ids=[rule for *_, rule in BAD])
def test_bad_code_is_reported(name: str, as_path: str | None, rule: str) -> None:
    expected = _lines_marked(name, rule)
    assert expected, f"{name} marks no line with `# expect: {rule}`"
    reported = {v for v in _check_fixture(name, as_path=as_path) if v.startswith(f"{rule}@")}
    assert sorted(reported) == sorted(expected)  # one per line, however many names it assigns


@pytest.mark.parametrize(
    ("name", "as_path"),
    [("good_module.py", None), ("good_constants.py", "pkg/constants/_limits.py")],
)
def test_good_code_passes(name: str, as_path: str | None) -> None:
    assert _check_fixture(name, as_path=as_path) == []


def test_a_violation_names_file_line_and_rule() -> None:
    module = parse(PurePosixPath("pkg/settings.py"), 'LIMIT: Final[int] = 3\n"""Limit."""\n')
    expected = (
        "pkg/settings.py:1: constant-outside-constants: "
        "move `LIMIT` to the package's `constants.py` (or `constants/`)"
    )
    assert [str(v) for v in check([module])] == [expected]
