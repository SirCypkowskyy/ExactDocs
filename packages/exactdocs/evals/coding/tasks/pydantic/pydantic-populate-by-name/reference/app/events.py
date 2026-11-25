"""Events from the billing API."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class Event(BaseModel):
    """One billing event."""

    model_config = ConfigDict(populate_by_name=True)

    event_id: str = Field(alias="eventId")
    occurred_at: datetime = Field(alias="occurredAt")
