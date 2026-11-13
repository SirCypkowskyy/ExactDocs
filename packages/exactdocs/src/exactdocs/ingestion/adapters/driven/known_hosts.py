"""Seed the ``known_hosts`` file with the host keys ExactDocs pins (see ``PINNED``)."""

import os
from pathlib import Path

from exactdocs.ingestion.constants import PINNED


def seed_known_hosts(path: Path) -> None:
    """Make sure ``path`` lists the pinned keys; the file (mode 0600) keeps what ssh added to it.

    Only missing pinned lines are appended, so a user's own entries stay. A pinned host whose
    entry was edited by hand is left for ssh to judge.

    Args:
        path: The ``known_hosts`` file; it and its folder are created when missing.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    wanted = PINNED
    have = path.read_text("utf-8").splitlines() if path.exists() else []
    missing = [line for line in wanted if line not in have]
    if not missing and path.exists():
        return
    prefix = "" if not have or path.read_text("utf-8").endswith("\n") else "\n"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(descriptor, "a", encoding="utf-8") as handle:
        handle.write(prefix + "\n".join(missing) + ("\n" if missing else ""))
