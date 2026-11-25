import demo

from app.models import SignUp


def test_the_username_is_normalized():
    assert SignUp(username="  Ada ").username == "ada"


def test_the_library_is_the_pinned_one():
    assert demo.__version__ in {"1.0", "2.0"}
