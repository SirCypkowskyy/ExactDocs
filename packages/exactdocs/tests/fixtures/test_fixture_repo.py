"""The fixture docs repository: stable SHAs, the content later issues rely on, both servers."""

import re
import tomllib
from pathlib import Path

import pytest
import yaml

from fixture_repo import FIXTURE, DocsRepo, build, git, git_bytes, headings

# Changing a file under docs-repo/ or history.toml changes these: see docs-repo/README.md.
GOLDEN_SHAS = {
    "refs/heads/main": "3fb0656f8c6ae525d96bedadb0f826bbd9201fa2",
    "refs/heads/next": "cefb01d4e80471e0ddde5184fe938ac05bf54051",
    "refs/tags/v1.3.0": "db8b674a770b689af277ae77afc0aa846fc43035",
    "refs/tags/v1.4.0": "3fb0656f8c6ae525d96bedadb0f826bbd9201fa2",
}
VERSIONS = ("v1.3.0", "v1.4.0", "next")
MAX_ARTICLE_BYTES = 2 * 1024 * 1024


def refs(listing: str) -> dict[str, str]:
    """``ref -> sha`` from ``git for-each-ref`` or ``git ls-remote`` output."""
    pairs = [line.replace("\t", " ").split(" ", 1) for line in listing.splitlines()]
    return {ref: sha for sha, ref in pairs if not ref.endswith("^{}")}


def local_refs(repo: Path) -> dict[str, str]:
    return refs(git("for-each-ref", "--format=%(objectname) %(refname)", cwd=repo))


def show(repo: Path, version: str, path: str) -> bytes:
    return git_bytes("show", f"{version}:{path}", cwd=repo)


def test_shas_are_golden(docs_repo: DocsRepo) -> None:
    assert local_refs(docs_repo.path) == GOLDEN_SHAS


def test_shas_do_not_depend_on_where_or_who_builds(tmp_path: Path) -> None:
    other = build(tmp_path / "elsewhere")
    assert local_refs(other) == GOLDEN_SHAS


def test_shas_do_not_depend_on_the_developers_global_git_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "xdg"
    (config / "git").mkdir(parents=True)
    (config / "git" / "ignore").write_text("*.png\n*.mdx\n")
    (config / "git" / "attributes").write_text("* text eol=crlf\n")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config))
    assert local_refs(build(tmp_path / "hostile")) == GOLDEN_SHAS


@pytest.mark.parametrize("transport", ["file_url", "http_url"])
def test_git_servers_list_the_same_refs(docs_repo: DocsRepo, transport: str) -> None:
    listed = refs(git("ls-remote", "--heads", "--tags", getattr(docs_repo, transport)))
    assert listed == GOLDEN_SHAS


def test_smart_http_serves_a_blobless_shallow_clone(docs_repo: DocsRepo, tmp_path: Path) -> None:
    clone = tmp_path / "clone"
    url = docs_repo.http_url
    git("clone", "-q", "--depth=1", "--filter=blob:none", "--branch=v1.4.0", url, str(clone))
    assert git("rev-parse", "HEAD", cwd=clone) == GOLDEN_SHAS["refs/tags/v1.4.0"]
    assert (clone / "docs" / "guide" / "install.md").is_file()


def test_commits_can_be_fetched_by_sha(docs_repo: DocsRepo, tmp_path: Path) -> None:
    git("init", "-q", str(tmp_path))
    sha = GOLDEN_SHAS["refs/tags/v1.3.0"]
    git("fetch", "-q", "--depth=1", docs_repo.http_url, sha, cwd=tmp_path)
    assert git("rev-parse", "FETCH_HEAD", cwd=tmp_path) == sha


def test_working_tree_is_main(docs_repo: DocsRepo) -> None:
    assert not git("status", "--porcelain", cwd=docs_repo.path)
    assert git("symbolic-ref", "HEAD", cwd=docs_repo.path) == "refs/heads/main"


def test_next_is_one_commit_ahead_of_v1_4_0(docs_repo: DocsRepo) -> None:
    ahead = git("rev-list", "--count", "v1.4.0..next", cwd=docs_repo.path)
    assert ahead == "1"
    changed = git("diff", "--name-status", "v1.4.0", "next", cwd=docs_repo.path)
    assert changed.splitlines() == [
        "A\tcontext7.json",
        "A\tdocs/assets/flow.svg",
        "A\tdocs/guide/diagrams.md",
        "M\tdocs/guide/install.md",
        "A\tdocs/guide/migration.md",
        "A\timg/flow.png",
    ]


def test_retry_policy_occurs_only_in_v1_4_0(docs_repo: DocsRepo) -> None:
    def files_with(version: str, pattern: str) -> list[str]:
        out = git("grep", "-Il", "-E", pattern, version, cwd=docs_repo.path, check=False)
        return out.splitlines()

    assert files_with("v1.3.0", "retry_policy") == []
    assert files_with("v1.4.0", "retry_policy")
    # A search for it must find nothing in v1.3.0, even when it splits the identifier into parts.
    assert files_with("v1.3.0", "(?i)retr(y|ies|ying)|polic") == []


def test_every_file_kind_later_issues_need_is_present(docs_repo: DocsRepo) -> None:
    repo = docs_repo.path

    def text(version: str, path: str) -> str:
        return show(repo, version, path).decode()

    install = text("v1.4.0", "docs/guide/install.md")
    front_matter = yaml.safe_load(install.split("---\n")[1])
    assert set(front_matter) == {"title", "tags", "description"}
    assert "```bash" in install
    assert "| Platform |" in install  # a table
    assert text("v1.3.0", "README.md").startswith("# Acme Payments\n")
    assert "docs/" in text("v1.3.0", "AGENTS.md")

    mdx = text("v1.4.0", "docs/api/client.mdx")
    assert "import { Callout" in mdx
    assert "<Callout" in mdx
    callouts = text("v1.3.0", "docs/guide/callouts.md")
    assert "> [!NOTE]" in callouts  # GitHub alerts
    assert ":::note" in callouts  # Docusaurus

    naming = text("v1.3.0", "docs/reference/naming.md")
    for identifier in ("snake_case", "camelCase", "--flag", "pkg.mod.fn"):
        assert identifier in naming

    # The title rules of E4-01: front matter, then first H1, then the file name.
    assert not text("v1.3.0", "docs/guide/auth.md").startswith("---")
    assert not re.search(r"^#|^---", text("v1.3.0", "docs/notes.md"), re.MULTILINE)


def test_renamed_file_is_detected_between_tags(docs_repo: DocsRepo) -> None:
    diff = git("diff", "-M", "--name-status", "v1.3.0", "v1.4.0", cwd=docs_repo.path)
    renames = [line.split("\t")[1:] for line in diff.splitlines() if line.startswith("R")]
    assert renames == [["docs/guide/setup.md", "docs/guide/install.md"]]


def test_latin1_file_decodes_by_detected_encoding_not_utf8(docs_repo: DocsRepo) -> None:
    raw = show(docs_repo.path, "v1.3.0", "docs/legacy/latin1.md")
    with pytest.raises(UnicodeDecodeError):
        raw.decode("utf-8")
    assert "crème brûlée" in raw.decode("latin-1")


def test_undecodable_file_decodes_as_nothing_sensible(docs_repo: DocsRepo) -> None:
    raw = show(docs_repo.path, "v1.3.0", "docs/legacy/undecodable.md")
    assert b"\0" not in raw  # it is not "binary"; it is text in no encoding
    for encoding in ("utf-8", "ascii", "cp1252"):
        with pytest.raises(UnicodeDecodeError):
            raw.decode(encoding)


def test_binary_files_contain_nul_bytes(docs_repo: DocsRepo) -> None:
    for path in ("docs/assets/logo.png", "docs/legacy/binary.md"):
        raw = show(docs_repo.path, "v1.3.0", path)
        assert raw.startswith(b"\x89PNG")
        assert b"\0" in raw


def test_oversized_file_is_above_the_default_cap(docs_repo: DocsRepo) -> None:
    size = int(git("cat-file", "-s", "v1.3.0:docs/reference/oversized.md", cwd=docs_repo.path))
    assert size > MAX_ARTICLE_BYTES
    # ... and it is the only article that is.
    sizes = git("ls-tree", "-r", "-l", "v1.3.0", cwd=docs_repo.path).splitlines()
    big = [line.split("\t")[1] for line in sizes if int(line.split()[3]) > MAX_ARTICLE_BYTES]
    assert big == ["docs/reference/oversized.md"]


def expected_queries() -> list[tuple[str, str, dict[str, str] | None]]:
    data = yaml.safe_load((FIXTURE / "expected-queries.yaml").read_text(encoding="utf-8"))
    return [
        (entry["query"], version, section)
        for entry in data["queries"]
        for version, section in entry["expected"].items()
    ]


def test_expected_queries_cover_the_versions() -> None:
    queries = expected_queries()
    assert {version for _, version, _ in queries} == set(VERSIONS)
    assert {"retry_policy", "snake_case", "camelCase", "--flag", "pkg.mod.fn"} <= {
        query for query, _, _ in queries
    }


@pytest.mark.parametrize(
    ("query", "version", "section"),
    [pytest.param(*row, id=f"{row[1]}:{row[0]}") for row in expected_queries()],
)
def test_expected_section_exists_in_that_version(
    docs_repo: DocsRepo, query: str, version: str, section: dict[str, str] | None
) -> None:
    repo = docs_repo.path
    if section is None:
        found = git(
            "grep", "-il", "-F", query.lower(), version, "--", "docs", cwd=repo, check=False
        )
        assert not found, f"{query!r} should find nothing in {version}"
        return
    article = show(repo, version, section["article"])
    text = (
        article.decode("latin-1") if section["article"].endswith("latin1.md") else article.decode()
    )
    assert tuple(section["heading_path"]) in headings(text)
    assert query.lower() in text.lower()


def test_history_names_every_commit_tree() -> None:
    history = tomllib.loads((FIXTURE / "history.toml").read_text(encoding="utf-8"))
    names = [commit["name"] for commit in history["commit"]]
    assert sorted(names) == sorted(p.name for p in (FIXTURE / "commits").iterdir())
