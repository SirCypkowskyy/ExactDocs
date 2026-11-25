from app.models import SignUp


def test_a_sign_up_keeps_its_email():
    assert SignUp(username="ada", email="ada@example.com").email == "ada@example.com"
