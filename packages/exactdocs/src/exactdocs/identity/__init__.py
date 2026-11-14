"""Identity domain: who may use this instance (local accounts, sessions and API tokens).

Public API for the composition root (``exactdocs.bootstrap``). Other domains must not import
this package; they declare their own driven port and bootstrap wires in an adapter.
"""

from exactdocs.identity.module import IdentityModule

__all__ = ["IdentityModule"]
