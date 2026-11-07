"""Processes sharing a data directory (PostgreSQL) never remove each other's live fetch folders."""

import fcntl
import os
import shutil
import threading
import time
from pathlib import Path

from exactdocs.bootstrap.workdirs import held, new_work_root, sweep_abandoned_work


def test_only_the_folders_of_processes_that_are_gone_are_removed(tmp_path: Path) -> None:
    work = tmp_path / "work"
    live, crashed, unowned = (new_work_root(work) for _ in range(3))
    with held(live):
        (live / "fetch-1").mkdir()
        crashed.mkdir()
        (crashed / ".owner").touch()  # its process died: nobody holds the lock
        unowned.mkdir()  # died before it created its owner file
        other = work / "fetch-old"  # SQLite's layout: left to its own sweep
        other.mkdir()

        sweep_abandoned_work(work)

        assert sorted(p.name for p in work.iterdir()) == sorted([live.name, other.name])
        assert (live / "fetch-1").is_dir()
        assert not (unowned / ".owner").exists()  # a sweep never creates one
    assert not live.exists()  # a process removes its own folder when it stops


def test_a_folder_swept_while_it_is_claimed_is_claimed_again(tmp_path: Path) -> None:
    folder = new_work_root(tmp_path / "work")
    folder.mkdir(parents=True)
    owner = folder / ".owner"
    owner.touch()
    sweeper = os.open(owner, os.O_RDWR)
    fcntl.flock(sweeper, fcntl.LOCK_EX)  # a sweep took the lock first...

    def finish_the_sweep() -> None:
        time.sleep(0.05)
        shutil.rmtree(folder)  # ...and removes the folder while it holds it
        os.close(sweeper)

    sweep = threading.Thread(target=finish_the_sweep)
    sweep.start()
    with held(folder):
        sweep.join()
        assert owner.is_file()  # a new owner file, locked by this process
        sweep_abandoned_work(tmp_path / "work")
        assert folder.is_dir()
