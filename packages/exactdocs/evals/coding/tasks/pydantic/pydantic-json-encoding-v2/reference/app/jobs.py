"""Scheduled jobs."""

from datetime import datetime, timedelta

from pydantic import BaseModel, field_serializer


class Job(BaseModel):
    """A job and its time limit."""

    name: str
    timeout: timedelta
    started_at: datetime

    @field_serializer("timeout", when_used="json")
    def timeout_in_milliseconds(self, value: timedelta) -> int:
        return value // timedelta(milliseconds=1)


def to_json(job: Job) -> str:
    """The job's JSON form."""
    return job.model_dump_json()
