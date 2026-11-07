"""Git work folders when several server processes may share one data directory (PostgreSQL).

On SQLite one process uses the data directory, and at start it removes the fetch folders a crash
left behind by their age. On PostgreSQL several processes may share it (``WEB_CONCURRENCY``), and a
long import keeps its folder for longer than any age would tell. So each process works in a folder
of its own under ``work/``, holding an exclusive ``flock`` on its ``.owner`` file while it runs;
a process that starts removes the folders whose lock it can take: their owner is gone.
"""

import fcntl
import os
import secrets
import shutil
import time
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from exactdocs.bootstrap.constants import (
    CLAIM_PAUSE_SECONDS,
    CLAIM_TRIES,
    PROCESS_WORK_OWNER,
    PROCESS_WORK_PREFIX,
)


def new_work_root(work: Path) -> Path:
    """Name a folder for this process's fetches under ``work``; ``held`` creates and claims it.

    Args:
        work: The data directory's ``work`` folder.

    Returns:
        The folder's path (not created yet).
    """
    return work / f"{PROCESS_WORK_PREFIX}{secrets.token_hex(8)}"


@contextmanager
def held(folder: Path) -> Generator[None]:
    """Create the folder and lock its owner file while the context runs, then remove it.

    Creating, locking and checking happen in that order, again until they hold together: a
    sweep that removed the folder in between (it found no owner, or took the lock first) leaves
    this process's lock on a file that is gone, which the check notices.

    Args:
        folder: A folder ``new_work_root`` named.

    Yields:
        Nothing, while the folder is this process's.

    Raises:
        OSError: The folder could not be claimed (it kept disappearing).
    """
    owner = folder / PROCESS_WORK_OWNER
    for _ in range(CLAIM_TRIES):
        try:
            folder.mkdir(mode=0o700, parents=True, exist_ok=True)
            descriptor = os.open(owner, os.O_RDWR | os.O_CREAT, 0o600)
        except FileNotFoundError:
            continue  # swept between the two steps
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            linked = owner.stat().st_ino == os.fstat(descriptor).st_ino
        except BlockingIOError, FileNotFoundError:
            linked = False  # a sweep holds or held it
        if not linked:
            os.close(descriptor)
            time.sleep(CLAIM_PAUSE_SECONDS)
            continue
        try:
            os.write(descriptor, f"{os.getpid()}\n".encode())
            yield
        finally:
            shutil.rmtree(folder, ignore_errors=True)
            os.close(descriptor)
        return
    message = f"could not claim the work folder {folder}"
    raise OSError(message)


def sweep_abandoned_work(work_root: Path) -> None:
    """Remove the process folders under ``work_root`` whose process is gone (blocking: in a thread).

    A folder whose owner file this sweep can lock, or that has none, belongs to no live process.
    It is removed while the lock is held, so its process (if it is starting) notices and claims
    it again. The sweep never creates an owner file.

    Args:
        work_root: The data directory's ``work`` folder.
    """
    if work_root.is_symlink() or not work_root.is_dir():
        return
    for folder in work_root.glob(PROCESS_WORK_PREFIX + "*"):
        if folder.is_symlink() or not folder.is_dir():
            continue
        try:
            descriptor = os.open(folder / PROCESS_WORK_OWNER, os.O_RDWR)
        except FileNotFoundError:
            shutil.rmtree(folder, ignore_errors=True)
            continue
        except OSError:
            continue
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            pass  # a live process holds it
        else:
            shutil.rmtree(folder, ignore_errors=True)
        finally:
            os.close(descriptor)
