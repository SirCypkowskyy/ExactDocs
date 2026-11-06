"""The import's step results are stored (pickled by DBOS) and read back by a later release.

A release that changes the shape of any of them must bump ``STEPS_VERSION``: a job started by
the release before then starts over instead of resuming from results of another shape. This test
fails until both are done: bump the version and record the new fingerprint here.
"""

import dataclasses
import enum
import hashlib
import json
import typing

from exactdocs.ingestion.adapters.driven.dbos import STEPS_VERSION
from exactdocs.ingestion.models import GitRename, ReadmeSummary
from exactdocs.ingestion.use_cases import _Batch, _Context7Read, _ImageBudget, _Missing

# Every type a step of the import returns (the rest is reached through their fields).
ROOTS = (_Batch, _ImageBudget, _Missing, _Context7Read, ReadmeSummary, GitRename)

FINGERPRINTS = {
    "jobs-1": "9bf7464faeb9cb3f19bb905319608080e03d640c21227eaf3ff85aae740f1463",
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
