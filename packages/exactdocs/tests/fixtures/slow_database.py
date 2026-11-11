"""A SQLite database whose statements stall for a while, like a lock wait or a stalled disk (#298).

Each connection gets a SQLite progress handler. It runs in aiosqlite's own thread, inside the
statement, so a stalled statement holds its connection's thread the way a slow one does in
production, while the event loop stays free.
"""

import time
from dataclasses import dataclass

from sqlalchemy import Connection, event
from sqlalchemy.engine.interfaces import AdaptedConnection
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.pool import ConnectionPoolEntry

INSTRUCTIONS: int = 1
"""SQLite calls the handler every this many virtual machine steps: even a tiny statement stalls."""
STATEMENT: str = "slow_database.statement"
"""Key of the pool record's ``info`` that holds the SQL its connection runs now."""


@dataclass(slots=True)
class _Running:
    """The statement a connection runs now: SQLAlchemy sets it, the progress handler reads it."""

    sql: str = ""
    """The statement's SQL."""


@dataclass(slots=True, kw_only=True)
class SlowDatabase:
    """Makes statements that run before ``until`` (a ``time.monotonic()``) last until then."""

    until: float = 0.0
    """Monotonic time the stall ends at; in the past, statements run at full speed."""
    only: str = ""
    """Text a statement's SQL must contain to stall; empty, every statement stalls."""

    @classmethod
    def on(cls, engine: AsyncEngine) -> SlowDatabase:
        """Watch an engine's new connections; call it before the engine connects for the first time.

        Args:
            engine: A SQLite engine.

        Returns:
            The switch, off.
        """
        slow = cls()
        event.listen(engine.sync_engine, "connect", slow._install)
        event.listen(engine.sync_engine, "before_cursor_execute", _note_statement)
        return slow

    def stall(self, seconds: float, *, only: str = "") -> None:
        """Make the statements running or starting in the next ``seconds`` last until then.

        Args:
            seconds: How long the stall lasts from now.
            only: Stall only statements whose SQL contains this; every statement when empty.
        """
        self.only = only
        self.until = time.monotonic() + seconds

    def remaining(self) -> float:
        """Tell how long the stall still lasts.

        Returns:
            Seconds, 0 once it is over.
        """
        return max(0.0, self.until - time.monotonic())

    def _install(self, dbapi_connection: AdaptedConnection, record: ConnectionPoolEntry) -> None:
        """Give a new connection the progress handler.

        Args:
            dbapi_connection: SQLAlchemy's adapter of the aiosqlite connection.
            record: The pool record, where the connection's current statement is kept.
        """
        running = record.info.setdefault(STATEMENT, _Running())
        dbapi_connection.run_async(
            lambda driver: driver.set_progress_handler(lambda: self._wait(running), INSTRUCTIONS)
        )

    def _wait(self, running: _Running) -> int:
        """Sleep out the stall, in the connection's thread, if the statement is one to hold.

        Args:
            running: The statement the connection runs.

        Returns:
            0: let the statement go on.
        """
        if self.only in running.sql:
            time.sleep(self.remaining())
        return 0


def _note_statement(
    connection: Connection,
    cursor: object,
    statement: str,
    parameters: object,
    context: object,
    executemany: bool,
) -> None:
    """Record the statement a connection is about to run, for its progress handler.

    Args:
        connection: The connection.
        cursor: Unused.
        statement: The SQL.
        parameters: Unused.
        context: Unused.
        executemany: Unused.
    """
    del cursor, parameters, context, executemany
    running = connection.info.get(STATEMENT)
    if isinstance(running, _Running):
        running.sql = statement
