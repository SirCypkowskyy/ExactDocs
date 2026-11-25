"""The documentation arms (#495): what the agent may use to answer, and how the judge is kept blind.

Every arm gets the same prompt, the same usage limits and the same instructions, apart from the
sentence that names its documentation tool; ``none`` has no tool and is told to answer from what
it knows or to say it does not know. The judge never learns the arm: every answer has the names of
every arm's product and tools removed before it is graded (``blind``).

``context7`` (#493) and ``grounded-docs`` (#492) are declared here so that their names are hidden
from the judge today and the command line knows them; their toolsets are not built yet
(``Arm.planned``).
"""

import re
from dataclasses import dataclass
from typing import Final

NONE: Final[str] = "none"
"""The control arm: no tools."""
EXACTDOCS: Final[str] = "exactdocs"
"""ExactDocs as shipped, ``exactdocs serve --stdio``."""
CONTEXT7: Final[str] = "context7"
"""The official Context7 MCP server (#493)."""
GROUNDED_DOCS: Final[str] = "grounded-docs"
"""Grounded Docs' MCP server over its own index (#492)."""

INSTRUCTIONS: Final[str] = """\
You help a developer with the libraries their project depends on. {source}

Answer the question briefly. Do not answer from another version of the library than the one the \
project uses."""
"""The agent's instructions, the same for every arm and model apart from ``{source}``."""
TOOL_SOURCE: Final[str] = """\
Your only source of documentation is the {tool} tools: find the library, search the \
documentation of exactly the version the project uses, and read the sections you need before \
answering. Answer from what you read, not from memory. If the documentation of that version does \
not answer the question, say that the documentation does not cover it."""
"""The source sentence of an arm with a documentation tool: only the tool's name differs."""
NO_TOOL_SOURCE: Final[str] = """\
You have no tools and no documentation: answer from what you know about the version the project \
uses. If you do not know what that version does, say that you do not know."""
"""The source sentence of the ``none`` arm."""
REDACTED: Final[str] = "[redacted]"
"""What a hidden name becomes in the answer the judge reads."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Arm:
    """One documentation arm."""

    name: str
    """Its name on the command line and in the report."""
    tool: str | None
    """The documentation tool the instructions name; ``None`` for no tool."""
    hidden: tuple[str, ...]
    """Product and tool names removed from every answer before the judge reads it."""
    retrieval: bool = False
    """It runs once per retrieval configuration (ExactDocs' own settings)."""
    planned: str | None = None
    """The issue that builds its toolset, while it is not built; ``None`` once it runs."""

    @property
    def instructions(self) -> str:
        """The agent's instructions for this arm.

        Returns:
            ``INSTRUCTIONS`` with the arm's source sentence.
        """
        source = NO_TOOL_SOURCE if self.tool is None else TOOL_SOURCE.format(tool=self.tool)
        return INSTRUCTIONS.format(source=source)


EXACTDOCS_TOOLS: Final[tuple[str, ...]] = (
    "article_outline",
    "list_articles",
    "list_libraries",
    "query-docs",
    "read_article",
    "read_chunk",
    "resolve-library-id",
    "search_all_docs",
    "search_docs",
    "view_article",
    "view_search",
)
"""ExactDocs' MCP tools (tests/bootstrap/snapshots/mcp_tools.json)."""
ARMS: Final[dict[str, Arm]] = {
    arm.name: arm
    for arm in (
        Arm(name=NONE, tool=None, hidden=()),
        Arm(
            name=EXACTDOCS,
            tool="ExactDocs",
            hidden=("ExactDocs", "Exact Docs", *EXACTDOCS_TOOLS),
            retrieval=True,
        ),
        Arm(
            name=CONTEXT7,
            tool="Context7",
            hidden=(
                "Context7",
                "Context 7",
                "resolve-library-id",
                "get-library-docs",
                "query-docs",
            ),
            planned="#493",
        ),
        Arm(
            name=GROUNDED_DOCS,
            tool="Grounded Docs",
            hidden=(
                "Grounded Docs",
                "grounded-docs",
                "docs-mcp-server",
                "search_docs",
                "list_libraries",
                "find_version",
                "fetch_url",
                "scrape_docs",
            ),
            planned="#492",
        ),
    )
}
"""Every arm, by name: the order runs and reports use."""
DEFAULT_ARMS: Final[tuple[str, ...]] = (NONE, EXACTDOCS)
"""The arms a run compares when none is given."""
BASELINES: Final[tuple[str, ...]] = (NONE, EXACTDOCS)
"""The arms every other arm is compared with, on the same cases."""


def parse_arms(names: list[str]) -> list[Arm]:
    """Read the arms a run asks for.

    Args:
        names: Arm names; each may hold several, comma-separated.

    Returns:
        The arms, in ``ARMS`` order, without repeats; ``DEFAULT_ARMS`` when none is given.

    Raises:
        ValueError: An unknown arm, or one whose toolset is not built yet.
    """
    asked = {n.strip() for name in names for n in name.split(",") if n.strip()} or set(DEFAULT_ARMS)
    for name in sorted(asked):
        arm = ARMS.get(name)
        if arm is None:
            message = f"unknown arm {name!r}; the arms are {', '.join(ARMS)}"
            raise ValueError(message)
        if arm.planned:
            message = f"the {name} arm is not built yet ({arm.planned})"
            raise ValueError(message)
    return [arm for name, arm in ARMS.items() if name in asked]


def _pattern(names: tuple[str, ...]) -> re.Pattern[str]:
    """Match any of the names as a whole word, longest first, ignoring case.

    Args:
        names: The names.

    Returns:
        The pattern.
    """
    ordered = sorted(set(names), key=lambda n: (-len(n), n))
    words = "|".join(re.escape(n) for n in ordered)
    return re.compile(rf"(?<![\w-])(?:{words})(?![\w-])", re.IGNORECASE)


HIDDEN: Final[re.Pattern[str]] = _pattern(tuple(n for arm in ARMS.values() for n in arm.hidden))
"""Every arm's hidden names: the same are removed from every answer, whatever its arm."""


def blind(answer: str) -> str:
    """Remove every arm's product and tool names from an answer, for the judge.

    Args:
        answer: The agent's answer.

    Returns:
        The answer with each such name replaced by ``REDACTED``.
    """
    return HIDDEN.sub(REDACTED, answer)
