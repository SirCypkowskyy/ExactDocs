"""Exception markers without a reason."""

from dataclasses import dataclass


@dataclass(slots=True, kw_only=True)  # conventions: allow-mutable-dataclass  # expect: exception-marker-without-reason
class NoDashes:
    """Marker without `-- reason`."""


@dataclass(slots=True, kw_only=True)  # conventions: allow-mutable-dataclass --  # expect: exception-marker-without-reason
class EmptyReason:
    """Marker with an empty reason."""
