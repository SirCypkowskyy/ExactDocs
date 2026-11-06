"""Pydantic models whose field docstrings would not reach the schemas."""

from pydantic import BaseModel, ConfigDict
from pydantic_settings import BaseSettings


class Plain(BaseModel):  # expect: model-without-attribute-docstrings
    """No config at all."""


class Frozen(BaseModel):  # expect: model-without-attribute-docstrings
    """A config without the flag."""

    model_config = ConfigDict(frozen=True)


class Child(Frozen):  # expect: model-without-attribute-docstrings
    """Inherits a config without the flag."""


class Settings(BaseSettings):  # expect: model-without-attribute-docstrings
    """Settings are models, too."""


class Configured(BaseModel):
    """Sets the flag."""

    model_config = ConfigDict(use_attribute_docstrings=True)


class Inherits(Configured):
    """Gets the flag from its base, even with a config of its own."""

    model_config = ConfigDict(frozen=True)
