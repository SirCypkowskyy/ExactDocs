from app.schemas import PasswordChange


def test_matching_passwords_are_accepted():
    assert PasswordChange(password="s3cret!", confirm="s3cret!").password == "s3cret!"
