"""ExactDocs' own database on a libSQL server (#474): SQLite's dialect over Turso's driver.

libSQL is the fork of SQLite behind Turso. A libSQL server (``sqld``, self-hosted, or a Turso
database) speaks SQL over HTTP: each connection is a stream on the server, kept from one request
to the next by a baton, so a transaction spans several statements as on a local file. Turso's
``turso-serverless`` is the DB-API driver for it (pure Python, the standard library's HTTP
client; the ``libsql-database`` extra), imported here only, and only once
``EXACTDOCS_DATABASE_URL`` names ``libsql://``.

The driver is synchronous. As aiosqlite does for ``sqlite3``, each connection runs on a thread
of its own (aiosqlite's ``Connection`` drives it), and SQLAlchemy's aiosqlite adaption makes it
async: ``LibsqlDialect`` is that dialect with another connect. It is SQLite's dialect, so every
SQLite adapter, revision and query of ExactDocs runs unchanged; it registers as
``sqlite+libsql``.

What ``_Connection`` adds to the driver, so it behaves as ``sqlite3`` where ExactDocs relies on it:

- its errors are ``sqlite3``'s (``IntegrityError``, ``OperationalError`` ...), with the server's
  code as ``sqlite_errorcode`` where it sent one, so SQLAlchemy wraps them as it wraps SQLite's;
- a statement outside a transaction is sent once more when the server had dropped the stream for
  inactivity (the statement never ran): a pooled connection can idle longer than the server keeps
  a stream. Inside a transaction that error stands: the server rolled it back;
- ``create_function`` accepts the two functions SQLAlchemy registers on every connection and
  registers nothing (a server cannot call back into this process); any other is refused.
"""

import importlib
import sqlite3
from collections.abc import Callable, Generator, Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from types import ModuleType
from typing import Any, cast

import aiosqlite
from sqlalchemy import pool
from sqlalchemy.connectors.asyncio import AsyncIODBAPIConnection
from sqlalchemy.dialects.sqlite.aiosqlite import (
    AsyncAdapt_aiosqlite_connection,
    AsyncAdapt_aiosqlite_dbapi,
    SQLiteDialect_aiosqlite,
)
from sqlalchemy.engine import URL
from sqlalchemy.engine.interfaces import ConnectArgsType
from sqlalchemy.util import await_

from exactdocs.bootstrap.constants import (
    LIBSQL_CHUNK_ROWS,
    LIBSQL_CLIENT_FUNCTIONS,
    LIBSQL_DIALECT_DRIVER,
    LIBSQL_DRIVER_MODULE,
    LIBSQL_EXPIRED,
    LIBSQL_TLS_KEY,
    LIBSQL_TOKEN_KEY,
)

type Parameters = Sequence[Any] | Mapping[str, Any]
"""A statement's parameters: positional (``?``) or named (``:name``)."""


def server_url(url: URL) -> str:
    """Name the server a ``sqlite+libsql://`` URL points at, as the driver takes it.

    Args:
        url: The database URL (``sqlite+libsql://host[:port][?tls=0]``).

    Returns:
        ``https://host[:port]``, or ``http://host[:port]`` with ``tls=0``.
    """
    tls = url.query.get(LIBSQL_TLS_KEY, "1")
    if isinstance(tls, tuple):
        tls = tls[-1] if tls else "1"
    scheme = "http" if tls == "0" else "https"
    netloc = url.host or ""
    if ":" in netloc:  # an IPv6 address
        netloc = f"[{netloc}]"
    if url.port:
        netloc = f"{netloc}:{url.port}"
    return f"{scheme}://{netloc}"


def auth_token(url: URL) -> str | None:
    """Read the server's token from the URL (``?authToken=...``, as Turso writes it).

    Args:
        url: The database URL.

    Returns:
        The token, or ``None`` for a server without authentication.
    """
    token = url.query.get(LIBSQL_TOKEN_KEY)
    if isinstance(token, tuple):
        token = token[-1] if token else None
    return token or None


def driver() -> ModuleType:
    """Import ``turso-serverless`` (the ``libsql-database`` extra), only now.

    Returns:
        The driver's module.
    """
    return importlib.import_module(LIBSQL_DRIVER_MODULE)


@contextmanager
def _as_sqlite_errors() -> Generator[None]:
    """Raise the driver's errors as ``sqlite3``'s, with the server's code where it sent one.

    A driver error becomes the ``sqlite3`` error of the same DB-API class (``IntegrityError``,
    ``OperationalError`` ...), so SQLAlchemy wraps it as it wraps SQLite's.

    Yields:
        Nothing; the block runs inside.

    Raises:
        ProgrammingError: A parameter the protocol cannot carry (an infinite float, a type it
            does not know).
    """
    module = driver()
    try:
        yield
    except (TypeError, ValueError) as error:  # a parameter the protocol cannot carry
        raise sqlite3.ProgrammingError(str(error)) from error
    except module.Error as error:
        kind = getattr(sqlite3, type(error).__name__, sqlite3.DatabaseError)
        if not isinstance(kind, type) or not issubclass(kind, sqlite3.Error):
            kind = sqlite3.DatabaseError
        translated = kind(str(error))
        # The driver raises its DB-API error `from None`; the server's error stays its context.
        server = error.__context__
        for code in (getattr(server, "extended_code", None), getattr(server, "code", None)):
            if isinstance(code, str) and isinstance(number := getattr(sqlite3, code, None), int):
                translated.sqlite_errorcode = number
                translated.sqlite_errorname = code
                break
        raise translated from error


def _value(value: object) -> object:
    """Adapt one parameter as ``sqlite3`` would: a ``memoryview`` (SQLAlchemy's BLOBs) is bytes.

    Args:
        value: The parameter.

    Returns:
        What the driver can send.
    """
    return bytes(value) if isinstance(value, memoryview) else value


def _adapted(parameters: Parameters) -> Parameters:
    """Adapt a statement's parameters (``_value``), positional or named.

    Args:
        parameters: The parameters.

    Returns:
        The adapted parameters, of the same shape.
    """
    if isinstance(parameters, Mapping):
        return {name: _value(value) for name, value in parameters.items()}
    return [_value(value) for value in parameters]


def _expired(error: sqlite3.Error) -> bool:
    """Tell whether the server refused a request because it had dropped the stream.

    Args:
        error: The translated error.

    Returns:
        ``True`` for an expired stream: the statement never ran.
    """
    return LIBSQL_EXPIRED in str(error).lower()


class _Cursor:
    """A ``sqlite3.Cursor``-shaped cursor over the driver's, for aiosqlite's thread."""

    def __init__(self, connection: _Connection, inner: Any) -> None:  # ruff: ignore[any-type]
        """Wrap a cursor of the driver.

        Args:
            connection: The connection it belongs to.
            inner: The driver's cursor.
        """
        self._connection = connection
        self._inner = inner

    @property
    def description(self) -> Any:  # ruff: ignore[any-type]
        """The columns of the last statement's rows (DB-API), or ``None``."""
        return self._inner.description

    @property
    def rowcount(self) -> int:
        """The rows the last statement changed, or ``-1`` for a query."""
        return self._inner.rowcount

    @property
    def lastrowid(self) -> int | None:
        """The ``rowid`` of the last row an ``INSERT`` or ``REPLACE`` added."""
        return self._inner.lastrowid

    @property
    def arraysize(self) -> int:
        """Rows ``fetchmany`` returns by default."""
        return self._inner.arraysize

    @arraysize.setter
    def arraysize(self, value: int) -> None:
        """Set the rows ``fetchmany`` returns by default.

        Args:
            value: The number of rows.
        """
        self._inner.arraysize = value

    def execute(self, sql: str, parameters: Parameters = ()) -> _Cursor:
        """Run one statement; outside a transaction, again once if the stream had expired.

        Args:
            sql: The statement.
            parameters: Its parameters.

        Returns:
            This cursor.

        Raises:
            OperationalError: The server refused the statement, or dropped the stream of an open
                transaction (which it rolled back).
        """
        values = _adapted(parameters)
        retry = not self._connection.in_transaction
        try:
            with _as_sqlite_errors():
                self._inner.execute(sql, values)
        except sqlite3.OperationalError as error:
            if not (retry and _expired(error)):
                raise
            with _as_sqlite_errors():
                self._inner.execute(sql, values)
        return self

    def executemany(self, sql: str, parameters: Iterable[Parameters]) -> _Cursor:
        """Run one statement for each set of parameters (one request each).

        Args:
            sql: The statement (``INSERT``, ``UPDATE``, ``DELETE`` or ``REPLACE``).
            parameters: The sets of parameters.

        Returns:
            This cursor.

        Raises:
            OperationalError: The server refused the statement, or dropped the stream of an open
                transaction (which it rolled back).
        """
        rows = [_adapted(row) for row in parameters]
        retry = not self._connection.in_transaction
        try:
            with _as_sqlite_errors():
                self._inner.executemany(sql, rows)
        except sqlite3.OperationalError as error:
            if not (retry and _expired(error)):
                raise
            with _as_sqlite_errors():
                self._inner.executemany(sql, rows)
        return self

    def executescript(self, script: str) -> _Cursor:
        """Run several statements at once, committing a transaction first (as ``sqlite3``).

        Args:
            script: The statements.

        Returns:
            This cursor.
        """
        with _as_sqlite_errors():
            self._inner.executescript(script)
        return self

    def fetchone(self) -> Any:  # ruff: ignore[any-type]
        """Return the next row.

        Returns:
            The row (a tuple), or ``None`` when there is none left.
        """
        return self._inner.fetchone()

    def fetchmany(self, size: int | None = None) -> list[Any]:
        """Return the next rows.

        Args:
            size: How many at most (``arraysize`` when ``None``).

        Returns:
            The rows.
        """
        return self._inner.fetchmany(size)

    def fetchall(self) -> list[Any]:
        """Return every row left.

        Returns:
            The rows.
        """
        return self._inner.fetchall()

    def close(self) -> None:
        """Close the cursor (its rows were all read already)."""
        self._inner.close()

    def __iter__(self) -> Iterator[Any]:
        """Iterate over the rows left.

        Returns:
            The rows.
        """
        return iter(self.fetchall())


class _Connection:
    """A ``sqlite3.Connection``-shaped connection over the driver's, for aiosqlite's thread."""

    def __init__(self, inner: Any) -> None:  # ruff: ignore[any-type]
        """Wrap a connection of the driver.

        Args:
            inner: The driver's connection, opened with ``isolation_level=None``.
        """
        self._inner = inner

    @property
    def in_transaction(self) -> bool:
        """Whether a transaction is open, as the server last said."""
        return self._inner.in_transaction

    @property
    def isolation_level(self) -> str | None:
        """``None``: SQLAlchemy (``_begin``) begins every transaction itself."""
        return self._inner.isolation_level

    @isolation_level.setter
    def isolation_level(self, value: str | None) -> None:
        """Set how the driver begins a transaction on its own (``None``: never).

        Args:
            value: ``None``, ``DEFERRED``, ``IMMEDIATE`` or ``EXCLUSIVE``.
        """
        self._inner.isolation_level = value

    @property
    def row_factory(self) -> Any:  # ruff: ignore[any-type]
        """The driver's row factory (``None``: tuples)."""
        return self._inner.row_factory

    @row_factory.setter
    def row_factory(self, value: Any) -> None:  # ruff: ignore[any-type]
        """Set the driver's row factory.

        Args:
            value: The factory, or ``None``.
        """
        self._inner.row_factory = value

    @property
    def text_factory(self) -> Any:  # ruff: ignore[any-type]
        """How text comes back (always ``str``)."""
        return self._inner.text_factory

    @text_factory.setter
    def text_factory(self, value: Any) -> None:  # ruff: ignore[any-type]
        """Set how text comes back.

        Args:
            value: The factory.
        """
        self._inner.text_factory = value

    def cursor(self) -> _Cursor:
        """Open a cursor.

        Returns:
            The cursor.
        """
        with _as_sqlite_errors():
            return _Cursor(self, self._inner.cursor())

    def execute(self, sql: str, parameters: Parameters = ()) -> _Cursor:
        """Run one statement on a new cursor.

        Args:
            sql: The statement.
            parameters: Its parameters.

        Returns:
            The cursor.
        """
        return self.cursor().execute(sql, parameters)

    def executemany(self, sql: str, parameters: Iterable[Parameters]) -> _Cursor:
        """Run one statement for each set of parameters, on a new cursor.

        Args:
            sql: The statement.
            parameters: The sets of parameters.

        Returns:
            The cursor.
        """
        return self.cursor().executemany(sql, parameters)

    def executescript(self, script: str) -> _Cursor:
        """Run several statements at once, on a new cursor.

        Args:
            script: The statements.

        Returns:
            The cursor.
        """
        return self.cursor().executescript(script)

    def commit(self) -> None:
        """Commit the open transaction, if any."""
        with _as_sqlite_errors():
            self._inner.commit()

    def rollback(self) -> None:
        """Roll the open transaction back, if any."""
        with _as_sqlite_errors():
            self._inner.rollback()

    def close(self) -> None:
        """Close the stream on the server (an open transaction is rolled back)."""
        with _as_sqlite_errors():
            self._inner.close()

    def create_function(
        self,
        name: str,
        narg: int,
        func: Callable[..., Any] | None,
        *,
        deterministic: bool = False,
    ) -> None:
        """Accept SQLAlchemy's own functions without registering them; refuse any other.

        Args:
            name: The SQL function's name.
            narg: Its number of arguments.
            func: Its implementation in Python.
            deterministic: Whether it is deterministic.

        Raises:
            sqlite3.NotSupportedError: A function other than SQLAlchemy's (``regexp``,
                ``floor``): a libSQL server cannot call this process.
        """
        del narg, func, deterministic
        if name.lower() not in LIBSQL_CLIENT_FUNCTIONS:
            message = f"a libSQL server cannot call the Python function {name!r}"
            raise sqlite3.NotSupportedError(message)


class _LibsqlDbapi(AsyncAdapt_aiosqlite_dbapi):
    """SQLAlchemy's aiosqlite DB-API adaption, connecting to a libSQL server instead of a file."""

    def connect(self, *arg: Any, **kw: Any) -> AsyncAdapt_aiosqlite_connection:  # ruff: ignore[any-type]
        """Open a connection: a stream on the server, driven on a thread of its own.

        Args:
            *arg: Unused (the dialect passes keywords only).
            **kw: ``url`` (``https://host[:port]``) and ``auth_token``.

        Returns:
            SQLAlchemy's async adaption of the connection.
        """
        del arg
        url, token = kw["url"], kw.get("auth_token")

        def connector() -> sqlite3.Connection:
            """Open the driver's connection, on aiosqlite's thread.

            Returns:
                The connection, shaped as ``sqlite3``'s.
            """
            with _as_sqlite_errors():
                inner = driver().connect(url, auth_token=token, isolation_level=None)
            # Duck-typed: aiosqlite calls the methods of sqlite3.Connection that it has.
            return cast("sqlite3.Connection", _Connection(inner))

        connection = aiosqlite.Connection(connector, LIBSQL_CHUNK_ROWS)
        # As SQLAlchemy does for aiosqlite: a forgotten connection never holds the exit.
        connection._thread.daemon = True  # ruff: ignore[private-member-access] (aiosqlite's thread)
        opened = cast("AsyncIODBAPIConnection", await_(connection))
        return AsyncAdapt_aiosqlite_connection(self, opened)


class LibsqlDialect(SQLiteDialect_aiosqlite):
    """SQLite's async dialect on a libSQL server (``sqlite+libsql://host[:port]``)."""

    driver = LIBSQL_DIALECT_DRIVER
    supports_statement_cache = True
    supports_server_side_cursors = False

    @classmethod
    def import_dbapi(cls) -> AsyncAdapt_aiosqlite_dbapi:
        """Return the DB-API module SQLAlchemy calls ``connect`` on.

        Returns:
            The aiosqlite adaption, connecting to the server.
        """
        return _LibsqlDbapi(aiosqlite, sqlite3)

    @classmethod
    def get_pool_class(cls, url: URL) -> type[pool.Pool]:
        """Pool connections as for a SQLite file: each connection is a stream on the server.

        Args:
            url: The database URL.

        Returns:
            The async queue pool.
        """
        del url
        return pool.AsyncAdaptedQueuePool

    def create_connect_args(self, url: URL) -> ConnectArgsType:
        """Turn the URL into the driver's arguments.

        Args:
            url: ``sqlite+libsql://host[:port][?tls=0&authToken=...]``.

        Returns:
            No positional argument; ``url`` and ``auth_token``.
        """
        return [], {"url": server_url(url), "auth_token": auth_token(url)}
