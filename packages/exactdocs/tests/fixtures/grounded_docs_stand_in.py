"""A stand-in Grounded Docs that replays recorded responses (pytest and behave, #492).

``grounded_docs_responses.json`` holds what Grounded Docs 3.4.1's ``search_docs`` really returned:
on ``retrieval_bench_stand_ins.tiny_corpus`` in both configurations (recorded through
``just grounded-bench``'s own code), and on three synthetic pages for the parser (``multi``); the
corpus folder's path is replaced by ``file:///corpus``. The stand-in "indexes" a folder by listing
it, embeds through the run's embedding endpoint when the configuration has one (as Grounded Docs
does), and answers a question with its recorded response, or with "No results found".
"""

import contextlib
import hashlib
import json
from collections.abc import AsyncGenerator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from retrieval_eval.grounded_docs import EMBEDDING_MODEL, NO_RESULTS
from retrieval_eval.grounded_docs_cli import Search, Stored
from retrieval_eval.openai_embeddings import LocalEmbedding

RESPONSES = Path(__file__).parent / "grounded_docs_responses.json"
FULL_TEXT = "full-text"
EMBEDDING = EMBEDDING_MODEL.split("/")[-1]


def recorded() -> dict[str, dict[str, str]]:
    """The recorded responses.

    Returns:
        Each configuration's (or ``multi``'s) response text by query.
    """
    return json.loads(RESPONSES.read_text(encoding="utf-8"))["responses"]


def _vector(text: str) -> list[float]:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return [b / 255 for b in digest[:8]]


def stand_in_embedding(model: str = EMBEDDING_MODEL) -> LocalEmbedding:
    """An embedding model that hashes text: what the endpoint serves in a test.

    Args:
        model: The name it answers to.

    Returns:
        The model (8 dimensions, a token per word).
    """
    return LocalEmbedding(
        model=model,
        revision="stand-in",
        dimensions=8,
        embed=lambda texts: [_vector(t) for t in texts],
        count=lambda texts: sum(len(t.split()) for t in texts),
    )


async def _embed(base_url: str, texts: Sequence[str], model: str) -> None:
    """Embed texts through the run's endpoint, as Grounded Docs' OpenAI client does.

    Args:
        base_url: ``OPENAI_API_BASE``.
        texts: The texts.
        model: ``DOCS_MCP_EMBEDDING_MODEL``.
    """
    body = {"input": list(texts), "model": model, "encoding_format": "float"}
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(f"{base_url}/embeddings", json=body)
    response.raise_for_status()
    assert len(response.json()["data"]) == len(texts)


def _pages(folder: Path, leave_out: frozenset[str]) -> dict[str, str]:
    """The files a folder holds, as Grounded Docs would store them.

    Args:
        folder: The folder.
        leave_out: Repository paths left out.

    Returns:
        Each file's ``file://`` URL and text.
    """
    return {
        f.as_uri(): f.read_text(encoding="utf-8")
        for f in sorted(folder.rglob("*"))
        if f.is_file() and f.relative_to(folder).as_posix() not in leave_out
    }


def _write(path: Path, data: bytes) -> None:
    """Write a data directory's database file.

    Args:
        path: The file.
        data: Its bytes.
    """
    path.write_bytes(data)


@dataclass(slots=True, kw_only=True)  # conventions: allow-mutable-dataclass -- records its calls
class ReplayingGroundedDocs:
    """Implements ``grounded_docs_cli.GroundedDocs`` from the recorded responses."""

    leave_out: frozenset[str] = frozenset()
    """Repository paths it does not index (as its default exclusions would)."""
    fail: frozenset[str] = frozenset()
    """Queries whose search fails."""
    indexed: list[tuple[str, str, tuple[int, int]]] = field(default_factory=list)
    """Every ``(library, version, (depth, pages))`` it was asked to index."""
    stores: dict[Path, dict[tuple[str, str], Stored]] = field(default_factory=dict)
    """What each data directory holds."""
    responses: dict[str, dict[str, str]] = field(default_factory=recorded)
    """The recorded responses."""

    def describe(self) -> dict[str, str]:
        """Name what runs.

        Returns:
            A stand-in's Node.js version.
        """
        return {"node": "v22.0.0 (stand-in)"}

    async def settings(self, store: Path, variables: Mapping[str, str]) -> dict[str, object]:
        """The settings in effect, as ``docs-mcp-server config`` prints a part of them.

        Args:
            store: The data directory.
            variables: The configuration's environment variables.

        Returns:
            The settings.
        """
        model = variables.get("DOCS_MCP_EMBEDDING_MODEL", "text-embedding-3-small")
        return {
            "app": {"storePath": str(store), "embeddingModel": model, "telemetryEnabled": False},
            "scraper": {"maxDepth": 3, "maxPages": 1000},
        }

    async def index(
        self,
        store: Path,
        variables: Mapping[str, str],
        version: tuple[str, str],
        folder: Path,
        limits: tuple[int, int],
    ) -> None:
        """List the folder's files as the version's pages; embed them when there is a model.

        Args:
            store: The data directory.
            variables: The configuration's environment variables.
            version: The library and version names.
            folder: The folder.
            limits: The crawl's maximum depth and pages.
        """
        self.indexed.append((*version, limits))
        files = _pages(folder, self.leave_out)
        if base := variables.get("OPENAI_API_BASE"):
            await _embed(base, list(files.values()), variables["DOCS_MCP_EMBEDDING_MODEL"])
        embedded = len(files) if "OPENAI_API_BASE" in variables else 0
        self.stores.setdefault(store, {})[version] = Stored(
            pages=frozenset(files), chunks=len(files), embedded=embedded
        )
        _write(store / "documents.db", b"stand-in" * len(self.stores[store]))

    def stored(self, store: Path) -> dict[tuple[str, str], Stored]:
        """What a data directory holds.

        Args:
            store: The data directory.

        Returns:
            Each library version's pages.
        """
        return dict(self.stores.get(store, {}))

    @contextlib.asynccontextmanager
    async def serving(self, store: Path, variables: Mapping[str, str]) -> AsyncGenerator[Search]:
        """Answer questions with the recorded responses of the configuration.

        Args:
            store: The data directory.
            variables: The configuration's environment variables.

        Yields:
            The search.
        """
        name = EMBEDDING if "DOCS_MCP_EMBEDDING_MODEL" in variables else FULL_TEXT
        replies = self.responses[name]

        async def search(library: str, version: str, query: str) -> str:
            """Replay one recorded response.

            Args:
                library: The library.
                version: The version.
                query: The question.

            Returns:
                Its recorded response, or "No results found".

            Raises:
                RuntimeError: The query is one of ``fail``.
            """
            if query in self.fail:
                message = f"search failed for {query!r}"
                raise RuntimeError(message)
            if base := variables.get("OPENAI_API_BASE"):
                await _embed(base, [query], variables["DOCS_MCP_EMBEDDING_MODEL"])
            stored = self.stores.get(store, {}).get((library, version))
            if stored is None or not stored.pages:
                return f"{NO_RESULTS}'{query}' in {library}."
            return replies.get(query, f"{NO_RESULTS}'{query}' in {library}.")

        yield search
