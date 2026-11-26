"""Events from the billing API."""

from datetime import datetime

from pydantic import BaseModel, Field


class Event(BaseModel):
    """One billing event."""

    event_id: str = Field(alias="eventId")
    occurred_at: datetime = Field(alias="occurredAt")
