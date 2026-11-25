from app.models import SignUp


def test_a_sign_up_has_a_username():
    assert SignUp(username="ada").username == "ada"
