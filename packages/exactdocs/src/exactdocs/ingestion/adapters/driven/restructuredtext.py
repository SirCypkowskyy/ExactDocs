"""reStructuredText (Sphinx) articles, converted to the Markdown the chunker and the reader take.

docutils parses the file; no Sphinx build runs, nothing is executed and nothing is fetched. The
document tree is written out as CommonMark (plus tables and GitHub alerts), so chunking, heading
paths, anchors, code languages, search, the outline and ``read_article`` work as for Markdown:

- sections become ``#`` headings by their nesting, whatever adornment style each level uses;
- paragraphs, lists, definition and field lists, block quotes, tables, images, footnotes;
- ``code-block`` / ``sourcecode`` / ``code`` / ``::`` / doctest blocks become fenced code with
  their language (``highlight`` and ``conf.py``'s ``highlight_language`` for ``::`` blocks);
- ``include`` and ``literalinclude`` read other files of the repository through
  ``IncludedFiles`` (relative to the article's folder, ``/x`` from the source root, the folder of
  the nearest ``conf.py``), at most ``MAX_INCLUDE_DEPTH`` deep;
- admonitions (``note``, ``warning``, ``seealso``, ``versionadded``, ``deprecated``...) become
  GitHub alerts; ``toctree``, ``index`` and other directives with nothing to read are dropped;
- ``:ref:`` (a link when the label is in the same file), ``:doc:`` (a link to the ``.rst``
  file), ``:class:``, ``:func:``, ``:meth:`` and the other object roles (code), substitutions;
- an unknown directive keeps its argument and content as text, an unknown role its text as code,
  and each is named in the article's problems.

The directives and roles are registered with docutils once, process-wide (docutils keeps them in
module registries); they read the conversion's context from the document's settings, so
conversions in several threads do not share state.
"""

import io
import logging
import posixpath
import re
import threading
from collections import UserDict
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import docutils
from docutils import nodes, statemachine, utils
from docutils.core import publish_doctree
from docutils.parsers.rst import Directive, directives, roles
from docutils.parsers.rst.states import Inliner

from exactdocs.ingestion.constants import MAX_INCLUDE_DEPTH, MAX_MARKUP_REASON
from exactdocs.ingestion.constants._restructuredtext import (
    _ADMONITION_TITLES,
    _ADMONITIONS,
    _CALLABLE_ROLES,
    _CODE_DIRECTIVES,
    _CODE_ROLES,
    _CONF,
    _CONTENT,
    _CONTEXT_SETTING,
    _CONVERTER_VERSION,
    _DEFAULT_LANGUAGES,
    _DESCRIPTIONS,
    _DIRECTIVE_START,
    _DOCTEST_LANGUAGE,
    _DOMAINS,
    _EXPLICIT_TITLE,
    _EXTENSION_LANGUAGES,
    _HIDDEN,
    _HIGHLIGHT_ATTRIBUTE,
    _HIGHLIGHT_CONF,
    _INLINE_SPECIAL,
    _LANGUAGE_TOKEN,
    _LINE_LENGTH_LIMIT,
    _LINES_SPEC,
    _LINK_ROLES,
    _MATH_LANGUAGE,
    _MAX_FRAGMENT_DEPTH,
    _MAX_HEADING_LEVEL,
    _MAX_SOURCE_ROOT_DEPTH,
    _NBSP,
    _NO_LANGUAGE,
    _OPTION_LINE,
    _PARAGRAPH_START,
    _PY_ROLES,
    _REF_ATTRIBUTE,
    _ROLE_TEXT,
    _SLUG_DROP,
    _TEXT_ROLES,
    _TITLED_ATTRIBUTE,
    _TRANSITION,
    _UNDERSCORE_EDGE,
    _UNKNOWN_DIRECTIVE,
    _UNKNOWN_ROLE,
)
from exactdocs.ingestion.models import ConvertedArticle, IncludeRefused
from exactdocs.ingestion.ports.driven import IncludedFiles

logger = logging.getLogger(__name__)

type _Options = Mapping[str, str | None]
type _RoleResult = tuple[list[nodes.Node], list[nodes.system_message]]


class _AnyOptions(UserDict[str, Callable[[str], str]]):
    """A directive ``option_spec`` that takes every option as text: Sphinx has many we ignore.

    It is never empty (docutils reads no options for an empty spec).
    """

    def __missing__(self, key: str) -> Callable[[str], str]:
        """Take an option this spec does not name.

        Args:
            key: The option's name.

        Returns:
            docutils' converter that keeps the value as text (or None).
        """
        del key
        return directives.unchanged


_any_options = _AnyOptions({"caption": directives.unchanged})


@dataclass(slots=True, kw_only=True)  # conventions: allow-mutable-dataclass -- grows while parsing
class _Context:
    """What one conversion knows and collects; directives and roles reach it through settings."""

    path: str
    """The article's repository path."""
    files: IncludedFiles
    """Reads the files ``include`` and ``literalinclude`` name."""
    root: str = ""
    """The source root: the folder of the nearest ``conf.py`` above the article ('' for the
    repository root)."""
    highlight: str = ""
    """The language of ``::`` blocks from ``conf.py`` (empty: none)."""
    parents: dict[str, str] = field(default_factory=dict)
    """The file that included each included file."""
    unknown_directives: dict[str, None] = field(default_factory=dict)
    """Unknown directive names, in order of appearance."""
    unknown_roles: dict[str, None] = field(default_factory=dict)
    """Unknown role names, in order of appearance."""
    notes: list[str] = field(default_factory=list)
    """Other problems (an include that could not be read), in order."""
    fragments: int = 0
    """How deep the content of unknown directives is being parsed again."""

    @property
    def folder(self) -> str:
        """The article's folder ('' at the repository root)."""
        return posixpath.dirname(self.path)

    def resolve(self, target: str) -> str | None:
        """Resolve a path an article names, as Sphinx does: ``/x`` from the source root.

        Args:
            target: The path as written.

        Returns:
            The repository path, or None when it leaves the repository or is not a plain path.
        """
        target = target.strip()
        if not target or "\\" in target or not target.isprintable() or "://" in target:
            return None
        base = self.root if target.startswith("/") else self.folder
        parts = [p for p in base.split("/") if p]
        for part in target.split("/"):
            if part == "..":
                if not parts:
                    return None
                parts.pop()
            elif part not in {"", "."}:
                parts.append(part)
        if not parts or any(p.lower() == ".git" for p in parts):
            return None
        return "/".join(parts)

    def link(self, target: str) -> str:
        """Write a repository path as a link from the article (relative to its folder).

        Args:
            target: A repository path.

        Returns:
            The link target.
        """
        return posixpath.relpath(target, self.folder or ".")

    def chain(self, source: str) -> list[str]:
        """The files that led to ``source``: it, the file that included it, ... the article.

        Args:
            source: A file being read.

        Returns:
            The chain, ``source`` first.
        """
        chain = [source]
        while (parent := self.parents.get(chain[-1])) is not None and parent not in chain:
            chain.append(parent)
        return chain

    def read(self, target: str, what: str) -> str | None:
        """Read a file an include names; a refusal becomes a note.

        Args:
            target: Its repository path.
            what: The directive, for the note.

        Returns:
            The text, or None when it could not be read.
        """
        result = self.files.read(target)
        if isinstance(result, IncludeRefused):
            self.notes.append(f"{what} {target}: {result.reason}")
            return None
        return result


def _context(document: nodes.document) -> _Context:
    """Return the conversion's context from a document's settings.

    Args:
        document: The document being parsed.

    Returns:
        The context.
    """
    return getattr(document.settings, _CONTEXT_SETTING)


def _language(value: str | None) -> str:
    """Keep what a Markdown fence's info string can carry of a language name.

    Args:
        value: A language as written (``python``, ``python+sql``, ``none``).

    Returns:
        The language, or '' for none.
    """
    match = _LANGUAGE_TOKEN.search(value or "")
    if match is None or match[0].lower() in _NO_LANGUAGE:
        return ""
    return match[0]


def _code_node(text: str, language: str, caption: str | None = None) -> list[nodes.Node]:
    """Make the nodes of a code block: an optional caption, then the code.

    Args:
        text: The code.
        language: Its language ('' for none).
        caption: The block's caption, if any.

    Returns:
        The nodes.
    """
    block = nodes.literal_block(text, text)
    block["language"] = language
    if caption:
        return [nodes.paragraph("", "", nodes.emphasis(caption, caption)), block]
    return [block]


class _CodeBlock(Directive):
    """``code-block`` / ``sourcecode`` / ``code`` / ``testcode``...: a code block."""

    optional_arguments = 1
    final_argument_whitespace = False
    option_spec = _any_options
    has_content = True

    def run(self) -> list[nodes.Node]:
        """Turn the content into a code block in the argument's language.

        Returns:
            The nodes.
        """
        if self.arguments:
            language = _language(self.arguments[0])
        else:
            language = _DEFAULT_LANGUAGES.get(self.name, "")
        text = "\n".join(self.content)
        if dedent := self.options.get("dedent"):
            text = _dedent(text, dedent)
        return _code_node(text, language, self.options.get("caption"))


class _Highlight(Directive):
    """``highlight``: the language of the ``::`` blocks after it."""

    required_arguments = 1
    option_spec = _any_options

    def run(self) -> list[nodes.Node]:
        """Leave a marker the writer reads in document order.

        Returns:
            An empty comment carrying the language.
        """
        marker = nodes.comment()
        marker[_HIGHLIGHT_ATTRIBUTE] = _language(self.arguments[0])
        return [marker]


class _Hidden(Directive):
    """``toctree``, ``index``...: nothing a reader needs; its content is not indexed."""

    optional_arguments = 1
    final_argument_whitespace = True
    option_spec = _any_options
    has_content = True

    def run(self) -> list[nodes.Node]:
        """Drop the directive.

        Returns:
            Nothing.
        """
        return []


class _Content(Directive):
    """``only``, ``ifconfig``, ``container``...: the content, as if the directive were not there."""

    optional_arguments = 1
    final_argument_whitespace = True
    option_spec = _any_options
    has_content = True

    def run(self) -> list[nodes.Node]:
        """Parse the content in place (a ``tab`` starts with its name in bold).

        Returns:
            The content's nodes.
        """
        box = nodes.container()
        if self.name == "tab" and self.arguments:
            box += nodes.paragraph("", "", nodes.strong(self.arguments[0], self.arguments[0]))
        self.state.nested_parse(self.content, self.content_offset, box)
        return [box]


class _Admonition(Directive):
    """Sphinx's admonitions with a title of their own (``seealso``, ``versionadded``...).

    docutils' own ``note``, ``warning``... are kept: they make the same nodes.
    """

    optional_arguments = 1
    final_argument_whitespace = True
    option_spec = _any_options
    has_content = True

    def run(self) -> list[nodes.Node]:
        """Make an admonition titled as Sphinx titles it.

        Returns:
            The admonition.
        """
        title = _ADMONITION_TITLES[self.name]
        argument = self.arguments[0] if self.arguments else ""
        if "{}" in title:  # the version, then (maybe) the first paragraph
            version, *rest = argument.split(None, 1) or [""]
            argument = rest[0] if rest else ""
            title = title.format(version)
        box = nodes.admonition(classes=[self.name])
        box += nodes.title(title, title)
        if argument.strip():
            text, messages = self.state.inline_text(argument.strip(), self.lineno)
            box += nodes.paragraph(argument, "", *text)
            box += messages
        self.state.nested_parse(self.content, self.content_offset, box)
        return [box]


class _Description(Directive):
    """An object description (``.. class::``, ``.. py:function::``, ``.. autoclass::``...)."""

    optional_arguments = 1
    final_argument_whitespace = True
    option_spec = _any_options
    has_content = True

    def run(self) -> list[nodes.Node]:
        """Show the signature as code, then the description.

        Returns:
            A container with the signature and the content.
        """
        word = _DESCRIPTIONS.get(self.name.rsplit(":", 1)[-1], "")
        box = nodes.container(classes=["description"])
        for signature in (self.arguments[0] if self.arguments else "").splitlines():
            if not signature.strip():
                continue
            shown = f"{word}{signature.strip()}" if word == "@" else f"{word} {signature.strip()}"
            code = nodes.literal("", shown.strip())
            box += nodes.paragraph("", "", nodes.strong("", "", code))
        self.state.nested_parse(self.content, self.content_offset, box)
        return [box]


class _Include(Directive):
    """``include``: the named file's text is read as if it were written here.

    Paths are relative to the article's folder (as in Sphinx, also inside an included file), or
    to the source root with a leading ``/``. ``:literal:`` and ``:code:`` include it as code;
    ``:start-line:``, ``:end-line:``, ``:start-after:`` and ``:end-before:`` cut it.
    """

    required_arguments = 1
    final_argument_whitespace = True
    option_spec = _any_options

    def run(self) -> list[nodes.Node]:
        """Insert the file's lines into the input, or a code block for ``:literal:``/``:code:``.

        Returns:
            Nothing (the lines are parsed next), or the code block.
        """
        context = _context(self.state.document)
        name = self.arguments[0].strip()
        offset = self.lineno - self.state_machine.input_offset - 1
        current = self.state_machine.input_lines.source(offset) or context.path
        target = None if name.startswith("<") else context.resolve(name)
        chain = context.chain(current)
        refused = (
            "not a path inside the repository"
            if target is None
            else "it includes itself"
            if target in chain
            else f"more than {MAX_INCLUDE_DEPTH} levels deep"
            if len(chain) > MAX_INCLUDE_DEPTH
            else None
        )
        if refused is not None or target is None:
            context.notes.append(f"include {target or name}: {refused}")
            return []
        text = context.read(target, "include")
        if text is None:
            return []
        text = _clip(text, self.options)
        if "literal" in self.options or "code" in self.options:
            return _code_node(text, _language(self.options.get("code")))
        context.parents[target] = current
        lines = statemachine.string2lines(text, 8, convert_whitespace=True)
        self.state_machine.insert_input(lines, target)
        return []


class _LiteralInclude(Directive):
    """``literalinclude``: a file of the repository (or part of it) as a code block."""

    required_arguments = 1
    final_argument_whitespace = True
    option_spec = _any_options

    def run(self) -> list[nodes.Node]:
        """Read the file and cut it as the options say.

        Returns:
            The code block, or nothing when the file could not be read.
        """
        context = _context(self.state.document)
        name = self.arguments[0].strip()
        target = context.resolve(name)
        if target is None:
            context.notes.append(f"literalinclude {name}: not a path inside the repository")
            return []
        text = context.read(target, "literalinclude")
        if text is None:
            return []
        options = self.options
        if pyobject := options.get("pyobject"):
            text = _python_object(text, pyobject.strip())
        if lines := options.get("lines"):
            text = _lines(text, lines)
        text = _clip(text, options)
        if dedent := options.get("dedent"):
            text = _dedent(text, dedent)
        kept = (options.get("prepend"), text.rstrip("\n"), options.get("append"))
        text = "\n".join(part for part in kept if part is not None)
        if "language" in options:
            language = _language(options.get("language"))
        else:
            language = _EXTENSION_LANGUAGES.get(posixpath.splitext(target)[1].lower(), "")
        return _code_node(text, language, options.get("caption"))


def _clip(text: str, options: _Options) -> str:
    """Cut an included file as its line and marker options say.

    ``start-line``/``end-line`` first (0-based, as docutils), then ``start-after``/``start-at``
    and ``end-before``/``end-at`` (the marker's line excluded or kept).

    Args:
        text: The file's text.
        options: The directive's options.

    Returns:
        The part kept.
    """
    lines = text.splitlines()
    start, end = _number(options.get("start-line")), _number(options.get("end-line"))
    if start is not None or end is not None:
        lines = lines[start:end]
    for key, keep in (("start-after", False), ("start-at", True)):
        if marker := options.get(key):
            found = next((i for i, line in enumerate(lines) if marker in line), None)
            if found is not None:
                lines = lines[found if keep else found + 1 :]
    for key, keep in (("end-before", False), ("end-at", True)):
        if marker := options.get(key):
            found = next((i for i, line in enumerate(lines) if marker in line), None)
            if found is not None:
                lines = lines[: found + 1 if keep else found]
    return "\n".join(lines)


def _number(value: str | None) -> int | None:
    """Read a line-number option.

    Args:
        value: The option's text, if given.

    Returns:
        The number, or None when absent or not a number.
    """
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def _lines(text: str, spec: str) -> str:
    """Keep the lines ``:lines:`` names (``1,3,5-10,20-``, 1-based).

    Args:
        text: The file's text.
        spec: The option's value.

    Returns:
        The lines kept, in the order named.
    """
    lines = text.splitlines()
    kept: list[str] = []
    for item in spec.split(","):
        match = _LINES_SPEC.match(item)
        if match is None or not (match[1] or match[3]):
            continue
        first = int(match[1]) if match[1] else 1
        last = (int(match[3]) if match[3] else len(lines)) if match[2] else first
        kept.extend(lines[max(first - 1, 0) : last])
    return "\n".join(kept)


def _dedent(text: str, amount: str) -> str:
    """Remove ``amount`` leading spaces from every line (not a number: the indent they share).

    Args:
        text: The code.
        amount: The option's value.

    Returns:
        The code, dedented.
    """
    lines = text.splitlines()
    try:
        width = int(amount)
    except ValueError:
        width = min((len(x) - len(x.lstrip(" ")) for x in lines if x.strip()), default=0)
    return "\n".join(x[min(width, len(x) - len(x.lstrip(" "))) :] for x in lines)


def _python_object(text: str, name: str) -> str:
    """Keep the ``class`` or ``def`` named by ``:pyobject:`` (``Class.method`` inside a class).

    Args:
        text: A Python file's text.
        name: The object's dotted name.

    Returns:
        Its lines (decorators included), or the whole text when it is not found.
    """
    lines = text.splitlines()
    start, end, indent = 0, len(lines), -1
    for part in name.split("."):
        pattern = re.compile(rf"^(\s*)(?:async\s+)?(?:def|class)\s+{re.escape(part)}\b")
        found = next(
            (
                (i, len(m[1]))
                for i in range(start, end)
                if (m := pattern.match(lines[i])) and len(m[1]) > indent
            ),
            None,
        )
        if found is None:
            return text
        start, indent = found
        end = next(
            (
                j
                for j in range(start + 1, end)
                if lines[j].strip() and len(lines[j]) - len(lines[j].lstrip()) <= indent
            ),
            end,
        )
    while start > 0 and lines[start - 1].lstrip().startswith("@"):
        start -= 1
    while end > start and not lines[end - 1].strip():
        end -= 1
    return "\n".join(lines[start:end])


def _split_title(text: str) -> tuple[str | None, str]:
    """Split a role's ``title <target>``.

    Args:
        text: The role's text, unescaped.

    Returns:
        The explicit title (None without one) and the target.
    """
    match = _EXPLICIT_TITLE.match(text)
    if match:
        return match[1], match[2].strip()
    return None, text.strip()


def _object_name(role: str, target: str) -> str:
    """Show an object reference as Sphinx does: ``~a.b.C`` is ``C``, ``.C`` is ``C``.

    Args:
        role: The role, without its domain.
        target: The target as written.

    Returns:
        The text shown (``f()`` for a function or method).
    """
    target = target.lstrip("!")
    if target.startswith("~"):
        target = target[1:].rsplit(".", 1)[-1]
    target = target.lstrip(".")
    if role in _CALLABLE_ROLES and not target.endswith(")"):
        target += "()"
    return target


def _shown(text: str, role: str) -> str:
    """The text a role shows: its explicit title, else its target as the role shows it.

    Args:
        text: The role's text, unescaped.
        role: The role, without its domain.

    Returns:
        The text.
    """
    title, target = _split_title(text)
    if title is not None:
        return title
    return _object_name(role, target) if role in _PY_ROLES else target


def _object_role(
    name: str, rawtext: str, text: str, lineno: int, inliner: Inliner,
    options: _Options | None = None, content: Sequence[str] = (),
) -> _RoleResult:  # fmt: skip
    """``:class:``, ``:func:``, ``:meth:``... and Sphinx's code roles: the name as code.

    Args:
        name: The role as written (``py:class``).
        rawtext: The whole role.
        text: Its text.
        lineno: Its line.
        inliner: docutils' inline parser.
        options: The role's options.
        content: The role's content.

    Returns:
        A literal node, and no messages.
    """
    del lineno, inliner, options, content
    shown = _shown(utils.unescape(text), name.lower().rsplit(":", 1)[-1])
    return [nodes.literal(rawtext, shown)], []


def _text_role(
    name: str, rawtext: str, text: str, lineno: int, inliner: Inliner,
    options: _Options | None = None, content: Sequence[str] = (),
) -> _RoleResult:  # fmt: skip
    """``:term:``, ``:guilabel:``, ``:abbr:``...: the text, without its target or explanation.

    Args:
        name: The role as written.
        rawtext: The whole role.
        text: Its text.
        lineno: Its line.
        inliner: docutils' inline parser.
        options: The role's options.
        content: The role's content.

    Returns:
        A text node, and no messages.
    """
    del lineno, inliner, options, content
    shown = _shown(utils.unescape(text), "")
    if name.lower().endswith("abbr"):
        shown = re.sub(r"\s*\([^()]*\)$", "", shown)
    return [nodes.inline(rawtext, shown.replace("&", "").strip())], []


def _link_role(
    name: str, rawtext: str, text: str, lineno: int, inliner: Inliner,
    options: _Options | None = None, content: Sequence[str] = (),
) -> _RoleResult:  # fmt: skip
    """``:ref:`` and ``:numref:`` (a label), ``:doc:`` and ``:download:`` (a file).

    A ``:ref:`` is resolved once the document's sections are known (``_REF_ATTRIBUTE``); a
    ``:doc:`` links to the ``.rst`` file it names.

    Args:
        name: The role as written.
        rawtext: The whole role.
        text: Its text.
        lineno: Its line.
        inliner: docutils' inline parser.
        options: The role's options.
        content: The role's content.

    Returns:
        A reference node (plain text when the target cannot be a link), and no messages.
    """
    del lineno, options, content
    context = _context(inliner.document)
    role = name.lower().rsplit(":", 1)[-1]
    title, target = _split_title(utils.unescape(text))
    target = target.lstrip("!~")
    if role in {"ref", "numref"}:
        node = nodes.reference(rawtext, title or target)
        node[_REF_ATTRIBUTE] = target.lower()
        node[_TITLED_ATTRIBUTE] = title is not None
        return [node], []
    path = context.resolve(target if role == "download" else f"{target}.rst")
    shown = title or posixpath.basename(target) or target
    if path is None:
        return [nodes.inline(rawtext, shown)], []
    return [nodes.reference(rawtext, shown, refuri=context.link(path))], []


_registry_lock = threading.Lock()
_registered: list[str] = []


def _register() -> None:
    """Register the Sphinx directives and roles with docutils (once per process)."""
    with _registry_lock:
        if _registered:
            return
        prefixes = ("", *(f"{d}:" for d in _DOMAINS))
        role_functions = (
            (_PY_ROLES | _CODE_ROLES, _object_role),
            (_TEXT_ROLES, _text_role),
            (_LINK_ROLES, _link_role),
        )
        for names, function in role_functions:
            for name in (f"{prefix}{name}" for prefix in prefixes for name in names):
                roles.register_local_role(name, function)
        classes: tuple[tuple[Iterable[str], type[Directive]], ...] = (
            ((f"{prefix}{name}" for prefix in prefixes for name in _DESCRIPTIONS), _Description),
            (_CODE_DIRECTIVES, _CodeBlock),
            (_HIDDEN, _Hidden),
            (_CONTENT, _Content),
            (_ADMONITION_TITLES, _Admonition),
        )
        for names, directive in classes:
            for name in names:
                directives.register_directive(name, directive)
        directives.register_directive("highlight", _Highlight)
        directives.register_directive("include", _Include)
        directives.register_directive("literalinclude", _LiteralInclude)
        _registered.append(docutils.__version__)


class RestructuredTextConverter:
    """The ``MarkupConverter`` for reStructuredText: docutils in, Markdown out (module docs)."""

    def __init__(self) -> None:
        """Register the Sphinx directives and roles with docutils (once per process)."""
        _register()

    @property
    def version(self) -> str:
        """The converter's version and docutils' (its parse decides the output)."""
        return f"restructuredtext {_CONVERTER_VERSION}, docutils {docutils.__version__}"

    def convert(self, path: str, source: str, files: IncludedFiles) -> ConvertedArticle:
        """Convert one reStructuredText file; see the ``MarkupConverter`` port.

        Never raises for what the file holds: a file docutils fails on is kept verbatim as a
        code block, with a problem.

        Args:
            path: The article's repository path.
            source: Its text.
            files: Reads the files its includes name.

        Returns:
            The Markdown body and the problems.
        """
        context = _Context(path=path, files=files)
        context.root, context.highlight = _source_root(context)
        try:
            document = _parse(source, context)
            body = _Writer(context, document).write()
        except Exception:
            logger.warning("could not convert %s from reStructuredText", path, exc_info=True)
            body = _fence(source, "rst") + "\n"
            return ConvertedArticle(
                body=body, problems=("not valid reStructuredText; imported as plain text",)
            )
        return ConvertedArticle(body=body, problems=_problems(context))


def _source_root(context: _Context) -> tuple[str, str]:
    """Find the Sphinx source root: the nearest folder above the article with a ``conf.py``.

    Args:
        context: The conversion's context.

    Returns:
        The root ('' for the repository root) and ``conf.py``'s ``highlight_language``.
    """
    parts = context.folder.split("/") if context.folder else []
    for depth in range(len(parts), max(-1, len(parts) - _MAX_SOURCE_ROOT_DEPTH - 1), -1):
        folder = "/".join(parts[:depth])
        found = context.files.read(f"{folder}/{_CONF}" if folder else _CONF)
        if not isinstance(found, IncludeRefused):
            match = _HIGHLIGHT_CONF.search(found)
            return folder, _language(match[1]) if match else ""
    return "", ""


def _parse(source: str, context: _Context) -> nodes.document:
    """Parse reStructuredText with the context in the settings; nothing is read or reported.

    Args:
        source: The text.
        context: The conversion's context.

    Returns:
        The document tree.
    """
    return publish_doctree(
        source,
        source_path=context.path,
        settings_overrides={
            "report_level": 5,
            "halt_level": 5,
            "warning_stream": io.StringIO(),
            "file_insertion_enabled": False,
            "raw_enabled": False,
            "_disable_config": True,
            "doctitle_xform": False,
            "sectsubtitle_xform": False,
            "docinfo_xform": False,
            "syntax_highlight": "none",
            "smart_quotes": False,
            "pep_references": False,
            "rfc_references": False,
            "line_length_limit": _LINE_LENGTH_LIMIT,
            "input_encoding": "unicode",
            "language_code": "en",
            _CONTEXT_SETTING: context,
        },
    )


def _problems(context: _Context) -> tuple[str, ...]:
    """Say what of the file was not converted, in one line.

    Args:
        context: The conversion's context.

    Returns:
        One problem, or none.
    """
    said: list[str] = []
    if context.unknown_directives:
        said.append(f"unknown directives kept as text: {', '.join(context.unknown_directives)}")
    if context.unknown_roles:
        said.append(f"unknown roles shown as code: {', '.join(context.unknown_roles)}")
    said.extend(dict.fromkeys(context.notes))
    if not said:
        return ()
    text = "reStructuredText: " + "; ".join(said)
    if len(text) > MAX_MARKUP_REASON:
        text = text[: MAX_MARKUP_REASON - 1] + "…"
    return (text,)


def _longest_backticks(text: str) -> int:
    """Length of the longest run of backticks in ``text``.

    Args:
        text: Any text.

    Returns:
        The length (0 without backticks).
    """
    return max((len(run) for run in re.findall(r"`+", text)), default=0)


def _fence(code: str, language: str) -> str:
    """Write a fenced code block that no backtick run in the code can close.

    Args:
        code: The code.
        language: Its language ('' for none).

    Returns:
        The fenced block.
    """
    tick = "`" * max(3, _longest_backticks(code) + 1)
    code = code.strip("\n")
    return f"{tick}{language}\n{code}\n{tick}" if code else f"{tick}{language}\n{tick}"


def _code_span(text: str) -> str:
    """Write inline code that no backtick run in it can close.

    Args:
        text: The code (newlines become spaces).

    Returns:
        The code span ('' for no code).
    """
    text = text.replace("\n", " ")
    if not text:
        return ""
    tick = "`" * (_longest_backticks(text) + 1)
    pad = " " if text.startswith("`") or text.endswith("`") or text.strip() != text else ""
    return f"{tick}{pad}{text}{pad}{tick}"


def _escape(text: str) -> str:
    """Escape running text so Markdown reads it as text (newlines become spaces).

    Args:
        text: Plain text.

    Returns:
        The Markdown.
    """
    text = _INLINE_SPECIAL.sub(lambda m: "\\" + m[0], text.replace("\n", " "))
    return _UNDERSCORE_EDGE.sub(r"\\_", text)


def _slug(text: str, used: set[str]) -> str:
    """GitHub's heading slug, as the Markdown chunker and the reader compute it.

    Args:
        text: The heading's plain text.
        used: Slugs issued in this article; the new one is added.

    Returns:
        The slug, unique within the article.
    """
    base = _SLUG_DROP.sub("", text.lower()).replace(" ", "-")
    slug, n = base, 0
    while slug in used:
        n += 1
        slug = f"{base}-{n}"
    used.add(slug)
    return slug


def _prefixed(text: str, first: str, rest: str) -> str:
    """Prefix the first line of a block with ``first`` and the others with ``rest``.

    Blank lines get ``rest`` without its trailing spaces.

    Args:
        text: The block.
        first: The first line's prefix.
        rest: The other lines' prefix.

    Returns:
        The block, prefixed.
    """
    lines = text.split("\n")
    out = [first + lines[0]]
    out.extend((rest + line) if line else rest.rstrip() for line in lines[1:])
    return "\n".join(out)


def _inline_first(blocks: list[str], label: str) -> list[str]:
    """Put a label before the first block: on its line when that is a one-line paragraph.

    Args:
        blocks: The blocks.
        label: The label, as Markdown.

    Returns:
        The blocks, the label first.
    """
    if blocks and "\n" not in blocks[0] and not blocks[0].startswith(("```", ">", "- ", "|")):
        return [f"{label}: {blocks[0]}", *blocks[1:]]
    return [label, *blocks]


def _wrapped(marker: str, text: str) -> str:
    """Wrap inline Markdown in emphasis markers (spaces at its ends stay outside).

    Args:
        marker: ``*`` or ``**``.
        text: The content.

    Returns:
        The emphasis, or the text when it is blank.
    """
    stripped = text.strip()
    if not stripped:
        return text
    lead = text[: len(text) - len(text.lstrip())]
    trail = text[len(text.rstrip()) :]
    return f"{lead}{marker}{stripped}{marker}{trail}"


def _row(cells: Sequence[str]) -> str:
    """Write a pipe table row.

    Args:
        cells: The cells, as Markdown.

    Returns:
        The row.
    """
    return "| " + " | ".join(cells) + " |"


def _dedented(lines: list[str]) -> list[str]:
    """Remove the indentation the lines share.

    Args:
        lines: The lines.

    Returns:
        The lines, dedented.
    """
    width = min((len(x) - len(x.lstrip()) for x in lines if x.strip()), default=0)
    return [x[width:] for x in lines]


def _role_shown(node: nodes.problematic) -> str | None:
    """The text an unknown role shows (its title, else its target as an object name).

    Args:
        node: Markup docutils could not resolve.

    Returns:
        The text, or None when it is not a role.
    """
    match = _ROLE_TEXT.match(node.astext())
    return _shown(utils.unescape(match[2]), "obj") if match else None


def _inline_leaves(node: nodes.Node) -> Iterator[nodes.Node]:
    """Yield the text-bearing leaves of inline content (a problematic node as one leaf).

    Args:
        node: An inline element.

    Yields:
        Text nodes, literals, problematic nodes and images, in order.
    """
    for child in node.children:
        if isinstance(child, nodes.system_message):
            continue
        if isinstance(child, nodes.Text | nodes.literal | nodes.problematic | nodes.image):
            yield child
        else:
            yield from _inline_leaves(child)


class _Writer:
    """Write a docutils document as Markdown: ``_blocks`` for body elements, ``_inline`` text."""

    def __init__(self, context: _Context, document: nodes.document) -> None:
        """Prepare the writer: every section's anchor, as the chunker will compute it.

        Args:
            context: The conversion's context.
            document: The parsed document.
        """
        self._context = context
        self._document = document
        self._highlight = context.highlight
        self._anchors: dict[str, str] = {}
        self._titles: dict[str, str] = {}
        self._block_writers: dict[type, Callable[[Any, int], list[str]]] = {
            nodes.section: self._section,
            nodes.literal_block: self._code,
            nodes.doctest_block: self._code,
            nodes.math_block: self._code,
            nodes.bullet_list: self._list,
            nodes.enumerated_list: self._list,
            nodes.definition_list: self._definitions,
            nodes.field_list: self._fields,
            nodes.option_list: self._options,
            nodes.block_quote: self._quote,
            nodes.line_block: self._line_block,
            nodes.table: self._table,
            nodes.Admonition: self._admonition,
            nodes.topic: self._topic,
            nodes.sidebar: self._topic,
            nodes.rubric: self._rubric,
            nodes.transition: self._rubric,
            nodes.image: self._image_block,
            nodes.figure: self._figure,
            nodes.footnote: self._note,
            nodes.citation: self._note,
            nodes.system_message: self._message,
            nodes.comment: self._comment,
            nodes.target: self._none,
            nodes.substitution_definition: self._none,
            nodes.pending: self._none,
            nodes.raw: self._none,
            nodes.title: self._none,
            nodes.meta: self._none,
            nodes.TextElement: self._text_block,
            nodes.Element: self._container,
        }
        self._inline_writers: dict[type, Callable[[Any], str]] = {
            nodes.Text: self._text,
            nodes.literal: self._literal,
            nodes.title_reference: self._literal,
            nodes.math: self._literal,
            nodes.emphasis: self._emphasis,
            nodes.strong: self._emphasis,
            nodes.reference: self._reference,
            nodes.footnote_reference: self._bracketed,
            nodes.citation_reference: self._bracketed,
            nodes.image: self._inline_image,
            nodes.problematic: self._problematic,
            nodes.system_message: self._nothing,
            nodes.substitution_reference: self._nothing,
            nodes.Element: self._children,
        }
        used: set[str] = set()
        for section in document.findall(nodes.section):
            title = section.next_node(nodes.title)
            text = self._plain(title) if title is not None else ""
            anchor = _slug(text, used)
            for key in (*section["names"], *section["ids"]):
                self._anchors.setdefault(key, anchor)
                self._titles.setdefault(key, text)

    def write(self) -> str:
        """Write the whole document.

        Returns:
            The Markdown body, ending with a newline ('' for an empty one).
        """
        children = list(self._document.children)
        first = next((c for c in children if not isinstance(c, nodes.comment | nodes.target)), None)
        if isinstance(first, nodes.field_list):  # Sphinx's file-wide metadata (:orphan:...)
            children.remove(first)
        text = "\n\n".join(self._all(children, 0)).strip("\n")
        return text + "\n" if text else ""

    def _all(self, children: Sequence[nodes.Node], level: int) -> list[str]:
        """Write body elements in order.

        Args:
            children: The elements.
            level: The section depth they are at.

        Returns:
            Their blocks.
        """
        return [block for child in children for block in self._blocks(child, level)]

    def _blocks(self, node: nodes.Node, level: int) -> list[str]:
        """Write one body element with the writer its class (or nearest base) has.

        Args:
            node: The element.
            level: The section depth it is at.

        Returns:
            Its blocks (none for what is not shown).
        """
        for kind in type(node).__mro__:
            if (write := self._block_writers.get(kind)) is not None:
                return write(node, level)
        return [_escape(node.astext())] if node.astext().strip() else []

    def _none(self, node: nodes.Node, level: int) -> list[str]:
        """Write nothing: a target, a substitution definition, a title met on its own...

        Args:
            node: The element.
            level: The section depth.

        Returns:
            Nothing.
        """
        del node, level
        return []

    def _comment(self, node: nodes.comment, level: int) -> list[str]:
        """Write nothing; a ``highlight`` directive's marker sets the language of ``::`` blocks.

        Args:
            node: The comment.
            level: The section depth.

        Returns:
            Nothing.
        """
        del level
        if _HIGHLIGHT_ATTRIBUTE in node.attributes:
            self._highlight = node[_HIGHLIGHT_ATTRIBUTE]
        return []

    def _container(self, node: nodes.Element, level: int) -> list[str]:
        """Write an element's children (a container, compound, legend, description...).

        Args:
            node: The element.
            level: The section depth.

        Returns:
            The children's blocks.
        """
        return self._all(node.children, level)

    def _text_block(self, node: nodes.Element, level: int) -> list[str]:
        """Write a paragraph (or another text element); a start Markdown would misread is escaped.

        Args:
            node: The element.
            level: The section depth.

        Returns:
            The block.
        """
        del level
        text = self._inline(node).strip()
        return [f"\\{text}" if _PARAGRAPH_START.match(text) else text] if text else []

    def _section(self, node: nodes.section, level: int) -> list[str]:
        """Write a section: its heading, at its depth, then its body.

        Args:
            node: The section.
            level: The depth of the section around it.

        Returns:
            The blocks.
        """
        title = node.next_node(nodes.title)
        heading = self._inline(title).strip() if title is not None else ""
        hashes = "#" * min(level + 1, _MAX_HEADING_LEVEL)
        body = [c for c in node.children if not isinstance(c, nodes.title)]
        return [f"{hashes} {heading}".rstrip(), *self._all(body, level + 1)]

    def _code(self, node: nodes.Element, level: int) -> list[str]:
        """Write a code block in its language (the ``highlight`` one for a ``::`` block).

        Args:
            node: The block (a literal, doctest or math block).
            level: The section depth.

        Returns:
            The fenced block.
        """
        del level
        if isinstance(node, nodes.doctest_block):
            return [_fence(node.astext(), _DOCTEST_LANGUAGE)]
        if isinstance(node, nodes.math_block):
            return [_fence(node.astext(), _MATH_LANGUAGE)]
        language = node.get("language")
        if language is None:
            classes = [c for c in node.get("classes", []) if c != "code"]
            language = _language(classes[0]) if classes else self._highlight
        return [_fence(node.astext(), language)]

    def _list(self, node: nodes.Element, level: int) -> list[str]:
        """Write a bullet or numbered list; tight when every item is one line.

        Args:
            node: The list.
            level: The section depth.

        Returns:
            The block.
        """
        start = int(node.get("start", 1)) if isinstance(node, nodes.enumerated_list) else None
        items = []
        for n, item in enumerate(node.children):
            marker = "- " if start is None else f"{start + n}. "
            text = "\n\n".join(self._all(item.children, level))
            items.append(_prefixed(text, marker, " " * len(marker)))
        return [_joined(items)] if items else []

    def _definitions(self, node: nodes.definition_list, level: int) -> list[str]:
        """Write a definition list as a list of ``**term**: definition`` items.

        Args:
            node: The list.
            level: The section depth.

        Returns:
            The block.
        """
        items = []
        for item in node.children:
            term = "".join(
                self._inline(c) if isinstance(c, nodes.term) else f" : {self._inline(c)}"
                for c in item.children
                if isinstance(c, nodes.term | nodes.classifier)
            )
            definition = item.next_node(nodes.definition)
            blocks = self._all(definition.children, level) if definition is not None else []
            items.append(_prefixed("\n\n".join(_inline_first(blocks, f"**{term}**")), "- ", "  "))
        return [_joined(items)] if items else []

    def _fields(self, node: nodes.field_list, level: int) -> list[str]:
        """Write a field list (``:param x: ...``) as a list of ``**name**: body`` items.

        Args:
            node: The list.
            level: The section depth.

        Returns:
            The block.
        """
        items = []
        for item in node.children:
            name, body = item.next_node(nodes.field_name), item.next_node(nodes.field_body)
            label = f"**{self._inline(name).strip()}**" if name is not None else ""
            blocks = self._all(body.children, level) if body is not None else []
            items.append(_prefixed("\n\n".join(_inline_first(blocks, label)), "- ", "  "))
        return [_joined(items)] if items else []

    def _options(self, node: nodes.option_list, level: int) -> list[str]:
        """Write a command-line option list as a list of ``--opt: description`` items.

        Args:
            node: The list.
            level: The section depth.

        Returns:
            The block.
        """
        items = []
        for item in node.children:
            group, description = (
                item.next_node(nodes.option_group),
                item.next_node(nodes.description),
            )
            names = ", ".join(_code_span(o.astext()) for o in group.children) if group else ""
            blocks = self._all(description.children, level) if description is not None else []
            items.append(_prefixed("\n\n".join(_inline_first(blocks, names)), "- ", "  "))
        return [_joined(items)] if items else []

    def _quote(self, node: nodes.block_quote, level: int) -> list[str]:
        """Write a block quote (with its attribution).

        Args:
            node: The quote.
            level: The section depth.

        Returns:
            The block.
        """
        blocks = []
        for child in node.children:
            if isinstance(child, nodes.attribution):
                blocks.append(f"— {self._inline(child)}")
            else:
                blocks.extend(self._blocks(child, level))
        return [_prefixed("\n\n".join(blocks), "> ", "> ")] if blocks else []

    def _line_block(self, node: nodes.line_block, level: int) -> list[str]:
        """Write a line block: each line kept, with a hard break; nested ones indented.

        Args:
            node: The line block.
            level: The section depth.

        Returns:
            The block.
        """
        del level
        lines = self._lines(node, 0)
        return ["\\\n".join(lines)] if lines else []

    def _lines(self, node: nodes.line_block, indent: int) -> list[str]:
        """The lines of a line block, nested blocks indented with no-break spaces.

        Args:
            node: The line block.
            indent: How deep it is nested in another line block.

        Returns:
            The lines, as Markdown.
        """
        lines: list[str] = []
        for child in node.children:
            if isinstance(child, nodes.line_block):
                lines.extend(self._lines(child, indent + 1))
            elif text := self._inline(child).strip():
                lines.append(_NBSP * (2 * indent) + text)
        return lines

    def _table(self, node: nodes.table, level: int) -> list[str]:
        """Write a table as a pipe table; spanned cells are left empty.

        The first row is the header when the table has none (a pipe table needs one).

        Args:
            node: The table.
            level: The section depth.

        Returns:
            The title (if any) and the table.
        """
        del level
        group = node.next_node(nodes.tgroup)
        if not isinstance(group, nodes.tgroup):
            return []
        width = int(group.get("cols", 0)) or 1
        head = [r for t in group.children if isinstance(t, nodes.thead) for r in t.children]
        body = [r for t in group.children if isinstance(t, nodes.tbody) for r in t.children]
        grid = self._grid([*head, *body], width)
        if not grid:
            return []
        lines = [_row(grid[0]), _row(["---"] * width), *(_row(r) for r in grid[1:])]
        title = node.next_node(nodes.title)
        caption = [f"**{self._inline(title).strip()}**"] if title is not None else []
        return [*caption, "\n".join(lines)]

    def _grid(self, rows: Sequence[nodes.Node], width: int) -> list[list[str]]:
        """Lay the table's rows out on a grid, honouring row and column spans.

        Args:
            rows: The rows, header first.
            width: How many columns the table has.

        Returns:
            Each row's cells, as Markdown.
        """
        grid: list[list[str]] = []
        spanned: set[tuple[int, int]] = set()
        for r, row in enumerate(rows):
            cells = [""] * width
            column = 0
            for entry in row.children:
                while (r, column) in spanned:
                    column += 1
                if column >= width:
                    break
                cells[column] = self._cell(entry)
                across, down = int(entry.get("morecols", 0)), int(entry.get("morerows", 0))
                spanned |= {
                    (r + dr, column + dc) for dr in range(down + 1) for dc in range(across + 1)
                }
                column += across + 1
            grid.append(cells)
        return grid

    def _cell(self, entry: nodes.Node) -> str:
        """Write a table cell on one line.

        Args:
            entry: The cell.

        Returns:
            Its Markdown, with ``|`` escaped.
        """
        parts: list[str] = []
        for child in entry.children:
            if isinstance(child, nodes.paragraph):
                parts.append(self._inline(child))
            elif isinstance(child, nodes.literal_block):
                parts.append(_code_span(child.astext()))
            elif isinstance(child, nodes.bullet_list | nodes.enumerated_list):
                parts.append("; ".join(_escape(i.astext()) for i in child.children))
            else:
                parts.append(_escape(child.astext()))
        return " ".join(p.strip() for p in parts if p.strip()).replace("|", "\\|")

    def _admonition(self, node: nodes.Element, level: int) -> list[str]:
        """Write an admonition as a GitHub alert, its title (if any) in bold first.

        Args:
            node: The admonition.
            level: The section depth.

        Returns:
            The block.
        """
        kind = node.tagname
        if kind == "admonition":
            named = [c for c in node.get("classes", []) if c in _ADMONITIONS]
            kind = named[0] if named else kind
        title = node.next_node(nodes.title)
        body = self._all([c for c in node.children if not isinstance(c, nodes.title)], level)
        if title is not None:
            body = _inline_first(body, f"**{self._inline(title).strip()}**")
        alert = "\n".join([f"[!{_ADMONITIONS.get(kind, 'NOTE')}]", "\n\n".join(body)]).rstrip()
        return [_prefixed(alert, "> ", "> ")]

    def _topic(self, node: nodes.Element, level: int) -> list[str]:
        """Write a topic or sidebar: its title in bold, then its body.

        Args:
            node: The topic or sidebar.
            level: The section depth.

        Returns:
            The blocks.
        """
        if "contents" in node.get("classes", []):  # docutils' own table of contents
            return []
        title = node.next_node(nodes.title)
        heading = [f"**{self._inline(title).strip()}**"] if title is not None else []
        body = [c for c in node.children if not isinstance(c, nodes.title | nodes.subtitle)]
        return [*heading, *self._all(body, level)]

    def _rubric(self, node: nodes.Element, level: int) -> list[str]:
        """Write a rubric in bold, or a transition as a rule.

        Args:
            node: The rubric or transition.
            level: The section depth.

        Returns:
            The block.
        """
        del level
        if isinstance(node, nodes.transition):
            return [_TRANSITION]
        return [f"**{self._inline(node).strip()}**"]

    def _image_block(self, node: nodes.image, level: int) -> list[str]:
        """Write an image on its own.

        Args:
            node: The image.
            level: The section depth.

        Returns:
            The block.
        """
        del level
        return [self._image(node)]

    def _image(self, node: nodes.image) -> str:
        """Write an image, its path relative to the article (``/x``: from the source root).

        Args:
            node: The image.

        Returns:
            The Markdown image.
        """
        uri = str(node.get("uri", ""))
        if "://" not in uri and not uri.startswith("data:"):
            path = self._context.resolve(uri)
            uri = self._context.link(path) if path else uri
        alt = _escape(str(node.get("alt", "")))
        target = f"<{uri}>" if re.search(r"[\s()<>]", uri) else uri
        return f"![{alt}]({target})"

    def _figure(self, node: nodes.figure, level: int) -> list[str]:
        """Write a figure: its image, caption (in italics) and legend.

        Args:
            node: The figure.
            level: The section depth.

        Returns:
            The blocks.
        """
        blocks: list[str] = []
        for child in node.children:
            if isinstance(child, nodes.caption):
                blocks.append(_wrapped("*", self._inline(child)))
            else:
                blocks.extend(self._blocks(child, level))
        return blocks

    def _note(self, node: nodes.Element, level: int) -> list[str]:
        """Write a footnote or citation as ``[label] text``.

        Args:
            node: The footnote or citation.
            level: The section depth.

        Returns:
            The blocks.
        """
        label = node.next_node(nodes.label)
        name = f"\\[{_escape(label.astext() if label is not None else '')}\\]"
        body = self._all([c for c in node.children if not isinstance(c, nodes.label)], level)
        return [f"{name} {body[0]}", *body[1:]] if body else [name]

    def _message(self, node: nodes.system_message, level: int) -> list[str]:
        """Write what a docutils message stands for: an unknown directive's text, else nothing.

        An unknown role is collected here too (its text is written where it was used).

        Args:
            node: The message.
            level: The section depth.

        Returns:
            The unknown directive's argument and content, else nothing.
        """
        message = node.next_node(nodes.paragraph)
        said = message.astext() if message is not None else ""
        if role := _UNKNOWN_ROLE.match(said):
            self._context.unknown_roles.setdefault(role[1], None)
            return []
        directive = _UNKNOWN_DIRECTIVE.match(said)
        block = node.next_node(nodes.literal_block)
        if directive is None or block is None:
            return []
        self._context.unknown_directives.setdefault(directive[1], None)
        return self._unknown(block.astext(), level)

    def _unknown(self, text: str, level: int) -> list[str]:
        """Write an unknown directive: its argument as a paragraph, its content parsed again.

        Args:
            text: The directive's text, as docutils kept it.
            level: The section depth.

        Returns:
            The blocks.
        """
        lines = text.split("\n")
        start = _DIRECTIVE_START.match(lines[0])
        argument = start[1].strip() if start else ""
        rest = lines[1:]
        while rest and rest[0].strip() and not _OPTION_LINE.match(rest[0]):
            argument = f"{argument} {rest.pop(0).strip()}".strip()
        while rest and rest[0].strip() and _OPTION_LINE.match(rest[0]):
            rest.pop(0)
        content = "\n".join(_dedented(rest)).strip("\n")
        blocks = [_escape(argument)] if argument else []
        context = self._context
        if not content:
            return blocks
        if context.fragments >= _MAX_FRAGMENT_DEPTH:
            return [*blocks, _fence(content, "rst")]
        context.fragments += 1
        try:
            fragment = _parse(content, context)
        finally:
            context.fragments -= 1
        return [*blocks, *self._all(fragment.children, level)]

    def _inline(self, node: nodes.Node) -> str:
        """Write inline content as Markdown, with the writer its class (or nearest base) has.

        Args:
            node: A text element or inline node.

        Returns:
            The Markdown, on one line.
        """
        for kind in type(node).__mro__:
            if (write := self._inline_writers.get(kind)) is not None:
                return write(node)
        return _escape(node.astext())

    def _children(self, node: nodes.Node) -> str:
        """Write an element's inline children.

        Args:
            node: The element.

        Returns:
            The Markdown.
        """
        return "".join(self._inline(child) for child in node.children)

    def _text(self, node: nodes.Node) -> str:
        """Write text, escaped.

        Args:
            node: A text node.

        Returns:
            The Markdown.
        """
        return _escape(node.astext())

    def _literal(self, node: nodes.Node) -> str:
        """Write inline code (a literal, a default-role reference, inline math).

        Args:
            node: The node.

        Returns:
            The code span.
        """
        return _code_span(node.astext())

    def _emphasis(self, node: nodes.Node) -> str:
        """Write emphasis or strong emphasis.

        Args:
            node: The node.

        Returns:
            The Markdown.
        """
        return _wrapped("**" if isinstance(node, nodes.strong) else "*", self._children(node))

    def _bracketed(self, node: nodes.Node) -> str:
        """Write a footnote or citation reference as ``[label]``.

        Args:
            node: The reference.

        Returns:
            The Markdown.
        """
        return f"\\[{_escape(node.astext())}\\]"

    def _nothing(self, node: nodes.Node) -> str:
        """Write nothing for a message or an unresolved substitution.

        Args:
            node: The node.

        Returns:
            ''.
        """
        del node
        return ""

    def _reference(self, node: nodes.reference) -> str:
        """Write a link: a URL, a section of this article, or the text when it goes nowhere.

        Args:
            node: The reference.

        Returns:
            The Markdown.
        """
        if (label := node.get(_REF_ATTRIBUTE)) is not None:
            anchor = self._anchors.get(label)
            if anchor is None:
                return _escape(node.astext())
            text = node.astext() if node.get(_TITLED_ATTRIBUTE) else self._titles[label]
            return f"[{_escape(text)}](#{anchor})"
        text = self._children(node) or _escape(node.get("refuri", ""))
        if uri := node.get("refuri"):
            target = f"<{uri}>" if re.search(r"[\s()<>]", uri) else uri
            return f"[{text}]({target})"
        if (refid := node.get("refid")) in self._anchors:
            return f"[{text}](#{self._anchors[refid]})"
        return text

    def _inline_image(self, node: nodes.Node) -> str:
        """Write an image inside text (a substitution's image).

        Args:
            node: The image.

        Returns:
            The Markdown image.
        """
        return self._image(node) if isinstance(node, nodes.image) else ""

    def _problematic(self, node: nodes.Node) -> str:
        """Write markup docutils could not resolve: an unknown role's text as code, else as is.

        Args:
            node: The problematic markup.

        Returns:
            The Markdown.
        """
        if isinstance(node, nodes.problematic) and (shown := _role_shown(node)) is not None:
            return _code_span(shown)
        return _escape(node.astext())

    def _plain(self, node: nodes.Node) -> str:
        """The text a heading shows, as markdown-it will read it back (for its anchor).

        Args:
            node: The title.

        Returns:
            The text, stripped.
        """
        parts: list[str] = []
        for child in _inline_leaves(node):
            if isinstance(child, nodes.problematic):
                parts.append(_role_shown(child) or child.astext())
            elif isinstance(child, nodes.image):
                parts.append(str(child.get("alt", "")))
            else:
                parts.append(child.astext().replace("\n", " "))
        return "".join(parts).strip()


def _joined(items: Sequence[str]) -> str:
    """Join list items: tight when each is one line, else with blank lines between.

    Args:
        items: The items, as Markdown.

    Returns:
        The list.
    """
    return ("\n" if all("\n" not in item for item in items) else "\n\n").join(items)
