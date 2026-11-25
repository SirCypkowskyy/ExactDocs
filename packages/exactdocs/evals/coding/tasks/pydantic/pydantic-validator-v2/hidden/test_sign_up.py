import pytest
from pydantic import ValidationError

from app.models import SignUp

MESSAGE = "username must be 3-20 letters, digits or underscores"


def test_the_username_is_stripped_and_lowercased():
    assert SignUp(username="  Ada_99 ", email="a@example.com").username == "ada_99"


@pytest.mark.parametrize("bad", ["ab", "a" * 21, "ada lovelace", "ada!", "   "])
def test_a_bad_username_is_rejected_with_the_message(bad):
    with pytest.raises(ValidationError) as raised:
        SignUp(username=bad, email="a@example.com")
    assert MESSAGE in str(raised.value)


def test_the_email_is_kept_as_given():
    assert SignUp(username="grace", email=" G@example.com").email == " G@example.com"
