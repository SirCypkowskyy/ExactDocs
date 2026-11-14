"""Re-chunking every version of a library from what it stores, after its chunking changed."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any

import pytest

from exactdocs.ingestion.adapters.driven.markdown_chunker import MarkdownChunker
from exactdocs.ingestion.adapters.driven.memory import InMemoryCheckpoints, InMemoryLibrarySources
from exactdocs.ingestion.constants import PARSER_VERSION, RECHUNK_JOB, REFRESH_JOB
from exactdocs.ingestion.errors import (
    RepositoryUnreachableError,
    ReprocessFailedError,
    StoredTextOutdatedError,
)
from exactdocs.ingestion.models import (
    ArticleChunk,
    ChunkingConfig,
    CopiedArticle,
    CopiedVersion,
    ImportedRef,
    ImportedTags,
    ImportedVersion,
    ImportSource,
    Job,
    JobId,
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
from exactdocs.ingestion.use_cases import RechunkLibraryUseCase, TagLocks

LIBRARY = "/acme/docs"
URL = RepositoryUrl(
    url="https://example.com/acme/docs",
    host_kind=RepositoryHost.GIT,
    library_id=ProposedId(LIBRARY),
)
SHALLOW = ChunkingConfig(split_depth=2)
SOURCE = ImportSource(
    url=URL,
    selection=PathSelection.of(["docs/"]),
    tag_rules=TagRule.many([("docs/api/**", "api")]),
    chunking=SHALLOW,
)
VERSIONS = [
    ImportedRef(ref="v1.0.0", kind=RefKind.TAG, commit_sha="a" * 40),
    ImportedRef(ref="main", kind=RefKind.BRANCH, commit_sha="b" * 40),
]
GUIDE = "# Guide\n\nIntro.\n\n## Install\n\nNeeds Python.\n\n### Docker\n\nRun it.\n"
API = "---\ntags: [auth]\n---\n# Auth\n\n## Tokens\n\nBearer.\n"
BROKEN = "---\ntitle: [\n---\n# Broken\n\n## Part\n\nx\n"
# A front matter that loads to nothing, then a block YAML refuses: the import keeps that block
# as Markdown (no note) and cuts at the heading inside it (#228).
ODD = "---\n# only a comment\n---\n---\ntitle: [unclosed\n# Heading inside\n---\n# Real\n\nBody.\n"


def stored(path: str, source: str, tags: tuple[str, ...] = ()) -> CopiedArticle:
    """What an import of ``source`` stores for it: its blob SHA, metadata and body."""
    parsed = parse_article(path, source)
    return CopiedArticle(
        path=path,
        blob_sha=git_blob_sha(source.encode()),
        title=parsed.title,
        front_matter=parsed.front_matter,
        tags=tags,
        content=parsed.body,
    )


ARTICLES = (
    stored("docs/guide.md", GUIDE, ("old",)),
    stored("docs/api/auth.md", API, ("auth",)),
    stored("docs/broken.md", BROKEN),
)


@pytest.fixture
def sources() -> InMemoryLibrarySources:
    return InMemoryLibrarySources(sources={LIBRARY: SOURCE}, versions={LIBRARY: list(VERSIONS)})


@dataclass
class Copier:
    """Copies what each version serves; a pending copy gets a new ID every time."""

    log: list[str]
    articles: dict[str, tuple[CopiedArticle, ...]] = field(
        default_factory=lambda: {"v1.0.0": ARTICLES, "main": ARTICLES[:1]}
    )
    outdated: set[str] = field(default_factory=set)
    copies: int = 0

    async def copy(self, library: str, ref: str, *, content_version: int) -> CopiedVersion | None:
        assert (library, content_version) == (LIBRARY, PARSER_VERSION)
        if ref in self.outdated:
            raise StoredTextOutdatedError(library, ref)
        if ref not in self.articles:
            return None
        self.copies += 1
        manifest_id = f"{ref}-copy{self.copies}"
        self.log.append(f"copy {manifest_id}")
        commit = next(v.commit_sha for v in VERSIONS if v.ref == ref)
        return CopiedVersion(
            manifest_id=manifest_id,
            kind=RefKind.TAG,
            commit_sha=commit,
            articles=self.articles[ref],
        )


@dataclass
class Tags:
    """The catalog's imported tags of the copies; manual tags are added on the way back."""

    log: list[str]
    manual: dict[str, tuple[str, ...]] = field(default_factory=dict)
    written: dict[str, dict[str, tuple[str, ...]]] = field(default_factory=dict)
    sources: dict[str, dict[str, ImportedTags]] = field(default_factory=dict)

    async def stored_tags(self, library: str, ref: str) -> None:
        raise NotImplementedError

    async def set_imported_tags(
        self, manifest_id: str, tags: Mapping[str, ImportedTags]
    ) -> dict[str, tuple[str, ...]]:
        self.log.append(f"tag {manifest_id}")
        self.written[manifest_id] = {p: t.tags for p, t in tags.items()}
        self.sources[manifest_id] = dict(tags)
        return {p: (*t.tags, *self.manual.get(p, ())) for p, t in tags.items()}


@dataclass
class Index:
    """Retrieval: chunk sets by config hash and blob, and what each manifest indexes."""

    log: list[str]
    sets: dict[tuple[str, str], tuple[ArticleChunk, ...]] = field(default_factory=dict)
    indexed: dict[str, ImportedVersion] = field(default_factory=dict)
    failing: set[str] = field(default_factory=set)
    kill_on: str | None = None

    async def known(
        self, config_hash: str, blob_shas: Sequence[str]
    ) -> Mapping[str, tuple[ArticleChunk, ...]]:
        return {s: self.sets[config_hash, s] for s in blob_shas if (config_hash, s) in self.sets}

    async def index(self, manifest_id: str, version: ImportedVersion) -> None:
        if version.ref in self.failing:
            reason = "locked"
            raise RepositoryUnreachableError(reason)
        if version.ref == self.kill_on:
            self.kill_on = None
            raise Killed
        self.log.append(f"index {manifest_id}")
        self.indexed[manifest_id] = version
        for article in version.articles:
            self.sets[version.config_hash, article.blob_sha] = article.chunks

    async def retag(self, manifest_id: str, tags: Mapping[str, tuple[str, ...]]) -> None:
        self.log.append(f"retag {manifest_id} {sorted(tags)}")

    async def discard(self, *, manifest_id: str | None, library: str) -> None:
        assert library == LIBRARY
        self.log.append(f"discard chunks {manifest_id}")

    async def remove(self, manifest_ids: Sequence[str]) -> None:
        raise NotImplementedError


@dataclass
class Publisher:
    """The catalog's activation; a version keeps serving its old manifest until then."""

    log: list[str]
    active: dict[str, str] = field(default_factory=lambda: {"v1.0.0": "m1", "main": "m2"})

    async def apply_manual_tags(self, manifest_id: str) -> dict[str, tuple[str, ...]]:
        self.log.append(f"manual tags {manifest_id}")
        return {}

    async def activate(self, manifest_id: str) -> None:
        self.log.append(f"activate {manifest_id}")
        self.active[manifest_id.split("-copy", maxsplit=1)[0]] = manifest_id

    async def discard(self, *, manifest_id: str | None, library: str) -> None:
        assert library == LIBRARY
        self.log.append(f"discard manifest {manifest_id}")

    def __getattr__(self, name: str) -> Any:
        raise NotImplementedError(name)


@dataclass
class Importer:
    """The refresh importer: it fetches, so a re-chunk must only use it as a fallback."""

    seen: list[Job] = field(default_factory=list)

    async def __call__(self, job: Job, progress, /) -> None:
        self.seen.append(job)
        await progress.chunking(chunked=5, reused=0)


@dataclass
class Progress:
    reports: list[tuple[int, int]] = field(default_factory=list)
    problems: list[tuple[str, ProblemCode, str]] = field(default_factory=list)
    counters: list[tuple[int, int]] = field(default_factory=list)
    parses: list[tuple[int, int]] = field(default_factory=list)

    async def report(self, *, done: int, total: int) -> None:
        self.reports.append((done, total))

    async def problem(self, path: str, code: ProblemCode, reason: str) -> None:
        self.problems.append((path, code, reason))

    async def chunking(self, *, chunked: int, reused: int) -> None:
        self.counters.append((chunked, reused))

    async def parsing(self, *, parsed: int, taken: int) -> None:
        self.parses.append((parsed, taken))


@dataclass
class World:
    sources: InMemoryLibrarySources
    log: list[str] = field(default_factory=list)
    copier: Copier = field(init=False)
    tags: Tags = field(init=False)
    index: Index = field(init=False)
    publisher: Publisher = field(init=False)
    importer: Importer = field(default_factory=Importer)
    progress: Progress = field(default_factory=Progress)

    def __post_init__(self) -> None:
        self.copier, self.tags = Copier(self.log), Tags(self.log)
        self.index, self.publisher = Index(self.log), Publisher(self.log)

    def handler(self, checkpoints: InMemoryCheckpoints | None = None) -> RechunkLibraryUseCase:
        return RechunkLibraryUseCase(
            sources=self.sources,
            copier=self.copier,
            chunker=MarkdownChunker(),
            tags=self.tags,
            versions=self.publisher,  # ty: ignore[invalid-argument-type]
            index=self.index,
            tag_locks=TagLocks(),
            importer=self.importer,
            checkpoints=checkpoints or InMemoryCheckpoints(),
        )

    async def run(self, checkpoints: InMemoryCheckpoints | None = None) -> None:
        job = Job.queued(
            job_id=JobId("job"),
            kind=RECHUNK_JOB,
            library=LIBRARY,
            version=None,
            now=datetime.now(UTC),
        ).started(datetime.now(UTC))
        await self.handler(checkpoints)(job, self.progress)


@pytest.fixture
def world(sources) -> World:
    return World(sources)


async def test_every_version_is_cut_again_from_its_stored_text_with_the_new_chunking(world):
    await world.run()

    assert world.importer.seen == []  # nothing is fetched
    version = world.index.indexed["v1.0.0-copy1"]
    assert version.config_hash == MarkdownChunker(SHALLOW).config_hash
    assert (version.commit_sha, version.refresh) == ("a" * 40, True)
    guide = next(a for a in version.articles if a.path == "docs/guide.md")
    assert [c.heading_path for c in guide.chunks] == [("Guide",), ("Guide", "Install")]
    assert "### Docker" in guide.chunks[1].content
    assert "".join(c.content for c in guide.chunks) == guide.content
    assert world.publisher.active == {"v1.0.0": "v1.0.0-copy1", "main": "main-copy2"}
    assert world.progress.reports == [(0, 2), (1, 2), (2, 2)]


async def test_a_version_serves_its_old_chunks_until_its_copy_is_indexed_and_activated(world):
    await world.run()

    assert world.log[:5] == [
        "copy v1.0.0-copy1",
        "tag v1.0.0-copy1",
        "index v1.0.0-copy1",
        "manual tags v1.0.0-copy1",  # manual tags last, as in an import
        "activate v1.0.0-copy1",
    ]


async def test_the_copies_get_the_tags_the_rules_give_now_and_keep_manual_ones(world):
    world.tags.manual = {"docs/guide.md": ("mine",)}

    await world.run()

    assert world.tags.written["v1.0.0-copy1"] == {
        "docs/guide.md": (),  # "old" came from a rule that is gone
        "docs/api/auth.md": ("api", "auth"),
        "docs/broken.md": (),
    }
    indexed = {a.path: a.tags for a in world.index.indexed["v1.0.0-copy1"].articles}
    assert indexed["docs/guide.md"] == ("mine",)
    assert indexed["docs/api/auth.md"] == ("api", "auth")
    assert world.tags.sources["v1.0.0-copy1"]["docs/api/auth.md"] == ImportedTags(
        tags=("api", "auth"), front_matter=("auth",), rules=("api",)
    )


async def test_a_blob_chunked_with_the_new_config_before_is_not_cut_again(world):
    await world.run()

    # "main" serves only the guide, which v1.0.0 cut moments before with the same config.
    assert world.progress.counters[-1] == (3, 1)
    assert world.progress.parses[-1] == (0, 4)  # every article taken from the copies, unparsed
    assert world.index.indexed["main-copy2"].articles[0].chunks == next(
        a.chunks for a in world.index.indexed["v1.0.0-copy1"].articles if a.path == "docs/guide.md"
    )


async def test_stored_text_with_malformed_front_matter_is_cut_as_the_import_cut_it(world):
    world.sources.sources[LIBRARY] = replace(SOURCE, chunking=ChunkingConfig())

    await world.run()

    broken = next(
        a for a in world.index.indexed["v1.0.0-copy1"].articles if a.path == "docs/broken.md"
    )
    imported = MarkdownChunker().chunk(parse_article("docs/broken.md", BROKEN))
    assert broken.chunks == tuple(imported)
    assert broken.chunks[0].heading_path == ()  # the broken block is text, not a heading


async def test_a_version_stored_by_an_older_parser_is_re_imported_instead(world):
    world.copier.outdated = {"main"}

    await world.run()

    assert [(j.kind, j.version, j.commit_sha) for j in world.importer.seen] == [
        (REFRESH_JOB, "main", "b" * 40)
    ]
    assert world.publisher.active["v1.0.0"] == "v1.0.0-copy1"
    assert world.progress.counters[-1] == (8, 0)  # 3 cut here, 5 by the re-import


async def test_a_failing_version_keeps_its_old_manifest_and_fails_the_job(world):
    world.index.failing = {"v1.0.0"}

    with pytest.raises(ReprocessFailedError) as raised:
        await world.run()

    assert raised.value.refs == ("v1.0.0",)
    assert raised.value.code == "repo_unreachable"
    assert world.publisher.active["v1.0.0"] == "m1"
    assert "discard chunks v1.0.0-copy1" in world.log
    assert "discard manifest v1.0.0-copy1" in world.log
    assert world.publisher.active["main"] == "main-copy2"  # the others go on


async def test_a_version_removed_since_the_job_listed_it_is_skipped(world):
    del world.copier.articles["main"]

    await world.run()

    assert set(world.index.indexed) == {"v1.0.0-copy1"}


class Killed(BaseException):
    """The process dies mid-step: nothing catches it, the step is not recorded."""


async def test_a_resumed_rechunk_skips_the_versions_it_had_finished(world):
    world.index.kill_on = "main"
    steps = InMemoryCheckpoints()
    with pytest.raises(Killed):
        await world.run(steps)
    assert "discard manifest main-copy2" in world.log  # what the killed step left pending
    resumed = steps.resumed()

    await world.run(resumed)

    assert resumed.ran == ["re-chunk main"]
    assert world.copier.copies == 3  # v1.0.0 is not copied again
    assert world.publisher.active == {"v1.0.0": "v1.0.0-copy1", "main": "main-copy3"}
    assert world.progress.reports[-1] == (2, 2)


async def test_an_article_only_its_file_can_rebuild_has_its_version_re_imported(world):
    world.copier.articles["main"] = (*ARTICLES[:1], stored("docs/odd.md", ODD))

    await world.run()

    assert [(j.kind, j.version, j.commit_sha) for j in world.importer.seen] == [
        (REFRESH_JOB, "main", "b" * 40)
    ]
    assert "main-copy2" not in world.index.indexed  # nothing cut from a guess
    assert "discard manifest main-copy2" in world.log
    assert "activate main-copy2" not in world.log
    assert world.publisher.active["v1.0.0"] == "v1.0.0-copy1"  # the others are cut from the copy
    assert world.progress.counters[-1] == (8, 0)  # 3 cut from v1.0.0's copy, 5 by the re-import


@pytest.mark.parametrize(
    "source",
    [
        GUIDE,
        API,
        BROKEN,  # malformed front matter: the block is not cut at
        ODD,
        "---\n\n---\n---\ntitle: [\n# Inside\n---\n# Real\n",  # an empty front matter
        "---\ntitle: T\n---\n---\ntitle: [\n# Inside\n---\n# Real\n",
        "---\n# a comment\n---\n---\nnext: block\n---\n# Real\n",  # a second mapping
        "---\nJust prose.\n---\n# Real\n",  # a thematic break around prose, no front matter
        "---\n# a comment\n---\n---\nJust prose.\n---\n# Real\n",
        "\u200b---\ntitle: [\n---\n# Real\n",  # an invisible character the parser strips
    ],
)
def test_a_copied_article_is_cut_as_its_import_cut_it_or_left_to_a_re_import(source):
    imported = parse_article("docs/a.md", source)
    rebuilt = stored("docs/a.md", source).parsed()

    if rebuilt is None:  # only a parse of the file can tell: the version is re-imported
        return
    chunker = MarkdownChunker()
    assert rebuilt.problems == imported.problems
    assert chunker.chunk(rebuilt) == chunker.chunk(imported)


@pytest.mark.parametrize("source", [GUIDE, API, BROKEN, "---\nJust prose.\n---\n# Real\n"])
def test_an_article_with_ordinary_front_matter_is_rebuilt_without_its_file(source):
    assert stored("docs/a.md", source).parsed() is not None


@pytest.mark.parametrize("source", [ODD, "---\n\n---\n---\ntitle: [\n# Inside\n---\n# Real\n"])
def test_a_blank_front_matter_before_an_invalid_block_needs_the_file(source):
    assert stored("docs/a.md", source).parsed() is None
