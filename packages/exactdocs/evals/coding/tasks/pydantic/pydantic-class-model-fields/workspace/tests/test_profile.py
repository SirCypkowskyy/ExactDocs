from app.profile import Profile


def test_a_profile_has_a_name():
    assert Profile(name="Ada").name == "Ada"
