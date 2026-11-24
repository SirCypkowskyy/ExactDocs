"""Usage domain (#510): daily counts of reads, searches and answers, reports and leaderboards.

Public API for the composition root (``exactdocs.bootstrap``). Other domains must not import
this package: bootstrap counts the requests their driving adapters serve.
"""

from exactdocs.usage.module import UsageModule

__all__ = ["UsageModule"]
