"""What ``open_database`` checks in a Supabase URL, before any connection is made (#244)."""

import logging

import pytest

from exactdocs.bootstrap.database import StartupError, open_database
from exactdocs.bootstrap.settings import Settings

KEY = "supabase-url-tests-secret-key-0123456789ab"


def _open(url: str) -> None:
    open_database(Settings(database_url=url, secret_key=KEY))


@pytest.mark.parametrize(
    "url",
    [
        # Supavisor, the shared pooler: transaction mode on 6543.
        "postgresql://postgres.abcdefghijklmnop:secret@aws-0-eu-central-1.pooler.supabase.com:6543/postgres",
        # The dedicated pooler (PgBouncer) on the project's own host: transaction mode only.
        "postgresql://postgres:secret@db.abcdefghijklmnop.supabase.co:6543/postgres?sslmode=require",
    ],
)
def test_the_transaction_mode_pooler_is_refused(url: str) -> None:
    with pytest.raises(StartupError) as refused:
        _open(url)

    message = str(refused.value)
    assert "transaction mode" in message
    assert "port 5432" in message
    assert "direct connection" in message
    assert "secret" not in message  # never echoes the password


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://postgres.abcdefghijklmnop:p@aws-0-eu-central-1.pooler.supabase.com:5432/postgres?sslmode=require",
        "postgresql://postgres:p@db.abcdefghijklmnop.supabase.co:5432/postgres?sslmode=verify-full",
        "postgresql://postgres:p@db.abcdefghijklmnop.supabase.co/postgres?sslmode=require",
        # Port 6543 elsewhere is just a port.
        "postgresql://exactdocs:p@db.example.com:6543/exactdocs",
    ],
)
def test_a_session_on_supabase_or_any_port_elsewhere_is_accepted(
    url: str, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING):
        _open(url)

    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


@pytest.mark.parametrize("query", ["", "?sslmode=prefer", "?sslmode=disable"])
def test_supabase_without_sslmode_require_is_warned_about(
    query: str, caplog: pytest.LogCaptureFixture
) -> None:
    url = f"postgresql://postgres:secret@db.abcdefghijklmnop.supabase.co:5432/postgres{query}"

    with caplog.at_level(logging.WARNING):
        _open(url)

    (warning,) = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert "sslmode=require" in warning.getMessage()
    assert "secret" not in warning.getMessage()
