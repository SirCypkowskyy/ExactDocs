"""Scheduled jobs."""

from datetime import datetime, timedelta

from pydantic import BaseModel


class Job(BaseModel):
    """A job and its time limit."""

    name: str
    timeout: timedelta
    started_at: datetime


def to_json(job: Job) -> str:
    """The job's JSON form."""
    raise NotImplementedError
