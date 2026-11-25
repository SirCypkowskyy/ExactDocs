from app.events import Event


def test_an_event_is_read_from_the_api_s_keys():
    event = Event.model_validate({"eventId": "e1", "occurredAt": "2024-05-01T12:00:00Z"})
    assert event.event_id == "e1"
