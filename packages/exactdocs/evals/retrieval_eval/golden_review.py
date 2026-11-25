"""The golden set's review (#490): a seeded sample, its verdicts, and checks over the whole set.

``golden/review.yaml`` records the verdict of every case of a stratified random sample (three per
question kind and project): ``correct``, ``fixed`` or ``removed``, with the problems found, who
reviewed it, when and why. ``just golden-validate`` checks it against the case files, and
``just bench-pages`` renders its summary (verdicts, problems, the error rate with a 95% Wilson
interval) on docs/benchmark/golden-set.md.

The whole-set checks read every section of every pinned version, cut as the importer cuts it, and
measure how the questions are worded against the docs: how much of a question's vocabulary its
expected section holds against the best other section of that version (a question that copies its
section's words favours keyword search), near-duplicate questions, and where the vocabulary of
each ``unanswerable`` case occurs in its version. See
docs/evals/golden-set.md#reviewing-the-golden-set.
"""

import datetime as dt
import math
import random
import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Final, Literal, get_args

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from exactdocs.ingestion.adapters.driven.markdown_chunker import MarkdownChunker
from exactdocs.ingestion.constants import DEFAULT_MAX_ARTICLE_BYTES
from exactdocs.ingestion.models import parse_article
from fixture_repo import git, git_bytes
from retrieval_eval.dataset import GoldenKind
from retrieval_eval.golden import GOLDEN_DIR, UNANSWERABLE, Corpus, GoldenCase, Project

REVIEW_FILE: Final[Path] = GOLDEN_DIR / "review.yaml"
"""The review's verdicts in the repository."""
Z_95: Final[float] = 1.959963984540054
"""The standard normal quantile of a two-sided 95% interval."""
COPY_RUN: Final[int] = 5
"""A question that shares this many consecutive words with its expected section copies it."""
COPY_CONTENT_WORDS: Final[int] = 3
"""... of which at least this many are not stop words."""
NEAR_DUPLICATE: Final[float] = 0.5
"""Two questions of a project are listed as near-duplicates when their content words overlap this
much (Jaccard)."""
UNANSWERABLE_FLAG: Final[float] = 0.75
"""An ``unanswerable`` case is checked by hand when one section holds this share of its words."""
OUTMATCHED_RANK: Final[int] = 3
"""The checks list the cases whose expected section is not among this many best matches on the
question's words."""

type Verdict = Literal["correct", "fixed", "removed"]
"""What the review decided for a case."""
type Problem = Literal[
    "unsupported-fact",
    "wrong-reference",
    "missing-section",
    "wrong-section",
    "wrong-kind",
    "answerable",
    "not-a-change",
    "ambiguous",
    "duplicate",
]
"""Why a case was wrong (docs/evals/golden-set.md#reviewing-the-golden-set):

- ``unsupported-fact``: a fact the expected sections do not state at that version (or only imply);
- ``wrong-reference``: the reference answer is wrong or incomplete for that version;
- ``missing-section``: another section of that version answers it as well, but is not expected;
- ``wrong-section``: an expected section does not answer it;
- ``wrong-kind``: the case has the wrong kind;
- ``answerable``: an ``unanswerable`` case that the version's docs do answer;
- ``not-a-change``: a ``version-change`` case whose change the neighbouring versions contradict;
- ``ambiguous``: the question has more than one fair answer, or none without guessing;
- ``duplicate``: another case asks the same of the same version.
"""
PROBLEMS: Final[tuple[str, ...]] = get_args(Problem.__value__)
"""Every problem category, in the order the summary lists them."""
KINDS: Final[tuple[str, ...]] = get_args(GoldenKind.__value__)
"""Every golden-set kind, in the order the case files' docs list them."""


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", use_attribute_docstrings=True)


class SampleSpec(_Model):
    """How the reviewed sample was drawn (``draw_sample``)."""

    seed: int
    """The random seed."""
    per_stratum: int = Field(ge=1)
    """Cases drawn per question kind and project."""
    drawn_from: str
    """The golden set's fingerprint when the sample was drawn (before any fix)."""


class ReviewEntry(_Model):
    """The verdict on one sampled case."""

    case: str = Field(min_length=1)
    """The case's name; for a fix that renamed it, the new name."""
    project: str
    """The project it was drawn from (its stratum)."""
    kind: GoldenKind
    """The kind it was drawn as (its stratum); a fix may have changed the case's kind since."""
    verdict: Verdict
    """``correct``, ``fixed`` (the case was corrected) or ``removed`` (it was deleted)."""
    problems: list[Problem] = Field(default_factory=list)
    """What was wrong; empty when correct."""
    reviewer: str = Field(min_length=1)
    """Who reviewed it."""
    date: dt.date
    """When."""
    note: str = ""
    """Why: the source line that proves a defect, or what was checked."""
    was: str | None = None
    """The case's name before a fix renamed it."""


class Review(_Model):
    """``golden/review.yaml``: the sample and its verdicts."""

    sample: SampleSpec
    """How the sample was drawn."""
    entries: list[ReviewEntry]
    """One verdict per sampled case."""


def load_review(path: Path = REVIEW_FILE) -> Review:
    """Read the review file.

    Args:
        path: The YAML file; the one in the repository by default.

    Returns:
        The review.
    """
    return Review.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def review_file_problems(
    cases: Sequence[tuple[str, GoldenCase]], path: Path = REVIEW_FILE
) -> list[str]:
    """Check the review file against the case files, as ``just golden-validate`` does.

    Args:
        cases: ``(project of its file, case)`` pairs.
        path: The review file; a missing file is no problem (there is no review yet).

    Returns:
        One problem per broken rule, each starting with the file name.
    """
    if not path.exists():
        return []
    try:
        review = load_review(path)
    except (ValidationError, yaml.YAMLError) as error:
        return [f"{path.name}: does not load: {error}"]
    return [f"{path.name}: {problem}" for problem in review_problems(review, cases)]


def review_problems(review: Review, cases: Sequence[tuple[str, GoldenCase]]) -> list[str]:
    """Check the verdicts against the cases.

    A ``correct`` or ``fixed`` case is in the set, a ``removed`` one is not; a case is reviewed
    once; ``correct`` names no problem and the other verdicts name at least one and say why;
    every stratum (kind and project) holds ``per_stratum`` entries, or all its cases when it has
    fewer (its cases now, plus the ones the review removed from it).

    Args:
        review: The review.
        cases: ``(project of its file, case)`` pairs.

    Returns:
        One ``<case>: <problem>`` line per broken rule.
    """
    names = {case.name for _, case in cases}
    problems = []
    seen: set[str] = set()
    for entry in review.entries:
        if entry.case in seen:
            problems.append(f"{entry.case}: reviewed twice")
        seen.add(entry.case)
        problems.extend(f"{entry.case}: {p}" for p in _entry_problems(entry, names))
    strata: Counter[tuple[str, str]] = Counter((e.project, e.kind) for e in review.entries)
    sizes: Counter[tuple[str, str]] = Counter(
        (project, case.metadata.kind if case.metadata else "") for project, case in cases
    )
    sizes.update((e.project, e.kind) for e in review.entries if e.verdict == "removed")
    for project in sorted({project for project, _ in cases}):
        for kind in KINDS:
            want = min(review.sample.per_stratum, sizes[project, kind])
            if (n := strata[project, kind]) != want:
                problems.append(f"{project} {kind}: {n} entries, not {want}")
    return problems


def _entry_problems(entry: ReviewEntry, names: set[str | None]) -> Iterable[str]:
    """Check one verdict.

    Args:
        entry: The verdict.
        names: The name of every case in the set.

    Yields:
        Each broken rule.
    """
    verdict = entry.verdict
    if verdict == "removed" and entry.case in names:
        yield "is removed but still in the golden set"
    if verdict != "removed" and entry.case not in names:
        yield f"is {verdict} but not in the golden set"
    if verdict == "correct" and entry.problems:
        yield "is correct but names problems"
    if verdict != "correct" and not entry.problems:
        yield f"is {verdict} but names no problem"
    if verdict != "correct" and not entry.note.strip():
        yield f"is {verdict} but has no note saying why"
    if entry.was is not None and entry.was in names:
        yield f"was renamed from {entry.was!r}, which is still in the set"
    if not entry.case.startswith(f"{entry.project} "):
        yield f"is not a case of {entry.project}"


def draw_sample(
    cases: Sequence[tuple[str, GoldenCase]], *, seed: int, per_stratum: int
) -> list[tuple[str, GoldenCase]]:
    """Draw a stratified random sample: ``per_stratum`` cases of every kind and project.

    Each stratum is drawn with its own generator, seeded with the seed and the stratum, from its
    cases in name order: the same seed and set always give the same sample, and adding a case to
    one stratum leaves the others' draws unchanged.

    Args:
        cases: ``(project of its file, case)`` pairs.
        seed: The random seed.
        per_stratum: Cases per stratum; a smaller stratum is taken whole.

    Returns:
        The sampled ``(project, case)`` pairs, by project, then kind, then name.
    """
    strata: dict[tuple[str, str], list[tuple[str, GoldenCase]]] = defaultdict(list)
    for project, case in cases:
        strata[project, case.metadata.kind if case.metadata else ""].append((project, case))
    sample = []
    for (project, kind), members in sorted(strata.items()):
        members.sort(key=lambda pc: pc[1].name or "")
        rng = random.Random(f"{seed}:{project}:{kind}")
        drawn = rng.sample(members, min(per_stratum, len(members)))
        sample.extend(sorted(drawn, key=lambda pc: pc[1].name or ""))
    return sample


def wilson(successes: int, n: int, z: float = Z_95) -> tuple[float, float]:
    """The Wilson score interval of a proportion.

    Args:
        successes: How many of the trials counted.
        n: The trials.
        z: The normal quantile; a two-sided 95% interval by default.

    Returns:
        ``(low, high)``; ``(0.0, 1.0)`` for no trials.
    """
    if n == 0:
        return 0.0, 1.0
    p = successes / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, centre - half), min(1.0, centre + half)


@dataclass(frozen=True, slots=True, kw_only=True)
class ReviewSummary:
    """What a review found."""

    size: int
    """The cases reviewed."""
    verdicts: Mapping[str, int]
    """Cases per verdict."""
    problems: Mapping[str, int]
    """Cases per problem category (a case may count in several)."""
    wrong: int
    """Cases found wrong (fixed or removed)."""
    interval: tuple[float, float]
    """The 95% Wilson interval of the share of wrong cases."""
    by_kind: Mapping[str, tuple[int, int]]
    """Per kind drawn: ``(wrong, reviewed)``."""
    by_project: Mapping[str, tuple[int, int]]
    """Per project: ``(wrong, reviewed)``."""

    @property
    def rate(self) -> float:
        """The share of reviewed cases found wrong."""
        return self.wrong / self.size if self.size else 0.0


def summarize(review: Review) -> ReviewSummary:
    """Count the verdicts and problems, and bound the error rate.

    Args:
        review: The review.

    Returns:
        The summary.
    """
    entries = review.entries
    wrong = sum(e.verdict != "correct" for e in entries)
    by_kind: dict[str, tuple[int, int]] = {}
    for kind in KINDS:
        of = [e for e in entries if e.kind == kind]
        by_kind[kind] = (sum(e.verdict != "correct" for e in of), len(of))
    by_project: dict[str, tuple[int, int]] = {}
    for project in sorted({e.project for e in entries}):
        of = [e for e in entries if e.project == project]
        by_project[project] = (sum(e.verdict != "correct" for e in of), len(of))
    return ReviewSummary(
        size=len(entries),
        verdicts={v: sum(e.verdict == v for e in entries) for v in get_args(Verdict.__value__)},
        problems={p: sum(p in e.problems for e in entries) for p in PROBLEMS},
        wrong=wrong,
        interval=wilson(wrong, len(entries)),
        by_kind=by_kind,
        by_project=by_project,
    )


def _pct(value: float) -> str:
    """A share as a percentage.

    Returns:
        ``12.3%``.
    """
    return f"{value * 100:.1f}%"


def review_block(review: Review) -> str:
    """The review's summary for docs/benchmark/golden-set.md (``just bench-pages``).

    Args:
        review: The review.

    Returns:
        The Markdown.
    """
    s = summarize(review)
    low, high = s.interval
    reviewers = sorted({e.reviewer for e in review.entries})
    dates = sorted({e.date for e in review.entries})
    when = dates[0].isoformat() if len(dates) == 1 else f"{dates[0]} to {dates[-1]}"
    lines = [
        (
            f"- Sample: {s.size} cases, {review.sample.per_stratum} per kind and project, seed "
            f"{review.sample.seed}, drawn from golden set `{review.sample.drawn_from}`."
        ),
        f"- Reviewed by: {'; '.join(reviewers)}, {when}.",
        (
            f"- Verdicts: {s.verdicts['correct']} correct, {s.verdicts['fixed']} fixed, "
            f"{s.verdicts['removed']} removed."
        ),
        (
            f"- Wrong cases: {s.wrong} of {s.size}, {_pct(s.rate)} "
            f"(95% Wilson interval {_pct(low)} to {_pct(high)})."
        ),
        "",
        "| Problem | Cases |",
        "|---|---|",
        *(f"| `{p}` | {n} |" for p, n in s.problems.items() if n),
        "",
        "| Kind | Wrong / reviewed |",
        "|---|---|",
        *(f"| `{k}` | {w} / {n} |" for k, (w, n) in s.by_kind.items()),
        "",
        "| Project | Wrong / reviewed |",
        "|---|---|",
        *(f"| {p} | {w} / {n} |" for p, (w, n) in s.by_project.items()),
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------- the docs as text


@dataclass(frozen=True, slots=True, kw_only=True)
class Section:
    """One section of a pinned version, as the importer cuts it (every heading starts one)."""

    article: str
    """The article's repository path."""
    heading_path: tuple[str, ...]
    """Its headings, from the top one."""
    anchor: str
    """The heading's anchor in the article; empty before the first heading."""
    text: str
    """Its Markdown, the parts of a split section joined."""

    @property
    def key(self) -> tuple[str, tuple[str, ...]]:
        """``(article, heading path)``, as a case names it."""
        return self.article, self.heading_path


def version_sections(repo: Path, commit: str, project: Project) -> list[Section]:
    """Cut every article of a pinned version as the importer would.

    Args:
        repo: The cached repository.
        commit: The pinned commit.
        project: The project (its include and exclude paths).

    Returns:
        Every section, by article path and position; a heading path repeated in an article is one
        section, as a case cannot tell them apart.
    """
    selection = project.selection
    paths = git("ls-tree", "-r", "--name-only", commit, cwd=repo).splitlines()
    sections = []
    for path in sorted(p for p in paths if selection.selects(p)):
        data = git_bytes("cat-file", "blob", f"{commit}:{path}", cwd=repo)
        if len(data) > DEFAULT_MAX_ARTICLE_BYTES:
            continue
        text = data.decode("utf-8-sig", errors="replace")
        merged: dict[tuple[str, ...], list[str]] = {}
        anchors: dict[tuple[str, ...], str] = {}
        for chunk in MarkdownChunker().chunk(parse_article(path, text)):
            merged.setdefault(chunk.heading_path, []).append(chunk.content)
            anchors.setdefault(chunk.heading_path, chunk.anchor)
        sections.extend(
            Section(article=path, heading_path=hp, anchor=anchors[hp], text="".join(parts))
            for hp, parts in merged.items()
        )
    return sections


def source_link(project: Project, commit: str, article: str, anchor: str = "") -> str:
    """Link to an article at a pinned commit on its host.

    Args:
        project: The project.
        commit: The commit.
        article: The article's path.
        anchor: A heading's anchor, if any.

    Returns:
        ``<repository>/blob/<commit>/<article>#<anchor>``.
    """
    base = project.repository.removesuffix(".git").rstrip("/")
    return f"{base}/blob/{commit}/{article}" + (f"#{anchor}" if anchor else "")


# --------------------------------------------------------------------------- words

_WORD: Final[re.Pattern[str]] = re.compile(r"[a-z0-9]+(?:_[a-z0-9]+)*")
_STOP: Final[frozenset[str]] = frozenset({
    "a", "about", "above", "after", "again", "against", "all", "also", "am", "an", "and", "any",
    "are", "aren", "as", "at", "be", "because", "been", "before", "being", "below", "between",
    "both", "but", "by", "can", "cannot", "could", "did", "didn", "do", "does", "doesn", "doing",
    "don", "down", "during", "each", "else", "even", "ever", "every", "few", "for", "from",
    "further", "get", "gets", "got", "had", "has", "have", "having", "he", "her", "here", "hers",
    "him", "his", "how", "i", "if", "in", "into", "is", "isn", "it", "its", "itself", "just",
    "let", "lets", "like", "make", "makes", "may", "me", "might", "more", "most", "must", "my",
    "no", "nor", "not", "now", "of", "off", "on", "once", "one", "only", "or", "other", "our",
    "ours", "out", "over", "own", "same", "shall", "she", "should", "so", "some", "such", "than",
    "that", "the", "their", "theirs", "them", "then", "there", "these", "they", "this", "those",
    "through", "to", "too", "under", "until", "up", "upon", "us", "use", "used", "uses", "using",
    "very", "via", "was", "we", "were", "what", "when", "where", "whether", "which", "while",
    "who", "whom", "why", "will", "with", "within", "without", "would", "yes", "yet", "you",
    "your", "yours", "instead", "way", "ways", "need", "needs", "want", "wants", "still",
})  # fmt: skip
"""English function words, and the words every how-to question uses, left out of the overlap."""
_MIN_PLURAL: Final[int] = 3
"""Words this short keep a final ``s``."""


def words(text: str) -> list[str]:
    """Split text into lower-case words (identifiers with ``_`` stay whole).

    Args:
        text: The text.

    Returns:
        The words in order.
    """
    return _WORD.findall(text.lower())


def stem(word: str) -> str:
    """Strip a plural or verb ending, crudely, so ``handlers`` and ``handler`` match.

    Args:
        word: A lower-case word.

    Returns:
        Its stem.
    """
    for suffix, keep, replace in (("ies", 4, "y"), ("ing", 5, ""), ("ed", 4, ""), ("es", 4, "")):
        if len(word) > keep and word.endswith(suffix):
            return word[: -len(suffix)] + replace
    if len(word) > _MIN_PLURAL and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def terms(text: str) -> set[str]:
    """The content words of a text, stemmed: what the overlap compares.

    Args:
        text: The text.

    Returns:
        Its stems, stop words and one-character words left out.
    """
    return {stem(w) for w in words(text) if w not in _STOP and len(w) > 1}


@dataclass(frozen=True, slots=True, kw_only=True)
class _Indexed:
    """A version's sections with their terms, and each term's inverse document frequency."""

    sections: list[Section]
    """The sections."""
    terms: list[set[str]]
    """The terms of each section, headings included."""
    idf: dict[str, float]
    """``log((N + 1) / (df + 1)) + 1`` of every term; a term no section has gets the highest."""
    n: int
    """The number of sections."""

    def weight(self, term: str) -> float:
        """The weight of a term in this version.

        Returns:
            Its IDF.
        """
        return self.idf.get(term, math.log(self.n + 1) + 1)

    def coverage(self, query: set[str], section: set[str]) -> float:
        """The IDF-weighted share of the query's terms a section holds.

        Returns:
            A value from 0 to 1; 0 for a query without terms.
        """
        total = sum(self.weight(t) for t in query)
        return sum(self.weight(t) for t in query & section) / total if total else 0.0

    def ranked(self, query: set[str]) -> list[tuple[float, int]]:
        """Every section by coverage of the query, best first.

        Returns:
            ``(coverage, section index)`` pairs.
        """
        return sorted(
            ((self.coverage(query, t), i) for i, t in enumerate(self.terms)),
            key=lambda ci: (-ci[0], ci[1]),
        )


def index(sections: list[Section]) -> _Indexed:
    """Index a version's sections for the overlap measures.

    Args:
        sections: The version's sections.

    Returns:
        The index.
    """
    section_terms = [terms(" ".join(s.heading_path) + "\n" + s.text) for s in sections]
    df = Counter(t for ts in section_terms for t in ts)
    n = len(sections)
    idf = {t: math.log((n + 1) / (d + 1)) + 1 for t, d in df.items()}
    return _Indexed(sections=sections, terms=section_terms, idf=idf, n=n)


def longest_run(question: str, text: str) -> list[str]:
    """The longest run of consecutive words a question shares with a text.

    Args:
        question: The question.
        text: The section.

    Returns:
        The shared words, in order.
    """
    q, t = words(question), words(text)
    match = SequenceMatcher(None, q, t, autojunk=False).find_longest_match()
    return q[match.a : match.a + match.size]


def copies(run: Sequence[str]) -> bool:
    """Tell whether a shared run of words is a copied phrase, not a shared name.

    Returns:
        True for ``COPY_RUN`` words or more, ``COPY_CONTENT_WORDS`` of them content words.
    """
    content = [w for w in run if w not in _STOP and len(w) > 1]
    return len(run) >= COPY_RUN and len(content) >= COPY_CONTENT_WORDS


# --------------------------------------------------------------------------- whole-set checks


@dataclass(frozen=True, slots=True, kw_only=True)
class Overlap:
    """How much of a question's vocabulary its expected section holds, against the others."""

    case: str
    """The case's name."""
    kind: str
    """Its kind."""
    expected: float
    """The best IDF-weighted coverage of the question's terms by an expected section."""
    best_other: float
    """The same for the best section of the version that is not expected."""
    rank: int
    """The best expected section's rank among all sections of the version by coverage (1 is
    first; ties go to the expected section)."""
    run: tuple[str, ...]
    """The longest run of words the question shares with an expected section."""
    other_section: str
    """The best other section, as ``article [heading > path]``."""

    @property
    def lead(self) -> float:
        """``expected - best_other``: how much better the expected section matches the words."""
        return self.expected - self.best_other

    @property
    def copied(self) -> bool:
        """The question copies a phrase of its expected section (``copies``)."""
        return copies(self.run)


@dataclass(frozen=True, slots=True, kw_only=True)
class Duplicate:
    """Two questions of a project that ask nearly the same."""

    a: str
    """One case's name."""
    b: str
    """The other's."""
    similarity: float
    """The Jaccard similarity of their content words."""
    same_version: bool
    """Both ask the same version (a true duplicate) rather than the same thing of two versions."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Vocabulary:
    """Where an ``unanswerable`` case's words occur in its version."""

    case: str
    """The case's name."""
    absent: tuple[str, ...]
    """Its terms no section of the version holds."""
    best: tuple[tuple[str, float, tuple[str, ...]], ...]
    """The sections holding most of its terms: ``(section, coverage, terms it lacks)``."""

    @property
    def flagged(self) -> bool:
        """One section holds ``UNANSWERABLE_FLAG`` of the weighted terms: check it by hand."""
        return bool(self.best) and self.best[0][1] >= UNANSWERABLE_FLAG


@dataclass(slots=True, kw_only=True)  # conventions: allow-mutable-dataclass -- filled per project
class Checks:
    """The whole-set checks."""

    overlaps: list[Overlap] = field(default_factory=list)
    """One per answerable case."""
    duplicates: list[Duplicate] = field(default_factory=list)
    """Near-duplicate question pairs."""
    vocabulary: list[Vocabulary] = field(default_factory=list)
    """One per unanswerable case."""


def _shown(section: Section) -> str:
    """Name a section.

    Returns:
        ``article [A > B]``.
    """
    return f"{section.article} [{' > '.join(section.heading_path)}]"


def overlap(case: GoldenCase, idx: _Indexed) -> Overlap | None:
    """Measure one answerable case's question against its version's sections.

    Args:
        case: The case.
        idx: Its version's index.

    Returns:
        The overlap, or ``None`` for a case that expects no section of the index.
    """
    hits = case.expected_output.hits if case.expected_output else []
    wanted = {(h.article, tuple(h.heading_path)) for h in hits}
    expected = [i for i, s in enumerate(idx.sections) if s.key in wanted]
    if not expected:
        return None
    query = terms(case.inputs.query)
    ranked = idx.ranked(query)
    best_expected = max(idx.coverage(query, idx.terms[i]) for i in expected)
    others = [(c, i) for c, i in ranked if i not in expected]
    best_other, other = others[0] if others else (0.0, -1)
    rank = 1 + sum(c > best_expected for c, i in ranked if i not in expected)
    runs = [longest_run(case.inputs.query, idx.sections[i].text) for i in expected]
    return Overlap(
        case=case.name or "",
        kind=case.metadata.kind if case.metadata else "",
        expected=round(best_expected, 4),
        best_other=round(best_other, 4),
        rank=rank,
        run=tuple(max(runs, key=len)),
        other_section=_shown(idx.sections[other]) if other >= 0 else "",
    )


def vocabulary(case: GoldenCase, idx: _Indexed, top: int = 3) -> Vocabulary:
    """Find where an unanswerable case's words occur in its version.

    Args:
        case: The case.
        idx: Its version's index.
        top: How many sections to list.

    Returns:
        Its absent terms and the sections holding most of them.
    """
    query = terms(case.inputs.query)
    absent = tuple(sorted(t for t in query if t not in idx.idf))
    best = tuple(
        (_shown(idx.sections[i]), round(c, 4), tuple(sorted(query - idx.terms[i])))
        for c, i in idx.ranked(query)[:top]
        if c > 0
    )
    return Vocabulary(case=case.name or "", absent=absent, best=best)


def near_duplicates(cases: Sequence[tuple[str, GoldenCase]]) -> list[Duplicate]:
    """Pair the questions of each project that share most of their content words.

    Args:
        cases: ``(project of its file, case)`` pairs.

    Returns:
        Every pair at ``NEAR_DUPLICATE`` or above, most similar first.
    """
    by_project: dict[str, list[GoldenCase]] = defaultdict(list)
    for project, case in cases:
        by_project[project].append(case)
    pairs = []
    for members in by_project.values():
        bags = [terms(c.inputs.query) for c in members]
        for i, a in enumerate(members):
            for j in range(i + 1, len(members)):
                union = bags[i] | bags[j]
                similarity = len(bags[i] & bags[j]) / len(union) if union else 0.0
                if similarity >= NEAR_DUPLICATE:
                    b = members[j]
                    pairs.append(
                        Duplicate(
                            a=a.name or "",
                            b=b.name or "",
                            similarity=round(similarity, 4),
                            same_version=a.inputs.version == b.inputs.version,
                        )
                    )
    return sorted(pairs, key=lambda d: (-d.similarity, d.a, d.b))


def run_checks(
    cases: Sequence[tuple[str, GoldenCase]], corpus: Corpus, repos: Mapping[str, Path]
) -> Checks:
    """Run the whole-set checks.

    Args:
        cases: ``(project of its file, case)`` pairs.
        corpus: The corpus manifest.
        repos: The cached repository of each project.

    Returns:
        The overlap of every answerable case, the near-duplicates and the vocabulary of every
        unanswerable case.
    """
    checks = Checks(duplicates=near_duplicates(cases))
    for project in corpus.projects:
        repo = repos.get(project.id)
        if repo is None:
            continue
        for version in project.versions:
            of = [c for p, c in cases if p == project.id and c.inputs.version == version.name]
            if not of:
                continue
            idx = index(version_sections(repo, version.commit, project))
            for case in of:
                if case.metadata and case.metadata.kind == UNANSWERABLE:
                    checks.vocabulary.append(vocabulary(case, idx))
                elif found := overlap(case, idx):
                    checks.overlaps.append(found)
    return checks


def _mean(values: Iterable[float]) -> float:
    """The mean, 0 for none.

    Returns:
        The mean.
    """
    values = list(values)
    return sum(values) / len(values) if values else 0.0


def checks_markdown(checks: Checks) -> str:
    """Render the whole-set checks.

    Args:
        checks: The checks.

    Returns:
        The Markdown report.
    """
    o = checks.overlaps
    lines = [
        "# Golden set: whole-set checks",
        "",
        "## Lexical overlap",
        "",
        (
            "Coverage: the IDF-weighted share of a question's content words (stemmed, stop words "
            "left out) that a section holds, headings included. *Expected*: its best expected "
            "section; *best other*: the best section of the same version that is not expected; "
            "*rank 1*: no other section covers more. *Copied*: the question shares a run of "
            f"{COPY_RUN} or more words ({COPY_CONTENT_WORDS} content words) with an expected "
            "section."
        ),
        "",
        "| Kind | Cases | Expected | Best other | Lead | Rank 1 | Copied |",
        "|---|---|---|---|---|---|---|",
    ]
    for kind in (*KINDS, "all"):
        of = [x for x in o if kind in {"all", x.kind}]
        if not of:
            continue
        lines.append(
            f"| {kind} | {len(of)} | {_pct(_mean(x.expected for x in of))} "
            f"| {_pct(_mean(x.best_other for x in of))} | {_pct(_mean(x.lead for x in of))} "
            f"| {_pct(_mean(x.rank == 1 for x in of))} | {sum(x.copied for x in of)} |"
        )
    copied = sorted((x for x in o if x.copied), key=lambda x: (-len(x.run), x.case))
    lines += ["", f"### Questions that copy their section ({len(copied)})", ""]
    lines += [f"- {x.case} — “{' '.join(x.run)}”" for x in copied] or ["None."]
    lines += [
        "",
        "### Expected section out-matched on words (rank above 3)",
        "",
        *(
            f"- {x.case}: rank {x.rank}, expected {_pct(x.expected)}, "
            f"best other {_pct(x.best_other)} ({x.other_section})"
            for x in sorted(o, key=lambda x: (-x.rank, x.case))
            if x.rank > OUTMATCHED_RANK
        ),
    ]
    d = checks.duplicates
    lines += [
        "",
        f"## Near-duplicate questions ({len(d)}; Jaccard of content words >= {NEAR_DUPLICATE})",
        "",
        (
            f"Same version: {sum(x.same_version for x in d)}; the same question of two versions: "
            f"{sum(not x.same_version for x in d)}."
        ),
        "",
        *(
            f"- {x.similarity:.2f}{' SAME VERSION' if x.same_version else ''}: {x.a} | {x.b}"
            for x in d
        ),
    ]
    v = checks.vocabulary
    lines += [
        "",
        f"## The vocabulary of the unanswerable cases ({len(v)})",
        "",
        (
            f"Flagged (one section holds {_pct(UNANSWERABLE_FLAG)} of the weighted words, check by "
            f"hand): {sum(x.flagged for x in v)}."
        ),
        "",
    ]
    for x in sorted(v, key=lambda x: (not x.flagged, x.case)):
        best = "; ".join(
            f"{s} {_pct(c)}" + (f" (lacks {', '.join(lacks)})" if lacks else "")
            for s, c, lacks in x.best
        )
        absent = f" Absent: {', '.join(x.absent)}." if x.absent else ""
        lines.append(f"- {'FLAG ' if x.flagged else ''}{x.case}.{absent} Best: {best or '-'}")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- the review sheet


def sheet_markdown(
    sample: Sequence[tuple[str, GoldenCase]],
    corpus: Corpus,
    texts: Mapping[tuple[str, str], Sequence[Section]] | None = None,
    *,
    seed: int,
) -> str:
    """Render the review sheet of a sample.

    Args:
        sample: The sampled ``(project, case)`` pairs.
        corpus: The corpus manifest.
        texts: Every section of each ``(project, version)``; with it, the sheet quotes the
            expected sections and lists the sections closest to the question and reference.
        seed: The sample's seed, shown in the title.

    Returns:
        The Markdown sheet.
    """
    lines = [
        f"# Golden-set review sheet (seed {seed}, {len(sample)} cases)",
        "",
        (
            "Check each case against the source at its pinned commit: every fact stated by the "
            "expected sections; the reference right for that version; no other section answering "
            "as well; the kind; an unanswerable case searched for in the whole docs tree; a "
            "version-change case against the neighbouring versions. Record the verdict in "
            "`packages/exactdocs/evals/golden/review.yaml`."
        ),
    ]
    for n, (project_id, case) in enumerate(sample, 1):
        project = corpus.project(project_id)
        if project is None:
            continue
        version = case.inputs.version
        commit = project.commit(version) or ""
        expected = case.expected_output
        lines += [
            "",
            f"## {n}. {case.name}",
            "",
            (
                f"- Kind: `{case.metadata.kind if case.metadata else '?'}`; version {version} "
                f"at `{commit[:12]}`"
            ),
            f"- Question: {case.inputs.query}",
            f"- Reference: {expected.reference if expected else ''}",
            "- Facts:",
            *(f"  - {f}" for f in (expected.facts if expected else [])),
            "- Sections:",
        ]
        sections = {s.key: s for s in (texts or {}).get((project_id, version), [])}
        for hit in expected.hits if expected else []:
            found = sections.get((hit.article, tuple(hit.heading_path)))
            link = source_link(project, commit, hit.article, found.anchor if found else "")
            lines.append(f"  - [{hit.article} [{' > '.join(hit.heading_path)}]]({link})")
        lines += ["- Verdict: ", "- Problems: ", "- Note: "]
        if texts is not None:
            lines += _evidence(case, project, texts)
    return "\n".join(lines) + "\n"


def _fence(text: str) -> str:
    """A code fence longer than any run of backticks in a text, so the text cannot close it.

    Returns:
        Three backticks or more.
    """
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    return "`" * max(3, longest + 1)


def _evidence(
    case: GoldenCase, project: Project, texts: Mapping[tuple[str, str], Sequence[Section]]
) -> list[str]:
    """Quote what a reviewer reads for a case: its sections and the closest others.

    Args:
        case: The case.
        project: Its project.
        texts: Every section of each ``(project, version)``.

    Returns:
        The lines.
    """
    version = case.inputs.version
    sections = list(texts.get((project.id, version), []))
    expected = case.expected_output
    wanted = {(h.article, tuple(h.heading_path)) for h in (expected.hits if expected else [])}
    lines = []
    for s in sections:
        if s.key in wanted:
            fence = _fence(s.text)
            lines += ["", f"#### Expected: {_shown(s)}", "", f"{fence}text", s.text.strip(), fence]
    idx = index(sections)
    query = terms(f"{case.inputs.query} {(expected.reference or '') if expected else ''}")
    close = [(c, i) for c, i in idx.ranked(query) if sections[i].key not in wanted][:5]
    lines += ["", "#### Closest other sections (question and reference words)", ""]
    lines += [f"- {_pct(c)} {_shown(sections[i])}" for c, i in close]
    names = [v.name for v in project.versions]
    at = names.index(version) if version in names else -1
    for other in (
        names[at - 1] if at > 0 else None,
        names[at + 1] if 0 <= at < len(names) - 1 else None,
    ):
        if other is None:
            continue
        there = list(texts.get((project.id, other), []))
        same = [s for s in there if s.key in wanted]
        oidx = index(there)
        top = oidx.ranked(query)[:3]
        lines += [
            "",
            f"#### Version {other}",
            "",
            *(f"- same section exists: {_shown(s)}" for s in same),
            *(f"- closest: {_pct(c)} {_shown(there[i])}" for c, i in top),
        ]
    return lines
