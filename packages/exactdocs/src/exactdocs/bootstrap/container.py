from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Self

from sqlalchemy.ext.asyncio import AsyncEngine

from exactdocs.bootstrap.bridges import CatalogIndexedVersions
from exactdocs.bootstrap.database import migrate, open_database
from exactdocs.bootstrap.settings import Settings
from exactdocs.catalog import CatalogModule
from exactdocs.catalog.adapters.driven.sqlite import SqliteLibraryRepository
from exactdocs.identity import IdentityModule
from exactdocs.identity.adapters.driven.argon2id import Argon2idPasswordHasher
from exactdocs.identity.adapters.driven.sqlite import SqliteAccountRepository
from exactdocs.retrieval import RetrievalModule
from exactdocs.retrieval.adapters.driven.memory import InMemoryExcerptIndex
from exactdocs_kernel import SystemClock


@dataclass(frozen=True, slots=True, kw_only=True)
class Container:
    """Every domain module, wired. Built once per process."""

    settings: Settings
    engine: AsyncEngine
    catalog: CatalogModule
    identity: IdentityModule
    retrieval: RetrievalModule

    @classmethod
    def build(cls, settings: Settings) -> Self:
        """Choose driven adapters and connect domains through bridges.

        Creates the data directory (``StartupError`` when it is unusable) but opens no
        connection; ``running()`` migrates the schema and releases the engine afterwards.
        """
        engine = open_database(settings)
        catalog = CatalogModule.build(repository=SqliteLibraryRepository(engine))
        identity = IdentityModule.build(
            repository=SqliteAccountRepository(engine),
            hasher=Argon2idPasswordHasher(),
            clock=SystemClock(),
        )
        retrieval = RetrievalModule.build(
            versions=CatalogIndexedVersions(catalog.resolve_version),
            index=InMemoryExcerptIndex(),
        )
        return cls(
            settings=settings,
            engine=engine,
            catalog=catalog,
            identity=identity,
            retrieval=retrieval,
        )

    @asynccontextmanager
    async def running(self) -> AsyncGenerator[None]:
        """Migrate the database to the latest schema, serve, then release the connections."""
        try:
            await migrate(self.engine)
            yield
        finally:
            await self.engine.dispose()
