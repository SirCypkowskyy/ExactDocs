"""``ImportVersionUseCase`` over fake ports: what is stored, in which order, and what is undone."""

import asyncio
import codecs
import os
from collections.abc import AsyncGenerator, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from exactdocs.ingestion.adapters.driven.markdown_chunker import MarkdownChunker
from exactdocs.ingestion.adapters.driven.memory import (
    InMemoryCredentialVault,
    InMemoryJobRepository,
    InMemoryLibrarySources,
)
from exactdocs.ingestion.errors import (
    CheckoutUnreadableError,
    CredentialsRequiredError,
    ImportNotPinnedError,
    ImportTooLargeError,
    NoArticlesError,
    RepositoryUnreachableError,
)
from exactdocs.ingestion.models import (
    IMPORT_JOB,
    MAX_JOB_NOTES,
    MAX_JOB_PROBLEMS,
    REFRESH_JOB,
    AccessToken,
    ArticleChunk,
    ImportedRef,
    Credential,
    ImportedVersion,
    ImportSource,
    Job,
    JobId,
    JobKind,
    JobState,
    ParsedArticle,
    PathSelection,
    ProblemCode,
    ProposedId,
    RefKind,
    RepositoryHost,
    RepositoryUrl,
    TagRule,
    git_blob_sha,
    parse_article,
)
from exactdocs.ingestion.module import import_job
from exactdocs.ingestion.use_cases import (
    ImportVersionUseCase,
    RunNextJobUseCase,
    Skip,
    _decode,
    _Progress,
)
from exactdocs_kernel import SystemClock

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
    credentials: list[Credential | None] = field(default_factory=list)
    tmp: Path | None = None
    after_write: Callable[[Path], None] = lambda _: None

    @asynccontextmanager
    async def fetch(
        self,
        repository: RepositoryUrl,
        commit_sha: str,
        selection: PathSelection,
        *,
        refs=(),
        credential: Credential | None = None,
    ) -> AsyncGenerator[Path]:
        del repository, selection
        self.credentials.append(credential)
        self.fetched.append((commit_sha, "", list(refs)))
        if self.error:
            raise self.error
        assert self.tmp is not None
        for name, data in self.files.items():
            (self.tmp / name).parent.mkdir(parents=True, exist_ok=True)
            (self.tmp / name).write_bytes(data)
        for name, target in self.links.items():
            (self.tmp / name).symlink_to(target)
        self.after_write(self.tmp)
        yield self.tmp


class Sources:
    def __init__(self, selection: PathSelection, rules: tuple[TagRule, ...] = ()) -> None:
        self.source = ImportSource(url=URL, selection=selection, tag_rules=rules)

    async def get(self, library: str) -> ImportSource:
        del library
        return self.source

    async def imported_versions(self, library: str) -> list[ImportedRef]:
        del library
        return []


@dataclass(slots=True)
class Side:
    """Plays the catalog (``VersionPublisher``) or retrieval (``ChunkIndex``), sharing one log."""

    name: str
    log: list[str]
    stored: list[ImportedVersion] = field(default_factory=list)
    described: list[tuple[str, str, str | None, str | None]] = field(default_factory=list)
    known_sets: dict[str, tuple[ArticleChunk, ...]] = field(default_factory=dict)
    known_calls: list[int] = field(default_factory=list)
    fail_at: str | None = None
    hang_at: str | None = None
    broken_discard: bool = False
    reached: asyncio.Event = field(default_factory=asyncio.Event)

    async def _step(self, step: str) -> None:
        self.log.append(f"{self.name} {step}")
        if self.fail_at == step:
            raise RuntimeError(step)
        if self.hang_at == step:
            self.reached.set()
            await asyncio.Event().wait()

    async def store(self, version: ImportedVersion) -> str:
        await self._step("store")
        self.stored.append(version)
        return "m1"

    async def activate(self, manifest_id: str) -> None:
        await self._step(f"activate {manifest_id}")

    async def describe(
        self, *, library: str, ref: str, title: str | None, description: str | None
    ) -> None:
        await self._step("describe")
        self.described.append((library, ref, title, description))

    async def known(
        self, config_hash: str, blob_shas: Sequence[str]
    ) -> Mapping[str, tuple[ArticleChunk, ...]]:
        del config_hash
        self.known_calls.append(len(blob_shas))
        return {sha: self.known_sets[sha] for sha in blob_shas if sha in self.known_sets}

    async def index(self, manifest_id: str, version: ImportedVersion) -> None:
        del version
        await self._step(f"index {manifest_id}")

    async def remove(self, manifest_ids: Sequence[str]) -> None:
        raise NotImplementedError

    async def discard(self, *, manifest_id: str | None, library: str) -> None:
        self.log.append(f"{self.name} discard {manifest_id} {library}")
        if self.broken_discard:
            raise OSError(manifest_id, library)


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
    problems: list[tuple[str, str, str]] = field(default_factory=list)
    counts: list[tuple[int, int]] = field(default_factory=list)

    async def chunking(self, *, chunked: int, reused: int) -> None:
        self.counts.append((chunked, reused))

    async def report(self, *, done: int, total: int) -> None:
        self.reports.append((done, total))

    async def problem(self, path: str, code: ProblemCode, reason: str) -> None:
        self.problems.append((path, code, reason))


def make_job(
    version: str | None = "v1", commit: str | None = SHA, kind: RefKind | None = RefKind.TAG
) -> Job:
    return Job.queued(
        job_id=JobId("j1"),
        kind="import",  # ty: ignore[invalid-argument-type]
        library="/a/b",
        version=version,
        commit_sha=commit,
        ref_kind=kind,
        now=datetime(2026, 1, 1, tzinfo=UTC),
    )


@dataclass(slots=True)
class World:
    run: ImportVersionUseCase
    gateway: Checkout
    catalog: Side
    chunks: Side
    chunker: CountingChunker
    progress: Progress

    @property
    def log(self) -> list[str]:
        return self.catalog.log


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
    max_import_bytes: int = 2**30,
    links: Mapping[str, str] | None = None,
    after_write: Callable[[Path], None] = lambda _: None,
    vault: InMemoryCredentialVault | None = None,
    kind: JobKind = IMPORT_JOB,
) -> World:
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    gateway = Checkout(files, links or {}, tmp=checkout, after_write=after_write)
    log: list[str] = []
    catalog, chunks, chunker = Side("catalog", log), Side("chunks", log), CountingChunker()
    handlers, _ = import_job(
        gateway=gateway,
        chunker=chunker,
        sources=Sources(selection or PathSelection.of(["docs/"]), rules),
        versions=catalog,
        index=chunks,
        vault=vault,
        max_article_bytes=max_bytes,
        max_import_bytes=max_import_bytes,
    )
    run = handlers[kind]
    return World(run, gateway, catalog, chunks, chunker, Progress())  # ty: ignore[invalid-argument-type]


async def test_a_version_is_stored_indexed_then_activated_and_progress_counts_files(
    world: World,
) -> None:
    await world.run(make_job(), world.progress)

    assert world.log == [
        "catalog store",
        "chunks index m1",
        "catalog activate m1",
        "catalog describe",
    ]
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


@pytest.mark.parametrize("kind", [IMPORT_JOB, REFRESH_JOB])
async def test_an_import_and_a_refresh_fetch_with_the_librarys_stored_credential(
    tmp_path: Path, kind: JobKind
) -> None:
    token = AccessToken(token="ghp_s3cretvalue")
    vault = InMemoryCredentialVault({"/a/b": token, "/other/lib": AccessToken(token="nope")})
    world = build_world(tmp_path, {"docs/auth.md": AUTH.encode()}, vault=vault, kind=kind)

    await world.run(make_job(), world.progress)

    assert world.gateway.credentials == [token]


@pytest.mark.parametrize("kind", [IMPORT_JOB, REFRESH_JOB])
async def test_a_public_library_is_fetched_without_a_credential(
    tmp_path: Path, kind: JobKind
) -> None:
    world = build_world(tmp_path, {"docs/auth.md": AUTH.encode()}, kind=kind)

    await world.run(make_job(), world.progress)

    assert world.gateway.credentials == [None]


@pytest.mark.parametrize("kind", [IMPORT_JOB, REFRESH_JOB])
async def test_an_unreadable_credential_fails_the_job_before_any_fetch(
    tmp_path: Path, kind: JobKind
) -> None:
    class Unreadable(InMemoryCredentialVault):
        async def load(self, library: str, scope: str) -> Credential | None:
            del library, scope
            raise CredentialsRequiredError

    world = build_world(tmp_path, {"docs/auth.md": AUTH.encode()}, vault=Unreadable(), kind=kind)

    with pytest.raises(CredentialsRequiredError):
        await world.run(make_job(), world.progress)

    assert world.gateway.fetched == []
    assert world.log == []


README = b"# Acme\n\nA payments SDK.\n"


async def test_the_root_readme_is_offered_after_activation_even_outside_the_selection(
    tmp_path: Path,
) -> None:
    world = build_world(tmp_path, {"docs/auth.md": AUTH.encode(), "README.md": README})

    await world.run(make_job(), world.progress)

    assert world.log[-2:] == ["catalog activate m1", "catalog describe"]
    assert world.catalog.described == [("/a/b", "v1", "Acme", "A payments SDK.")]
    assert [a.path for a in world.catalog.stored[0].articles] == ["docs/auth.md"]


async def test_readme_md_wins_over_readme_mdx(tmp_path: Path) -> None:
    files = {"docs/a.md": INSTALL.encode(), "README.mdx": b"# Mdx\n", "README.md": b"# Md\n"}
    world = build_world(tmp_path, files)

    await world.run(make_job(), world.progress)

    assert world.catalog.described == [("/a/b", "v1", "Md", None)]


@pytest.mark.parametrize(
    "readme", [None, b"\xff\xfe not utf-8", b"x" * 3000], ids=["missing", "not-utf8", "too-big"]
)
async def test_an_unusable_readme_is_offered_as_empty(tmp_path: Path, readme: bytes | None) -> None:
    files = {"docs/a.md": INSTALL.encode()} | ({} if readme is None else {"README.md": readme})
    world = build_world(tmp_path, files, max_bytes=2048)

    await world.run(make_job(), world.progress)

    assert world.catalog.described == [("/a/b", "v1", None, None)]


async def test_a_catalog_that_refuses_the_readme_does_not_fail_the_import(tmp_path: Path) -> None:
    world = build_world(tmp_path, {"docs/a.md": INSTALL.encode(), "README.md": README})
    world.catalog.fail_at = "describe"

    await world.run(make_job(), world.progress)

    assert world.log == [
        "catalog store",
        "chunks index m1",
        "catalog activate m1",
        "catalog describe",
    ]


async def test_nothing_is_offered_when_the_import_fails(tmp_path: Path) -> None:
    world = build_world(tmp_path, {"docs/a.md": INSTALL.encode(), "README.md": README})
    world.chunks.fail_at = "index m1"

    with pytest.raises(RuntimeError):
        await world.run(make_job(), world.progress)

    assert world.catalog.described == []


async def test_rule_tags_come_before_front_matter_tags(tmp_path: Path) -> None:
    world = build_world(
        tmp_path, {"docs/auth.md": AUTH.encode()}, rules=(TagRule.of("docs/**", "Api"),)
    )

    await world.run(make_job(), world.progress)

    assert world.catalog.stored[0].articles[0].tags == ("api", "auth")


async def test_a_blob_that_was_chunked_before_is_not_chunked_again(tmp_path: Path) -> None:
    world = build_world(tmp_path, {"docs/a.md": AUTH.encode(), "docs/b.md": INSTALL.encode()})
    known = tuple(MarkdownChunker().chunk(_parsed(AUTH)))
    world.chunks.known_sets[git_blob_sha(AUTH.encode())] = known

    await world.run(make_job(), world.progress)

    assert world.chunker.chunked == ["docs/b.md"]  # only the blob nobody chunked
    assert world.catalog.stored[0].articles[0].chunks == known
    assert world.progress.counts == [(1, 1)]  # b.md chunked now, a.md reused


async def test_known_chunk_sets_are_asked_for_in_batches_not_per_file(tmp_path: Path) -> None:
    files = {f"docs/{i}.md": f"# Doc {i}\n\ntext {i}\n".encode() for i in range(1100)}
    world = build_world(tmp_path, files)

    await world.run(make_job(), world.progress)

    assert world.chunks.known_calls == [500, 500, 100]


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

    assert world.log == []


@pytest.mark.parametrize("failing", ["store", "index m1", "activate m1"])
async def test_a_failure_before_activation_discards_chunks_then_manifest(
    world: World, failing: str
) -> None:
    (world.chunks if failing.startswith("index") else world.catalog).fail_at = failing

    with pytest.raises(RuntimeError):
        await world.run(make_job(), world.progress)

    pending = "None" if failing == "store" else "m1"
    discards = [e for e in world.log if " discard " in e]
    assert discards == [f"chunks discard {pending} /a/b", f"catalog discard {pending} /a/b"]
    assert ("catalog activate m1" in world.log) == (failing == "activate m1")


@pytest.mark.parametrize("hanging", ["store", "index m1", "activate m1"])
async def test_a_cancelled_import_discards_chunks_then_manifest(world: World, hanging: str) -> None:
    side = world.chunks if hanging.startswith("index") else world.catalog
    side.hang_at = hanging
    task = asyncio.create_task(world.run(make_job(), world.progress))
    await side.reached.wait()

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    for _ in range(5):  # the clean-up outlives the cancelled task
        await asyncio.sleep(0)

    pending = "None" if hanging == "store" else "m1"
    discards = [e for e in world.log if " discard " in e]
    assert discards == [f"chunks discard {pending} /a/b", f"catalog discard {pending} /a/b"]


async def test_a_failing_chunk_discard_still_discards_the_manifest(world: World) -> None:
    world.catalog.fail_at = "activate m1"
    world.chunks.broken_discard = True

    with pytest.raises(RuntimeError, match="activate m1"):  # the cause, not the clean-up error
        await world.run(make_job(), world.progress)

    assert "catalog discard m1 /a/b" in world.log


async def test_a_selection_without_articles_publishes_nothing(tmp_path: Path) -> None:
    world = build_world(tmp_path, {"elsewhere/readme.md": b"# x"})

    with pytest.raises(NoArticlesError):
        await world.run(make_job(), world.progress)

    assert world.log == []


async def test_files_that_cannot_be_read_are_skipped_with_a_reason(tmp_path: Path) -> None:
    secret = tmp_path / "secret.md"
    secret.write_text("# do not import me")
    world = build_world(
        tmp_path,
        {
            "docs/ok.md": INSTALL.encode(),
            "docs/latin1.md": "caf\xe9".encode("latin-1"),
            "docs/utf16.md": "# caf\xe9".encode("utf-16"),
            "docs/binary.md": b"\x89PNG\0\0",
            "docs/undecodable.md": b"caf\x81",
            "docs/big.md": b"x" * 100,
        },
        links={"docs/link.md": str(secret)},
        max_bytes=50,
    )

    await world.run(make_job(), world.progress)

    articles = {a.path: a for a in world.catalog.stored[0].articles}
    assert sorted(articles) == ["docs/latin1.md", "docs/ok.md", "docs/utf16.md"]
    assert "caf\xe9" in articles["docs/latin1.md"].content
    assert "caf\xe9" in articles["docs/utf16.md"].content
    assert {path: code for path, code, _ in world.progress.problems} == {
        "docs/big.md": ProblemCode.TOO_LARGE,
        "docs/binary.md": ProblemCode.BINARY,
        "docs/undecodable.md": ProblemCode.UNDECODABLE,
        "docs/link.md": ProblemCode.NOT_A_FILE,
    }
    assert ("docs/big.md", ProblemCode.TOO_LARGE, "larger than 50 bytes") in world.progress.problems
    assert world.progress.reports[-1] == (7, 7)  # skipped files count as processed


async def test_a_file_name_that_is_not_utf8_is_skipped_with_a_printable_path(
    tmp_path: Path,
) -> None:
    odd = os.fsdecode(b"docs/caf\xe9.md")
    world = build_world(tmp_path, {odd: INSTALL.encode(), "docs/ok.md": INSTALL.encode()})

    await world.run(make_job(), world.progress)

    assert [a.path for a in world.catalog.stored[0].articles] == ["docs/ok.md"]
    ((path, code, _),) = world.progress.problems
    assert code == ProblemCode.BAD_FILE_NAME
    assert path.isprintable()
    path.encode()  # would raise on a lone surrogate


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads everything")
async def test_a_file_that_cannot_be_opened_is_skipped_not_fatal(tmp_path: Path) -> None:
    def lock(folder: Path) -> None:
        (folder / "docs/locked.md").chmod(0)

    world = build_world(
        tmp_path,
        {"docs/ok.md": INSTALL.encode(), "docs/locked.md": INSTALL.encode()},
        after_write=lock,
    )

    await world.run(make_job(), world.progress)

    assert [a.path for a in world.catalog.stored[0].articles] == ["docs/ok.md"]
    assert world.progress.problems == [("docs/locked.md", ProblemCode.UNREADABLE, "unreadable")]


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads everything")
async def test_a_folder_that_cannot_be_listed_fails_the_import_before_anything_is_stored(
    tmp_path: Path,
) -> None:
    def lock(folder: Path) -> None:
        (folder / "docs/secret").chmod(0)

    world = build_world(
        tmp_path,
        {"docs/ok.md": INSTALL.encode(), "docs/secret/a.md": INSTALL.encode()},
        after_write=lock,
    )

    try:
        with pytest.raises(CheckoutUnreadableError):
            await world.run(make_job(), world.progress)
    finally:
        (tmp_path / "checkout/docs/secret").chmod(0o700)

    assert world.log == []


async def test_a_file_over_the_cap_is_not_opened(tmp_path: Path, monkeypatch) -> None:
    world = build_world(
        tmp_path, {"docs/ok.md": INSTALL.encode(), "docs/big.md": b"x" * 100}, max_bytes=50
    )
    opened: list[str] = []
    real_open = os.open

    def recording_open(path, *args, **kwargs):
        opened.append(str(path))
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(os, "open", recording_open)

    await world.run(make_job(), world.progress)

    assert [Path(p).name for p in opened] == ["ok.md"]


async def test_an_import_over_the_byte_budget_fails_before_anything_is_stored(
    tmp_path: Path,
) -> None:
    world = build_world(
        tmp_path,
        {"docs/a.md": b"a" * 60, "docs/b.md": b"b" * 60},
        max_import_bytes=100,
    )

    with pytest.raises(ImportTooLargeError):
        await world.run(make_job(), world.progress)

    assert world.log == []


async def test_a_job_without_a_pinned_commit_is_refused(world: World) -> None:
    with pytest.raises(ImportNotPinnedError):
        await world.run(make_job(commit=None), world.progress)
    with pytest.raises(ImportNotPinnedError):
        await world.run(make_job(version=None), world.progress)


async def test_the_kind_comes_from_the_job_and_a_branch_is_fetched_by_its_ref(
    world: World,
) -> None:
    await world.run(make_job(version="main", kind=RefKind.BRANCH), world.progress)

    assert world.catalog.stored[0].kind is RefKind.BRANCH
    assert world.gateway.fetched == [(SHA, "", ["refs/heads/main"])]


async def test_a_pinned_commit_is_fetched_by_sha_alone(world: World) -> None:
    await world.run(make_job(version=SHA, kind=RefKind.COMMIT), world.progress)

    assert world.catalog.stored[0].kind is RefKind.COMMIT
    assert world.gateway.fetched == [(SHA, "", [])]


class CountingJobs:
    def __init__(self) -> None:
        self.saves = 0

    async def save(self, job: Job) -> None:
        del job
        self.saves += 1


async def test_progress_is_stored_now_and_then_not_for_every_file() -> None:
    jobs = CountingJobs()
    progress = _Progress(jobs, make_job())  # ty: ignore[invalid-argument-type]

    await progress.report(done=0, total=1000)
    for done in range(1, 1001):
        await progress.report(done=done, total=1000)
        await progress.problem(f"docs/{done}.md", ProblemCode.BINARY, "skipped")

    assert jobs.saves < 30
    assert (progress.job.done, progress.job.total) == (1000, 1000)
    assert len(progress.job.problems) == MAX_JOB_PROBLEMS  # the cap holds for exactly 1000


def test_a_job_lists_a_bounded_number_of_skipped_files() -> None:
    job = make_job()
    for i in range(MAX_JOB_PROBLEMS + 50):
        job = job.with_problem(f"docs/{i}.md", ProblemCode.BINARY, "skipped")

    assert len(job.problems) == MAX_JOB_PROBLEMS + 1
    assert not job.problems[-1].path
    assert job.problems[-1].code == ProblemCode.TRUNCATED
    assert job.problems[-1].reason.startswith("50 more")
    assert job.skipped_count == MAX_JOB_PROBLEMS + 50


def test_front_matter_notes_are_capped_apart_and_never_crowd_out_skips() -> None:
    job = make_job()
    for i in range(MAX_JOB_NOTES + 30):
        job = job.with_problem(f"n/{i}.md", ProblemCode.FRONT_MATTER, "note")
    for i in range(MAX_JOB_PROBLEMS + 5):
        job = job.with_problem(f"docs/{i}.md", ProblemCode.BINARY, "skipped")
    job = job.with_problem("late.md", ProblemCode.FRONT_MATTER, "ignored")  # notes are full

    assert job.notes == MAX_JOB_NOTES
    assert job.skipped_count == MAX_JOB_PROBLEMS + 5
    assert len(job.problems) == MAX_JOB_NOTES + MAX_JOB_PROBLEMS + 1


async def test_front_matter_problems_are_listed_per_file_and_the_article_is_imported(
    tmp_path: Path,
) -> None:
    broken = "---\ntitle: [unclosed\n---\n# Install\n\nbody\n"
    world = build_world(
        tmp_path, {"docs/broken.md": broken.encode(), "docs/ok.md": INSTALL.encode()}
    )

    await world.run(make_job(), world.progress)

    assert [a.path for a in world.catalog.stored[0].articles] == ["docs/broken.md", "docs/ok.md"]
    ((path, code, reason),) = world.progress.problems
    assert (path, code) == ("docs/broken.md", ProblemCode.FRONT_MATTER)
    assert reason.startswith("malformed front matter")


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (b"plain", "plain"),
        (b"\xef\xbb\xbfhi", "hi"),  # UTF-8 BOM stripped
        (b"caf\xe9", "caf\xe9"),  # Latin-1 via Windows-1252
        ("h\xe9".encode("utf-16"), "h\xe9"),
        (codecs.BOM_UTF16_BE + "h\xe9".encode("utf-16-be"), "h\xe9"),
        ("h\xe9".encode("utf-32"), "h\xe9"),
        (b"a\0b", ProblemCode.BINARY),
        (b"\xef\xbb\xbfa\0b", ProblemCode.BINARY),  # a UTF-8 BOM does not excuse NULs
        (b"caf\x81", ProblemCode.UNDECODABLE),  # undefined in Windows-1252
        (b"\xff\xfeh", ProblemCode.UNDECODABLE),  # BOM, odd length: no mojibake fallback
        (b"\xff\xfe\x00\xd8", ProblemCode.UNDECODABLE),  # lone surrogate
        (b"\x01\x02\x03\x04\x05abc\xe9", ProblemCode.UNDECODABLE),  # control characters
    ],
)
def test_decode(data: bytes, expected: str | ProblemCode) -> None:
    result = _decode(data)
    if isinstance(expected, ProblemCode):
        assert isinstance(result, Skip)
        assert result.code == expected
    else:
        assert result == expected


async def test_a_readme_that_is_a_symlink_is_absent(tmp_path: Path) -> None:
    world = build_world(
        tmp_path,
        {"docs/a.md": INSTALL.encode(), "secret.md": README},
        links={"README.md": "secret.md"},
    )

    await world.run(make_job(), world.progress)

    assert world.catalog.described == [("/a/b", "v1", None, None)]


async def test_a_readme_that_is_not_a_plain_file_is_absent(tmp_path: Path) -> None:
    world = build_world(tmp_path, {"docs/a.md": INSTALL.encode()})
    world.gateway.after_write = lambda folder: os.mkfifo(folder / "README.md")

    await world.run(make_job(), world.progress)

    assert world.catalog.described == [("/a/b", "v1", None, None)]


async def test_a_summary_that_blows_up_does_not_fail_the_import(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(source: str) -> object:
        raise RecursionError(source)

    monkeypatch.setattr("exactdocs.ingestion.use_cases.readme_summary", explode)
    world = build_world(tmp_path, {"docs/a.md": INSTALL.encode(), "README.md": README})

    await world.run(make_job(), world.progress)

    assert world.catalog.described == [("/a/b", "v1", None, None)]
    assert world.log[-2:] == ["catalog activate m1", "catalog describe"]


async def test_a_library_removed_before_the_import_runs_fails_the_job_cleanly(
    world: World,
) -> None:
    jobs = InMemoryJobRepository.of([make_job()])
    importer = replace(world.run, sources=InMemoryLibrarySources())
    run_next = RunNextJobUseCase(jobs, SystemClock(), {IMPORT_JOB: importer})

    assert await run_next()

    job = await jobs.get(JobId("j1"))
    assert job is not None
    assert job.state is JobState.FAILED
    assert job.error is not None
    assert "/a/b" in job.error
    assert world.log == []  # nothing stored
    assert world.gateway.fetched == []


async def test_two_new_files_with_the_same_content_are_one_chunk_set(tmp_path: Path) -> None:
    world = build_world(tmp_path, {"docs/a.md": INSTALL.encode(), "docs/b.md": INSTALL.encode()})

    await world.run(make_job(), world.progress)

    assert world.progress.counts == [(1, 0)]  # one chunk set cut, none reused
