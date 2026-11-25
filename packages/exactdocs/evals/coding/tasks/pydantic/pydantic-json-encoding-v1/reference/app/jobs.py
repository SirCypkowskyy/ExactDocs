"""Scheduled jobs."""

from datetime import datetime, timedelta

from pydantic import BaseModel


class Job(BaseModel):
    """A job and its time limit."""

    name: str
    timeout: timedelta
    started_at: datetime

    class Config:
        json_encoders = {timedelta: lambda value: value // timedelta(milliseconds=1)}


def to_json(job: Job) -> str:
    """The job's JSON form."""
    return job.json()
