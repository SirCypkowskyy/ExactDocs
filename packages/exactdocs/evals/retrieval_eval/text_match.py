"""Match a documentation tool's text results to the golden corpus's sections (#491).

The retrieval benchmark (#347) scores ExactDocs by reading each result's chunk ID back. Other
tools (Context7, Grounded Docs, a grep or fixed-window baseline) return text, so this module
decides from the text alone which sections of the corpus a result holds, in every pinned version
of the project, without a model.

Each pinned version's articles are cut as the golden set names its sections: the importer's own
parser and chunker at ``h6`` (every heading starts a section) with no size bound, so a section is
one heading's own text. Text is normalized to words (HTML entities decoded, link targets, bare
URLs and HTML or JSX tags dropped, case folded, letters and digits only) and compared as sets of
``SHINGLE_WORDS``-word shingles, so a reflowed paragraph, another list marker or Markdown
rendered as plain text still matches. A result answers a section when it holds at least
``MATCH_THRESHOLD`` of the section's own shingles (a coarser result: the section is inside it),
or when at least ``MATCH_THRESHOLD`` of the result's shingles lie in the section with its
subsections (a finer result: it is a part of the section). These are the text forms of the
nested match rule of chunk-ID scoring (``golden_run.nested_match``). See
docs/evals.md#scoring-text-results.
"""

import html
import re
import unicodedata
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final, Self

from exactdocs.ingestion.adapters.driven.markdown_chunker import MarkdownChunker
from exactdocs.ingestion.models import ChunkingConfig, parse_article
from retrieval_eval.golden import Project
from retrieval_eval.ingestion_cli import article_sources

SHINGLE_WORDS: Final[int] = 5
"""Words per shingle. A text of fewer words is one shingle of all of them."""
MATCH_THRESHOLD: Final[float] = 0.8
"""The share of shingles that must agree for a result to answer a section (calibrated against
chunk-ID scoring, docs/evals.md#calibration)."""
SECTION_CHUNKING: Final[ChunkingConfig] = ChunkingConfig(max_section_chars=None)
"""How the corpus is cut into sections: every heading, no merging, no bound (the golden set's
``h6``; ``golden.article_sections`` cuts the same headings)."""
_FENCE_INFO: Final[re.Pattern[str]] = re.compile(r"^([ \t]*(?:`{3,}|~{3,}))[^\n`]*$", re.MULTILINE)
"""A code fence line with its info string (```` ```tsx title="app.tsx" ````); a rendering
keeps the code and drops the info string."""
_ITEM_NUMBER: Final[re.Pattern[str]] = re.compile(r"^[ \t>]*\d{1,9}[.)](?=[ \t])", re.MULTILINE)
"""An ordered list item's number (``1.``), which a rendering turns into list markup."""
_LINK_TARGET: Final[re.Pattern[str]] = re.compile(r"\]\([^()\s]*(?:\([^()\s]*\)[^()\s]*)*\)")
"""The target of a Markdown link or image: ``](url)``; the text before it stays."""
_URL: Final[re.Pattern[str]] = re.compile(r"\b(?:https?|ftp)://[^\s<>()\[\]`'\"]+")
"""A bare URL: a tool may keep or drop it."""
_TAG: Final[re.Pattern[str]] = re.compile(r"</?[A-Za-z][\w.:-]*(?:\s[^<>]*)?/?>")
"""An HTML or JSX tag (``<Tabs>``, ``<a href=...>``, ``</div>``), which a rendering drops."""
_WORD: Final[re.Pattern[str]] = re.compile(r"[^\W_]+")
"""A word: a run of letters and digits (``on_startup`` is two words, as ``on startup``)."""


def words(text: str) -> list[str]:
    """Normalize a text to the words it is compared by.

    Args:
        text: Markdown, plain text or HTML-escaped text.

    Returns:
        Its words, case folded, in order.
    """
    text = _FENCE_INFO.sub(r"\1", unicodedata.normalize("NFKC", html.unescape(text)))
    text = _ITEM_NUMBER.sub(" ", text)
    text = _TAG.sub(" ", _URL.sub(" ", _LINK_TARGET.sub("] ", text)))
    return _WORD.findall(text.casefold())


def shingles(tokens: Sequence[str], size: int = SHINGLE_WORDS) -> frozenset[str]:
    """Cut words into overlapping shingles of ``size`` words.

    Args:
        tokens: The words, in order.
        size: Words per shingle.

    Returns:
        The distinct shingles; one of every word when there are fewer than ``size``, none when
        there is no word.
    """
    if len(tokens) < size:
        return frozenset({" ".join(tokens)}) if tokens else frozenset()
    return frozenset(" ".join(tokens[i : i + size]) for i in range(len(tokens) - size + 1))


@dataclass(frozen=True, slots=True, kw_only=True)
class Section:
    """A section of the corpus: where it lives, as a golden case names it."""

    version: str
    """The pinned version."""
    article: str
    """The article's repository path."""
    heading_path: tuple[str, ...]
    """Its headings from the H1; empty for the text before the first heading."""


class Verdict(StrEnum):
    """What a result's text says about the version it came from, for a version asked."""

    RIGHT = "right"
    """It matches sections of the version asked and of no other."""
    NEUTRAL = "neutral"
    """It matches sections of the version asked and of another: the text cannot tell them apart."""
    WRONG = "wrong"
    """It matches sections of another version and none of the version asked."""
    UNMATCHED = "unmatched"
    """It matches no section of any pinned version (text outside the corpus, or too little)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class TextMatch:
    """The sections one text result answers, in every pinned version of its project."""

    sections: frozenset[Section]
    """Every section it answers."""

    @property
    def versions(self) -> frozenset[str]:
        """The versions of those sections."""
        return frozenset(s.version for s in self.sections)

    def verdict(self, version: str) -> Verdict:
        """Say what the text says of its version, for a question about ``version``.

        Args:
            version: The version asked.

        Returns:
            ``RIGHT``, ``NEUTRAL``, ``WRONG`` or ``UNMATCHED``.
        """
        versions = self.versions
        if not versions:
            return Verdict.UNMATCHED
        if version not in versions:
            return Verdict.WRONG
        return Verdict.NEUTRAL if len(versions) > 1 else Verdict.RIGHT

    def answers(self, version: str, article: str, heading_path: Sequence[str]) -> bool:
        """Tell whether it answers one section.

        Args:
            version: The section's version.
            article: Its article.
            heading_path: Its heading path.

        Returns:
            True when the section is among those it answers.
        """
        wanted = Section(version=version, article=article, heading_path=tuple(heading_path))
        return wanted in self.sections


@dataclass(frozen=True, slots=True, kw_only=True)
class _Unit:
    """One heading's own text in the index."""

    section: Section
    """The section it is (two occurrences of a heading path are two units of one section)."""
    size: int
    """Its distinct shingles."""
    lineage: tuple[int, ...]
    """Its own index and those of the sections it is nested in, innermost first."""


@dataclass(frozen=True, slots=True, kw_only=True)
class SectionIndex:
    """Every section of every pinned version of one project, by shingle."""

    units: tuple[_Unit, ...]
    """Each heading's own text, in corpus order."""
    postings: Mapping[str, tuple[int, ...]]
    """The units holding each shingle."""
    threshold: float = MATCH_THRESHOLD
    """The share of shingles that must agree."""

    @classmethod
    def build(
        cls, versions: Mapping[str, Mapping[str, str]], *, threshold: float = MATCH_THRESHOLD
    ) -> Self:
        """Index articles: cut each at every heading and shingle each section.

        Args:
            versions: Each version's articles: the Markdown of each repository path.
            threshold: The share of shingles that must agree.

        Returns:
            The index.
        """
        chunker = MarkdownChunker(SECTION_CHUNKING)
        units: list[_Unit] = []
        postings: dict[str, list[int]] = {}
        for version, articles in versions.items():
            for path, text in sorted(articles.items()):
                open_: list[tuple[tuple[str, ...], tuple[int, ...]]] = []
                for chunk in chunker.chunk(parse_article(path, text)):
                    heading_path = chunk.heading_path
                    while open_ and not _within(heading_path, open_[-1][0]):
                        open_.pop()
                    index = len(units)
                    lineage = (index, *(open_[-1][1] if open_ else ()))
                    if heading_path:  # the text before the first heading holds nothing
                        open_.append((heading_path, lineage))
                    own = shingles(words(chunk.content))
                    units.append(
                        _Unit(
                            section=Section(
                                version=version, article=path, heading_path=heading_path
                            ),
                            size=len(own),
                            lineage=lineage,
                        )
                    )
                    for shingle in own:
                        postings.setdefault(shingle, []).append(index)
        return cls(
            units=tuple(units),
            postings={s: tuple(ids) for s, ids in postings.items()},
            threshold=threshold,
        )

    @classmethod
    def of_project(cls, project: Project, repo: Path, *, threshold: float = MATCH_THRESHOLD) -> Self:
        """Index every pinned version of a project from its cached repository.

        Args:
            project: The project (its versions and docs paths).
            repo: The cached repository (``golden.fetch``).
            threshold: The share of shingles that must agree.

        Returns:
            The index of every article the importer would take, as it reads them.
        """
        versions = {
            pinned.name: {
                path: body
                for path, body in article_sources(repo, pinned.commit, project).items()
                if body is not None
            }
            for pinned in project.versions
        }
        return cls.build(versions, threshold=threshold)

    def with_threshold(self, threshold: float) -> Self:
        """Return the same index matching at another threshold (the calibration's sweep).

        Args:
            threshold: The share of shingles that must agree.

        Returns:
            A copy sharing the shingles.
        """
        return type(self)(units=self.units, postings=self.postings, threshold=threshold)

    def match(self, text: str) -> TextMatch:
        """Find every section a text result answers.

        Args:
            text: The result's text, as the tool returned it.

        Returns:
            The sections it holds (a coarser result) or lies within (a finer one).
        """
        own = shingles(words(text))
        if not own:
            return TextMatch(sections=frozenset())
        held: Counter[int] = Counter()  # the shingles of a unit's own text found in the result
        within: Counter[int] = Counter()  # the result's shingles found in a unit's subtree
        for shingle in own:
            units = self.postings.get(shingle, ())
            held.update(units)
            within.update({i for unit in units for i in self.units[unit].lineage})
        need = self.threshold - 1e-9
        found = {i for i, n in held.items() if n / self.units[i].size >= need}
        found |= {i for i, n in within.items() if n / len(own) >= need}
        return TextMatch(sections=frozenset(self.units[i].section for i in found))

    def match_all(self, texts: Iterable[str]) -> list[TextMatch]:
        """Match several results.

        Args:
            texts: The results' texts, in rank order.

        Returns:
            One match per result, in the same order.
        """
        return [self.match(text) for text in texts]


def _within(path: tuple[str, ...], parent: tuple[str, ...]) -> bool:
    """Tell whether a heading path is nested in another.

    Args:
        path: The inner heading path.
        parent: The outer one (not empty).

    Returns:
        True when ``parent`` is a proper prefix of ``path``.
    """
    return len(path) > len(parent) and path[: len(parent)] == parent
