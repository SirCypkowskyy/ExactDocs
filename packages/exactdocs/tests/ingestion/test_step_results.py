"""Jobs' step results are stored (pickled by DBOS) and read back by a later release.

The import's and the re-processing jobs' (``reprocess``, ``rechunk``, ``retag``). A release
that changes the shape of any of them must bump ``STEPS_VERSION``: a job started by the release
before then starts over instead of resuming from results of another shape. This test fails
until both are done: bump the version and record the new fingerprint here.
"""

import dataclasses
import enum
import hashlib
import json
import typing

from exactdocs.ingestion.constants import STEPS_VERSION
from exactdocs.ingestion.models import ChunkingConfig, GitRename, ImportedRef, ReadmeSummary
from exactdocs.ingestion.use_cases import (
    _Batch,
    _Context7Read,
    _ImageBudget,
    _Missing,
    _VersionOutcome,
)

# Every type a step of a job returns (the rest is reached through their fields): the import's,
# then the re-processing jobs' (``reprocess``, ``rechunk``, ``retag``).
ROOTS = (
    ChunkingConfig,
    _Batch,
    _ImageBudget,
    _Missing,
    _Context7Read,
    ReadmeSummary,
    GitRename,
    ImportedRef,
    _VersionOutcome,
)

FINGERPRINTS = {
    "jobs-1": "9bf7464faeb9cb3f19bb905319608080e03d640c21227eaf3ff85aae740f1463",
    "jobs-2": "332748524fa2b742b1046783782c8e545c92949d0835ae0c6c4ebaf74159114a",
    "jobs-3": "a2759f3dbbb75d22e28409afd9e8902af066e7bcb64ee225c14a89558e448834",
    "jobs-4": "e19a8daa379611288797942dcd93db43fdf4fd15d59d74ee2445fc065d6aef48",
    "jobs-5": "7dc27c94e6f797e0a5c0cf1d186ad1d483bd4207894040d0ae06f6859ab70485",
    "jobs-6": "02834bb3cb61684b0c569b4c10679b893c7398991696bee42c14981b4fdebdfc",
}


def _name(tp: object) -> str:
    return getattr(tp, "__qualname__", None) or repr(tp)


def shape(roots: tuple[type, ...]) -> dict[str, object]:
    """Each reachable dataclass with its fields (name and type), each enum by its name."""
    found: dict[str, object] = {}
    todo: list[object] = list(roots)
    while todo:
        tp = todo.pop()
        todo.extend(typing.get_args(tp))
        origin = typing.get_origin(tp)
        if origin is not None:
            todo.append(origin)
            continue
        if not isinstance(tp, type) or f"{tp.__module__}.{tp.__qualname__}" in found:
            continue
        key = f"{tp.__module__}.{tp.__qualname__}"
        if dataclasses.is_dataclass(tp):
            hints = typing.get_type_hints(tp)  # evaluated now: no forward references left
            fields = [(f.name, hints[f.name]) for f in dataclasses.fields(tp)]
            found[key] = [(name, repr(hint)) for name, hint in fields]
            todo.extend(hint for _, hint in fields)
        elif issubclass(tp, enum.Enum):
            found[key] = "enum"  # adding a member keeps stored members readable
    return found


def fingerprint(roots: tuple[type, ...]) -> str:
    text = json.dumps(shape(roots), sort_keys=True)
    return hashlib.sha256(text.encode()).hexdigest()


def test_the_shape_of_stored_step_results_is_the_one_steps_version_names() -> None:
    assert FINGERPRINTS.get(STEPS_VERSION) == fingerprint(ROOTS), (
        "the import's step results changed shape: bump STEPS_VERSION in "
        "ingestion/adapters/driven/dbos.py and record the new fingerprint in this test"
    )


def test_the_fingerprint_sees_a_changed_field() -> None:
    @dataclasses.dataclass(frozen=True)
    class Before:
        path: str

    @dataclasses.dataclass(frozen=True)
    class After:
        path: str
        size: int

    After.__qualname__ = Before.__qualname__
    assert fingerprint((Before,)) != fingerprint((After,))
