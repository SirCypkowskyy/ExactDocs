"""Constants of the sources file (``exactdocs.sources.yaml``): its limits and ref shapes."""

import re
from typing import Final

MAX_SOURCES: Final[int] = 300
"""Libraries one sources file (one plan or apply request) may declare."""
MAX_SOURCE_REFS: Final[int] = 100
"""Refs one library of a sources file may declare."""
MAX_SOURCE_TITLE: Final[int] = 120
"""Longest title a sources file may declare for a library, in characters."""
MAX_SOURCE_DESCRIPTION: Final[int] = 500
"""Longest description a sources file may declare for a library, in characters."""
MAX_SOURCE_REF: Final[int] = 255
"""Longest ref a sources file may declare, in characters."""
FULL_SHA: Final[re.Pattern[str]] = re.compile(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}")
"""A full commit SHA (SHA-1 or SHA-256): a declared ref that names a commit."""
SHORT_SHA: Final[re.Pattern[str]] = re.compile(r"(?=[^a-fA-F]*[a-fA-F])(?=\D*\d)[0-9a-fA-F]{7,63}")
"""Hex with both a letter and a digit, shorter than a full SHA: an abbreviated commit, refused.

A short SHA resolves to the full one, so the version would never carry the declared name and
every plan would show it again. Only digits (``20240101``) or only letters (``deadbeef``) can be
a tag or a branch name and are allowed.
"""
SOURCE_MISMATCH: Final[str] = "source_mismatch"
"""The code of a declared library whose ID exists with another repository URL."""
SOURCES_SCHEMA_DIALECT: Final[str] = "https://json-schema.org/draft/2020-12/schema"
"""The JSON Schema dialect of the sources file's schema (what pydantic generates)."""
SOURCES_SCHEMA_TITLE: Final[str] = "ExactDocs sources file (exactdocs.sources.yaml)"
"""The title of the sources file's JSON Schema, as editors show it."""
