"""A project's guide pinned at two versions, for the text scorer's tests (pytest and behave).

``Install`` is the same in v1 and v2, ``Configure`` changed in v2 and ``Lifespan`` exists only in
v2, so a text result can be of one version, of both, or of the other.
"""

from retrieval_eval.text_match import SectionIndex

INSTALL = """## Install

Run pip to install the demo package from the package index. It needs Python 3.12 or newer and
pulls in no other dependency, so the install takes a few seconds on any machine.
"""

CONFIGURE_V1 = """## Configure

Set the `timeout` option in the [settings file](settings.md). The timeout is counted in seconds
and defaults to thirty; a value of zero turns it off entirely.

- Every request waits at most that long for an answer.
- A request that runs out of time fails with a timeout error and is never retried.
"""

CONFIGURE_V2 = """## Configure

Pass a `Settings` object to the client instead of writing a settings file. Its `deadline` field
replaces the old timeout and is counted in milliseconds, with no default at all.

- A request without a deadline waits until the server answers.
- Retries are configured on the same object, with a back-off between attempts.
"""

LIFESPAN = """## Lifespan

Open the client in an async context manager: it connects on entry and closes every pooled
connection on exit, even when the block raises.
"""

INTRO = """# Guide

The demo package talks to the demo server and hands back plain Python objects.

"""


def two_version_corpus() -> dict[str, dict[str, str]]:
    """The guide at both versions.

    Returns:
        Each version's articles: ``docs/guide.md`` and its Markdown.
    """
    return {
        "v1": {"docs/guide.md": f"{INTRO}{INSTALL}\n{CONFIGURE_V1}"},
        "v2": {"docs/guide.md": f"{INTRO}{INSTALL}\n{CONFIGURE_V2}\n{LIFESPAN}"},
    }


def two_version_index() -> SectionIndex:
    """Index the guide at both versions.

    Returns:
        The index, at the scorer's threshold.
    """
    return SectionIndex.build(two_version_corpus())
