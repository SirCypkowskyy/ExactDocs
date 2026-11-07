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
    ChunkIn,
    IndexManifestCommand,
    OutlineSectionOut,
    ReadChunkQuery,
)
from exactdocs.retrieval.errors import ArticleNotFoundError, VersionNotIndexedError
from exactdocs.retrieval.models import (
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
    assert found.commit_sha == "c" * 40
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


def section(position: int, *headings: str) -> SectionRef:
    return SectionRef(
        chunk_id=ChunkId(f"c{position}"),
        position=position,
        heading_path=headings,
        occurrence_index=0,
        content_hash=f"h{position}",
        anchor=f"a{position}",
    )


def test_a_heading_that_starts_no_chunk_is_a_node_without_one() -> None:
    tree = outline([section(0, "A", "B"), section(1, "A", "C"), section(2, "D")])

    a, d = tree.sections
    assert (a.heading, a.section) == ("A", None)
    assert [(c.heading, c.section and c.section.chunk_id) for c in a.children] == [
        ("B", "c0"),
        ("C", "c1"),
    ]
    assert (d.heading, d.section and d.section.chunk_id, d.children) == ("D", "c2", ())
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
