"""Data crossing the retrieval boundary. Immutable, validated."""

from collections.abc import Iterable
from typing import Self

from pydantic import BaseModel, ConfigDict, Field

from exactdocs.retrieval.models import Excerpt


class _Dto(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class SearchDocsQuery(_Dto):
    """Search within exactly one library version."""

    library: str = Field(min_length=1)
    version: str = Field(min_length=1)
    query: str = Field(min_length=1)
    limit: int = Field(default=5, ge=1, le=50)


class ExcerptOut(_Dto):
    """One verbatim excerpt with its provenance."""

    text: str
    source_url: str
    library: str
    version: str
    commit_sha: str | None

    @classmethod
    def from_model(cls, excerpt: Excerpt) -> Self:
        """Map a domain value object to its boundary representation."""
        return cls(
            text=excerpt.text,
            source_url=excerpt.source_url,
            library=excerpt.target.library,
            version=excerpt.target.version,
            commit_sha=excerpt.commit_sha,
        )


class SearchDocsResult(_Dto):
    """Excerpts ordered from most to least relevant."""

    excerpts: list[ExcerptOut]

    @classmethod
    def from_models(cls, excerpts: Iterable[Excerpt]) -> Self:
        """Map domain value objects, keeping their order."""
        return cls(excerpts=[ExcerptOut.from_model(e) for e in excerpts])
