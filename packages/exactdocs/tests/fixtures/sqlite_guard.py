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
"""

import sqlite3
import sys
import threading
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Opened:
    """A connection opened inside the block, and where."""

    connection: sqlite3.Connection
    database: str
    thread: str


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
    left = [each for each in opened if is_open(each.connection)]
    opened.clear()
    if left:
        named = "\n".join(f"  {each.database} (opened in thread {each.thread})" for each in left)
        message = (
            f"{len(left)} SQLite connection(s) opened here are still open:\n{named}\n"
            "Close them (contextlib.closing; `with sqlite3.connect()` does not close), dispose "
            "the engine, or run the container (`async with container.running()`)."
        )
        raise AssertionError(message)
