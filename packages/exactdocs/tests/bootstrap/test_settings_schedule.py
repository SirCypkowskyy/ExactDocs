"""``EXACTDOCS_AUTO_SYNC_SCHEDULE`` is checked when the settings are read, with a clear message."""

import pytest
from pydantic import ValidationError

from exactdocs.bootstrap.settings import Settings


@pytest.mark.parametrize("schedule", ["0 * * * * *", "*/5 * * * *", "* * * * * *"])
def test_a_cron_expression_is_accepted(schedule: str) -> None:
    assert Settings(auto_sync_schedule=schedule).auto_sync_schedule == schedule


@pytest.mark.parametrize("schedule", ["", "every minute", "61 * * * * *"])
def test_anything_else_stops_startup_naming_the_variable(schedule: str) -> None:
    with pytest.raises(ValidationError, match="EXACTDOCS_AUTO_SYNC_SCHEDULE"):
        Settings(auto_sync_schedule=schedule)
