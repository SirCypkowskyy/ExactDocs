"""The identity DTOs' schema descriptions name the limits the domain enforces."""

from typing import Any

import pytest
from pydantic import BaseModel

from exactdocs.identity.constants import (
    MAX_PASSWORD_LENGTH,
    MAX_TOKEN_NAME_INPUT,
    MAX_TOKEN_NAME_LENGTH,
    MAX_USERNAME_LENGTH,
    MIN_PASSWORD_LENGTH,
)
from exactdocs.identity.dtos import (
    CreateFirstAdminCommand,
    CreateTokenCommand,
    LoginForTokenCommand,
    ResetPasswordCommand,
)


def field_schema(model: type[BaseModel], name: str) -> dict[str, Any]:
    return model.model_json_schema()["properties"][name]


def test_the_first_admins_username_description_names_the_length_limit() -> None:
    description = field_schema(CreateFirstAdminCommand, "username")["description"]

    assert f"1 to {MAX_USERNAME_LENGTH} characters" in description


@pytest.mark.parametrize("model", [CreateFirstAdminCommand, ResetPasswordCommand])
def test_a_new_passwords_description_names_the_length_limits(model: type[BaseModel]) -> None:
    schema = field_schema(model, "password")

    assert f"{MIN_PASSWORD_LENGTH} to {MAX_PASSWORD_LENGTH} characters" in schema["description"]
    assert (schema["minLength"], schema["maxLength"]) == (MIN_PASSWORD_LENGTH, MAX_PASSWORD_LENGTH)


@pytest.mark.parametrize("model", [CreateTokenCommand, LoginForTokenCommand])
def test_a_token_names_description_agrees_with_its_schema_limit(model: type[BaseModel]) -> None:
    schema = field_schema(model, "name")

    assert schema["maxLength"] == MAX_TOKEN_NAME_INPUT
    assert f"1 to {MAX_TOKEN_NAME_LENGTH} characters once trimmed" in schema["description"]
    assert f"`maxLength` ({MAX_TOKEN_NAME_INPUT}) only caps the raw input" in schema["description"]
