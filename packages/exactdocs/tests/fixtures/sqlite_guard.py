"""Fail the test that leaves a SQLite connection open, not a later one (#300).

A ``sqlite3.Connection`` nobody closes is finalized whenever the garbage collector reaches it,
which can be during an unrelated later test; ``filterwarnings = error`` then fails that test with
"unclosed database". A pooled connection of an engine nobody disposes (a container built but never
run) is such a connection: aiosqlite holds a plain ``sqlite3.Connection`` in its worker thread.

``no_connection_left_open()`` keeps every ``sqlite3.Connection`` opened inside the block, from any
thread, through the ``sqlite3.connect/handle`` audit event, and raises when one is still open after
it. It needs no garbage collection, so it is cheap, and it also finds a connection that something
still reaches (a ``gc.collect()`` would not finalize it yet). Keeping the connections until the
block ends only delays a leaked connection's own warning to that point, still inside the test.

When connections are still open after the block, the guard waits up to ``CLOSE_GRACE`` for them to
close before it fails (see there). A reported leak drops the guard's own references before
raising, so when nothing else holds the connection it is finalized in that test's teardown, not in
a later test. Something else may still hold it (a fixture's undisposed engine, through the test's
arguments); then it can still be finalized later, but the test that leaked it has already failed.

Only connections opened inside the block are tracked. The autouse fixture runs per test, so a
session- or module-scoped fixture is covered only for what it opens in its own setup. An engine
such a fixture owns but a test uses lazily opens its pooled connection inside the first test that
uses it, and that test is flagged. Open (warm) the connection in the fixture itself, or dispose the
engine at the end of each test that uses it.
"""

import sqlite3
import sys
import threading
import time
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Opened:
    """A connection opened inside the block, and where."""

    connection: sqlite3.Connection
    database: str
    thread: str


CLOSE_GRACE = 2.0
"""Seconds to wait for connections still open after a block to close, before failing.

``DBOS._destroy`` shuts its executor down with ``wait=False``, so ``DBOS.destroy`` returns while a
step already running in an executor thread still holds a system-DB connection; that thread closes it
a moment later. A real leak stays open, so it still fails, only this much later.
"""
CLOSE_POLL = 0.01
"""Seconds between checks while waiting for ``CLOSE_GRACE``."""

_watching: list[list[Opened]] = []  # the open blocks, innermost last
_database = threading.local()  # the path of the connection this thread is opening


def _record(event: str, args: tuple[object, ...]) -> None:
    if not _watching:
        return
    if event == "sqlite3.connect":  # raised just before ``sqlite3.connect/handle``, same thread
        _database.name = str(args[0])
    elif event == "sqlite3.connect/handle" and isinstance(args[0], sqlite3.Connection):
        name = getattr(_database, "name", "?")
        _watching[-1].append(Opened(args[0], name, threading.current_thread().name))


sys.addaudithook(_record)  # audit hooks cannot be removed: it does nothing outside a block


def is_open(connection: sqlite3.Connection) -> bool:
    """Tell whether a connection is still open, from any thread.

    Returns:
        ``False`` once it is closed.
    """
    try:
        _ = connection.in_transaction  # checks only that it is open, not the calling thread
    except sqlite3.ProgrammingError:
        return False
    return True


@contextmanager
def no_connection_left_open() -> Generator[None]:
    """Run a block, then raise if a SQLite connection it opened is still open.

    Raises:
        AssertionError: Names the database of each connection left open.
    """
    opened: list[Opened] = []
    _watching.append(opened)
    try:
        yield
    finally:
        _watching.remove(opened)
    left = _still_open(opened)
    opened.clear()
    if not left:
        return
    named = "\n".join(f"  {each.database} (opened in thread {each.thread})" for each in left)
    message = (
        f"{len(left)} SQLite connection(s) opened here are still open:\n{named}\n"
        "Close them (contextlib.closing; `with sqlite3.connect()` does not close), dispose "
        "the engine, or run the container (`async with container.running()`)."
    )
    left.clear()  # finalize the leaked connections here, not when a later test collects garbage
    raise AssertionError(message)


def _still_open(opened: list[Opened]) -> list[Opened]:
    """Wait up to ``CLOSE_GRACE`` for the open connections to close.

    Returns:
        The connections still open after the grace; empty at once when all are closed.
    """
    deadline = time.monotonic() + CLOSE_GRACE
    left = [each for each in opened if is_open(each.connection)]
    while left and time.monotonic() < deadline:
        time.sleep(CLOSE_POLL)
        left = [each for each in left if is_open(each.connection)]
    return left
