"""Retrieval value objects. Pure Python: no frameworks, no I/O."""

from dataclasses import dataclass

from exactdocs.retrieval.errors import EmptySearchTextError


@dataclass(frozen=True, slots=True, kw_only=True)
class DocTarget:
    """The exact library version a search is pinned to. Version is a hard filter."""

    library: str
    version: str


@dataclass(frozen=True, slots=True, kw_only=True)
class SearchText:
    """What the agent is looking for: an identifier, an error code or a question."""

    value: str

    def __post_init__(self) -> None:
        if not self.value.strip():
            raise EmptySearchTextError


@dataclass(frozen=True, slots=True, kw_only=True)
class Excerpt:
    """Original documentation text, never a summary, with where it came from."""

    text: str
    source_url: str
    target: DocTarget
    commit_sha: str | None = None
