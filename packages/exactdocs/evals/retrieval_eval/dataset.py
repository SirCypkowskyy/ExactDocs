"""The dataset: questions pinned to a version, and the section that answers each."""

import hashlib
import json
from pathlib import Path
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic_evals import Dataset

DATASET_FILE: Final[Path] = Path(__file__).with_name("dataset.yaml")
"""The dataset in the repository, in Pydantic Evals' YAML format."""


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Question(_Model):
    """What a case asks: a query against exactly one version of the fixture library."""

    query: str
    """The query, an identifier or a natural-language question."""
    version: str
    """The version the question is pinned to; any result of another version is wrong."""
    tags: list[str] = Field(default_factory=list)
    """Only articles so tagged (the ranking table's tag-filtered queries)."""
    tags_match: Literal["any", "all"] = "any"
    """Whether a chunk needs any or all of ``tags``."""


class Hit(_Model):
    """One returned (or expected) section, and the version it came from."""

    version: str
    """The version that answered."""
    article: str
    """The article path, repo-relative."""
    heading_path: list[str]
    """The section's headings, from the H1."""
    commit_sha: str | None = None
    """The commit the result was read from, when the mode says."""


class Answer(_Model):
    """What a mode returned for a question (the expected output: the ideal answer)."""

    hits: list[Hit]
    """Best first. Expected: the one section that answers, or none when the version has none."""
    pinned_commit: str | None = None
    """The commit the asked version points at; a hit of another commit is of another version."""
    answered_by: str | None = None
    """The mode that really answered (a pipeline may fall back to a cheaper one)."""
    tokens: int = 0
    """Model tokens the answer cost (0 without a model)."""
    usd: float = 0.0
    """What those tokens cost, in USD."""
    search_ms: float | None = None
    """How long the search took, when the retriever measured it (else the whole task counts)."""


class CaseInfo(_Model):
    """Where a case comes from."""

    kind: Literal["identifier", "question"]
    """``identifier``: the fixture's expected-queries.yaml; ``question``: natural language."""


type RetrievalDataset = Dataset[Question, Answer, CaseInfo]
"""The dataset type: inputs, outputs (and expected outputs), metadata."""


def load_dataset(path: Path = DATASET_FILE) -> RetrievalDataset:
    """Read the dataset.

    Args:
        path: The YAML file; the one in the repository by default.

    Returns:
        The cases, without evaluators (the suite adds them).
    """
    return Dataset[Question, Answer, CaseInfo].from_file(path)


def fingerprint(dataset: RetrievalDataset) -> str:
    """Hash what the dataset states, so a baseline knows which dataset it measured.

    Only each question (its inputs, defaults left out) and the sections it expects (version,
    article, heading path) count: renaming, reordering or commenting cases keeps the fingerprint,
    and so does a field added to the models with a default. Adding, removing or changing a
    question or an expected section changes it (and resets the baseline, docs/evals.md).

    Args:
        dataset: The cases.

    Returns:
        ``sha256:`` and the first 16 hex digits of the hash.
    """
    cases = sorted(
        json.dumps(
            [
                case.inputs.model_dump(mode="json", exclude_defaults=True),
                [
                    [hit.version, hit.article, hit.heading_path]
                    for hit in (case.expected_output.hits if case.expected_output else [])
                ],
            ],
            sort_keys=True,
        )
        for case in dataset.cases
    )
    digest = hashlib.sha256("\n".join(cases).encode()).hexdigest()
    return f"sha256:{digest[:16]}"
