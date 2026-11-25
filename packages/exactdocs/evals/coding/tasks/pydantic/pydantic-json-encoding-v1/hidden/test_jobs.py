import json
from datetime import datetime, timedelta, timezone

from app.jobs import Job, to_json

JOB = Job(
    name="backup",
    timeout=timedelta(minutes=1, seconds=30, milliseconds=250),
    started_at=datetime(2024, 5, 1, 12, 0, tzinfo=timezone.utc),
)


def test_the_timeout_is_whole_milliseconds():
    data = json.loads(to_json(JOB))
    assert data["timeout"] == 90250
    assert isinstance(data["timeout"], int)


def test_the_start_stays_iso_8601():
    assert json.loads(to_json(JOB))["started_at"].startswith("2024-05-01T12:00:00")


def test_the_model_s_own_json_uses_milliseconds_too():
    assert json.loads(JOB.json())["timeout"] == 90250


def test_python_values_are_unchanged():
    assert JOB.dict()["timeout"] == timedelta(seconds=90.25)
