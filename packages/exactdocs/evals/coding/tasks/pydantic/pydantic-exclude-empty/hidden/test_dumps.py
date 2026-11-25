import json

from app.patch import ContactPatch


def test_empty_values_are_left_out():
    assert ContactPatch().model_dump() == {}
    assert json.loads(ContactPatch().model_dump_json()) == {}


def test_set_values_are_kept():
    patch = ContactPatch(email="a@example.com", nickname="ada")
    assert patch.model_dump() == {"email": "a@example.com", "nickname": "ada"}
    assert json.loads(patch.model_dump_json()) == {"email": "a@example.com", "nickname": "ada"}


def test_a_phone_alone():
    assert ContactPatch(phone="+44 20 7946 0000").model_dump() == {"phone": "+44 20 7946 0000"}
