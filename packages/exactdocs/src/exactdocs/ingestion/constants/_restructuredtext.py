"""Constants of reStructuredText (Sphinx) articles and of their converter to Markdown (#435)."""

import re
from typing import Final

MARKDOWN_SUFFIXES: Final[tuple[str, ...]] = (".md", ".mdx")
"""File suffixes of Markdown articles."""
RESTRUCTUREDTEXT_SUFFIXES: Final[tuple[str, ...]] = (".rst", ".txt")
"""File suffixes of reStructuredText articles (a ``.txt`` file only when a path names it)."""
EXPLICIT_SUFFIXES: Final[tuple[str, ...]] = (".txt",)
"""Suffixes that make a file an article only when an include pattern names the suffix
(``doc/**/*.txt``, ``doc/index.txt``): a folder pattern alone does not take them."""
MAX_INCLUDES: Final[int] = 64
"""Files one reStructuredText article may include (``include``, ``literalinclude``), its source
root's ``conf.py`` counted; more are left out with a problem."""
MAX_INCLUDE_DEPTH: Final[int] = 8
"""How deep ``include`` directives may nest (a file included by an included file is depth 2)."""
_MAX_FRAGMENT_DEPTH: Final[int] = 8
"""How deep the content of unknown directives is parsed again inside each other."""
_MAX_SOURCE_ROOT_DEPTH: Final[int] = 16
"""Folders above an article looked in for the Sphinx ``conf.py`` that marks its source root."""
MAX_MARKUP_REASON: Final[int] = 500
"""Longest text of an article's markup problem, in characters."""
_CONVERTER_VERSION: Final[int] = 1
"""Bump on any change to how reStructuredText is written as Markdown: it is part of a converted
article's key, so every such article is converted and chunked again at its next import."""
_CONF: Final[str] = "conf.py"
"""The Sphinx configuration file: its folder is the source root (``/x`` paths start there)."""
_HIGHLIGHT_CONF: Final[re.Pattern[str]] = re.compile(
    r"^highlight_language\s*=\s*['\"]([\w+#.-]+)['\"]", re.MULTILINE
)
"""``highlight_language = "python"`` in ``conf.py``: read as text, never executed."""
_LANGUAGE_TOKEN: Final[re.Pattern[str]] = re.compile(r"[\w+#.-]+")
"""A code block's language: what a Markdown fence's info string may carry."""
_EXPLICIT_TITLE: Final[re.Pattern[str]] = re.compile(r"^(.+?)\s*<([^<>]*)>$", re.DOTALL)
"""A role's ``title <target>`` (Sphinx's ``explicit_title_re``)."""
_ROLE_TEXT: Final[re.Pattern[str]] = re.compile(r"^:([\w:+.-]+):`(.*)`$", re.DOTALL)
"""The raw text of an interpreted-text role, as docutils keeps it for an unknown one."""
_UNKNOWN_DIRECTIVE: Final[re.Pattern[str]] = re.compile(r'^Unknown directive type "([^"]+)"\.')
"""docutils' message for a directive it has no class for (English: the parser's language)."""
_UNKNOWN_ROLE: Final[re.Pattern[str]] = re.compile(r'^Unknown interpreted text role "([^"]+)"\.')
"""docutils' message for a role it has no function for."""
_DIRECTIVE_START: Final[re.Pattern[str]] = re.compile(r"^\s*\.\.\s+[\w:+.-]+::[ \t]*(.*)$")
"""The first line of a directive: its arguments follow the ``::``."""
_OPTION_LINE: Final[re.Pattern[str]] = re.compile(r"^\s*:[\w-]+:(\s|$)")
"""A directive option line (``:linenos:``, ``:caption: x``)."""
_LINES_SPEC: Final[re.Pattern[str]] = re.compile(r"^\s*(\d*)\s*(-?)\s*(\d*)\s*$")
"""One item of ``literalinclude``'s ``:lines:`` (``3``, ``3-5``, ``3-``, ``-5``)."""
_SLUG_DROP: Final[re.Pattern[str]] = re.compile(r"[^\w\- ]")
"""Characters a heading anchor drops (as GitHub does, and the Markdown chunker)."""
_PARAGRAPH_START: Final[re.Pattern[str]] = re.compile(
    r"^(?:[#>+=|~-]|\d{1,9}[.)](?:\s|$)|\*(?:\s|$))"
)
"""A paragraph start Markdown would read as a heading, quote, list, rule or table: escaped."""
_INLINE_SPECIAL: Final[re.Pattern[str]] = re.compile(r"[\\`*\[\]]|<(?=[A-Za-z/!?])|&(?=#?\w+;)")
"""Characters escaped in running text so it stays text in Markdown."""
_UNDERSCORE_EDGE: Final[re.Pattern[str]] = re.compile(r"(?<![^\W_])_|_(?![^\W_])")
"""An underscore not inside a word (``_private``, ``x_``): it could open or close emphasis."""
_PY_ROLES: Final[frozenset[str]] = frozenset(
    {
        "class",
        "func",
        "meth",
        "attr",
        "mod",
        "obj",
        "exc",
        "data",
        "const",
        "any",
        "type",
        "member",
        "var",
        "macro",
        "struct",
        "enum",
        "enumerator",
        "expr",
        "texpr",
        "decorator",
        "property",
    }
)
"""Cross-reference roles to Python (and C/C++/JavaScript) objects: shown as code."""
_CALLABLE_ROLES: Final[frozenset[str]] = frozenset({"func", "meth"})
"""Roles Sphinx shows with ``()`` after the name (``add_function_parentheses``)."""
_DOMAINS: Final[tuple[str, ...]] = ("py", "c", "cpp", "js", "rst", "std")
"""Domain prefixes a role or directive may carry (``:py:class:``, ``.. py:function::``)."""
_CODE_ROLES: Final[frozenset[str]] = frozenset(
    {
        "command",
        "envvar",
        "file",
        "kbd",
        "keyword",
        "makevar",
        "mimetype",
        "option",
        "program",
        "regexp",
        "samp",
        "token",
        "manpage",
        "code",
    }
)
"""Sphinx roles whose text is shown as code."""
_TEXT_ROLES: Final[frozenset[str]] = frozenset(
    {"term", "dfn", "guilabel", "menuselection", "abbr", "sub", "sup", "subscript", "superscript"}
)
"""Sphinx roles whose text is shown as plain text (``abbr``: without its explanation)."""
_LINK_ROLES: Final[frozenset[str]] = frozenset({"ref", "numref", "doc", "download"})
"""Roles that point at a section label or another document."""
_ADMONITIONS: Final[dict[str, str]] = {
    "note": "NOTE",
    "tip": "TIP",
    "hint": "TIP",
    "important": "IMPORTANT",
    "warning": "WARNING",
    "attention": "WARNING",
    "caution": "CAUTION",
    "danger": "CAUTION",
    "error": "CAUTION",
    "admonition": "NOTE",
    "seealso": "NOTE",
    "todo": "NOTE",
    "versionadded": "NOTE",
    "versionchanged": "NOTE",
    "versionremoved": "WARNING",
    "deprecated": "WARNING",
}
"""Admonition kinds and the GitHub alert each becomes (the web reader renders those)."""
_ADMONITION_TITLES: Final[dict[str, str]] = {
    "seealso": "See also",
    "todo": "Todo",
    "versionadded": "Added in version {}",
    "versionchanged": "Changed in version {}",
    "versionremoved": "Removed in version {}",
    "deprecated": "Deprecated since version {}",
}
"""The title Sphinx gives the admonitions that have one of their own."""
_DESCRIPTIONS: Final[dict[str, str]] = {
    "class": "class",
    "exception": "exception",
    "function": "",
    "method": "",
    "classmethod": "classmethod",
    "staticmethod": "staticmethod",
    "attribute": "attribute",
    "property": "property",
    "data": "data",
    "decorator": "@",
    "decoratormethod": "@",
    "member": "",
    "macro": "macro",
    "type": "type",
    "var": "",
    "struct": "struct",
    "enum": "enum",
    "envvar": "",
    "option": "",
    "describe": "",
    "object": "",
    "autoclass": "class",
    "autoexception": "exception",
    "autofunction": "",
    "automethod": "",
    "autoattribute": "attribute",
    "autoproperty": "property",
    "autodata": "data",
    "autodecorator": "@",
    "automodule": "module",
    "module": "module",
}
"""Object descriptions (Python domain, autodoc) and the word shown before their signature."""
_HIDDEN: Final[frozenset[str]] = frozenset(
    {
        "toctree",
        "index",
        "contents",
        "currentmodule",
        "tabularcolumns",
        "sectionauthor",
        "moduleauthor",
        "codeauthor",
        "testsetup",
        "testcleanup",
        "autosummary",
        "default-role",
        "default-domain",
        "meta",
        "raw",
    }
)
"""Directives with nothing to read: a table of contents, an index entry, settings, raw output."""
_CONTENT: Final[frozenset[str]] = frozenset(
    {"only", "ifconfig", "centered", "hlist", "container", "compound", "glossary", "tab", "tabs"}
)
"""Directives whose content is read as it is, the directive itself adding nothing."""
_CODE_DIRECTIVES: Final[frozenset[str]] = frozenset(
    {"code-block", "sourcecode", "code", "testcode", "testoutput", "doctest", "productionlist"}
)
"""Directives whose content is a code block (in the argument's language, if any)."""
_DEFAULT_LANGUAGES: Final[dict[str, str]] = {
    "testcode": "python",
    "doctest": "pycon",
    "testoutput": "text",
    "productionlist": "text",
}
"""The language of a code directive that names none."""
_EXTENSION_LANGUAGES: Final[dict[str, str]] = {
    ".py": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".ini": "ini",
    ".cfg": "ini",
    ".sh": "bash",
    ".bash": "bash",
    ".sql": "sql",
    ".html": "html",
    ".xml": "xml",
    ".css": "css",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".rs": "rust",
    ".go": "go",
    ".java": "java",
    ".rb": "ruby",
    ".feature": "gherkin",
    ".rst": "rst",
    ".md": "markdown",
    ".txt": "text",
}
"""A ``literalinclude`` without ``:language:`` gets the language of its file's suffix."""
_NO_LANGUAGE: Final[frozenset[str]] = frozenset({"default", "none", "guess"})
"""Highlight settings that name no language: the code block gets none."""
_DOCTEST_LANGUAGE: Final[str] = "pycon"
"""The language of a doctest block (``>>> ``) in the output."""
_MATH_LANGUAGE: Final[str] = "math"
"""The fence info of a math block."""
_HIGHLIGHT_ATTRIBUTE: Final[str] = "exactdocs_highlight"
"""Marks the comment node a ``highlight`` directive leaves: the language of the ``::`` blocks
after it."""
_REF_ATTRIBUTE: Final[str] = "exactdocs_ref"
"""Marks a reference made by ``:ref:``: the label, resolved once the document's sections are
known."""
_NBSP: Final[str] = "\N{NO-BREAK SPACE}"
"""Indents the lines of a nested line block (Markdown keeps it; a space it would drop)."""
_TITLED_ATTRIBUTE: Final[str] = "exactdocs_titled"
"""Marks a ``:ref:`` reference that has an explicit title (else the section's title is shown)."""
_CONTEXT_SETTING: Final[str] = "exactdocs_context"
"""The docutils setting that carries a conversion's context to the directives and roles."""
_TRANSITION: Final[str] = "* * *"
"""A transition: never ``---``, so a body never starts with what looks like front matter."""
_MAX_HEADING_LEVEL: Final[int] = 6
"""Markdown's deepest heading; deeper sections are shown at this level."""
_LINE_LENGTH_LIMIT: Final[int] = 100_000
"""Longest line docutils accepts, in characters (its default of 10,000 refuses minified data)."""
