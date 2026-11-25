"""The documentation arms (#495): what the agent may use to answer, and how the judge is kept blind.

Every arm gets the same prompt, the same usage limits and the same instructions, apart from the
sentence that names its documentation tool; ``none`` has no tool and is told to answer from what
it knows or to say it does not know. The judge never learns the arm: every answer has the names of
every arm's product and tools removed before it is graded (``blind``).

Each arm with a tool gets only that tool's MCP tools (``Arm.tools``): ExactDocs as shipped, the
official Context7 MCP server (#493) and Grounded Docs' MCP server over its own index of the pinned
versions (#492). ``agent_bench.servers`` starts them.
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
    configured: bool = False
    """It runs once per configuration of its server: ExactDocs' retrieval settings
    (``--retrieval``), Grounded Docs' index (``--grounded-docs``)."""
    tools: tuple[str, ...] | None = None
    """The MCP tools the agent gets, by name; ``None``: every tool its server lists."""
    traced: bool = True
    """What the agent reads in full can be traced to the golden set's sections at a version
    (*Read the answer*, *Read another version*). Not for a service that answers from its own index
    of sources the run does not know."""

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
CONTEXT7_TOOLS: Final[tuple[str, ...]] = ("query-docs", "resolve-library-id")
"""The tools the official Context7 MCP server lists (without its research preview): all of them
are the ``context7`` arm's."""
GROUNDED_DOCS_TOOLS: Final[tuple[str, ...]] = (
    "find_version",
    "list_libraries",
    "list_pages",
    "read_page",
    "search_docs",
)
"""The ``grounded-docs`` arm's tools: what Grounded Docs lists in its read-only mode, without
``fetch_url``, which reads any web page and so would give this arm alone the web."""
GROUNDED_DOCS_OTHER_TOOLS: Final[tuple[str, ...]] = (
    "cancel_job",
    "fetch_url",
    "get_job_info",
    "list_jobs",
    "refresh_version",
    "remove_docs",
    "scrape_docs",
)
"""Grounded Docs' other tools (indexing and the web), never the agent's; hidden all the same."""
ARMS: Final[dict[str, Arm]] = {
    arm.name: arm
    for arm in (
        Arm(name=NONE, tool=None, hidden=()),
        Arm(
            name=EXACTDOCS,
            tool="ExactDocs",
            hidden=("ExactDocs", "Exact Docs", *EXACTDOCS_TOOLS),
            configured=True,
        ),
        Arm(
            name=CONTEXT7,
            tool="Context7",
            hidden=(
                "Context7",
                "Context 7",
                "context7-mcp",
                "Upstash",
                "get-library-docs",
                *CONTEXT7_TOOLS,
            ),
            tools=CONTEXT7_TOOLS,
            traced=False,
        ),
        Arm(
            name=GROUNDED_DOCS,
            tool="Grounded Docs",
            hidden=(
                "Grounded Docs",
                "grounded-docs",
                "docs-mcp-server",
                *GROUNDED_DOCS_TOOLS,
                *GROUNDED_DOCS_OTHER_TOOLS,
            ),
            configured=True,
            tools=GROUNDED_DOCS_TOOLS,
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
        ValueError: An unknown arm.
    """
    asked = {n.strip() for name in names for n in name.split(",") if n.strip()} or set(DEFAULT_ARMS)
    if unknown := sorted(asked - set(ARMS)):
        message = f"unknown arm {unknown[0]!r}; the arms are {', '.join(ARMS)}"
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
