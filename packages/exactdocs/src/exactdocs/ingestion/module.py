"""Wiring of the ingestion domain.

It has no use cases yet: the parser in ``models`` is pure and the import use cases arrive with
E1-05 and E3-05a, which add their driven adapters and driving ports here.
"""

from dataclasses import dataclass
from typing import Self


@dataclass(frozen=True, slots=True, kw_only=True)
class IngestionModule:
    """The ingestion's driving ports, ready to be exposed by driving adapters."""

    @classmethod
    def build(cls) -> Self:
        """Assemble the use cases around the given driven adapters."""
        return cls()
