import pytest
from pydantic import ValidationError

from app.users import UserOut, UserRow, to_api


def row(**changes):
    values = {"id": 7, "name": "Ada", "email": "ada@example.com", "password_hash": "x"}
    return UserRow(**(values | changes))


def test_a_row_is_shown_without_its_password_hash():
    shown = to_api(row())
    assert isinstance(shown, UserOut)
    assert shown.dict() == {"id": 7, "name": "Ada", "email": "ada@example.com"}


def test_the_model_reads_any_object_s_attributes():
    class Admin(UserOut):
        role: str

    admin = row()
    admin.role = "owner"
    assert Admin.from_orm(admin).role == "owner"


def test_a_row_with_a_bad_value_is_rejected():
    with pytest.raises(ValidationError):
        to_api(row(id="not a number"))
