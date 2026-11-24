"""#507: CI's behave shards hold every feature file once, in groups of about the same time."""

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[4]


def _shards() -> ModuleType:
    """``deploy/behave_shards.py``, loaded by its path (a standalone script, not a package)."""
    spec = importlib.util.spec_from_file_location("behave_shards", ROOT / "deploy/behave_shards.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


shards = _shards()


@pytest.mark.parametrize("splits", [1, 2, 3, 5])
def test_every_feature_file_is_in_exactly_one_group(
    splits: int, capsys: pytest.CaptureFixture[str]
) -> None:
    printed = []
    for group in range(1, splits + 1):
        assert shards.main(["--splits", str(splits), "--group", str(group)]) == 0
        printed += capsys.readouterr().out.split()

    features = shards.feature_files()
    assert len(features) > 50
    assert sorted(printed) == features
    assert all((ROOT / path).is_file() for path in printed)


def test_the_longest_go_first_each_to_the_group_with_the_least_time() -> None:
    durations = {"a": 10.0, "b": 9.0, "c": 4.0, "d": 3.0, "e": 1.0}

    groups = shards.split(list(durations), durations, 2)

    assert groups == [["a", "d", "e"], ["b", "c"]]  # 14 and 13 seconds


def test_a_feature_without_a_time_counts_as_the_average() -> None:
    durations = {"a": 6.0, "b": 2.0}  # "new" counts as 4

    groups = shards.split(["a", "b", "new"], durations, 2)

    assert groups == [["a"], ["b", "new"]]


def test_the_times_are_read_from_behaves_junit_reports(tmp_path: Path) -> None:
    (tmp_path / "TESTS-access_log.xml").write_text(
        '<testsuite name="access_log.Access log" tests="4" time="8.230026"><testcase/></testsuite>',
        encoding="utf-8",
    )
    (tmp_path / "TESTS-no_such_feature.xml").write_text(
        '<testsuite name="gone" time="3.0"></testsuite>', encoding="utf-8"
    )

    assert shards.measured(tmp_path) == {"packages/exactdocs/features/access_log.feature": 8.23}


def test_the_recorded_times_name_existing_feature_files() -> None:
    durations = shards.json.loads(shards.DURATIONS.read_text(encoding="utf-8"))

    assert set(durations) <= set(shards.feature_files())
