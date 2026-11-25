"""The harnesses and their pinned CLI releases, installed from npm with their integrity checked.

Each CLI is installed once per release into ``~/.cache/exactdocs/harnesses/<harness>/<version>``
(``grounded_docs_cli.npm_install``: the registry's integrity hash in the lock file must be the
pinned one), then mounted read-only into each run's container.
"""

import hashlib
import io
import platform
import sys
import tarfile
from pathlib import Path
from typing import Final

import httpx

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
RIPGREP_VERSION: Final[str] = "14.1.1"
"""The ripgrep release every run's container gets: OpenCode's and Gemini CLI's search tools run
``rg``, and OpenCode would otherwise try to download it, which the gate refuses."""
RIPGREP_BUILDS: Final[dict[str, tuple[str, str]]] = {
    machine: (
        f"https://github.com/BurntSushi/ripgrep/releases/download/14.1.1/ripgrep-14.1.1-{build}"
        ".tar.gz",
        sha256,
    )
    for machines, build, sha256 in (
        (
            ("x86_64", "amd64"),
            "x86_64-unknown-linux-musl",
            "4cf9f2741e6c465ffdb7c26f38056a59e2a2544b51f7cc128ef28337eeae4d8e",
        ),
        (
            ("aarch64", "arm64"),
            "aarch64-unknown-linux-gnu",
            "c827481c4ff4ea10c9dc7a4022c8de5db34a5737cb74484d62eb94a95841ab2f",
        ),
    )
    for machine in machines
}
"""Its Linux builds by machine (``platform.machine()``, lower case): the URL and the SHA-256 the
release publishes; a download with another hash is refused. The x86-64 build is static; the
ARM64 one needs glibc, which the containers' Debian image has."""


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


def install_ripgrep(home: Path, *, offline: bool = False) -> Path | None:
    """Download the pinned static ripgrep (once), its hash checked.

    Args:
        home: Where the CLIs are kept (``harnesses_home``).
        offline: Download nothing; use what is there.

    Returns:
        The folder holding ``rg``; ``None`` off Linux or on a machine with no pinned build.

    Raises:
        RuntimeError: The download failed, or its hash is not the pinned one.
    """
    build = RIPGREP_BUILDS.get(platform.machine().lower())
    if sys.platform != "linux" or build is None:
        return None
    folder = home / "ripgrep" / RIPGREP_VERSION
    if (folder / "rg").exists():
        return folder
    if offline:
        message = f"ripgrep {RIPGREP_VERSION} is not in {folder} (--offline)"
        raise RuntimeError(message)
    url, sha256 = build
    try:
        response = httpx.get(url, follow_redirects=True, timeout=120)
        data = response.raise_for_status().content
    except httpx.HTTPError as error:
        message = f"ripgrep {RIPGREP_VERSION} could not be downloaded: {error}"
        raise RuntimeError(message) from error
    if hashlib.sha256(data).hexdigest() != sha256:
        message = f"ripgrep {RIPGREP_VERSION}: the download's hash is not the pinned one"
        raise RuntimeError(message)
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        member = next(m for m in archive.getmembers() if m.name.endswith("/rg") and m.isfile())
        binary = archive.extractfile(member)
        if binary is None:
            message = f"ripgrep {RIPGREP_VERSION}: no rg in the archive"
            raise RuntimeError(message)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "rg").write_bytes(binary.read())
    (folder / "rg").chmod(0o755)
    return folder
