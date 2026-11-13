"""Fail the test that leaves a psycopg connection open, not a later one (#333).

A ``psycopg.Connection`` nobody closes is finalized whenever the garbage collector reaches it,
which can be during an unrelated later test; ``filterwarnings = error`` then fails that test with
"was deleted while still open". The SQLite guard (``sqlite_guard``, #302) does the same for
``sqlite3``; this one covers PostgreSQL, sync and async connections alike.

``no_psycopg_connection_left_open()`` keeps every psycopg connection created inside the block,
from any thread, by wrapping ``BaseConnection.__init__`` (``psycopg.connect``,
``AsyncConnection.connect`` and SQLAlchemy's psycopg dialects all end there), and raises when one is
still open after it. Each connection keeps where it was opened, so the failure names the code that
opened it: the repository's own innermost frames, or, when a library thread opened it with none of
ours on the stack (DBOS's ``dynamic_scheduler_loop``), the innermost library frames that called the
database layer. "Opened in thread" names the thread that opened the connection; for a pooled one
that need not be the thread that leaked it. Before raising, the guard closes the leaked connections
(best effort), so the "deleted while still open" warning cannot surface in a later test either.

As with the SQLite guard, the check waits up to ``CLOSE_GRACE`` for connections a background thread
is still closing (DBOS shuts its executor down without waiting), and only connections opened inside
the block are tracked: a session- or module-scoped fixture is covered only for what it opens in its
own setup. A pooled connection that such a fixture's engine opens lazily inside a test is flagged in
that test; warm the pool in the fixture, or dispose the engine at the end of each test using it.
"""

import contextlib
import threading
import time
import traceback
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from psycopg._connection_base import BaseConnection
from psycopg.pq.abc import PGconn

CLOSE_GRACE = 2.0
"""Seconds to wait for connections still open after a block to close, before failing."""
CLOSE_POLL = 0.01
"""Seconds between checks while waiting for ``CLOSE_GRACE``."""
SHOWN_FRAMES = 4
"""How many of the opening call's own frames (outside libraries) a failure shows."""

_REPOSITORY = str(Path(__file__).parents[4])
_LIBRARIES = ("site-packages", "/lib/python")
_DATABASE_LAYER = ("/psycopg/", "/psycopg_pool/", "/sqlalchemy/")
"""Libraries skipped in the fallback: every connection passes through them."""


@dataclass(frozen=True, slots=True)
class Opened:
    """A connection opened inside the block, and where."""

    connection: BaseConnection[Any]
    database: str
    thread: str
    where: tuple[str, ...]


type Init = Callable[[BaseConnection[Any], PGconn], None]

_watching: list[list[Opened]] = []  # the open blocks, innermost last
_lock = threading.Lock()


def _where() -> tuple[str, ...]:
    """Return the innermost frames that led to this connection; see ``_pick``."""
    # Without source lines: this runs for every connection a test opens.
    stack = traceback.StackSummary.extract(traceback.walk_stack(None), lookup_lines=False)
    return _pick(list(reversed(stack)))


def _pick(stack: list[traceback.FrameSummary]) -> tuple[str, ...]:
    """Pick the frames a failure shows from a stack, outermost first.

    Args:
        stack: The stack, outermost frame first.

    Returns:
        The innermost ``SHOWN_FRAMES`` frames of the repository's own code; when there are none (a
        library thread opened the connection), the innermost library frames outside the database
        layer, shown from ``site-packages/`` on.
    """
    stack = [frame for frame in stack if frame.filename != __file__]
    ours = [
        f"{frame.filename.removeprefix(_REPOSITORY + '/')}:{frame.lineno} in {frame.name}"
        for frame in stack
        if frame.filename.startswith(_REPOSITORY)
        and not any(part in frame.filename for part in _LIBRARIES)
    ]
    if ours:
        return tuple(ours[-SHOWN_FRAMES:])
    libraries = [
        f"{frame.filename.rpartition('site-packages/')[2]}:{frame.lineno} in {frame.name}"
        for frame in stack
        if "site-packages/" in frame.filename
        and not any(part in frame.filename for part in _DATABASE_LAYER)
    ]
    return tuple(libraries[-SHOWN_FRAMES:])


def _watched(init: Init) -> Init:
    def watched_init(self: BaseConnection[Any], pgconn: PGconn) -> None:
        init(self, pgconn)
        if not _watching:
            return
        database = (self.pgconn.db or b"?").decode(errors="replace")
        opened = Opened(self, database, threading.current_thread().name, _where())
        with _lock:
            if _watching:
                _watching[-1].append(opened)

    return watched_init


# Installed once, at import, for the whole run: it does nothing outside a block.
pytest.MonkeyPatch().setattr(BaseConnection, "__init__", _watched(BaseConnection.__init__))


@contextmanager
def no_psycopg_connection_left_open() -> Generator[None]:
    """Run a block, then raise if a psycopg connection it opened is still open.

    Raises:
        AssertionError: Names the database of each connection left open, and where it was opened.
    """
    opened: list[Opened] = []
    with _lock:
        _watching.append(opened)
    try:
        yield
    finally:
        with _lock:
            _watching.remove(opened)
    left = _still_open(opened)
    opened.clear()
    if not left:
        return
    named = "\n".join(
        f"  {each.database} (opened in thread {each.thread})"
        + "".join(f"\n    at {frame}" for frame in each.where)
        for each in left
    )
    message = (
        f"{len(left)} psycopg connection(s) opened here are still open:\n{named}\n"
        "Close them (`with psycopg.connect(...)`), dispose the engine, or run the container "
        "(`async with container.running()`).\n"
        "The guard has closed them, so a pooled engine that still holds one may report "
        '"the connection is closed" once in a later test: that comes from this leak.'
    )
    # Close them here: something else (a pool record) may still hold them, and a later test
    # would then get their "deleted while still open" warning when the garbage collector runs.
    # ``pgconn.finish()`` closes sync and async connections alike, without an event loop.
    for each in left:
        with contextlib.suppress(Exception):
            each.connection.pgconn.finish()
    left.clear()
    raise AssertionError(message)


def _still_open(opened: list[Opened]) -> list[Opened]:
    """Wait up to ``CLOSE_GRACE`` for the open connections to close.

    Returns:
        The connections still open after the grace; empty at once when all are closed.
    """
    deadline = time.monotonic() + CLOSE_GRACE
    left = [each for each in opened if not each.connection.closed]
    while left and time.monotonic() < deadline:
        time.sleep(CLOSE_POLL)
        left = [each for each in left if not each.connection.closed]
    return left
