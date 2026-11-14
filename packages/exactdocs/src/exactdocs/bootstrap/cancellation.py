"""Whether the running task is being cancelled, whatever its ``CancelledError`` turned into."""

import asyncio


def being_cancelled() -> bool:
    """Whether a cancellation of the running task is in progress.

    A statement cancelled while it runs can raise another error as it unwinds (a SQLAlchemy
    ``PendingRollbackError``, or a database error during the rollback): that error replaces the
    ``CancelledError``. A background loop that logs errors and goes on must stop on it all the
    same, so its ``except Exception`` re-raises when this is true (#308).

    The flag also stays set after a ``CancelledError`` that was caught and not ``uncancel()``-ed
    (``asyncio.timeout`` and ``wait_for`` do uncancel): an ordinary error after it would then end
    the loop too. Nothing in the upkeep's path catches one that way; keep it so.

    Returns:
        ``True`` while the task has a cancellation request it has not taken back.
    """
    task = asyncio.current_task()
    return task is not None and task.cancelling() > 0
