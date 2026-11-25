from datetime import datetime, timezone

from app.events import Event

AT = datetime(2024, 5, 1, 12, 0, tzinfo=timezone.utc)


def test_the_api_s_aliases_are_accepted():
    event = Event.model_validate({"eventId": "e1", "occurredAt": "2024-05-01T12:00:00Z"})
    assert (event.event_id, event.occurred_at) == ("e1", AT)


def test_the_field_names_are_accepted():
    event = Event(event_id="e2", occurred_at=AT)
    assert (event.event_id, event.occurred_at) == ("e2", AT)


def test_dumps_are_unchanged():
    event = Event(event_id="e3", occurred_at=AT)
    assert event.model_dump() == {"event_id": "e3", "occurred_at": AT}
    assert event.model_dump(by_alias=True) == {"eventId": "e3", "occurredAt": AT}
