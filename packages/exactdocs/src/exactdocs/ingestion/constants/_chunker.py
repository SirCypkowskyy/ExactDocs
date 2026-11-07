"""Constants of the Markdown chunker."""

import re
from typing import Final

_LINE: Final[re.Pattern[str]] = re.compile(r"[^\r\n]*(?:\r\n|\r|\n)|[^\r\n]+")
"""Markdown-it numbers lines by , and only (not U+2028, U+0085 and the like)"""
_ANCHOR_DROP: Final[re.Pattern[str]] = re.compile(r"[^\w\- ]")
"""Characters a heading anchor drops (as GitHub does)."""
_LANGUAGE: Final[re.Pattern[str]] = re.compile(r"[\w+#-]+")
"""`python{1,3}` and `{.python}` both name python."""
