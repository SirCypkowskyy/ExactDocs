"""Glue between retrieval's AI providers and ingestion's ``embed`` jobs (RET-01).

Retrieval may not call ingestion (bridges point the other way), so the composition root queues
the embedding when something retrieval owns changes the embedding space.
"""

import logging
from dataclasses import dataclass
from datetime import datetime

from exactdocs.bootstrap.constants import WINDOW_RESET_GRACE_SECONDS
from exactdocs.ingestion.dtos import QueueEmbeddingCommand
from exactdocs.ingestion.ports.driving import QueueEmbedding
from exactdocs.retrieval.dtos import ProviderOut, SaveProviderCommand
from exactdocs.retrieval.models import ModelRole, SpendWindow
from exactdocs.retrieval.ports.driving import SaveProvider

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True, kw_only=True)
class SaveProviderThenEmbed:
    """Implements retrieval's ``SaveProvider``, then queues the embedding when it may have to run.

    Saving the profile the embedding role points at (a new one, another kind, another endpoint)
    can make a new embedding space: every version not covered by it is queued at once, instead of
    at the next start or import. A profile no embedding role uses queues nothing.
    """

    save_provider: SaveProvider
    """Retrieval's use case."""
    queue_embedding: QueueEmbedding
    """Ingestion's: queues an ``embed`` job per version not fully embedded (none twice)."""

    async def __call__(self, command: SaveProviderCommand) -> ProviderOut:
        """Save the profile, then queue the embedding if the embedding role uses it.

        Args:
            command: The profile.

        Returns:
            The stored profile, as retrieval answered. A failure to queue is logged, never
            returned: the profile is saved, and the next start queues what is missing.
        """
        saved = await self.save_provider(command)
        if ModelRole.EMBEDDING in saved.roles:
            try:
                queued = await self.queue_embedding(QueueEmbeddingCommand())
            except Exception:
                logger.exception("could not queue the embedding after %s changed", saved.name)
            else:
                if queued.queued:
                    logger.info(
                        "AI provider %s changed: %d versions are being embedded again",
                        saved.name,
                        queued.queued,
                    )
        return saved


def seconds_to_next_window(now: datetime) -> float:
    """Count the seconds until just after the next UTC midnight, when spend windows reset.

    Args:
        now: An aware time.

    Returns:
        The wait, a little past midnight so the new window is surely the current one.
    """
    reset = SpendWindow.DAY.resets_at(now)
    return (reset - now).total_seconds() + WINDOW_RESET_GRACE_SECONDS
