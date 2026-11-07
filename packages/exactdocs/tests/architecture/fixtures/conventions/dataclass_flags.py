"""Dataclasses without `frozen=True, slots=True, kw_only=True` and without a marker."""

import dataclasses
from dataclasses import dataclass
from dataclasses import dataclass as dc


@dataclass  # expect: dataclass-flags
class Bare:
    """No flags."""


@dataclass(frozen=True, slots=True)  # expect: dataclass-flags
class Positional:
    """No kw_only."""


@dataclasses.dataclass(slots=True, kw_only=True)  # expect: dataclass-flags
class Mutable:
    """No frozen."""


@dataclass(frozen=False, slots=True, kw_only=True)  # expect: dataclass-flags
class ExplicitlyMutable:
    """A flag set to False is missing, too."""


@dataclass(slots=True, kw_only=True)  # conventions: allow-dict -- not the missing flag  # expect: dataclass-flags
class WrongMarker:
    """The marker excuses `slots`, but `frozen` is missing."""


@dc(frozen=True)  # expect: dataclass-flags
class Aliased:
    """`dataclass` imported under another name."""
