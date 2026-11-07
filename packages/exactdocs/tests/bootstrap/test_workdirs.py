"""Processes sharing a data directory (PostgreSQL) never remove each other's live fetch folders."""

from pathlib import Path

from exactdocs.bootstrap.workdirs import held, new_work_root, sweep_abandoned_work


def test_only_the_folders_of_processes_that_are_gone_are_removed(tmp_path: Path) -> None:
    work = tmp_path / "work"
    live, gone = new_work_root(work), new_work_root(work)
    with held(live):
        (live / "fetch-1").mkdir()
        with held(gone):
            (gone / "fetch-2").mkdir()
        gone.mkdir()  # its process ended without removing it (a crash)
        (gone / ".owner").touch()
        half_made = new_work_root(work)  # died before it held its folder
        other = work / "fetch-old"  # SQLite's layout: left to its own sweep
        other.mkdir()

        sweep_abandoned_work(work)

        assert sorted(p.name for p in work.iterdir()) == sorted([live.name, other.name])
        assert (live / "fetch-1").is_dir()
        assert not half_made.exists()
    assert not live.exists()  # a process removes its own folder when it stops
