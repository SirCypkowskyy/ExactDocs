"""Architecture rules of the modular monolith, enforced with ArchUnitPython.

See docs/architecture.md for the reasoning behind every rule.
"""

from pathlib import Path

import pytest
from archunitpython import CheckOptions, assert_passes, project_files

ROOT = Path(__file__).resolve().parents[2]
SRC = str(ROOT / "src")
KERNEL_SRC = str(ROOT.parent / "exactdocs-kernel" / "src")
PACKAGE = ROOT / "src" / "exactdocs"

COMPOSITION_ROOT = "bootstrap"
DOMAINS = sorted(
    p.name
    for p in PACKAGE.iterdir()
    if p.is_dir() and (p / "__init__.py").exists() and p.name != COMPOSITION_ROOT
)

# The fixed module set of every domain. Each entry may be a module (`x.py`) or a package (`x/`).
REQUIRED = {"__init__", "models", "dtos", "ports", "use_cases", "adapters", "module"}
OPTIONAL = {"errors", "constants"}

# Inner -> outer. A layer may import only layers that come before it in this list.
LAYERS = ["constants", "errors", "models", "dtos", "ports", "use_cases", "module"]
# Layers are optional per domain (e.g. `errors`) and may be a module or a package.
_ALLOW_EMPTY = CheckOptions(allow_empty_tests=True)
DATABASE_LIBRARIES = ["sqlalchemy*", "alembic*", "aiosqlite*"]
FRAMEWORKS = [
    "fastapi*",
    "fastmcp*",
    "starlette*",
    "uvicorn*",
    "httpx*",
    "dbos*",
    "argon2*",
    # MCP Apps UI (#115): built by the MCP adapters only.
    "prefab_ui*",
    *DATABASE_LIBRARIES,
    # The AI stack (the `[ai]` and `[local]` extras): adapters and bootstrap only, imported once
    # a model is configured (docs/decisions/ai-retrieval.md, "Where the code lives").
    "pydantic_ai*",
    "pydantic_monty*",
    "fastembed*",
    "onnxruntime*",
    "sqlite_vec*",
    "pgvector*",
]


def _path(domain: str, part: str = "") -> str:
    """Glob for a file (``x.py``) or everything under a folder of the domain."""
    base = f"**/exactdocs/{domain}"
    if part.endswith(".py"):
        return f"{base}/{part}"
    return f"{base}/{part}/**" if part else f"{base}/**"  # note: `**/**` would match nothing


def _layer(domain: str, layer: str) -> list[str]:
    # A layer can grow from `models.py` into `models/`; match both shapes.
    return [_path(domain, f"{layer}.py"), _path(domain, layer)]


def test_domains_are_discovered() -> None:
    assert {"catalog", "identity", "retrieval"} <= set(DOMAINS)


@pytest.mark.parametrize("domain", DOMAINS)
def test_domain_has_the_standard_module_set(domain: str) -> None:
    entries = {p.stem for p in (PACKAGE / domain).iterdir() if p.suffix == ".py" or p.is_dir()} - {
        "__pycache__"
    }

    assert entries >= REQUIRED, f"{domain} is missing {sorted(REQUIRED - entries)}"
    assert entries <= REQUIRED | OPTIONAL, (
        f"{domain} has non-standard modules {sorted(entries - REQUIRED - OPTIONAL)}; "
        "put them inside one of the standard modules instead"
    )
    for split in ("ports", "adapters"):
        children = {p.stem for p in (PACKAGE / domain / split).iterdir()}
        assert {"driving", "driven"} <= children, f"{domain}.{split} needs driving + driven"


def test_no_import_cycles() -> None:
    assert_passes(project_files(SRC).should().have_no_cycles())


@pytest.mark.parametrize(
    ("domain", "other"),
    [(d, o) for d in DOMAINS for o in [*DOMAINS, COMPOSITION_ROOT] if o != d],
)
def test_domains_do_not_import_each_other_or_the_composition_root(domain: str, other: str) -> None:
    assert_passes(
        project_files(SRC)
        .in_path(_path(domain))
        .should_not()
        .depend_on_files()
        .in_path(_path(other))
        .because("domains talk only through ports wired in exactdocs.bootstrap")
    )


@pytest.mark.parametrize("domain", DOMAINS)
@pytest.mark.parametrize(
    ("inner", "outer"),
    [(inner, outer) for i, inner in enumerate(LAYERS) for outer in [*LAYERS[i + 1 :], "adapters"]],
)
def test_dependencies_point_inwards(domain: str, inner: str, outer: str) -> None:
    for source in _layer(domain, inner):
        for target in _layer(domain, outer):
            assert_passes(
                project_files(SRC)
                .in_path(source)
                .should_not()
                .depend_on_files()
                .in_path(target)
                .because(f"{inner} is closer to the core than {outer}"),
                _ALLOW_EMPTY,
            )


@pytest.mark.parametrize("domain", DOMAINS)
@pytest.mark.parametrize(("source", "target"), [("driving", "driven"), ("driven", "driving")])
def test_adapters_do_not_use_each_other(domain: str, source: str, target: str) -> None:
    assert_passes(
        project_files(SRC)
        .in_path(_path(domain, f"adapters/{source}"))
        .should_not()
        .depend_on_files()
        .in_path(_path(domain, f"adapters/{target}"))
        .because("adapters meet only through ports")
    )


@pytest.mark.parametrize("domain", DOMAINS)
@pytest.mark.parametrize("side", ["driving", "driven"])
def test_adapters_depend_on_ports_not_on_use_cases(domain: str, side: str) -> None:
    for target in _layer(domain, "use_cases") + _layer(domain, "module"):
        assert_passes(
            project_files(SRC)
            .in_path(_path(domain, f"adapters/{side}"))
            .should_not()
            .depend_on_files()
            .in_path(target)
            .because("adapters know ports (Protocols), never concrete use cases")
        )


@pytest.mark.parametrize("domain", DOMAINS)
@pytest.mark.parametrize("layer", LAYERS)
@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_core_is_framework_free(domain: str, layer: str, framework: str) -> None:
    for source in _layer(domain, layer):
        assert_passes(
            project_files(SRC)
            .in_path(source)
            .should_not()
            .depend_on_external_modules()
            .matching(framework)
            .because("frameworks belong in adapters and bootstrap"),
            _ALLOW_EMPTY,
        )


@pytest.mark.parametrize("domain", DOMAINS)
@pytest.mark.parametrize("library", DATABASE_LIBRARIES)
def test_database_libraries_live_only_in_driven_adapters_and_bootstrap(
    domain: str, library: str
) -> None:
    # The core is covered by `test_core_is_framework_free`; driving adapters are checked here.
    assert_passes(
        project_files(SRC)
        .in_path(_path(domain, "adapters/driving"))
        .should_not()
        .depend_on_external_modules()
        .matching(library)
        .because("persistence belongs to driven adapters; the schema to bootstrap"),
        _ALLOW_EMPTY,
    )


@pytest.mark.parametrize("domain", [domain for domain in DOMAINS if domain != "ingestion"])
def test_dbos_lives_only_in_ingestion_adapters_and_bootstrap(domain: str) -> None:
    # Ingestion's core is covered by `test_core_is_framework_free`; jobs are ingestion's.
    assert_passes(
        project_files(SRC)
        .in_path(_path(domain))
        .should_not()
        .depend_on_external_modules()
        .matching("dbos*")
        .because("durable jobs belong to ingestion's adapters, wired in bootstrap"),
        _ALLOW_EMPTY,
    )


@pytest.mark.parametrize("domain", DOMAINS)
def test_no_domain_imports_cryptography(domain: str) -> None:
    # One secret box serves every domain; each reaches it through its own `SecretBox` port.
    assert_passes(
        project_files(SRC)
        .in_path(_path(domain))
        .should_not()
        .depend_on_external_modules()
        .matching("cryptography*")
        .because("the secret box lives in bootstrap; domains declare a SecretBox port"),
        _ALLOW_EMPTY,
    )


@pytest.mark.parametrize("domain", DOMAINS)
@pytest.mark.parametrize("layer", ["models", "errors"])
def test_domain_model_does_not_depend_on_pydantic(domain: str, layer: str) -> None:
    for source in _layer(domain, layer):
        assert_passes(
            project_files(SRC)
            .in_path(source)
            .should_not()
            .depend_on_external_modules()
            .matching("pydantic*")
            .because("entities are plain dataclasses; validation at the boundary lives in dtos"),
            _ALLOW_EMPTY,
        )


@pytest.mark.parametrize("module", ["exactdocs*", "fastapi*", "fastmcp*", "pydantic*"])
def test_kernel_depends_on_nothing_but_the_standard_library(module: str) -> None:
    assert_passes(
        project_files(KERNEL_SRC)
        .should_not()
        .depend_on_external_modules()
        .matching(module)
        .because("the shared kernel is the stable core every domain builds on")
    )
