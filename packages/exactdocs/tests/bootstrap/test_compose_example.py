"""docs/deployment/ shows the files CI runs from ``deploy/``: compose example, Supabase setup."""

import re
from pathlib import Path

ROOT = Path(__file__).parents[4]


def test_the_deployment_page_shows_the_compose_file_ci_runs() -> None:
    page = (ROOT / "docs" / "deployment" / "postgresql.md").read_text(encoding="utf-8")
    block = r"<!-- {name}: start -->\n```yaml\n(.*?)```\n<!-- {name}: end -->"
    shown = re.search(block.format(name=re.escape("compose.postgres.yaml")), page, re.DOTALL)

    assert shown is not None, "docs/deployment/postgresql.md lost its compose.postgres.yaml block"
    assert shown.group(1) == (ROOT / "deploy" / "compose.postgres.yaml").read_text(encoding="utf-8")


def test_the_deployment_page_shows_the_supabase_setup_ci_runs() -> None:
    page = (ROOT / "docs" / "deployment" / "supabase.md").read_text(encoding="utf-8")
    block = r"<!-- {name}: start -->\n```sql\n(.*?)```\n<!-- {name}: end -->"
    shown = re.search(block.format(name=re.escape("supabase.sql")), page, re.DOTALL)

    assert shown is not None, "docs/deployment/supabase.md lost its supabase.sql block"
    assert shown.group(1) == (ROOT / "deploy" / "supabase.sql").read_text(encoding="utf-8")
