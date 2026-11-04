"""``ImportVersionUseCase`` over fake ports: what is stored, in which order, and what is undone."""

import asyncio
import os
from collections.abc import AsyncGenerator, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pytest

from exactdocs.ingestion.adapters.driven.markdown_chunker import MarkdownChunker
from exactdocs.ingestion.errors import (
    ImportNotPinnedError,
    NoArticlesError,
    RepositoryUnreachableError,
    UnknownRefError,
)
from exactdocs.ingestion.models import (
    ArticleChunk,
    ImportedVersion,
    ImportSource,
    Job,
    JobId,
    ParsedArticle,
    PathSelection,
    ProposedId,
    RefKind,
    RemoteRef,
    RemoteRefs,
    RepositoryHost,
    RepositoryUrl,
    TagRule,
    git_blob_sha,
    parse_article,
)
from exactdocs.ingestion.module import import_job
from exactdocs.ingestion.use_cases import ImportVersionUseCase

SHA = "a" * 40
URL = RepositoryUrl(
    url="https://example.com/acme/docs", host_kind=RepositoryHost.GIT, library_id=ProposedId("/a/b")
)
AUTH = "---\ntags: [auth]\n---\n# Auth\n\nTokens.\n\n## Issue\n\nIssue a token.\n"
INSTALL = "# Install\n\nRun it.\n"


@dataclass(slots=True)
class Checkout:
    """A fake ``GitGateway`` that writes ``files`` into the folder it yields."""

    files: Mapping[str, bytes]
    links: Mapping[str, str] = field(default_factory=dict)
    error: Exception | None = None
    fetched: list[tuple[str, str, list[str]]] = field(default_factory=list)
    tmp: Path | None = None

    @asynccontextmanager
    async def fetch(
        self, repository: RepositoryUrl, commit_sha: str, selection: PathSelection, *, refs=()
    ) -> AsyncGenerator[Path]:
        del repository, selection
        self.fetched.append((commit_sha, "", list(refs)))
        if self.error:
            raise self.error
        assert self.tmp is not None
        for name, data in self.files.items():
            (self.tmp / name).parent.mkdir(parents=True, exist_ok=True)
            (self.tmp / name).write_bytes(data)
        for name, target in self.links.items():
            (self.tmp / name).symlink_to(target)
        yield self.tmp


class Remote:
    def __init__(self, *refs: RemoteRef) -> None:
        self.refs = refs

    async def list_refs(self, repository: RepositoryUrl, *patterns: str) -> RemoteRefs:
        del repository, patterns
        return RemoteRefs(default_branch="main", refs=self.refs)


class Sources:
    def __init__(self, selection: PathSelection, rules: tuple[TagRule, ...] = ()) -> None:
        self.source = ImportSource(url=URL, selection=selection, tag_rules=rules)

    async def get(self, library: str) -> ImportSource:
        del library
        return self.source


@dataclass(slots=True)
class Catalog:
    """Plays both the catalog and retrieval and records every call, in order."""

    calls: list[str] = field(default_factory=list)
    stored: list[ImportedVersion] = field(default_factory=list)
    known_sets: dict[str, tuple[ArticleChunk, ...]] = field(default_factory=dict)
    fail_at: str | None = None
    hang_at: str | None = None
    broken_discard: bool = False
    reached: asyncio.Event = field(default_factory=asyncio.Event)
    discards: list[tuple[str | None, str]] = field(default_factory=list)

    async def _step(self, name: str) -> None:
        self.calls.append(name)
        if self.fail_at == name:
            raise RuntimeError(name)
        if self.hang_at == name:
            self.reached.set()
            await asyncio.Event().wait()

    async def store(self, version: ImportedVersion) -> str:
        await self._step("store")
        self.stored.append(version)
        return "m1"

    async def activate(self, manifest_id: str) -> None:
        await self._step(f"activate {manifest_id}")

    async def known(
        self, config_hash: str, blob_shas: Sequence[str]
    ) -> Mapping[str, tuple[ArticleChunk, ...]]:
        del config_hash
        return {sha: self.known_sets[sha] for sha in blob_shas if sha in self.known_sets}

    async def index(self, manifest_id: str, version: ImportedVersion) -> None:
        del version
        await self._step(f"index {manifest_id}")

    async def discard(self, *, manifest_id: str | None, library: str) -> None:
        self.calls.append("discard")
        if self.broken_discard:
            raise OSError(manifest_id, library)
        self.discards.append((manifest_id, library))


class CountingChunker:
    def __init__(self) -> None:
        self.inner = MarkdownChunker()
        self.chunked: list[str] = []
        self.config_hash = self.inner.config_hash

    def chunk(self, article: ParsedArticle) -> Sequence[ArticleChunk]:
        self.chunked.append(article.path)
        return self.inner.chunk(article)


@dataclass(slots=True)
class Progress:
    reports: list[tuple[int, int]] = field(default_factory=list)
    problems: list[tuple[str, str]] = field(default_factory=list)

    async def report(self, *, done: int, total: int) -> None:
        self.reports.append((done, total))

    async def problem(self, path: str, reason: str) -> None:
        self.problems.append((path, reason))


def make_job(version: str | None = "v1", commit: str | None = SHA) -> Job:
    return Job.queued(
        job_id=JobId("j1"),
        kind="import",  # ty: ignore[invalid-argument-type]
        library="/a/b",
        version=version,
        commit_sha=commit,
        now=datetime(2026, 1, 1, tzinfo=UTC),
    )


@dataclass(slots=True)
class World:
    run: ImportVersionUseCase
    gateway: Checkout
    catalog: Catalog
    chunker: CountingChunker
    progress: Progress


@pytest.fixture
def world(tmp_path: Path) -> World:
    return build_world(
        tmp_path, {"docs/auth.md": AUTH.encode(), "docs/install.md": INSTALL.encode()}
    )


def build_world(
    tmp_path: Path,
    files: Mapping[str, bytes],
    *,
    selection: PathSelection | None = None,
    rules: tuple[TagRule, ...] = (),
    max_bytes: int = 2**20,
    links: Mapping[str, str] | None = None,
) -> World:
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    gateway = Checkout(files, links or {}, tmp=checkout)
    catalog, chunker = Catalog(), CountingChunker()
    remote = Remote(RemoteRef(name="refs/tags/v1", sha=SHA))
    handlers, _ = import_job(
        gateway=gateway,
        remote=remote,
        chunker=chunker,
        sources=Sources(selection or PathSelection.of(["docs/"]), rules),
        versions=catalog,
        index=catalog,
        max_article_bytes=max_bytes,
    )
    (run,) = handlers.values()
    return World(run, gateway, catalog, chunker, Progress())  # ty: ignore[invalid-argument-type]


async def test_a_version_is_stored_indexed_then_activated_and_progress_counts_files(
    world: World,
) -> None:
    await world.run(make_job(), world.progress)

    assert world.catalog.calls == ["store", "index m1", "activate m1"]
    (version,) = world.catalog.stored
    assert (version.library, version.ref, version.kind, version.commit_sha) == (
        "/a/b",
        "v1",
        RefKind.TAG,
        SHA,
    )
    assert [a.path for a in version.articles] == ["docs/auth.md", "docs/install.md"]
    auth = version.articles[0]
    assert (auth.title, auth.tags, auth.blob_sha) == (
        "Auth",
        ("auth",),
        git_blob_sha(AUTH.encode()),
    )
    assert [c.heading_path for c in auth.chunks] == [("Auth",), ("Auth", "Issue")]
    assert world.progress.reports == [(0, 2), (1, 2), (2, 2)]
    assert world.gateway.fetched == [(SHA, "", ["refs/tags/v1"])]


async def test_rule_tags_come_before_front_matter_tags(tmp_path: Path) -> None:
    world = build_world(
        tmp_path, {"docs/auth.md": AUTH.encode()}, rules=(TagRule.of("docs/**", "Api"),)
    )

    await world.run(make_job(), world.progress)

    assert world.catalog.stored[0].articles[0].tags == ("api", "auth")


async def test_a_blob_that_was_chunked_before_is_not_chunked_again(tmp_path: Path) -> None:
    world = build_world(tmp_path, {"docs/a.md": AUTH.encode(), "docs/b.md": INSTALL.encode()})
    known = tuple(MarkdownChunker().chunk(_parsed(AUTH)))
    world.catalog.known_sets[git_blob_sha(AUTH.encode())] = known

    await world.run(make_job(), world.progress)

    assert world.chunker.chunked == ["docs/b.md"]  # only the blob nobody chunked
    assert world.catalog.stored[0].articles[0].chunks == known


async def test_two_files_with_the_same_bytes_are_chunked_once(tmp_path: Path) -> None:
    world = build_world(tmp_path, {"docs/a.md": INSTALL.encode(), "docs/b.md": INSTALL.encode()})

    await world.run(make_job(), world.progress)

    assert world.chunker.chunked == ["docs/a.md"]
    assert [a.path for a in world.catalog.stored[0].articles] == ["docs/a.md", "docs/b.md"]


def _parsed(text: str) -> ParsedArticle:
    return parse_article("docs/a.md", text)


async def test_a_fetch_that_fails_stores_nothing(world: World) -> None:
    world.gateway.error = RepositoryUnreachableError("connection refused")

    with pytest.raises(RepositoryUnreachableError):
        await world.run(make_job(), world.progress)

    assert world.catalog.calls == []


@pytest.mark.parametrize("failing", ["store", "index m1", "activate m1"])
async def test_a_failure_before_activation_discards_the_pending_data(
    world: World, failing: str
) -> None:
    world.catalog.fail_at = failing

    with pytest.raises(RuntimeError):
        await world.run(make_job(), world.progress)

    stored = failing != "store"
    assert world.catalog.discards == [("m1" if stored else None, "/a/b")] * 2
    assert ("activate m1" in world.catalog.calls) == (failing == "activate m1")


@pytest.mark.parametrize("hanging", ["store", "index m1", "activate m1"])
async def test_a_cancelled_import_discards_the_pending_data(world: World, hanging: str) -> None:
    world.catalog.hang_at = hanging
    task = asyncio.create_task(world.run(make_job(), world.progress))
    await world.catalog.reached.wait()

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # once for the chunks and once for the manifest (the fake plays both)
    assert world.catalog.discards == [("m1" if hanging != "store" else None, "/a/b")] * 2


async def test_a_failing_discard_does_not_hide_the_failure(world: World) -> None:
    world.catalog.fail_at = "index m1"

    world.catalog.broken_discard = True
    with pytest.raises(RuntimeError, match="index m1"):
        await world.run(make_job(), world.progress)


async def test_a_selection_without_articles_publishes_nothing(tmp_path: Path) -> None:
    world = build_world(tmp_path, {"elsewhere/readme.md": b"# x"})

    with pytest.raises(NoArticlesError):
        await world.run(make_job(), world.progress)

    assert world.catalog.calls == []


async def test_files_that_cannot_be_read_are_skipped_with_a_reason(tmp_path: Path) -> None:
    secret = tmp_path / "secret.md"
    secret.write_text("# do not import me")
    world = build_world(
        tmp_path,
        {
            "docs/ok.md": INSTALL.encode(),
            "docs/latin1.md": "caf\xe9".encode("latin-1"),
            "docs/big.md": b"x" * 100,
        },
        links={"docs/link.md": str(secret)},
        max_bytes=50,
    )

    await world.run(make_job(), world.progress)

    assert [a.path for a in world.catalog.stored[0].articles] == ["docs/ok.md"]
    assert dict(world.progress.problems) == {
        "docs/big.md": "larger than 50 bytes",
        "docs/latin1.md": "not valid UTF-8",
        "docs/link.md": "not a regular file",
    }
    assert world.progress.reports[-1] == (4, 4)  # skipped files count as processed


async def test_a_file_over_the_cap_is_not_opened(tmp_path: Path, monkeypatch) -> None:
    world = build_world(tmp_path, {"docs/ok.md": INSTALL.encode(), "docs/big.md": b"x" * 100})
    world.run = ImportVersionUseCase(  # same ports, small cap
        world.run.gateway,
        world.run.remote,
        world.run.chunker,
        world.run.sources,
        world.run.versions,
        world.run.index,
        50,
    )
    opened: list[str] = []
    real_open = os.open
    monkeypatch.setattr(
        os, "open", lambda path, *a, **k: (opened.append(str(path)), real_open(path, *a, **k))[1]
    )

    await world.run(make_job(), world.progress)

    assert [Path(p).name for p in opened] == ["ok.md"]


async def test_a_job_without_a_pinned_commit_is_refused(world: World) -> None:
    with pytest.raises(ImportNotPinnedError):
        await world.run(make_job(commit=None), world.progress)
    with pytest.raises(ImportNotPinnedError):
        await world.run(make_job(version=None), world.progress)


async def test_a_ref_the_remote_no_longer_has_is_refused(world: World) -> None:
    with pytest.raises(UnknownRefError):
        await world.run(make_job(version="v9"), world.progress)

    assert world.gateway.fetched == []


async def test_a_pinned_commit_is_fetched_without_asking_the_remote(world: World) -> None:
    await world.run(make_job(version=SHA), world.progress)

    assert world.catalog.stored[0].kind is RefKind.COMMIT
    assert world.gateway.fetched == [(SHA, "", [])]
