"""Interface preferences: what may be saved, the defaults, and one set per account."""

from datetime import UTC, datetime
from typing import Any, get_args

import pytest
from pydantic import SecretStr, ValidationError

from exactdocs.identity.adapters.driven.memory import (
    InMemoryAccountRepository,
    InMemoryFailedSignInLog,
    InMemoryPreferencesRepository,
    InMemorySessionRepository,
    InMemoryTokenRepository,
)
from exactdocs.identity.constants import TEXT_SCALES
from exactdocs.identity.dtos import (
    AccountPreferences,
    CreateFirstAdminCommand,
    CreateUserCommand,
    GetPreferencesQuery,
    InterfacePreferences,
    SavePreferencesCommand,
)
from exactdocs.identity.errors import InvalidPreferencesError
from exactdocs.identity.models import (
    Contrast,
    Font,
    Language,
    Motion,
    Preferences,
    TextScale,
    TextSpacing,
    Theme,
)
from exactdocs.identity.module import IdentityModule
from identity_stand_ins import no_external_sign_in

DEFAULTS: dict[str, Any] = {
    "theme": "system",
    "contrast": "standard",
    "text_scale": 100,
    "text_spacing": "standard",
    "motion": "system",
    "font": "default",
    "underline_links": False,
    "large_targets": False,
    "language": "system",
    "library_logos": True,
}
CHOSEN: dict[str, Any] = {
    "theme": "dark",
    "contrast": "more",
    "text_scale": 150,
    "text_spacing": "wide",
    "motion": "reduced",
    "font": "dyslexic",
    "underline_links": True,
    "large_targets": True,
    "language": "pl",
    "library_logos": False,
}


class FakeHasher:
    async def hash(self, password: str) -> str:
        return f"fake${password}"

    async def verify(self, password_hash: str, password: str) -> bool:
        return password_hash == f"fake${password}"


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 11, 23, 12, 0, tzinfo=UTC)


# --- the boundary: what a client may send


@pytest.mark.parametrize("scale", TEXT_SCALES)
def test_every_offered_text_size_is_accepted(scale: int) -> None:
    assert InterfacePreferences.model_validate({**CHOSEN, "text_scale": scale}).text_scale == scale


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("text_scale", 95),
        ("text_scale", 0),
        ("text_scale", 1000),
        ("text_scale", "100"),
        ("text_scale", 100.5),
        ("text_scale", True),
        ("theme", "sepia"),
        ("theme", "Dark"),
        ("theme", None),
        ("contrast", "less"),
        ("text_spacing", "narrow"),
        ("motion", "none"),
        ("font", "comic-sans"),
        ("underline_links", "yes"),
        ("underline_links", "true"),
        ("large_targets", 1),
        ("large_targets", None),
        ("language", "de"),
        ("language", "PL"),
        ("language", "pl-PL"),
        ("language", None),
        ("library_logos", "false"),
        ("library_logos", 0),
        ("library_logos", None),
    ],
)
def test_a_value_the_interface_does_not_offer_is_refused(field: str, value: object) -> None:
    with pytest.raises(ValidationError) as raised:
        InterfacePreferences.model_validate({**CHOSEN, field: value})

    assert [error["loc"] for error in raised.value.errors()] == [(field,)]


def test_an_unknown_setting_is_refused() -> None:
    with pytest.raises(ValidationError) as raised:
        InterfacePreferences.model_validate({**CHOSEN, "sparkles": True})

    assert [(e["loc"], e["type"]) for e in raised.value.errors()] == [
        (("sparkles",), "extra_forbidden")
    ]


@pytest.mark.parametrize("field", list(DEFAULTS))
def test_every_setting_is_required(field: str) -> None:
    with pytest.raises(ValidationError) as raised:
        InterfacePreferences.model_validate({k: v for k, v in CHOSEN.items() if k != field})

    assert [(e["loc"], e["type"]) for e in raised.value.errors()] == [((field,), "missing")]


def test_the_boundary_offers_exactly_the_domains_choices() -> None:
    fields = InterfacePreferences.model_fields
    for name, choices in [
        ("theme", Theme),
        ("contrast", Contrast),
        ("text_spacing", TextSpacing),
        ("motion", Motion),
        ("font", Font),
        ("language", Language),
    ]:
        assert get_args(fields[name].annotation) == tuple(c.value for c in choices), name
    assert get_args(fields["text_scale"].annotation) == TEXT_SCALES
    assert get_args(TextScale) == TEXT_SCALES


def test_the_defaults_are_the_documented_ones() -> None:
    assert InterfacePreferences.from_model(Preferences()).model_dump() == DEFAULTS


def test_a_round_trip_through_the_domain_keeps_every_setting() -> None:
    chosen = InterfacePreferences.model_validate(CHOSEN)

    assert InterfacePreferences.from_model(chosen.to_model()) == chosen


# --- the domain: what an account's preferences may hold


@pytest.mark.parametrize("scale", [95, 0, -100, 200, 101])
def test_the_domain_refuses_a_text_size_it_does_not_offer(scale: Any) -> None:
    with pytest.raises(InvalidPreferencesError) as raised:
        Preferences(text_scale=scale)

    assert raised.value.code == "invalid_preferences"
    assert "90, 100, 110, 125, 150" in str(raised.value)


def test_the_domain_defaults_follow_the_operating_system_and_change_nothing() -> None:
    assert Preferences() == Preferences(
        theme=Theme.SYSTEM,
        contrast=Contrast.STANDARD,
        text_scale=100,
        text_spacing=TextSpacing.STANDARD,
        motion=Motion.SYSTEM,
        font=Font.DEFAULT,
        underline_links=False,
        large_targets=False,
        language=Language.SYSTEM,
        library_logos=True,
    )


# --- the use cases: one set per account


async def _module() -> tuple[IdentityModule, str, str]:
    identity = IdentityModule.build(
        repository=InMemoryAccountRepository(),
        sessions=InMemorySessionRepository(),
        tokens=InMemoryTokenRepository(),
        hasher=FakeHasher(),
        failures=InMemoryFailedSignInLog(),
        clock=FixedClock(),
        **no_external_sign_in(),
    )
    ada = await identity.create_first_admin(
        CreateFirstAdminCommand(username="ada", password=SecretStr("correct horse battery staple"))
    )
    bob = await identity.create_user(
        CreateUserCommand(username="bob", password=SecretStr("bob's long passphrase"))
    )
    return identity, ada.id, bob.id


def save(account_id: str, preferences: dict[str, Any]) -> SavePreferencesCommand:
    return SavePreferencesCommand(
        account_id=account_id, preferences=InterfacePreferences.model_validate(preferences)
    )


async def test_an_account_that_never_saved_gets_the_defaults_unsaved() -> None:
    identity, ada, _ = await _module()

    state = await identity.get_preferences(GetPreferencesQuery(account_id=ada))

    assert state.model_dump() == {"saved": False, "preferences": DEFAULTS}


async def test_saved_preferences_come_back_saved_and_replace_the_previous_ones() -> None:
    identity, ada, _ = await _module()

    saved = await identity.save_preferences(save(ada, CHOSEN))
    assert saved == AccountPreferences(
        saved=True, preferences=InterfacePreferences.model_validate(CHOSEN)
    )
    assert await identity.get_preferences(GetPreferencesQuery(account_id=ada)) == saved

    # Saving the defaults is a choice too: they stay saved, so a browser's own do not win.
    back = await identity.save_preferences(save(ada, DEFAULTS))
    assert back.model_dump() == {"saved": True, "preferences": DEFAULTS}
    assert await identity.get_preferences(GetPreferencesQuery(account_id=ada)) == back


async def test_each_account_has_its_own_preferences() -> None:
    identity, ada, bob = await _module()

    bobs = {**DEFAULTS, "font": "hyperlegible", "language": "en"}
    await identity.save_preferences(save(ada, CHOSEN))
    await identity.save_preferences(save(bob, bobs))

    ada_now = await identity.get_preferences(GetPreferencesQuery(account_id=ada))
    bob_now = await identity.get_preferences(GetPreferencesQuery(account_id=bob))
    assert ada_now.model_dump() == {"saved": True, "preferences": CHOSEN}
    assert bob_now.model_dump() == {"saved": True, "preferences": bobs}


@pytest.mark.parametrize("language", ["system", "en", "pl"])
async def test_every_offered_language_is_saved_and_read_back(language: str) -> None:
    identity, ada, _ = await _module()

    await identity.save_preferences(save(ada, {**CHOSEN, "language": language}))

    now = await identity.get_preferences(GetPreferencesQuery(account_id=ada))
    assert now.preferences.language == language


async def test_library_logos_are_shown_until_the_person_hides_them() -> None:
    identity, ada, _ = await _module()

    before = await identity.get_preferences(GetPreferencesQuery(account_id=ada))
    hidden = await identity.save_preferences(save(ada, {**DEFAULTS, "library_logos": False}))
    shown = await identity.save_preferences(save(ada, {**DEFAULTS, "library_logos": True}))

    assert before.preferences.library_logos is True
    assert hidden.preferences.library_logos is False
    assert shown.preferences.library_logos is True
    now = await identity.get_preferences(GetPreferencesQuery(account_id=ada))
    assert now.model_dump() == {"saved": True, "preferences": DEFAULTS}


async def test_the_store_holds_domain_preferences_by_account() -> None:
    store = InMemoryPreferencesRepository()
    stand_ins = no_external_sign_in()
    stand_ins["preferences"] = store
    identity = IdentityModule.build(
        repository=InMemoryAccountRepository(),
        sessions=InMemorySessionRepository(),
        tokens=InMemoryTokenRepository(),
        hasher=FakeHasher(),
        failures=InMemoryFailedSignInLog(),
        clock=FixedClock(),
        **stand_ins,
    )

    await identity.save_preferences(save("id-ada", CHOSEN))

    assert store.preferences == {
        "id-ada": Preferences(
            theme=Theme.DARK,
            contrast=Contrast.MORE,
            text_scale=150,
            text_spacing=TextSpacing.WIDE,
            motion=Motion.REDUCED,
            font=Font.DYSLEXIC,
            underline_links=True,
            large_targets=True,
            language=Language.PL,
            library_logos=False,
        )
    }
