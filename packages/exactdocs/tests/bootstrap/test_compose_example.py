"""The README shows the files CI runs from ``deploy/``: the compose example, the Supabase setup."""

import re
from pathlib import Path

ROOT = Path(__file__).parents[4]


def test_the_readme_shows_the_compose_file_ci_runs() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    block = r"<!-- {name}: start -->\n```yaml\n(.*?)```\n<!-- {name}: end -->"
    shown = re.search(block.format(name=re.escape("compose.postgres.yaml")), readme, re.DOTALL)

    assert shown is not None, "the README lost its compose.postgres.yaml block"
    assert shown.group(1) == (ROOT / "deploy" / "compose.postgres.yaml").read_text(encoding="utf-8")


def test_the_readme_shows_the_supabase_setup_ci_runs() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    block = r"<!-- {name}: start -->\n```sql\n(.*?)```\n<!-- {name}: end -->"
    shown = re.search(block.format(name=re.escape("supabase.sql")), readme, re.DOTALL)

    assert shown is not None, "the README lost its supabase.sql block"
    assert shown.group(1) == (ROOT / "deploy" / "supabase.sql").read_text(encoding="utf-8")
