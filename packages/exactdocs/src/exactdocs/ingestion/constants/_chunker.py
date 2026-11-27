"""Constants of the Markdown chunker."""

import re
from typing import Final

_LINE: Final[re.Pattern[str]] = re.compile(r"[^\r\n]*(?:\r\n|\r|\n)|[^\r\n]+")
"""Markdown-it numbers lines by , and only (not U+2028, U+0085 and the like)"""
_ANCHOR_DROP: Final[re.Pattern[str]] = re.compile(r"[^\w\- ]")
"""Characters a heading anchor drops (as GitHub does)."""
_ATTRIBUTE_LIST: Final[re.Pattern[str]] = re.compile(
    r"\s*\{:?[ \t]*"
    r"(?:(?:#[\w.:-]+|\.[\w:-]+|[\w-]+=(?:\"[^\"]*\"|'[^']*'|[^\s{}\"']+))(?=[ \t}])[ \t]*)+"
    r"\}\s*$"
)
"""A heading's trailing attribute list: ``{ #id }`` (MkDocs attr_list), ``{#id}`` (Docusaurus),
``{: #id .class key=value }``. Only ids, classes and ``key=value`` count, so ``{}`` or ``{1, 2}``
stay text. Each item ends at a blank or the ``}``, so a run of characters splits into items one
way only (no exponential backtracking). The web reader's ``parse.ts`` has the same pattern."""
_ATTRIBUTE_ID: Final[re.Pattern[str]] = re.compile(r"(?<![^\s{:])#([\w.:-]+)")
"""An ``#id`` in an attribute list, not one inside a quoted value (the last one wins)."""
_LANGUAGE: Final[re.Pattern[str]] = re.compile(r"[\w+#-]+")
"""`python{1,3}` and `{.python}` both name python."""
_HTML_TAG: Final[re.Pattern[str]] = re.compile(
    r"<(/?)([A-Za-z][\w.:-]*)((?:[^<>\"'{}]|\"[^\"]*\"|'[^']*'|\{[^{}]*\})*)>"
)
"""An HTML or JSX tag: closing slash, name, then the attributes (quoted values and ``{...}``
expressions may hold ``>``), a self-closing one ending in ``/``."""
_BLOCK_TAGS: Final[frozenset[str]] = frozenset(
    {
        "address",
        "article",
        "aside",
        "audio",
        "blockquote",
        "center",
        "details",
        "dialog",
        "div",
        "dl",
        "fieldset",
        "figure",
        "footer",
        "form",
        "header",
        "main",
        "nav",
        "ol",
        "picture",
        "pre",
        "section",
        "table",
        "ul",
        "video",
    }
)
"""HTML tags a section is never split inside: block containers whose end tag is never left out
(unlike ``p``, ``li`` or ``td``). A JSX component (a capitalised name, as MDX's ``<Tabs>``) counts
too."""
_HTML_COMMENT: Final[re.Pattern[str]] = re.compile(r"<!--.*?-->", re.DOTALL)
"""An HTML comment: the tags in it do not count."""
