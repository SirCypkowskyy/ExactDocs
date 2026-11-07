"""The PostgreSQL compose example in the README is the file CI starts (``deploy/``)."""

import re
from pathlib import Path

ROOT = Path(__file__).parents[4]


def test_the_readme_shows_the_compose_file_ci_runs() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    block = r"<!-- {name}: start -->\n```yaml\n(.*?)```\n<!-- {name}: end -->"
    shown = re.search(block.format(name=re.escape("compose.postgres.yaml")), readme, re.DOTALL)

    assert shown is not None, "the README lost its compose.postgres.yaml block"
    assert shown.group(1) == (ROOT / "deploy" / "compose.postgres.yaml").read_text(encoding="utf-8")
