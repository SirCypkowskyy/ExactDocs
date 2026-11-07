"""Git work folders when several server processes may share one data directory (PostgreSQL).

On SQLite one process uses the data directory, and at start it removes the fetch folders a crash
left behind by their age. On PostgreSQL several processes may share it (``WEB_CONCURRENCY``), and a
long import keeps its folder for longer than any age would tell. So each process works in a folder
of its own under ``work/``, holding an exclusive ``flock`` on its ``.owner`` file while it runs;
a process that starts removes the folders whose lock it can take: their owner is gone.
"""

import fcntl
import os
import shutil
import tempfile
from collections.abc import Generator
from contextlib import contextmanager, suppress
from pathlib import Path

from exactdocs.bootstrap.constants import PROCESS_WORK_OWNER, PROCESS_WORK_PREFIX


def new_work_root(work: Path) -> Path:
    """Create a folder for this process's fetches under ``work`` (``held`` claims it).

    Args:
        work: The data directory's ``work`` folder.

    Returns:
        The new folder. Until it is held, a sweep may remove it: the git adapter creates its
        work root again before each fetch.
    """
    work.mkdir(mode=0o700, parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=PROCESS_WORK_PREFIX, dir=work))


@contextmanager
def held(folder: Path) -> Generator[None]:
    """Lock the folder's owner file while the context runs, then remove the folder.

    Args:
        folder: A folder ``new_work_root`` made.

    Yields:
        Nothing, while the folder is this process's.
    """
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (folder / PROCESS_WORK_OWNER).open("w", encoding="utf-8") as owner:
        fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)  # ours: nobody else takes it
        owner.write(f"{os.getpid()}\n")
        owner.flush()
        try:
            yield
        finally:
            shutil.rmtree(folder, ignore_errors=True)


def sweep_abandoned_work(work_root: Path) -> None:
    """Remove the process folders under ``work_root`` whose process is gone (blocking: in a thread).

    Args:
        work_root: The data directory's ``work`` folder.
    """
    if work_root.is_symlink() or not work_root.is_dir():
        return
    for folder in work_root.glob(PROCESS_WORK_PREFIX + "*"):
        if folder.is_symlink() or not folder.is_dir():
            continue
        try:
            with (folder / PROCESS_WORK_OWNER).open("a", encoding="utf-8") as owner:
                fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            continue  # a live process holds it
        except OSError:
            pass  # no owner file: it died while creating the folder
        with suppress(OSError):
            shutil.rmtree(folder)
