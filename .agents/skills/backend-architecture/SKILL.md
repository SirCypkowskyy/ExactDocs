---
name: backend-architecture
description: Use when adding or changing Python code in ExactDocs - a new domain, use case, port, adapter, or cross-domain interaction. Gives the module set, Protocol-based ports & adapters patterns and the wiring steps that keep the architecture tests green.
---

# Backend architecture (modular monolith + hexagonal)

Full reasoning: `docs/architecture.md`. Reference implementation: `packages/exactdocs/src/exactdocs/catalog/`.

## Non-negotiables

- A domain never imports another domain or `bootstrap`. Only `exactdocs_kernel` is shared.
- Ports are `typing.Protocol`. Nothing inherits from a port (no `abc.ABC`, ruff bans it).
- The core (`errors`, `models`, `dtos`, `ports`, `use_cases`, `module`) imports no framework.
  `models`/`errors` don't import Pydantic.
- Driving adapters depend on driving ports; driven adapters implement driven ports. Adapters
  never import `use_cases` or `module`, nor each other.
- Only these names at a domain's top level: `__init__`, `constants`, `errors`, `models`, `dtos`, `ports/`
  (`driving`, `driven`), `use_cases`, `module`, `adapters/` (`driving/`, `driven/`). Any of the
  modules may become a package of the same name when it grows.

## Conventions the tests check (`tests/architecture/test_conventions.py`)

- Constants only in the package's `constants.py` (or `constants/` topic modules re-exported by
  its `__init__`), as `NAME: Final[T] = value` followed by a `"""docstring"""`. `constants`
  imports only the kernel and the standard library.
- Every `@dataclass(frozen=True, slots=True, kw_only=True)`; otherwise a marker with a reason on
  the decorator line: `# conventions: allow-mutable-dataclass|allow-positional|allow-dict -- why`.
- Every function and method, private and nested ones too, has a Google docstring with `Args:`
  for each parameter and `Returns:`/`Yields:` when it returns something; `Raises:` for domain
  errors it raises.
- Every dataclass and pydantic field has an attribute docstring; DTO bases set
  `use_attribute_docstrings=True`, so it becomes the OpenAPI / MCP description.
- Private by default (`_name`); public API re-exported from `__init__.py` / `__all__`.
- There is no baseline and no exemption: `test_conventions.py` fails on any function in
  `packages/*/src` without a complete docstring, and ruff (pydoclint `DOC201`/`DOC501`) fails on
  any docstring anywhere, tests included, that omits a returned value or a raised exception.

## Add a use case to an existing domain

1. `models.py`: new entities/value objects (frozen, slotted, keyword-only dataclasses), invariants in `__post_init__`
   raising errors from `errors.py`.
2. `dtos.py`: query/command + result as frozen Pydantic models; `from_model` classmethods.
3. `ports/driving.py`: `class DoThing(Protocol): async def __call__(self, query: DoThingQuery) -> DoThingResult: ...`
4. `ports/driven.py`: any new needs (`async` methods, domain types in and out).
5. `use_cases.py`: `@dataclass(frozen=True, slots=True, kw_only=True) class DoThingUseCase` with driven ports
   as fields and `async def __call__`.
6. `module.py`: add the field `do_thing: DoThing` and build it in `build(...)`.
7. Adapters: route in `adapters/driving/http.py`, tool in `adapters/driving/mcp.py`
   (read-only tools get `annotations=READ_ONLY`), each taking the driving port as a keyword argument.
8. `bootstrap/http.py` / `bootstrap/mcp.py`: pass `container.<domain>.do_thing` to the adapters.

## Add a domain

```
src/exactdocs/<domain>/
  __init__.py          from exactdocs.<domain>.module import <Domain>Module; __all__ = [...]
  constants.py  errors.py  models.py  dtos.py  use_cases.py  module.py
  ports/__init__.py  ports/driving.py  ports/driven.py
  adapters/__init__.py  adapters/driving/__init__.py  adapters/driven/__init__.py
```

Then build it in `bootstrap/container.py` (pick its driven adapters) and expose it in
`bootstrap/http.py` and `bootstrap/mcp.py`. The architecture tests pick the new folder up
automatically.

## Persist something (SQLite)

See *Persistence* in `docs/architecture.md`: tables prefixed with the domain, an Alembic revision
in `bootstrap/migrations/versions` (`just migration "..."`), a `sqlite.py` driven adapter that
takes the `AsyncEngine`, and a case in the adapter contract test next to the memory adapter.

## One domain needs another

Don't import it. In the **consumer**, declare a driven port in its own words:

```python
# retrieval/ports/driven.py
class SearchableVersions(Protocol):
    async def find(self, library: str, ref: str | None) -> SearchableVersion | None: ...
```

In **bootstrap/bridges.py**, implement it with the provider's *driving* port and wire it in
`container.py`. See `CatalogSearchableVersions`.

## Shared code

Generic, stable, framework-free building blocks (error base classes, `Clock`) go in
`packages/exactdocs-kernel`. Business concepts don't; they belong to a domain. When in doubt,
duplicate a small type rather than couple two domains.

## Patterns we use

- Structural typing: a test double or adapter is any class with the right methods.
- `NewType` ids, `typing.Self` factories (`InMemoryLibraryRepository.of(...)`).
- Explicit composition root; no DI container, no globals, no module-level singletons.
- Domain errors subclass kernel errors; HTTP mapping lives only in `bootstrap/http.py`.
- Python 3.14: no `from __future__ import annotations`, no `TYPE_CHECKING` imports.
