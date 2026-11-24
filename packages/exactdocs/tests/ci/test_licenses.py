"""The licences travel with what is published (#533).

Each package's wheel and sdist carry the repository's LICENSE (PEP 639 `license-files`, which
takes no path outside the package, so each package holds a copy), and every third-party README
excerpt among the test fixtures has its source and licence written down.
"""

import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[4]
PACKAGES = ["exactdocs", "exactdocs-kernel"]
READMES = ROOT / "packages" / "exactdocs" / "tests" / "fixtures" / "readmes"


@pytest.mark.parametrize("package", PACKAGES)
def test_each_package_ships_the_repository_license(package: str) -> None:
    directory = ROOT / "packages" / package
    project = tomllib.loads((directory / "pyproject.toml").read_text())["project"]

    assert project["license"] == "Apache-2.0"
    assert project["license-files"] == ["LICENSE"]
    assert (directory / "LICENSE").read_bytes() == (ROOT / "LICENSE").read_bytes()


def test_every_readme_fixture_names_its_source_and_licence() -> None:
    provenance = (READMES / "README.md").read_text(encoding="utf-8")
    fixtures = sorted(p.name for p in READMES.glob("*.md") if p.name != "README.md")

    assert fixtures
    for name in fixtures:
        row = next(
            (line for line in provenance.splitlines() if line.startswith(f"| `{name}` ")), ""
        )
        assert "MIT" in row or "Apache" in row or "BSD" in row, f"{name}: no licence in README.md"
        assert "github.com/" in row, f"{name}: no source in README.md"
