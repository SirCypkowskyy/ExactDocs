"""The harnesses and their pinned CLI releases, installed from npm with their integrity checked.

Each CLI is installed once per release into ``~/.cache/exactdocs/harnesses/<harness>/<version>``
(``grounded_docs_cli.npm_install``: the registry's integrity hash in the lock file must be the
pinned one), then mounted read-only into each run's container.
"""

from pathlib import Path
from typing import Final

from harness_bench.claude_code import ClaudeCode
from harness_bench.codex import Codex
from harness_bench.gemini_cli import GeminiCli
from harness_bench.harness import Harness
from harness_bench.opencode import OpenCode
from retrieval_eval.golden import default_cache_dir
from retrieval_eval.grounded_docs_cli import npm_install

HARNESSES: Final[dict[str, Harness]] = {
    h.name: h for h in (ClaudeCode(), Codex(), GeminiCli(), OpenCode())
}
"""Every harness, by name: the order runs and reports use."""


def harnesses_home() -> Path:
    """Where the CLIs are installed, by default.

    Returns:
        ``<the golden cache's parent>/harnesses`` (``~/.cache/exactdocs/harnesses``).
    """
    return default_cache_dir().parent / "harnesses"


def parse_harnesses(names: list[str]) -> list[Harness]:
    """Read the harnesses a run asks for.

    Args:
        names: Harness names; each may hold several, comma-separated.

    Returns:
        The harnesses, in ``HARNESSES`` order, without repeats.

    Raises:
        ValueError: None given, or an unknown one.
    """
    asked = {n.strip() for name in names for n in name.split(",") if n.strip()}
    if not asked:
        message = f"give --harness ({', '.join(HARNESSES)})"
        raise ValueError(message)
    if unknown := sorted(asked - set(HARNESSES)):
        message = f"unknown harness {unknown[0]!r}; the harnesses are {', '.join(HARNESSES)}"
        raise ValueError(message)
    return [h for name, h in HARNESSES.items() if name in asked]


def install(harness: Harness, home: Path, *, offline: bool = False) -> Path:
    """Install a harness's pinned CLI (once), or check the one there.

    Args:
        harness: The harness.
        home: Where the CLIs are kept (``harnesses_home``).
        offline: Install nothing; use what is there.

    Returns:
        The CLI's command, ``<prefix>/node_modules/.bin/<executable>``.
    """
    release = harness.release
    return npm_install(
        home / harness.name / release.version,
        release.package,
        release.version,
        release.integrity,
        offline=offline,
        entry=f"node_modules/.bin/{release.executable}",
    )
