import pytest
from pydantic import ValidationError

from app.settings import ServerSettings


def test_strings_are_stripped():
    assert ServerSettings(host="  example.org \n", port=80).host == "example.org"


def test_an_unknown_field_is_rejected():
    with pytest.raises(ValidationError):
        ServerSettings(host="example.org", port=80, prot=81)


def test_settings_cannot_be_changed():
    settings = ServerSettings(host="example.org", port=80)
    with pytest.raises((TypeError, ValidationError)):
        settings.port = 81
    assert settings.port == 80
