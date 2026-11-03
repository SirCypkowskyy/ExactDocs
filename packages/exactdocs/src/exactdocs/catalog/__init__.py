"""Catalog domain: which libraries and versions ExactDocs knows about.

Public API for the composition root (``exactdocs.bootstrap``). Other domains must not import
this package; they declare their own driven port and bootstrap wires in an adapter.
"""

from exactdocs.catalog.module import CatalogModule

__all__ = ["CatalogModule"]
