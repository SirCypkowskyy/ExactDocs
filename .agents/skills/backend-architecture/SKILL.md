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
- Only these names at a domain's top level: `__init__`, `errors`, `models`, `dtos`, `ports/`
  (`driving`, `driven`), `use_cases`, `module`, `adapters/` (`driving/`, `driven/`). Any of the
  modules may become a package of the same name when it grows.

## Add a use case to an existing domain

1. `models.py`: new entities/value objects (frozen slotted dataclasses), invariants in `__post_init__`
   raising errors from `errors.py`.
2. `dtos.py`: query/command + result as frozen Pydantic models; `from_model` classmethods.
3. `ports/driving.py`: `class DoThing(Protocol): async def __call__(self, query: DoThingQuery) -> DoThingResult: ...`
4. `ports/driven.py`: any new needs (`async` methods, domain types in and out).
5. `use_cases.py`: `@dataclass(frozen=True, slots=True) class DoThingUseCase` with driven ports
   as fields and `async def __call__`.
6. `module.py`: add the field `do_thing: DoThing` and build it in `build(...)`.
7. Adapters: route in `adapters/driving/http.py`, tool in `adapters/driving/mcp.py`
   (read-only tools get `annotations=READ_ONLY`), each taking the driving port as a keyword argument.
8. `bootstrap/http.py` / `bootstrap/mcp.py`: pass `container.<domain>.do_thing` to the adapters.

## Add a domain

```
src/exactdocs/<domain>/
  __init__.py          from exactdocs.<domain>.module import <Domain>Module; __all__ = [...]
  errors.py  models.py  dtos.py  use_cases.py  module.py
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
class IndexedVersions(Protocol):
    async def is_indexed(self, target: DocTarget) -> bool: ...
```

In **bootstrap/bridges.py**, implement it with the provider's *driving* port and wire it in
`container.py`. See `CatalogIndexedVersions`.

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
