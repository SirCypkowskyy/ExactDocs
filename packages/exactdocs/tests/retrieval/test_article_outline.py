"""``article_outline``: an article's heading tree with chunk IDs, from exactly one version."""

from dataclasses import dataclass

import pytest
from pydantic import ValidationError

from exactdocs.retrieval.adapters.driven.memory import (
    InMemoryChunkRepository,
    InMemoryDefaultVersions,
    InMemoryLibraries,
    InMemorySearchIndex,
)
from exactdocs.retrieval.dtos import (
    ArticleChunksIn,
    ArticleOutlineOut,
    ArticleOutlineQuery,
    ChunkHeadingIn,
    ChunkIn,
    IndexManifestCommand,
    OutlineSectionOut,
    ReadChunkQuery,
)
from exactdocs.retrieval.errors import ArticleNotFoundError, VersionNotIndexedError
from exactdocs.retrieval.models import (
    ChunkHeading,
    ChunkId,
    DocTarget,
    ManifestStatus,
    SearchableVersion,
    SectionRef,
    SourceHost,
    outline,
)
from exactdocs.retrieval.module import RetrievalModule
from exactdocs_kernel import NOTICE

LIB = "/acme/payments"
REPO = "https://github.com/acme/payments"
INSTALL = "docs/guide/install.md"
# (heading path, text): a preamble, nesting, a heading repeated under two parents.
SECTIONS = [
    ([], "Read this first."),
    (["Guide"], "# Guide\n\nEverything you need."),
    (["Guide", "Install"], "## Install\n\nPython 3.12."),
    (["Guide", "Install", "Docker"], "### Docker\n\ndocker run acme"),
    (["Guide", "Install", "Docker", "Troubleshooting"], "#### Troubleshooting\n\nport taken"),
    (["Guide", "Install", "From source"], "### From source\n\npip install -e ."),
    (["Guide", "Install", "From source", "Troubleshooting"], "#### Troubleshooting\n\npip -V"),
]


def version(ref: str, manifest: str) -> SearchableVersion:
    return SearchableVersion(
        library=LIB,
        version=ref,
        manifest_id=manifest,
        commit_sha="c" * 40,
        repository_url=REPO,
        host=SourceHost.GITHUB,
    )


@dataclass(slots=True)
class FakeVersions:
    """Plays the catalog: ``v1.4.0`` is the default version, ``v1.3.0`` an older one."""

    async def find(self, library: str, ref: str | None) -> SearchableVersion | None:
        known = {"v1.3.0": version("v1.3.0", "m13"), "v1.4.0": version("v1.4.0", "m14")}
        return known.get(ref or "v1.4.0") if library.lower() == LIB else None

    async def active_id(self, target: DocTarget) -> str | None:
        del target
        return None

    async def statuses(self, manifest_ids: object) -> dict[str, ManifestStatus]:
        del manifest_ids
        return {}


def article(path: str, sections: list[tuple[list[str], str]]) -> ArticleChunksIn:
    return ArticleChunksIn(
        path=path,
        blob_sha=f"blob-{path}",
        chunks=[
            ChunkIn(
                heading_path=headings,
                occurrence_index=0,
                content=text,
                content_hash=f"h-{n}",
                anchor=headings[-1].lower().replace(" ", "-") if headings else "",
            )
            for n, (headings, text) in enumerate(sections)
        ],
    )


@pytest.fixture
async def retrieval() -> RetrievalModule:
    chunks = InMemoryChunkRepository()
    index = InMemorySearchIndex(chunks=chunks)
    fake = FakeVersions()
    module = RetrievalModule.build(
        defaults=InMemoryDefaultVersions(),
        libraries=InMemoryLibraries(),
        searchable=fake,
        manifests=fake,
        chunks=chunks,
        search=index,
        maintenance=index,
    )
    for manifest, ref, articles in [
        ("m13", "v1.3.0", [article("docs/guide/setup.md", [(["Setup"], "# Setup")])]),
        ("m14", "v1.4.0", [article(INSTALL, SECTIONS)]),
    ]:
        await module.index_manifest(
            IndexManifestCommand(
                manifest_id=manifest, library=LIB, ref=ref, config_hash="cfg", articles=articles
            )
        )
    return module


def shape(sections: list[OutlineSectionOut]) -> list[tuple[str, object]]:
    return [(s.heading, shape(s.children)) for s in sections]


def every(sections: list[OutlineSectionOut]) -> list[OutlineSectionOut]:
    return [n for s in sections for n in [s, *every(s.children)]]


async def get(retrieval: RetrievalModule, path: str, ref: str | None) -> ArticleOutlineOut:
    return await retrieval.article_outline(ArticleOutlineQuery(library=LIB, ref=ref, path=path))


async def test_an_outline_is_the_heading_tree_with_a_chunk_id_per_heading(
    retrieval: RetrievalModule,
) -> None:
    found = await get(retrieval, INSTALL, "v1.4.0")

    assert shape(found.sections) == [
        (
            "Guide",
            [
                (
                    "Install",
                    [
                        ("Docker", [("Troubleshooting", [])]),
                        ("From source", [("Troubleshooting", [])]),
                    ],
                )
            ],
        )
    ]
    nodes = every(found.sections)
    ids = [n.chunk_id for n in nodes]
    assert all(ids)
    assert len({found.preamble_chunk_id, *ids}) == len(SECTIONS) == found.chunks
    assert [n.anchor for n in nodes][:3] == ["guide", "install", "docker"]
    assert (found.library, found.version, found.article_path) == (LIB, "v1.4.0", INSTALL)
    assert (found.commit_sha, found.manifest_id) == ("c" * 40, "m14")
    assert found.source_url == f"{REPO}/blob/{'c' * 40}/{INSTALL}"
    assert found.notice == NOTICE


async def test_every_chunk_id_of_the_outline_reads_its_section(
    retrieval: RetrievalModule,
) -> None:
    found = await get(retrieval, INSTALL, "v1.4.0")

    first = await retrieval.read_chunk(ReadChunkQuery(chunk_id=found.preamble_chunk_id or ""))
    docker = found.sections[0].children[0].children[0]
    read = await retrieval.read_chunk(ReadChunkQuery(chunk_id=docker.chunk_id or ""))
    assert first.position == 0
    assert read.heading_path == ["Guide", "Install", "Docker"]
    assert read.article_path == INSTALL


async def test_an_outline_has_no_body_text(retrieval: RetrievalModule) -> None:
    sent = (await get(retrieval, INSTALL, "v1.4.0")).model_dump_json()

    for _, text in SECTIONS:
        body = text.split("\n\n")[-1]
        assert body not in sent, body


async def test_no_ref_means_the_default_version(retrieval: RetrievalModule) -> None:
    assert (await get(retrieval, INSTALL, None)).version == "v1.4.0"
    assert (await get(retrieval, INSTALL, "  ")).version == "v1.4.0"


async def test_a_path_of_another_version_is_not_found_in_this_one(
    retrieval: RetrievalModule,
) -> None:
    with pytest.raises(ArticleNotFoundError) as missing:
        await get(retrieval, "docs/guide/setup.md", "v1.4.0")
    assert missing.value.code == "not_found"
    assert "list_articles" in str(missing.value)

    assert (await get(retrieval, "docs/guide/setup.md", "v1.3.0")).sections[0].heading == "Setup"


@dataclass(slots=True)
class FakeSuggestions:
    """Plays the catalog's close-path lookup for one version."""

    asked: list[tuple[DocTarget, str]]

    async def close_to(self, target: DocTarget, path: str) -> list[str]:
        self.asked.append((target, path))
        return [INSTALL]


async def test_a_wrong_path_lists_the_close_matches_of_that_version() -> None:
    chunks = InMemoryChunkRepository()
    index = InMemorySearchIndex(chunks=chunks)
    fake, suggestions = FakeVersions(), FakeSuggestions(asked=[])
    module = RetrievalModule.build(
        defaults=InMemoryDefaultVersions(),
        libraries=InMemoryLibraries(),
        searchable=fake,
        manifests=fake,
        chunks=chunks,
        search=index,
        maintenance=index,
        suggestions=suggestions,
    )

    with pytest.raises(ArticleNotFoundError) as missing:
        await get(module, "docs/guide/instal.md", None)

    assert missing.value.close_matches == (INSTALL,)
    assert repr(INSTALL) in str(missing.value)
    assert "not instructions" in str(missing.value)
    assert suggestions.asked == [(DocTarget(library=LIB, version="v1.4.0"), "docs/guide/instal.md")]


async def test_a_version_that_is_not_imported_gets_nothing(retrieval: RetrievalModule) -> None:
    with pytest.raises(VersionNotIndexedError):
        await get(retrieval, INSTALL, "v9.9.9")


@pytest.mark.parametrize(
    "fields",
    [
        {"library": "payments", "path": INSTALL},
        {"library": LIB, "path": ""},
        {"library": LIB, "path": "p" * 5000},
        {"library": LIB, "path": INSTALL, "ref": "r" * 300},
    ],
)
def test_bad_input_is_refused(fields: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        ArticleOutlineQuery.model_validate(fields)


def section(
    position: int, *headings: str, records: tuple[ChunkHeading, ...] | None = None
) -> SectionRef:
    return SectionRef(
        chunk_id=ChunkId(f"c{position}"),
        position=position,
        heading_path=headings,
        occurrence_index=0,
        content_hash=f"h{position}",
        anchor=f"a{position}",
        headings=records,
    )


def record(*path: str, starts: bool = False) -> ChunkHeading:
    return ChunkHeading(heading_path=path, anchor=f"#{path[-1]}", starts_chunk=starts)


def test_a_heading_that_starts_no_chunk_is_a_node_without_one() -> None:
    tree = outline([section(0, "A", "B"), section(1, "A", "C"), section(2, "D")])

    a, d = tree.sections
    assert (a.heading, a.entry) == ("A", None)
    assert [(c.heading, c.entry and c.entry.chunk_id) for c in a.children] == [
        ("B", "c0"),
        ("C", "c1"),
    ]
    assert (d.heading, d.entry and d.entry.chunk_id, d.children) == ("D", "c2", ())
    assert tree.preamble is None


def test_a_repeated_heading_is_two_siblings_each_with_its_own_children() -> None:
    tree = outline([section(0, "A"), section(1, "A", "x"), section(2, "A"), section(3, "A", "y")])

    assert [(n.heading, [c.heading for c in n.children]) for n in tree.sections] == [
        ("A", ["x"]),
        ("A", ["y"]),
    ]


def test_an_article_without_headings_is_only_a_preamble() -> None:
    tree = outline([section(0)])

    assert tree.preamble is not None
    assert tree.preamble.chunk_id == "c0"
    assert tree.sections == ()


def flat(tree) -> list[tuple[str, str | None, str | None, bool | None]]:
    """Every node as ``(heading, chunk ID, anchor, starts chunk)``, in document order."""

    def walk(nodes) -> list[tuple[str, str | None, str | None, bool | None]]:
        found = []
        for n in nodes:
            e = n.entry
            found.append((n.heading, e and e.chunk_id, e and e.anchor, e and e.starts_chunk))
            found += walk(n.children)
        return found

    return walk(tree.sections)


def test_a_merged_heading_is_a_node_of_the_chunk_that_holds_it_with_its_own_anchor() -> None:
    tree = outline(
        [
            section(0, "A", records=(record("A", starts=True), record("A", "B"))),
            section(1, "A", "C", records=(record("A", "C", starts=True), record("A", "C", "D"))),
            section(2, "E", records=(record("E", starts=True),)),
        ]
    )

    assert [(n.heading, [c.heading for c in n.children]) for n in tree.sections] == [
        ("A", ["B", "C"]),
        ("E", []),
    ]
    assert flat(tree) == [
        ("A", "c0", "#A", True),
        ("B", "c0", "#B", False),
        ("C", "c1", "#C", True),
        ("D", "c1", "#D", False),
        ("E", "c2", "#E", True),
    ]


def test_a_heading_merged_into_the_preamble_points_to_the_preamble() -> None:
    tree = outline(
        [
            section(0, records=(record("Deep"),)),
            section(1, "A", records=(record("A", starts=True),)),
        ]
    )

    assert tree.preamble is not None
    assert tree.preamble.chunk_id == "c0"
    assert flat(tree) == [("Deep", "c0", "#Deep", False), ("A", "c1", "#A", True)]


def test_sections_stored_without_heading_records_give_the_outline_of_their_first_headings() -> None:
    old = outline([section(0, "A"), section(1, "A", "C")])
    mixed = outline(
        [section(0, "A"), section(1, "A", "C", records=(record("A", "C", starts=True),))]
    )

    expected = [("A", "c0", "a0", True), ("C", "c1", "a1", True)]
    assert flat(old) == expected
    assert flat(mixed) == [("A", "c0", "a0", True), ("C", "c1", "#C", True)]


async def test_an_outline_of_merged_chunks_lists_every_heading_and_marks_the_merged_ones() -> None:
    chunks = InMemoryChunkRepository()
    index = InMemorySearchIndex(chunks=chunks)
    fake = FakeVersions()
    module = RetrievalModule.build(
        defaults=InMemoryDefaultVersions(),
        libraries=InMemoryLibraries(),
        searchable=fake,
        manifests=fake,
        chunks=chunks,
        search=index,
        maintenance=index,
    )

    def heading(*path: str, anchor: str, starts: bool = False) -> ChunkHeadingIn:
        return ChunkHeadingIn(heading_path=list(path), anchor=anchor, starts_chunk=starts)

    merged = [
        ChunkIn(
            heading_path=["Guide"],
            occurrence_index=0,
            content="# Guide\n\nAll.\n\n## Install\n\nPython.\n\n### Docker\n\nrun\n",
            content_hash="h-0",
            anchor="guide",
            headings=[
                heading("Guide", anchor="guide", starts=True),
                heading("Guide", "Install", anchor="install"),
                heading("Guide", "Install", "Docker", anchor="docker"),
            ],
        ),
        ChunkIn(
            heading_path=["Guide", "Upgrade"],
            occurrence_index=0,
            content="## Upgrade\n\npip install -U\n",
            content_hash="h-1",
            anchor="upgrade",
            headings=[heading("Guide", "Upgrade", anchor="upgrade", starts=True)],
        ),
    ]
    await module.index_manifest(
        IndexManifestCommand(
            manifest_id="m14",
            library=LIB,
            ref="v1.4.0",
            config_hash="merging",
            articles=[ArticleChunksIn(path=INSTALL, blob_sha="b", chunks=merged)],
        )
    )

    found = await get(module, INSTALL, "v1.4.0")

    assert shape(found.sections) == [("Guide", [("Install", [("Docker", [])]), ("Upgrade", [])])]
    nodes = every(found.sections)
    guide, install, docker, upgrade = nodes
    assert [n.anchor for n in nodes] == ["guide", "install", "docker", "upgrade"]
    assert [n.starts_chunk for n in nodes] == [True, False, False, True]
    assert install.chunk_id == docker.chunk_id == guide.chunk_id != upgrade.chunk_id
    assert found.chunks == 2
    sent = found.model_dump_json()
    assert "Python." not in sent
    assert "pip install" not in sent


async def test_every_heading_of_an_outline_stored_without_records_starts_its_chunk(
    retrieval: RetrievalModule,
) -> None:
    found = await get(retrieval, INSTALL, "v1.4.0")

    assert all(n.starts_chunk for n in every(found.sections))


@pytest.mark.parametrize(
    "headings",
    [
        [{"heading_path": ["A", "B"], "anchor": "b", "starts_chunk": True}],
        [
            {"heading_path": ["A"], "anchor": "a", "starts_chunk": False},
            {"heading_path": ["A"], "anchor": "a", "starts_chunk": True},
        ],
        [{"heading_path": [], "anchor": "", "starts_chunk": False}],
    ],
    ids=["another-path-starts-it", "not-first", "no-heading"],
)
def test_heading_records_that_do_not_match_their_chunk_are_refused(headings: list) -> None:
    with pytest.raises(ValidationError):
        ChunkIn.model_validate(
            {
                "heading_path": ["A"],
                "occurrence_index": 0,
                "content": "# A",
                "content_hash": "h",
                "anchor": "a",
                "headings": headings,
            }
        )


def test_a_heading_no_chunk_records_has_no_chunk_anchor_or_starts_chunk() -> None:
    tree = outline([section(0, "A", "B")])

    (a,) = [OutlineSectionOut.from_model(node) for node in tree.sections]
    assert (a.chunk_id, a.anchor, a.starts_chunk) == (None, None, None)
    assert (a.children[0].chunk_id, a.children[0].starts_chunk) == ("c0", True)
