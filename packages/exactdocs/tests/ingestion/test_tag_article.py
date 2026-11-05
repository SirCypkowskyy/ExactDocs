"""Tagging an article path by hand: the catalog stores the tags, the chunk index gets the copies."""

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

import pytest

from exactdocs.ingestion.dtos import TagArticleCommand
from exactdocs.ingestion.models import ArticleChunk, ImportedVersion, TaggedPath
from exactdocs.ingestion.use_cases import TagArticleUseCase
from exactdocs_kernel import NotFoundError


@dataclass(slots=True)
class FakeCatalog:
    retagged: dict[str, dict[str, tuple[str, ...]]] = field(default_factory=dict)
    known: bool = True

    async def set_tags(self, library: str, path: str, tags: Sequence[str]) -> TaggedPath:
        if not self.known:
            message = f"library {library!r} not found"
            raise NotFoundError(message)
        return TaggedPath(
            library=library.lower(),
            path=path,
            tags=tuple(sorted(t.lower() for t in tags)),
            retagged=self.retagged,
        )


@dataclass(slots=True)
class FakeIndex:
    """A ``ChunkIndex`` of which tagging only uses ``retag``."""

    copies: list[tuple[str, dict[str, tuple[str, ...]]]] = field(default_factory=list)

    async def retag(self, manifest_id: str, tags: Mapping[str, tuple[str, ...]]) -> None:
        self.copies.append((manifest_id, dict(tags)))

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


def command(*tags: str) -> TagArticleCommand:
    return TagArticleCommand(library="/Acme/Payments", path="guide/setup.md", tags=list(tags))


async def test_every_touched_manifest_gets_the_new_tags_in_the_chunk_index() -> None:
    catalog = FakeCatalog(
        retagged={
            "m1": {"guide/setup.md": ("guide", "onboarding")},
            "m2": {"guide/install.md": ("onboarding",)},
        }
    )
    index = FakeIndex()

    tagged = await TagArticleUseCase(catalog, index)(command("Onboarding"))

    assert (tagged.library, tagged.path, tagged.tags) == (
        "/acme/payments",
        "guide/setup.md",
        ["onboarding"],
    )
    assert index.copies == [
        ("m1", {"guide/setup.md": ("guide", "onboarding")}),
        ("m2", {"guide/install.md": ("onboarding",)}),
    ]


async def test_an_unknown_library_changes_nothing() -> None:
    index = FakeIndex()

    with pytest.raises(NotFoundError):
        await TagArticleUseCase(FakeCatalog(known=False), index)(command("x"))

    assert index.copies == []


async def test_tagging_waits_while_an_import_activates_a_version() -> None:
    lock = asyncio.Lock()
    index = FakeIndex()
    tag = TagArticleUseCase(FakeCatalog(retagged={"m1": {"a.md": ("x",)}}), index, lock)

    async with lock:  # what the importer holds from re-tagging to activation
        waiting = asyncio.create_task(tag(command("x")))
        await asyncio.sleep(0)
        assert not waiting.done()
        assert index.copies == []
    await waiting

    assert index.copies == [("m1", {"a.md": ("x",)})]
