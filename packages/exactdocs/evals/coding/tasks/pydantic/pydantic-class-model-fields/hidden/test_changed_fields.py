from app.profile import Profile


def test_the_changed_fields_in_declaration_order():
    before = Profile(name="Ada", bio="maths", website=None)
    after = Profile(name="Ada", bio="poetry", website="https://example.org")
    assert before.changed_fields(after) == ["bio", "website"]


def test_nothing_changed():
    assert Profile(name="Ada").changed_fields(Profile(name="Ada")) == []


def test_a_subclass_s_fields_count_too():
    class TeamProfile(Profile):
        team: str = ""

    before = TeamProfile(name="Ada", team="engines")
    after = TeamProfile(name="Grace", team="compilers")
    assert before.changed_fields(after) == ["name", "team"]
