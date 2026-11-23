"""Score a documentation tool's text results on the golden set, and calibrate the scorer (#491).

``text_match`` maps each text result to the corpus's sections; this module turns those matches
into the retrieval benchmark's own rows and metrics (``retrieval_bench.Row``, ``metrics_of``), so a
tool that returns text is measured exactly as ExactDocs is, and adds what only text tells: the
share of version-neutral and unmatched results, the tokens of context returned per question, and
the share of the case's facts the returned text holds. The calibration scores ExactDocs' own BM25
results both ways, by chunk ID and by text, and records how often they agree. See
docs/evals.md#scoring-text-results.
"""

import html
import math
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from statistics import fmean
from typing import Any, Final, Self

from markdown_it import MarkdownIt
from pydantic import BaseModel, ConfigDict

from retrieval_eval.dataset import Answer, Hit
from retrieval_eval.evaluators import SectionMatch, wrong_version_hits
from retrieval_eval.golden import GoldenCase
from retrieval_eval.ingestion import tokens
from retrieval_eval.retrieval_bench import NDCG_AT, BenchMetrics, Row, metrics_of, row_of
from retrieval_eval.suite import percentile
from retrieval_eval.text_match import (
    MATCH_THRESHOLD,
    SHINGLE_WORDS,
    Section,
    SectionIndex,
    TextMatch,
    Verdict,
    words,
)

SCHEMA_VERSION: Final[int] = 1
"""The JSON report's layout; bumped when a field is renamed or removed."""
FACT_SHARE: Final[float] = 0.75
"""A fact is in the returned text when at least this share of its content words is."""
MIN_AGREEMENT: Final[float] = 0.98
"""The calibration's criterion: the share of hit and miss decisions the text scorer must take as
chunk-ID scoring does, on ExactDocs' own results at ``GATED_CHUNKING``."""
GATED_CHUNKING: Final[str] = "default"
"""The chunking configuration the criterion applies to: what ExactDocs ships."""
SWEEP: Final[tuple[float, ...]] = (0.5, 0.6, 0.7, 0.8, 0.9, 1.0)
"""The thresholds the calibration tries besides ``MATCH_THRESHOLD``."""
_DIGITS: Final[int] = 4
"""Shares are rounded to this many decimals."""
_EPSILON: Final[float] = 1e-9
"""Float noise tolerated when comparing shares."""
_STOPWORDS: Final[frozenset[str]] = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "been", "but", "by", "can", "do", "does", "for",
    "from", "has", "have", "how", "i", "if", "in", "into", "is", "it", "its", "of", "on", "or",
    "so", "that", "the", "their", "them", "then", "there", "these", "they", "this", "to", "was",
    "were", "what", "when", "where", "which", "while", "who", "will", "with", "you", "your",
})  # fmt: skip
"""Words a fact is not judged by."""
_KEEP_ENDING: Final[int] = 3
"""A word this short keeps its ``s`` (``has``, ``was``, ``its``)."""
_MARKDOWN: Final[MarkdownIt] = MarkdownIt("commonmark").enable("table")
"""Renders Markdown as a tool that returns plain text would show it."""
_HTML_TAG: Final[re.Pattern[str]] = re.compile(r"<[^>]+>")
"""Any tag of the rendered HTML."""


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", use_attribute_docstrings=True)


def plain_text(markdown: str) -> str:
    """Render Markdown and keep only its text: a result as a tool that renders it returns it.

    Args:
        markdown: The Markdown.

    Returns:
        The rendered text, tags dropped, entities decoded, every run of whitespace one space.
    """
    rendered = _HTML_TAG.sub(" ", _MARKDOWN.render(markdown))
    return " ".join(html.unescape(rendered).split())


def _stem(word: str) -> str:
    """Strip a plural ``s`` (``queries`` -> ``query``), so a fact and the docs agree on number.

    Args:
        word: A normalized word.

    Returns:
        The word without its plural ending.
    """
    if len(word) > _KEEP_ENDING + 1 and word.endswith("ies"):
        return word.removesuffix("ies") + "y"
    if len(word) > _KEEP_ENDING and word.endswith("s") and not word.endswith("ss"):
        return word.removesuffix("s")
    return word


def fact_terms(text: str) -> frozenset[str]:
    """The content words a fact is judged by: normalized words, stopwords left out, plurals cut.

    Args:
        text: A fact or a returned text.

    Returns:
        The terms.
    """
    return frozenset(_stem(w) for w in words(text) if w not in _STOPWORDS)


def facts_found(facts: Sequence[str], text: str) -> int:
    """Count the facts a text holds: ``FACT_SHARE`` of each fact's terms must be in it.

    Args:
        facts: The case's facts.
        text: Everything a tool returned for the case.

    Returns:
        How many of the facts it holds.
    """
    held = fact_terms(text)
    found = 0
    for fact in facts:
        terms = fact_terms(fact)
        found += bool(terms) and len(terms & held) / len(terms) >= FACT_SHARE - _EPSILON
    return found


class TextAnswer(_Model):
    """What a tool returned for one question: the text of each result, best first."""

    texts: list[str]
    """One text per result, in the tool's order (a harness splits a response into its results)."""
    search_ms: float | None = None
    """How long the tool took, when the harness measured it."""
    tokens: int = 0
    """Model tokens the tool spent, when known (0 otherwise)."""
    usd: float = 0.0
    """What those cost, in USD."""


class TextRow(_Model):
    """One case as a tool answered it in text, scored from the text."""

    case: str
    """The case's name."""
    row: Row
    """The retrieval benchmark's row (ranks, nDCG, wrong version, empty), from the text."""
    results: int
    """How many results came back."""
    neutral: int
    """Results whose text matches the version asked and another pinned version."""
    unmatched: int
    """Results whose text matches no section of any pinned version."""
    context_tokens: int
    """Estimated tokens of every result's text (``ingestion.tokens``: characters / 4)."""
    tokens_to_hit: int | None
    """Estimated tokens of the results up to and including the first expected section's; None
    when it is not in the top 10."""
    facts: int
    """The facts the case lists."""
    facts_found: int
    """Of those, how many the returned text holds (``facts_found``)."""


def first_ranks(expected: Sequence[Hit], matches: Sequence[TextMatch]) -> list[int | None]:
    """The rank, in the top 10, of the first result that answers each expected section.

    Args:
        expected: The sections that answer the case.
        matches: Each result's matches, best first.

    Returns:
        One rank (or None) per expected section, in their order.
    """
    return [
        next(
            (
                rank
                for rank, match in enumerate(matches[:NDCG_AT], start=1)
                if match.answers(e.version, e.article, e.heading_path)
            ),
            None,
        )
        for e in expected
    ]


def _section_ranks(expected: Sequence[Hit], matches: Sequence[TextMatch]) -> tuple[int, ...]:
    """The ranks of the results that answer an expected section no earlier result answered.

    The text form of ``retrieval_bench.section_ranks``.

    Args:
        expected: The sections that answer the case.
        matches: Each result's matches, best first.

    Returns:
        One rank per expected section found in the top 10, ascending.
    """
    left = list(expected)
    ranks = []
    for rank, match in enumerate(matches[:NDCG_AT], start=1):
        found = next((e for e in left if match.answers(e.version, e.article, e.heading_path)), None)
        if found is not None:
            left.remove(found)
            ranks.append(rank)
    return tuple(ranks)


def _ndcg(expected: int, ranks: Sequence[int]) -> float:
    """nDCG@10 with binary relevance, as ``retrieval_bench.ndcg_at`` defines it.

    Args:
        expected: How many sections the case expects.
        ranks: The ranks of the relevant results (``_section_ranks``).

    Returns:
        DCG / ideal DCG, in [0, 1]; 0 when nothing is expected.
    """
    dcg = sum(1 / math.log2(rank + 1) for rank in ranks)
    ideal = sum(1 / math.log2(rank + 1) for rank in range(1, min(expected, NDCG_AT) + 1))
    return dcg / ideal if ideal else 0.0


def text_row(case: GoldenCase, answer: TextAnswer, index: SectionIndex) -> TextRow:
    """Score one case from the text a tool returned.

    Args:
        case: The golden case.
        answer: The tool's results.
        index: The sections of every pinned version of the case's project.

    Returns:
        The row.
    """
    expected = case.expected_output.hits if case.expected_output else []
    facts = [f for f in (case.expected_output.facts if case.expected_output else []) if f.strip()]
    matches = index.match_all(answer.texts)
    verdicts = [m.verdict(case.inputs.version) for m in matches]
    rank = first_ranks(expected[:1], matches)[0] if expected else None
    ranks = _section_ranks(expected, matches)
    sizes = [tokens(text) for text in answer.texts]
    return TextRow(
        case=case.name or "",
        row=Row(
            case=case.name or "",
            kind=case.metadata.kind if case.metadata else "",
            project=case.inputs.project or "",
            answerable=bool(expected),
            rank=rank,
            ndcg=_ndcg(len(expected), ranks),
            sections=len(expected),
            section_ranks=ranks,
            wrong_version=Verdict.WRONG in verdicts,
            empty=not answer.texts,
            search_ms=answer.search_ms or 0.0,
            tokens=answer.tokens,
            usd=answer.usd,
        ),
        results=len(answer.texts),
        neutral=verdicts.count(Verdict.NEUTRAL),
        unmatched=verdicts.count(Verdict.UNMATCHED),
        context_tokens=sum(sizes),
        tokens_to_hit=sum(sizes[:rank]) if rank else None,
        facts=len(facts),
        facts_found=facts_found(facts, "\n\n".join(answer.texts)),
    )


class TextMetrics(_Model):
    """A tool's numbers over a set of cases, scored from its text."""

    metrics: BenchMetrics
    """The retrieval benchmark's metrics (recall@k, section recall, MRR, nDCG@10, wrong-version
    rate, no answer, latency, model tokens and USD), each result's sections read from its text."""
    results_per_question: float
    """Over every case: results returned."""
    version_neutral_share: float | None
    """Over every result returned: share whose text is in the version asked and in another."""
    unmatched_share: float | None
    """Over every result returned: share whose text matches no section of any pinned version."""
    context_tokens_per_question: float
    """Over every case: estimated tokens of all the text returned."""
    context_tokens_p95: float
    """Nearest-rank p95 of the same."""
    tokens_to_first_hit: float | None
    """Over answerable cases whose first expected section is in the top 10: estimated tokens of
    the results up to and including it."""
    facts_found_rate: float | None
    """Over answerable cases: the mean share of the case's facts the returned text holds."""


def _rate(part: float, whole: float) -> float | None:
    return round(part / whole, _DIGITS) if whole else None


def text_metrics(rows: Sequence[TextRow]) -> TextMetrics:
    """Aggregate text rows.

    Args:
        rows: The cases' rows.

    Returns:
        The metrics.
    """
    results = sum(r.results for r in rows)
    to_hit = [r.tokens_to_hit for r in rows if r.tokens_to_hit is not None]
    with_facts = [r for r in rows if r.row.answerable and r.facts]
    context = [float(r.context_tokens) for r in rows]
    return TextMetrics(
        metrics=metrics_of([r.row for r in rows]),
        results_per_question=round(fmean(r.results for r in rows), 2) if rows else 0.0,
        version_neutral_share=_rate(sum(r.neutral for r in rows), results),
        unmatched_share=_rate(sum(r.unmatched for r in rows), results),
        context_tokens_per_question=round(fmean(context), 1) if rows else 0.0,
        context_tokens_p95=percentile(context, 0.95),
        tokens_to_first_hit=round(fmean(to_hit), 1) if to_hit else None,
        facts_found_rate=(
            round(fmean(r.facts_found / r.facts for r in with_facts), _DIGITS)
            if with_facts
            else None
        ),
    )


class TextResult(_Model):
    """One tool's text results on the golden set, scored from the text."""

    tool: str
    """What answered: a tool, a mode, a configuration."""
    metrics: TextMetrics
    """Over every case."""
    by_kind: dict[str, TextMetrics]
    """Per question kind."""
    by_project: dict[str, TextMetrics]
    """Per project."""
    wrong_version_cases: list[str]
    """Cases with a result whose text is only in another version."""

    @classmethod
    def of(cls, tool: str, rows: Sequence[TextRow]) -> Self:
        """Aggregate a tool's rows, overall, by question kind and by project.

        Args:
            tool: The tool's name.
            rows: Every case's row.

        Returns:
            The result.
        """

        def by(key: Callable[[TextRow], str]) -> dict[str, TextMetrics]:
            """Group the rows.

            Args:
                key: The group of a row.

            Returns:
                The metrics of each group, by name.
            """
            groups: dict[str, list[TextRow]] = {}
            for row in rows:
                groups.setdefault(key(row), []).append(row)
            return {name: text_metrics(group) for name, group in sorted(groups.items())}

        return cls(
            tool=tool,
            metrics=text_metrics(rows),
            by_kind=by(lambda r: r.row.kind),
            by_project=by(lambda r: r.row.project),
            wrong_version_cases=[r.case for r in rows if r.row.wrong_version],
        )


# ---------------------------------------------------------------- calibration


class Agreement(_Model):
    """How often the text scorer takes a hit or miss decision as chunk-ID scoring does."""

    decisions: int
    """One per expected section of every answerable case: where it is in the top 10, if at all."""
    agreed: int
    """Decisions where both found the section at the same rank, or neither found it."""
    rate: float
    """``agreed`` / ``decisions``."""
    hit_miss_rate: float
    """The share where both found it in the top 10, or neither did, at whatever rank."""


def agreement(pairs: Sequence[tuple[int | None, int | None]]) -> Agreement:
    """Count agreeing decisions.

    Args:
        pairs: ``(chunk-ID rank, text rank)`` per decision; None for not in the top 10.

    Returns:
        The agreement; a rate of 1 when there is no decision.
    """
    agreed = sum(a == b for a, b in pairs)
    hit_miss = sum((a is None) == (b is None) for a, b in pairs)
    total = len(pairs)
    return Agreement(
        decisions=total,
        agreed=agreed,
        rate=round(agreed / total, _DIGITS) if total else 1.0,
        hit_miss_rate=round(hit_miss / total, _DIGITS) if total else 1.0,
    )


class Disagreement(_Model):
    """A decision the two scorings take differently."""

    case: str
    """The case's name."""
    section: str
    """The expected section: ``<version> <article> [heading > path]``."""
    chunk_id_rank: int | None
    """Where chunk-ID scoring found it in the top 10."""
    text_rank: int | None
    """Where the text scorer found it."""
    why: str
    """What the result at the earlier of the two ranks is."""


class SweepPoint(_Model):
    """The agreement at one threshold."""

    threshold: float
    """The share of shingles that must agree."""
    rate: float
    """Agreement on the results as ExactDocs returned them."""
    rendered_rate: float
    """Agreement on the same results rendered as plain text (``plain_text``)."""


class Calibration(_Model):
    """ExactDocs' own BM25 results at one chunking configuration, scored by chunk ID and by text."""

    chunking: str
    """The chunking configuration the corpus was imported with."""
    threshold: float
    """The text scorer's threshold (``MATCH_THRESHOLD``)."""
    agreement: Agreement
    """With chunk-ID scoring as the retrieval benchmark scores it (the nested match rule)."""
    held_agreement: Agreement
    """With chunk-ID scoring that also counts a chunk holding the section's heading under
    another heading path (a section merged into a sibling's chunk), which the nested rule does
    not."""
    rendered_agreement: Agreement
    """With chunk-ID scoring, the results rendered as plain text first."""
    wrong_version_agreement: float
    """Over every case: share where both say a result is of another version, or neither does."""
    sweep: list[SweepPoint]
    """The agreement at each threshold of ``SWEEP``."""
    disagreements: list[Disagreement]
    """Every decision of ``agreement`` the two take differently."""
    chunk_id: BenchMetrics
    """The benchmark's metrics, scored by chunk ID."""
    text: TextMetrics
    """The same results, scored from their text."""
    facts_in_expected_sections: float | None
    """Over answerable cases: the share of facts held by the expected sections' own text (with
    their subsections), the most a tool can reach on the facts signal."""
    facts_in_other_results: float | None
    """Over answerable cases: the share of facts held by the results of another question of the
    same version (the next such case), what text that does not answer reaches."""

    @property
    def passed(self) -> bool:
        """Whether the agreement meets ``MIN_AGREEMENT``."""
        return self.agreement.rate >= MIN_AGREEMENT - _EPSILON


def _first(expected: Hit, hits: Sequence[Hit], matches: SectionMatch) -> int | None:
    """The rank of the first hit in the top 10 that answers a section.

    Args:
        expected: The section.
        hits: What ExactDocs returned, best first.
        matches: When a hit answers it.

    Returns:
        The rank, or None.
    """
    return next(
        (rank for rank, hit in enumerate(hits[:NDCG_AT], start=1) if matches(expected, hit)), None
    )


def _shown(hit: Hit) -> str:
    return f"{hit.version} {hit.article} [{' > '.join(hit.heading_path)}]"


def _why(ranks: Sequence[int | None], hits: Sequence[Hit]) -> str:
    """Say why two decisions differ, from the result at the earlier rank.

    Args:
        ranks: The section's chunk-ID rank, text rank and held-heading rank.
        hits: What ExactDocs returned, best first.

    Returns:
        A short reason.
    """
    by_id, by_text, by_held = ranks
    if by_text is not None and (by_id is None or by_text < by_id):
        hit = hits[by_text - 1]
        if by_held == by_text:
            return (
                f"the chunk at rank {by_text} holds the section under another heading path "
                f"({_shown(hit)}), which the nested rule does not count"
            )
        return (
            f"the chunk at rank {by_text} ({_shown(hit)}) holds the section's text, but is "
            "another article or version"
        )
    if by_id is not None:
        return (
            f"the chunk at rank {by_id} ({_shown(hits[by_id - 1])}) holds less than the "
            "threshold of the section's text"
        )
    return "neither found it"  # pragma: no cover -- only disagreements are explained


type _Pair = tuple[int | None, int | None]
"""A decision taken twice: ``(chunk-ID rank, text rank)``, None for not in the top 10."""


@dataclass(slots=True, kw_only=True)  # conventions: allow-mutable-dataclass -- fills case by case
class _Tally:
    """What the calibration counts, case by case."""

    pairs: list[_Pair] = field(default_factory=list)
    """Chunk-ID (nested rule) against text."""
    held_pairs: list[_Pair] = field(default_factory=list)
    """Chunk-ID counting held headings against text."""
    rendered_pairs: list[_Pair] = field(default_factory=list)
    """Chunk-ID against the text rendered as plain text."""
    sweep: dict[float, tuple[list[bool], list[bool]]] = field(
        default_factory=lambda: {t: ([], []) for t in SWEEP}
    )
    """Per threshold: each decision agreed, on the text as returned and as rendered."""
    disagreements: list[Disagreement] = field(default_factory=list)
    """The decisions of ``pairs`` that differ."""
    wrong_agreed: int = 0
    """Cases both scorings judge alike on another version."""
    id_rows: list[Row] = field(default_factory=list)
    """Chunk-ID rows."""
    text_rows: list[TextRow] = field(default_factory=list)
    """Text rows."""


def _tally(
    tally: _Tally,
    case: GoldenCase,
    found: tuple[Answer, Sequence[str]],
    index: SectionIndex,
    rules: tuple[SectionMatch, SectionMatch],
) -> None:
    """Score one case both ways and count its decisions.

    Args:
        tally: The counts so far.
        case: The case.
        found: What ExactDocs returned for it, and the text of each hit.
        index: The case's project's sections.
        rules: The chunk-ID rule and the held-heading rule.
    """
    answer, texts = found
    matches, held = rules
    expected = case.expected_output.hits if case.expected_output else []
    rendered = [plain_text(t) for t in texts]
    by_ids = [_first(e, answer.hits, matches) for e in expected]
    by_held = [_first(e, answer.hits, held) for e in expected]
    by_text = first_ranks(expected, index.match_all(texts))
    tally.pairs.extend(zip(by_ids, by_text, strict=True))
    tally.held_pairs.extend(zip(by_held, by_text, strict=True))
    tally.rendered_pairs.extend(
        zip(by_ids, first_ranks(expected, index.match_all(rendered)), strict=True)
    )
    tally.disagreements.extend(
        Disagreement(
            case=case.name or "",
            section=_shown(e),
            chunk_id_rank=by_id,
            text_rank=by_txt,
            why=_why((by_id, by_txt, by_hld), answer.hits),
        )
        for e, by_id, by_txt, by_hld in zip(expected, by_ids, by_text, by_held, strict=True)
        if by_id != by_txt
    )
    for threshold, (plain, as_rendered) in tally.sweep.items():
        at = index.with_threshold(threshold)
        for variant, out in ((texts, plain), (rendered, as_rendered)):
            ranks = first_ranks(expected, at.match_all(variant))
            out.extend(a == b for a, b in zip(by_ids, ranks, strict=True))
    row = text_row(case, TextAnswer(texts=list(texts), search_ms=answer.search_ms), index)
    tally.wrong_agreed += bool(wrong_version_hits(case.inputs, answer)) == row.row.wrong_version
    tally.id_rows.append(row_of(case, answer, matches))
    tally.text_rows.append(row)


def _mean_or_one(values: Sequence[bool]) -> float:
    return round(fmean(values), _DIGITS) if values else 1.0


def calibrate(
    chunking: str,
    cases: Sequence[GoldenCase],
    results: Mapping[str, tuple[Answer, Sequence[str]]],
    indexes: Mapping[str, SectionIndex],
    *,
    matches: SectionMatch,
    held: SectionMatch,
) -> Calibration:
    """Score ExactDocs' own results by chunk ID and by text, and compare the decisions.

    Args:
        chunking: The chunking configuration the results come from.
        cases: The golden cases.
        results: Each case's answer (by its name), with the text of each hit (the chunk's
            content, as ``read_chunk`` returns it).
        indexes: Each project's sections.
        matches: The benchmark's chunk-ID rule (``golden_run.nested_match``).
        held: The rule that also counts a chunk holding the section's heading.

    Returns:
        The calibration.
    """
    tally = _Tally()
    for case in cases:
        found = results[case.name or ""]
        _tally(tally, case, found, indexes[case.inputs.project or ""], (matches, held))
    ceiling, control = _facts_bounds(cases, results, indexes)
    return Calibration(
        chunking=chunking,
        threshold=next((i.threshold for i in indexes.values()), MATCH_THRESHOLD),
        agreement=agreement(tally.pairs),
        held_agreement=agreement(tally.held_pairs),
        rendered_agreement=agreement(tally.rendered_pairs),
        wrong_version_agreement=round(tally.wrong_agreed / len(cases), _DIGITS) if cases else 1.0,
        sweep=[
            SweepPoint(
                threshold=t, rate=_mean_or_one(plain), rendered_rate=_mean_or_one(as_rendered)
            )
            for t, (plain, as_rendered) in tally.sweep.items()
        ],
        disagreements=tally.disagreements,
        chunk_id=metrics_of(tally.id_rows),
        text=text_metrics(tally.text_rows),
        facts_in_expected_sections=ceiling,
        facts_in_other_results=control,
    )


def _facts_bounds(
    cases: Sequence[GoldenCase],
    results: Mapping[str, tuple[Answer, Sequence[str]]],
    indexes: Mapping[str, SectionIndex],
) -> tuple[float | None, float | None]:
    """What the facts signal reaches on the answer itself, and on text that does not answer.

    Args:
        cases: The golden cases.
        results: Each case's answer and texts.
        indexes: Each project's sections.

    Returns:
        The mean share of facts held by the expected sections' text, and by the results of the
        next answerable case of the same project and version; None without such cases.
    """
    answerable = [
        c for c in cases if c.expected_output and c.expected_output.hits and c.expected_output.facts
    ]
    ceiling: list[float] = []
    control: list[float] = []
    for i, case in enumerate(answerable):
        facts = case.expected_output.facts if case.expected_output else []
        index = indexes[case.inputs.project or ""]
        expected = case.expected_output.hits if case.expected_output else []
        own = "\n\n".join(
            index.text_of(
                Section(version=e.version, article=e.article, heading_path=tuple(e.heading_path))
            )
            for e in expected
        )
        ceiling.append(facts_found(facts, own) / len(facts))
        same = (case.inputs.project, case.inputs.version)
        other = next(
            (
                o
                for o in [*answerable[i + 1 :], *answerable[:i]]
                if (o.inputs.project, o.inputs.version) == same
            ),
            None,
        )
        if other is not None:
            texts = results[other.name or ""][1]
            control.append(facts_found(facts, "\n\n".join(texts)) / len(facts))
    return (
        round(fmean(ceiling), _DIGITS) if ceiling else None,
        round(fmean(control), _DIGITS) if control else None,
    )


# ---------------------------------------------------------------- the report


class TextScorerReport(_Model):
    """The calibration's JSON report (``text-scorer.json``), documented in docs/evals.md."""

    schema_version: int = SCHEMA_VERSION
    golden: str
    """The golden set's fingerprint."""
    cases: int
    projects: list[str]
    corpus: list[dict[str, str]]
    """Every pinned version: ``project``, ``version``, ``commit``."""
    environment: dict[str, str]
    """The ExactDocs commit, Python, platform, CPU and library versions (as the retrieval
    benchmark records them)."""
    scorer: dict[str, Any]
    """The scorer's fixed settings: ``shingle_words``, ``threshold``, ``fact_share``,
    ``min_agreement``, ``gated_chunking``."""
    calibrations: list[Calibration]
    """One per chunking configuration run."""


def scorer_settings() -> dict[str, Any]:
    """The text scorer's fixed settings, as the report records them.

    Returns:
        ``shingle_words``, ``threshold``, ``fact_share``, ``min_agreement``, ``gated_chunking``.
    """
    return {
        "shingle_words": SHINGLE_WORDS,
        "threshold": MATCH_THRESHOLD,
        "fact_share": FACT_SHARE,
        "min_agreement": MIN_AGREEMENT,
        "gated_chunking": GATED_CHUNKING,
    }


def problems(report: TextScorerReport) -> list[str]:
    """Say what fails the calibration: an agreement under ``MIN_AGREEMENT`` at ``GATED_CHUNKING``.

    Args:
        report: The run.

    Returns:
        One problem per failing calibration.
    """
    return [
        (
            f"{c.chunking}: the text scorer agrees with chunk-ID scoring on "
            f"{_pct(c.agreement.rate)} of {c.agreement.decisions} decisions, under "
            f"{_pct(MIN_AGREEMENT)}"
        )
        for c in report.calibrations
        if c.chunking == GATED_CHUNKING and not c.passed
    ]


def _pct(value: float | None) -> str:
    return "-" if value is None else f"{value * 100:.1f}%"


def _num(value: float | None, digits: int = 0) -> str:
    return "-" if value is None else f"{value:.{digits}f}"


def results_table(results: Sequence[TextResult]) -> list[str]:
    """A table comparing tools scored from their text, one line per tool.

    Args:
        results: The tools' results.

    Returns:
        The lines.
    """
    lines = [
        (
            "| tool | recall@1 | recall@5 | recall@10 | section recall@5 | MRR | nDCG@10 "
            "| wrong version | no answer | version-neutral | unmatched | results / q "
            "| context tokens / q | tokens to first hit | facts found |"
        ),
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        t, m = r.metrics, r.metrics.metrics
        lines.append(
            f"| {r.tool} | {_pct(m.recall_at_1)} | {_pct(m.recall_at_5)} "
            f"| {_pct(m.recall_at_10)} | {_pct(m.section_recall_at_5)} | {m.mrr:.3f} "
            f"| {m.ndcg_at_10:.3f} | {_pct(m.wrong_version_rate)} | {_pct(m.no_answer_rate)} "
            f"| {_pct(t.version_neutral_share)} | {_pct(t.unmatched_share)} "
            f"| {t.results_per_question:.1f} | {t.context_tokens_per_question:.0f} "
            f"| {_num(t.tokens_to_first_hit)} | {_pct(t.facts_found_rate)} |"
        )
    return lines


def markdown(report: TextScorerReport) -> str:
    """Render the calibration as a Markdown summary.

    Args:
        report: The run.

    Returns:
        The agreement per chunking, the threshold sweep, both scorings side by side, what only
        the text scorer reports, and every disagreement.
    """
    s = report.scorer
    lines = [
        "# Text scorer calibration",
        "",
        (
            f"ExactDocs' BM25 results for the golden set's {report.cases} cases "
            f"(`{report.golden}`) on {', '.join(report.projects)}, scored by chunk ID and from "
            f"their text alone: {s['shingle_words']}-word shingles, threshold "
            f"{s['threshold']:g}, facts at {s['fact_share']:g} of their words. A decision is "
            "where an expected section is in the top 10 (its rank), or that it is not; the "
            f"criterion is {_pct(s['min_agreement'])} agreement at `{s['gated_chunking']}`. "
            f"ExactDocs `{report.environment.get('exactdocs_commit', '?')}`. "
            "Definitions: docs/evals.md#scoring-text-results."
        ),
        "",
        "## Agreement with chunk-ID scoring",
        "",
        (
            "| chunking | decisions | same rank | hit / miss | rendered as plain text "
            "| counting held headings | wrong version (cases) | criterion |"
        ),
        "|---|---|---|---|---|---|---|---|",
    ]
    for c in report.calibrations:
        verdict = ("met" if c.passed else "NOT MET") if c.chunking == s["gated_chunking"] else "-"
        lines.append(
            f"| `{c.chunking}` | {c.agreement.decisions} | {_pct(c.agreement.rate)} "
            f"| {_pct(c.agreement.hit_miss_rate)} | {_pct(c.rendered_agreement.rate)} "
            f"| {_pct(c.held_agreement.rate)} | {_pct(c.wrong_version_agreement)} | {verdict} |"
        )
    lines.extend(_sweep(report.calibrations))
    lines.extend(
        [
            "",
            "## Both scorings side by side",
            "",
            (
                "| chunking | scored by | recall@1 | recall@5 | recall@10 | section recall@5 "
                "| MRR | nDCG@10 | wrong version | no answer |"
            ),
            "|---|---|---|---|---|---|---|---|---|---|",
        ]
    )
    for c in report.calibrations:
        for name, m in (("chunk ID", c.chunk_id), ("text", c.text.metrics)):
            lines.append(
                f"| `{c.chunking}` | {name} | {_pct(m.recall_at_1)} | {_pct(m.recall_at_5)} "
                f"| {_pct(m.recall_at_10)} | {_pct(m.section_recall_at_5)} | {m.mrr:.3f} "
                f"| {m.ndcg_at_10:.3f} | {_pct(m.wrong_version_rate)} "
                f"| {_pct(m.no_answer_rate)} |"
            )
    lines.extend(
        [
            "",
            "## What only the text tells",
            "",
            (
                "| chunking | results / q | version-neutral | unmatched | context tokens / q "
                "| p95 | tokens to first hit | facts found | facts in the expected sections "
                "| facts in another question's results |"
            ),
            "|---|---|---|---|---|---|---|---|---|---|",
        ]
    )
    for c in report.calibrations:
        t = c.text
        lines.append(
            f"| `{c.chunking}` | {t.results_per_question:.1f} | {_pct(t.version_neutral_share)} "
            f"| {_pct(t.unmatched_share)} | {t.context_tokens_per_question:.0f} "
            f"| {t.context_tokens_p95:.0f} | {_num(t.tokens_to_first_hit)} "
            f"| {_pct(t.facts_found_rate)} | {_pct(c.facts_in_expected_sections)} "
            f"| {_pct(c.facts_in_other_results)} |"
        )
    lines.extend(_disagreements(report.calibrations))
    return "\n".join(lines) + "\n"


def _sweep(calibrations: Sequence[Calibration]) -> list[str]:
    """The threshold sweep: agreement per threshold and chunking, as returned and rendered.

    Args:
        calibrations: Every calibration.

    Returns:
        The lines.
    """
    if not calibrations:
        return []
    lines = [
        "",
        "## Threshold sweep (same rank; as returned / rendered as plain text)",
        "",
        "| threshold | " + " | ".join(f"`{c.chunking}`" for c in calibrations) + " |",
        "|---|" + "---|" * len(calibrations),
    ]
    for i, point in enumerate(calibrations[0].sweep):
        cells = " | ".join(
            f"{_pct(c.sweep[i].rate)} / {_pct(c.sweep[i].rendered_rate)}" for c in calibrations
        )
        chosen = " (chosen)" if abs(point.threshold - calibrations[0].threshold) < _EPSILON else ""
        lines.append(f"| {point.threshold:g}{chosen} | {cells} |")
    return lines


def _disagreements(calibrations: Sequence[Calibration]) -> list[str]:
    """Every decision the two scorings take differently, per chunking.

    Args:
        calibrations: Every calibration.

    Returns:
        The lines.
    """
    lines = ["", "## Disagreements", ""]
    for c in calibrations:
        if not c.disagreements:
            lines.append(f"- `{c.chunking}`: none")
            continue
        lines.append(f"- `{c.chunking}`: {len(c.disagreements)}")
        lines.extend(
            f"  - {d.case}: {d.section}: chunk ID {_num(d.chunk_id_rank)}, text "
            f"{_num(d.text_rank)}; {d.why}"
            for d in c.disagreements
        )
    return lines
