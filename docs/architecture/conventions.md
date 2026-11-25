# Python conventions

!!! abstract "TL;DR"

    - Ports are `Protocol`s, never ABCs; everything is a frozen, slotted, keyword-only dataclass
      unless a marked comment says why not.
    - Constants live in `constants.py`, typed `Final` and documented. Everything else is private
      unless re-exported.
    - Every function, field and MCP tool is documented in Google style, and a checker enforces it.
    - The rules are enforced by tests, ruff, ty and fallow ([What enforces it](#what-enforces-it)).

## Rules

- **`Protocol`, not ABC.** Ports are structural. Adapters and use cases never inherit from them;
  `ty` checks conformance where they are wired (`CatalogModule.build(repository=...)`).
  Importing `abc.ABC` is banned by ruff. The only inheritance in the codebase is exceptions.
- **Immutable by default.** `@dataclass(frozen=True, slots=True, kw_only=True)` for entities,
  value objects, use cases, modules and adapters; `ConfigDict(frozen=True, extra="forbid")` for
  DTOs. A dataclass that cannot follow it says why on its decorator line, with a non-empty reason
  (several markers are comma-separated):

    | Marker | Drops | Example |
    |---|---|---|
    | `# conventions: allow-mutable-dataclass -- <reason>` | `frozen` | |
    | `allow-positional` | `kw_only` | a one-field value object built like a conversion,<br/>Starlette middleware |
    | `allow-dict` | `slots` | |
- **Constants in `constants.py`.** A module-level constant (an `UPPER_CASE` name, or anything
  `Final`) lives only in its package's `constants.py`, or in a `constants/` package whose
  `__init__.py` re-exports the public ones from private topic modules (`constants/_git.py`, see
  `ingestion`).
    - Each is typed `Final[<type>]` and followed by an attribute docstring:

        ```python
        SESSION_IDLE: Final[timedelta] = timedelta(days=7)
        """Idle time after which a web session expires."""
        ```

    - `constants` is a domain's innermost layer: it imports only the kernel and the standard
      library, so a value that needs a domain type is keyed by the enum's values (`"queued"`, not
      `JobState.QUEUED`) or becomes a method.
    - Module-level framework objects (SQLAlchemy tables and clauses, a `TypeAdapter`, a parser, a
      lock) are not constants: they stay with the adapter that uses them and are named in lower
      case.
    - Lower case is reserved for such objects. A fixed value (a number, a string, a pattern, a set
      or mapping of literals) is a constant whatever its name, and the checker only sees it when it
      is `UPPER_CASE` or `Final`, so write it that way.
    - Enum members and `__all__` are not constants.
    - A chained assignment (`A = B = 1`) and an assignment in a module-level `if`/`try`/`with`
      block define constants too.
- **Private by default.** A module, function, class or constant that is not part of its package's
  public API is private (`_name`); what other packages use is re-exported by the package's
  `__init__.py` and listed in `__all__`. Within a domain, a private name may be imported from the
  module that owns it (a private constant from `constants`).
- **Docstrings everywhere, Google style.** Every function, method and nested function has one,
  private ones included (ruff's own rules skip them). It lists every parameter under `Args:`
  (`self`/`cls` excluded), the result under `Returns:` (`Yields:` for a generator; a property
  describes the attribute instead) and raised domain errors under `Raises:`.
- **MCP tool descriptions come from a constant.** FastMCP publishes a tool function's docstring
  as the tool's description, `Args:` and `Returns:` included. So a new tool passes
  `description=` from a `Final` string in its domain's `constants.py` (written for the agent that
  picks the tool) and keeps a full Google docstring on the function, as `article_outline` does.
  The conventions test fails on any undocumented tool function.
- **Field docstrings.** Every dataclass field and every pydantic field has an attribute docstring
  on the line after it. Pydantic models set `use_attribute_docstrings=True` (the domains' `_Dto`
  bases do), so the docstring is the field's description in OpenAPI and the MCP tool schemas;
  `Field(description=...)` is only for descriptions shared through a constant.
- **Use cases are callables.** `await catalog.list_libraries()` reads like the port name, and any
  `async def` with the same signature is a valid test double.
- **Explicit composition root, no DI container.** `bootstrap/container.py` builds everything
  once, in plain code. Tests build modules directly with in-memory adapters.
- **Python 3.14 idioms.** Lazy annotations (PEP 649, no `from __future__` and no
  `TYPE_CHECKING` blocks), `type` aliases (PEP 695), `typing.Self`, `NewType` for identifiers.
- **Errors.** Domains raise kernel error subclasses (`NotFoundError`...). The HTTP adapter maps
  them to status codes in one place (`bootstrap/http.py`); MCP returns them as tool errors.
- **Async all the way.** Ports are `async`; synchronous libraries are wrapped in adapters.

## What enforces it

| Rule | Enforced by |
|---|---|
| Domain isolation, layer direction, adapter rules, framework-free core,<br/>no cycles, kernel purity | ArchUnitPython,<br/>`packages/exactdocs/tests/architecture/test_architecture.py` |
| Fixed module set per domain, driving/driven split | same file (filesystem check) |
| Bridges point one way: retrieval to catalog,<br/>ingestion to catalog / retrieval | `test_bridge_direction.py` |
| No domain imports `cryptography` (the secret box is bootstrap's) | `test_architecture.py` |
| No `abc.ABC`, no relative imports, every ruff rule incl. preview,<br/>Google docstrings that document every returned value and raised exception | ruff[^ruff] |
| Constants placement, `Final` and docstrings; docstrings on every function<br/>with complete `Args:` / `Returns:`; field docstrings; `use_attribute_docstrings`;<br/>dataclass flags and exception markers | `test_conventions.py`[^conventions] |
| Protocol conformance, types | ty |
| Web: features don't import each other; `shared` imports no feature;<br/>routes use feature public APIs | fallow (`web/.fallowrc.json`) + Biome `noRestrictedImports` |

[^ruff]: `select = ["ALL"]`, `preview = true`, pydocstyle `google`, pydoclint `DOC201` / `DOC501`
    on `packages/*/src`, `deploy/` and `evals/`. Tests and features are exempt from `D` and `DOC`.

[^conventions]: An AST checker over `packages/*/src`, with a bad and a good fixture per rule. Every
    function must be documented.
