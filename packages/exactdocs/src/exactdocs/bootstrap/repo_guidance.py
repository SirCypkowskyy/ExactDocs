"""Glue between retrieval's repo guidance setting and ingestion's ``reprocess`` job (RET-08).

Retrieval may not call ingestion (bridges point the other way), so the composition root re-imports
a library's versions when its repo guidance is turned on: the versions imported before then kept
no instruction file, and a sync of an unchanged commit (or a tag) imports nothing.
"""

import logging
from dataclasses import dataclass

from exactdocs.ingestion.constants import REPROCESS_JOB
from exactdocs.ingestion.dtos import EnqueueJobCommand
from exactdocs.ingestion.ports.driving import EnqueueJob
from exactdocs.retrieval.dtos import (
    GetLibraryRetrievalQuery,
    LibraryRetrievalOut,
    RepoGuidance,
    SetLibraryRetrievalCommand,
)
from exactdocs.retrieval.ports.driving import GetLibraryRetrieval, SetLibraryRetrieval

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True, kw_only=True)
class SetRetrievalThenReprocess:
    """Implements retrieval's ``SetLibraryRetrieval``, then re-imports when guidance turns on.

    Turning repo guidance on (``off`` to ``notes`` or ``trusted``) queues one ``reprocess`` of
    the library, which re-imports every version at its commit, so each keeps its instruction
    files without a new upstream commit. Any other change needs no import: ``off`` and
    ``notes`` / ``trusted`` take effect at search time.
    """

    get_library_retrieval: GetLibraryRetrieval
    """Retrieval's read of the setting before it changes."""
    set_library_retrieval: SetLibraryRetrieval
    """Retrieval's use case."""
    enqueue_job: EnqueueJob
    """Ingestion's: queues the ``reprocess``."""

    async def __call__(self, command: SetLibraryRetrievalCommand) -> LibraryRetrievalOut:
        """Store the setting, then queue the re-import if repo guidance was just turned on.

        Args:
            command: The library and its settings.

        Returns:
            The stored settings, as retrieval answered. A failure to queue is logged, never
            returned: the setting is stored, and the versions keep no instruction files until
            they are re-imported: edit the setting again (off, then on) or queue a reprocess.
            A re-sync of an unchanged commit does not re-import them.
        """
        before = await self.get_library_retrieval(GetLibraryRetrievalQuery(library=command.library))
        saved = await self.set_library_retrieval(command)
        if before.repo_guidance is RepoGuidance.OFF and saved.repo_guidance is not RepoGuidance.OFF:
            try:
                await self.enqueue_job(
                    EnqueueJobCommand(kind=REPROCESS_JOB, library=saved.library.lower())
                )
            except Exception:
                logger.exception("could not re-import %s for its repo guidance", saved.library)
        return saved
