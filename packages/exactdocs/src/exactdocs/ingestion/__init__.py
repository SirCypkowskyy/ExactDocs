"""Ingestion domain: turning a git repository into articles, chunks and tags.

Public API for the composition root (``exactdocs.bootstrap``). Other domains must not import
this package; they declare their own driven port and bootstrap wires in an adapter.
"""

from exactdocs.ingestion.module import IngestionModule, TagLocks, collect_job, import_job

__all__ = ["IngestionModule", "TagLocks", "collect_job", "import_job"]
