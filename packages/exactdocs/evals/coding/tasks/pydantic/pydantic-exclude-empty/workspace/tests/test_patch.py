from app.patch import ContactPatch


def test_a_patch_holds_its_values():
    assert ContactPatch(email="a@example.com").email == "a@example.com"
