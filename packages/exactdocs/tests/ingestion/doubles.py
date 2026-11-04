"""Ports that a test does not exercise: any call is a test bug."""

from collections.abc import Mapping, Sequence

from exactdocs.ingestion.models import ArticleChunk, ImportedVersion, Removed


class NoRemovals:
    async def remove_version(self, library: str, ref: str) -> Removed:
        raise NotImplementedError

    async def remove_library(self, library: str) -> Removed:
        raise NotImplementedError


class NoIndex:
    async def known(
        self, config_hash: str, blob_shas: Sequence[str]
    ) -> Mapping[str, tuple[ArticleChunk, ...]]:
        raise NotImplementedError

    async def index(self, manifest_id: str, version: ImportedVersion) -> None:
        raise NotImplementedError

    async def discard(self, *, manifest_id: str | None, library: str) -> None:
        raise NotImplementedError

    async def remove(self, manifest_ids: Sequence[str]) -> None:
        raise NotImplementedError
