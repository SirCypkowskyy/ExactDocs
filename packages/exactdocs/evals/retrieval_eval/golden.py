"""The golden set (#345): questions with known answers over real projects' pinned docs.

``golden/corpus.yaml`` pins each project's repository, docs paths and one commit per version;
``golden/cases/<project>.yaml`` holds that project's cases in the retrieval dataset's own
Pydantic Evals format (``dataset.py``). Nothing upstream is vendored: each pinned commit is
fetched (``--depth 1``) into a cache outside the repository, and the section check reads the
articles from there with the importer's own parser and chunker. See docs/evals.md.
"""

import difflib
import os
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Final
from urllib.parse import urlsplit

import yaml
from pydantic import BaseModel, ConfigDict, Field
from pydantic_evals import Case, Dataset

from exactdocs.ingestion.adapters.driven.markdown_chunker import MarkdownChunker
from exactdocs.ingestion.constants import DEFAULT_MAX_ARTICLE_BYTES
from exactdocs.ingestion.models import PathSelection, parse_article
from fixture_repo import git, git_bytes
from retrieval_eval.dataset import GOLDEN_KINDS, Answer, CaseInfo, Question, RetrievalDataset

GOLDEN_DIR: Final[Path] = Path(__file__).parents[1] / "golden"
"""The golden set in the repository."""
CORPUS_FILE: Final[Path] = GOLDEN_DIR / "corpus.yaml"
"""The corpus manifest."""
CASES_DIR: Final[Path] = GOLDEN_DIR / "cases"
"""One case file per project, named after the project's ID."""
UNANSWERABLE: Final[str] = "unanswerable"
"""The kind of a case its version does not answer: it expects no section and no facts."""
CROSS_PAGE: Final[str] = "cross-page"
"""The kind of a case that needs sections of more than one article."""
MIN_CROSS_PAGE_ARTICLES: Final[int] = 2
"""The fewest articles a cross-page case expects sections of."""

type GoldenCase = Case[Question, Answer, CaseInfo]
"""One golden-set case."""


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class PinnedVersion(_Model):
    """One version of a project: its name and the commit it is pinned to."""

    name: str = Field(min_length=1)
    """The version as cases name it (the release tag)."""
    commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    """The full commit SHA it is imported at."""


class Project(_Model):
    """One upstream project whose docs the golden set asks about."""

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    """The project's ID: its case file is ``cases/<id>.yaml``."""
    title: str
    """Its display name."""
    repository: str
    """The git repository the docs live in (a URL ``git fetch`` takes)."""
    include: list[str] = Field(min_length=1)
    """The docs paths imported (``PathSelection`` include patterns)."""
    exclude: list[str] = Field(default_factory=list)
    """Paths left out (``PathSelection`` exclude patterns)."""
    licence: str
    """The SPDX licence of the repository, which covers its docs."""
    attribution: str
    """The copyright line to credit."""
    notes: str = ""
    """What this project brings to the corpus."""
    versions: list[PinnedVersion] = Field(min_length=1)
    """The pinned versions."""

    @property
    def library(self) -> str:
        """The library ID it is imported under: ``/<owner>/<repo>`` from the repository URL."""
        names = urlsplit(self.repository).path.strip("/").removesuffix(".git").split("/")
        return "/" + "/".join(names[-2:])

    @property
    def selection(self) -> PathSelection:
        """The files the importer takes as articles."""
        return PathSelection.of(self.include, self.exclude)

    def commit(self, version: str) -> str | None:
        """Return the commit a version is pinned to.

        Args:
            version: The version's name.

        Returns:
            The SHA, or ``None`` when the project has no such version.
        """
        return next((v.commit for v in self.versions if v.name == version), None)


class Corpus(_Model):
    """The corpus manifest."""

    projects: list[Project]
    """The projects, each with its pinned versions."""

    def project(self, project_id: str) -> Project | None:
        """Find a project.

        Args:
            project_id: Its ID.

        Returns:
            The project, or ``None``.
        """
        return next((p for p in self.projects if p.id == project_id), None)


def load_corpus(path: Path = CORPUS_FILE) -> Corpus:
    """Read the corpus manifest.

    Args:
        path: The YAML file; the one in the repository by default.

    Returns:
        The corpus.
    """
    return Corpus.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def default_cache_dir() -> Path:
    """Where fetched projects are kept: ``$XDG_CACHE_HOME/exactdocs/golden`` (``~/.cache``).

    Returns:
        The directory (it may not exist yet).
    """
    base = os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache"
    return Path(base) / "exactdocs" / "golden"


def has_commit(repo: Path, commit: str) -> bool:
    """Tell whether a cached repository holds a commit.

    Args:
        repo: The bare repository.
        commit: The SHA.

    Returns:
        True when the commit is there.
    """
    return git("cat-file", "-t", commit, cwd=repo, check=False) == "commit"


def fetch(project: Project, cache_dir: Path, *, offline: bool = False) -> Path:
    """Fetch every pinned commit of a project that the cache lacks, ``--depth 1``.

    The cache is a bare repository per project, configured so the importer can fetch a commit
    from it by SHA (as from a git host); each pinned commit is kept reachable by a tag named
    after its version.

    Args:
        project: The project.
        cache_dir: The cache directory.
        offline: Fetch nothing; the commits must already be cached.

    Returns:
        The cached repository.

    Raises:
        RuntimeError: A commit could not be fetched, or is missing offline.
    """
    repo = cache_dir / f"{project.id}.git"
    if not (repo / "HEAD").exists():
        repo.mkdir(parents=True, exist_ok=True)
        git("init", "-q", "--bare", "--template=", str(repo))
        git("config", "uploadpack.allowAnySHA1InWant", "true", cwd=repo)
        git("config", "uploadpack.allowFilter", "true", cwd=repo)
    missing = [v.commit for v in project.versions if not has_commit(repo, v.commit)]
    if missing and offline:
        message = f"{project.id}: not cached (offline): {', '.join(missing)}"
        raise RuntimeError(message)
    if missing:
        git("fetch", "-q", "--depth=1", "--no-tags", project.repository, *missing, cwd=repo)
    for version in project.versions:
        git("update-ref", f"refs/tags/{version.name}", version.commit, cwd=repo)
    return repo


def load_cases(cases_dir: Path = CASES_DIR) -> tuple[list[tuple[str, GoldenCase]], list[str]]:
    """Read every case file.

    Args:
        cases_dir: The directory of ``<project>.yaml`` files.

    Returns:
        ``(project, case)`` for every case, by file in name order; and one problem per file that
        does not load (YAML or the dataset's schema).
    """
    cases: list[tuple[str, GoldenCase]] = []
    problems = []
    for path in sorted(cases_dir.glob("*.yaml")):
        try:
            dataset = Dataset[Question, Answer, CaseInfo].from_file(path)
        except (ValueError, yaml.YAMLError) as error:  # pydantic's ValidationError is a ValueError
            problems.append(f"{path.name}: does not load: {error}")
            continue
        cases.extend((path.stem, case) for case in dataset.cases)
    return cases, problems


def load_golden(cases_dir: Path = CASES_DIR) -> RetrievalDataset:
    """Read the whole golden set as one dataset, for a benchmark to run.

    Args:
        cases_dir: The directory of ``<project>.yaml`` files.

    Returns:
        Every case; run ``just golden-validate`` first, this does not check them.

    Raises:
        ValueError: A file does not load.
    """
    cases, problems = load_cases(cases_dir)
    if problems:
        raise ValueError("; ".join(problems))
    return Dataset[Question, Answer, CaseInfo](name="golden", cases=[case for _, case in cases])


def schema_problems(cases: Sequence[tuple[str, GoldenCase]], corpus: Corpus) -> list[str]:
    """Check the rules of a golden case that the dataset's models do not.

    Args:
        cases: ``(project of its file, case)`` pairs.
        corpus: The corpus manifest.

    Returns:
        One ``<case>: <problem>`` line per broken rule.
    """
    problems = []
    seen: set[str] = set()
    for file_project, case in cases:
        name = case.name or "(unnamed)"
        if name in seen:
            problems.append(f"{name}: the name is used by another case")
        seen.add(name)
        problems.extend(f"{name}: {p}" for p in _case_problems(file_project, case, corpus))
    return problems


def _case_problems(file_project: str, case: GoldenCase, corpus: Corpus) -> Iterable[str]:
    """Check one case.

    Args:
        file_project: The project its file is named after.
        case: The case.
        corpus: The corpus manifest.

    Yields:
        Each broken rule.
    """
    question = case.inputs
    kind = case.metadata.kind if case.metadata else None
    if not case.name:
        yield "has no name"
    if kind not in GOLDEN_KINDS:
        yield f"kind is {kind!r}, not one of {', '.join(sorted(GOLDEN_KINDS))}"
    if question.project != file_project:
        yield f"project is {question.project!r}, but it is in {file_project}.yaml"
    project = corpus.project(file_project)
    if project is None:
        yield f"the corpus has no project {file_project!r}"
    elif project.commit(question.version) is None:
        yield f"{file_project} has no pinned version {question.version!r}"
    if case.expected_output is None:
        yield "has no expected_output"
    else:
        yield from _answer_problems(kind, question.version, case.expected_output)


def _answer_problems(kind: str | None, version: str, expected: Answer) -> Iterable[str]:
    """Check what a case expects against its kind.

    Args:
        kind: The case's kind.
        version: The version it asks about.
        expected: Its expected sections, reference answer and facts.

    Yields:
        Each broken rule.
    """
    if not (expected.reference or "").strip():
        yield "has no reference answer"
    if kind == UNANSWERABLE:
        if expected.hits:
            yield "is unanswerable but expects sections"
        if expected.facts:
            yield "is unanswerable but lists facts"
    else:
        if not expected.hits:
            yield "expects no section: name them, or make it unanswerable"
        if not [f for f in expected.facts if f.strip()]:
            yield "lists no facts a correct answer must contain"
    if kind == CROSS_PAGE and len({hit.article for hit in expected.hits}) < MIN_CROSS_PAGE_ARTICLES:
        yield "is cross-page but expects sections of fewer than two articles"
    for hit in expected.hits:
        if hit.version != version:
            yield f"expects a section of {hit.version}, not of its version {version}"


def article_sections(
    repo: Path, commit: str, article: str, selection: PathSelection
) -> set[tuple[str, ...]] | str:
    """Cut an article at a commit as the importer would, and return its sections.

    The article is read from the cached repository, parsed by ``parse_article`` and cut by the
    default ``MarkdownChunker``; every heading starts a chunk with the default settings, so the
    chunks' heading paths are every section ExactDocs produces for it.

    Args:
        repo: The cached repository.
        commit: The pinned commit.
        article: The article's repository path.
        selection: The project's include and exclude paths.

    Returns:
        The heading paths of its chunks, or why the importer would not take it.
    """
    if not selection.selects(article):
        return "is not a .md/.mdx file under the project's include paths"
    if git("cat-file", "-t", f"{commit}:{article}", cwd=repo, check=False) != "blob":
        return "does not exist at the pinned commit"
    data = git_bytes("cat-file", "blob", f"{commit}:{article}", cwd=repo)
    if len(data) > DEFAULT_MAX_ARTICLE_BYTES:
        return f"is larger than the importer takes ({DEFAULT_MAX_ARTICLE_BYTES} bytes)"
    # shortcut: UTF-8 only, where the importer also takes UTF-16 and Windows-1252; no corpus
    # file needs them today, use the importer's decoding if one does.
    text = data.decode("utf-8-sig")
    return {chunk.heading_path for chunk in MarkdownChunker().chunk(parse_article(article, text))}


def section_problems(
    cases: Sequence[tuple[str, GoldenCase]], corpus: Corpus, repos: Mapping[str, Path]
) -> list[str]:
    """Check that every expected section exists at its version's pinned commit.

    Args:
        cases: ``(project of its file, case)`` pairs.
        corpus: The corpus manifest.
        repos: The cached repository of each project.

    Returns:
        One ``<case>: <problem>`` line per missing article or section, with the closest
        sections the article has when only the heading path is wrong.
    """
    problems = []
    cut: dict[tuple[str, str, str], set[tuple[str, ...]] | str] = {}
    for file_project, case in cases:
        project = corpus.project(file_project)
        repo = repos.get(file_project)
        hits = case.expected_output.hits if case.expected_output else []
        for hit in hits:
            commit = project.commit(hit.version) if project else None
            if project is None or repo is None or commit is None:
                continue  # a schema problem, reported there
            key = (file_project, commit, hit.article)
            if key not in cut:
                cut[key] = article_sections(repo, commit, hit.article, project.selection)
            sections = cut[key]
            where = f"{hit.version}:{hit.article}"
            if isinstance(sections, str):
                problems.append(f"{case.name}: {where} {sections}")
            elif tuple(hit.heading_path) not in sections:
                problems.append(
                    f"{case.name}: {where} has no section {_shown(hit.heading_path)}"
                    + _closest(hit.heading_path, sections)
                )
    return problems


def _shown(path: Sequence[str]) -> str:
    """Show a heading path.

    Args:
        path: The headings, H1 first.

    Returns:
        ``[A > B]``.
    """
    return "[" + " > ".join(path) + "]"


def _closest(path: Sequence[str], sections: set[tuple[str, ...]]) -> str:
    """Suggest the article's sections closest to a wrong heading path.

    Args:
        path: The heading path a case names.
        sections: The article's sections.

    Returns:
        ``; closest: ...`` with up to three sections, or nothing when none is close.
    """
    shown = {_shown(s): s for s in sections}
    close = difflib.get_close_matches(_shown(path), list(shown), n=3, cutoff=0.5)
    return f"; closest: {', '.join(close)}" if close else ""
