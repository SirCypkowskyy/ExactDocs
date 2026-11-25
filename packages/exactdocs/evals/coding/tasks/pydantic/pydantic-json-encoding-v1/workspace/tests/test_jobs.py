from datetime import datetime, timedelta

from app.jobs import Job


def test_a_job_holds_its_timeout():
    job = Job(name="backup", timeout=timedelta(seconds=5), started_at=datetime(2024, 1, 1))
    assert job.timeout.total_seconds() == 5
