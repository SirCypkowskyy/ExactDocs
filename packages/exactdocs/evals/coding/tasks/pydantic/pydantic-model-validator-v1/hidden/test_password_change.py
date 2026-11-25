import pytest
from pydantic import ValidationError

from app.schemas import PasswordChange


def test_matching_passwords_are_accepted():
    change = PasswordChange(password="s3cret!", confirm="s3cret!")
    assert (change.password, change.confirm) == ("s3cret!", "s3cret!")


def test_a_mismatch_is_rejected():
    with pytest.raises(ValidationError) as raised:
        PasswordChange(password="s3cret!", confirm="secret!")
    assert "passwords do not match" in str(raised.value)


def test_a_missing_field_is_reported_without_the_mismatch():
    with pytest.raises(ValidationError) as raised:
        PasswordChange(password="s3cret!")
    text = str(raised.value)
    assert "confirm" in text
    assert "passwords do not match" not in text
