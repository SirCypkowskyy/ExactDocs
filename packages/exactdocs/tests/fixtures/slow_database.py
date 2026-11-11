"""A SQLite database whose statements stall for a while, like a lock wait or a stalled disk (#298).

Each connection gets a SQLite progress handler. It runs in aiosqlite's own thread, inside the
statement, so a stalled statement holds its connection's thread the way a slow one does in
production, while the event loop stays free.
"""

import time
from dataclasses import dataclass

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.util.concurrency import await_

INSTRUCTIONS: int = 1
"""SQLite calls the handler every this many virtual machine steps: even a tiny statement stalls."""


@dataclass(slots=True, kw_only=True)
class SlowDatabase:
    """Makes every statement that runs before ``until`` (a ``time.monotonic()``) last until then."""

    until: float = 0.0
    """Monotonic time the stall ends at; in the past, statements run at full speed."""

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
        return slow

    def stall(self, seconds: float) -> None:
        """Make the statements running or starting in the next ``seconds`` last until then.

        Args:
            seconds: How long the stall lasts from now.
        """
        self.until = time.monotonic() + seconds

    def remaining(self) -> float:
        """Tell how long the stall still lasts.

        Returns:
            Seconds, 0 once it is over.
        """
        return max(0.0, self.until - time.monotonic())

    def _install(self, dbapi_connection: object, record: object) -> None:
        """Give a new connection the progress handler.

        Args:
            dbapi_connection: SQLAlchemy's adapter of the aiosqlite connection.
            record: The pool record, unused.
        """
        del record
        driver = getattr(dbapi_connection, "driver_connection", None)
        assert driver is not None
        await_(driver.set_progress_handler(self._wait, INSTRUCTIONS))

    def _wait(self) -> int:
        """Sleep out the stall, in the connection's thread.

        Returns:
            0: let the statement go on.
        """
        time.sleep(self.remaining())
        return 0
