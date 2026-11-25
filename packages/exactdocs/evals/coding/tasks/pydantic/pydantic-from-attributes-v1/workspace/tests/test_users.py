from app.users import UserOut, UserRow


def test_a_user_can_be_built_from_values():
    assert UserOut(id=1, name="Ada", email="ada@example.com").name == "Ada"


def test_a_row_holds_its_hash():
    assert UserRow(1, "Ada", "ada@example.com", "x").password_hash == "x"
