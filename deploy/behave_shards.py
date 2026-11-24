"""The behave feature files in groups of about the same running time: CI's behave shards (#507).

    behave_shards.py --splits 3 --group 1        the feature files of group 1 of 3, one per line
    behave_shards.py --store <junit directory>   record each feature's time from behave's JUnit
                                                 reports (`behave --junit --junit-directory=...`)

The times are kept in `.behave_durations` at the repository root (JSON: a feature file's path ->
seconds), refreshed by `just bdd-durations`; a feature it does not know counts as the average.
Longest first, each feature goes to the group with the least time so far, so the groups differ by
less than the longest feature. Stdlib only.
"""

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FEATURES = ROOT / "packages" / "exactdocs" / "features"
DURATIONS = ROOT / ".behave_durations"
SUITE_TIME = re.compile(r'<testsuite\b[^>]*\btime="([0-9.]+)"')
"""A feature's time: the ``time`` of its report's ``<testsuite>``."""


def feature_files(directory: Path = FEATURES) -> list[str]:
    """Every feature file in ``directory``.

    Returns:
        Their paths from the repository root, sorted.
    """
    return sorted(path.relative_to(ROOT).as_posix() for path in directory.glob("*.feature"))


def split(paths: list[str], durations: dict[str, float], splits: int) -> list[list[str]]:
    """Put ``paths`` in ``splits`` groups of about the same total time.

    Returns:
        The groups, each sorted; a path without a duration counts as the average.
    """
    known = [durations[path] for path in paths if path in durations]
    default = sum(known) / len(known) if known else 1.0
    groups: list[list[str]] = [[] for _ in range(splits)]
    totals = [0.0] * splits
    for path in sorted(paths, key=lambda p: (-durations.get(p, default), p)):
        least = min(range(splits), key=lambda i: (totals[i], i))
        groups[least].append(path)
        totals[least] += durations.get(path, default)
    return [sorted(group) for group in groups]


def measured(junit: Path, directory: Path = FEATURES) -> dict[str, float]:
    """Each feature's time from behave's JUnit reports (``TESTS-<feature>.xml``, one per file).

    Returns:
        Seconds by the feature file's path from the repository root.
    """
    found: dict[str, float] = {}
    for report in sorted(junit.glob("TESTS-*.xml")):
        feature = directory / f"{report.stem.removeprefix('TESTS-')}.feature"
        time = SUITE_TIME.search(report.read_text(encoding="utf-8"))
        if feature.exists() and time is not None:
            found[feature.relative_to(ROOT).as_posix()] = round(float(time.group(1)), 3)
    return found


def main(argv: list[str] | None = None) -> int:
    """Print a group's feature files, or record the times (``--store``).

    Returns:
        The exit status.
    """
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--splits", type=int, help="how many groups")
    parser.add_argument("--group", type=int, help="which group to print, from 1")
    parser.add_argument("--store", type=Path, help="a JUnit directory to record the times from")
    args = parser.parse_args(argv)
    if args.store is not None:
        times = measured(args.store)
        if not times:
            parser.error(f"no behave JUnit report of a feature file in {args.store}")
        DURATIONS.write_text(json.dumps(times, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"{len(times)} feature times in {DURATIONS.relative_to(ROOT)}")
        return 0
    if args.splits is None or args.group is None or not 1 <= args.group <= args.splits:
        parser.error("give --splits N and --group i (1 <= i <= N), or --store DIR")
    durations = json.loads(DURATIONS.read_text(encoding="utf-8")) if DURATIONS.exists() else {}
    print("\n".join(split(feature_files(), durations, args.splits)[args.group - 1]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
