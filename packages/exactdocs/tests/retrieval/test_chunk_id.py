import hashlib
import json
from dataclasses import replace

import pytest

from exactdocs.retrieval.errors import DuplicateChunkError
from exactdocs.retrieval.models import (
    Chunk,
    ChunkSet,
    article_chunk_rows,
    chunk_id,
)

KNOWN = ("/acme/payments/main", "guide/install.md", ("Guide", "Install"), 0, "c0ffee")


def test_the_chunk_id_of_a_known_input_never_changes() -> None:
    """Golden: changing the hash orphans every chunk ID a client has stored."""
    assert chunk_id(*KNOWN) == "d5c5f2135393d4c1ad1aa3ce19db9128"


@pytest.mark.parametrize(
    "changed",
    [
        ("/acme/payments/v1.4.0", *KNOWN[1:]),
        (KNOWN[0], "guide/other.md", *KNOWN[2:]),
        (*KNOWN[:2], ("Guide", "Setup"), *KNOWN[3:]),
        (*KNOWN[:3], 1, KNOWN[4]),
        (*KNOWN[:4], "c0ffef"),
    ],
)
def test_every_input_changes_the_chunk_id(changed: tuple) -> None:
    assert chunk_id(*changed) != chunk_id(*KNOWN)


def test_part_0_keeps_the_id_a_whole_section_had_and_another_part_changes_it() -> None:
    assert chunk_id(*KNOWN, 0) == chunk_id(*KNOWN)
    assert chunk_id(*KNOWN, 1) != chunk_id(*KNOWN)
    assert chunk_id(*KNOWN, 1) != chunk_id(*KNOWN, 2)
    assert chunk_id(*KNOWN[:3], 1, KNOWN[4]) != chunk_id(*KNOWN[:3], 0, KNOWN[4], 1)


def test_part_0_keeps_the_digest_a_chunk_set_had_before_parts_existed() -> None:
    whole = ChunkSet(blob_sha="b", config_hash="h", chunks=(chunk("A", "a"),))
    split = ChunkSet(
        blob_sha="b", config_hash="h", chunks=(chunk("A", "a"), replace(chunk("A", "b"), part=1))
    )

    before = json.dumps([[["A"], 0, "a", "a"]], separators=(",", ":"))  # the shape before #141
    assert whole.digest == hashlib.sha256(before.encode()).hexdigest()
    assert split.digest != replace(split, chunks=(chunk("A", "a"), chunk("A", "b"))).digest


def test_two_parts_of_one_section_get_two_ids() -> None:
    parts = ChunkSet(
        blob_sha="b", config_hash="h", chunks=(chunk("A", "x"), replace(chunk("A", "x"), part=1))
    )

    first, second = article_chunk_rows("/o/r/main", "a.md", parts, ())
    assert first.chunk_id != second.chunk_id


def test_a_separator_inside_a_heading_cannot_collide_with_a_longer_heading_path() -> None:
    assert chunk_id("v", "a.md", ("A > B",), 0, "h") != chunk_id("v", "a.md", ("A", "B"), 0, "h")


def chunk(heading: str, text: str, occurrence: int = 0) -> Chunk:
    return Chunk(
        heading_path=(heading,),
        occurrence_index=occurrence,
        content=text,
        content_hash=text,
        anchor=heading.lower(),
    )


def test_rows_link_each_chunk_to_its_neighbours_and_carry_the_tags() -> None:
    chunks = ChunkSet(
        blob_sha="b",
        config_hash="h",
        chunks=(chunk("A", "a"), chunk("B", "b"), chunk("C", "c")),
    )

    first, middle, last = article_chunk_rows("/o/r/main", "a.md", chunks, ("api",))

    assert (first.position, first.total, first.prev_chunk_id) == (0, 3, None)
    assert (middle.prev_chunk_id, middle.next_chunk_id) == (first.chunk_id, last.chunk_id)
    assert (last.position, last.next_chunk_id) == (2, None)
    assert {first.tags, middle.tags, last.tags} == {("api",)}


def test_two_chunks_that_would_share_an_id_are_refused() -> None:
    twins = ChunkSet(blob_sha="b", config_hash="h", chunks=(chunk("A", "x"), chunk("A", "x")))

    with pytest.raises(DuplicateChunkError):
        article_chunk_rows("/o/r/main", "a.md", twins, ())
