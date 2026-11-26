"""The GHCR retention passes (.github/workflows/ghcr-retention.yml) keep each variant apart (#246).

dataaxiom/ghcr-cleanup-action drops from a pass every image one of whose tags, or whose digest
(`sha256:...`), matches `exclude-tags`. The patterns are JavaScript regular expressions; the ones
used here (anchors, groups, alternation, `\\d`, negative lookahead) mean the same in Python.
"""

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[4]
WORKFLOW = ROOT / ".github" / "workflows" / "ghcr-retention.yml"

DIGEST = "sha256:" + "ab" * 32
SIGNATURE = "sha256-" + "cd" * 32 + ".sig"
# One release of each channel and variant, with every tag the release workflow gives it.
IMAGES = {
    ("base", "stable"): ["0.4.0", "0.4", "latest"],
    ("base", "dev"): ["0.4.0.dev1", "0.4.0.dev1-abc1234", "dev"],
    ("ai", "stable"): ["0.4.0-ai", "0.4-ai", "latest-ai"],
    ("ai", "dev"): ["0.4.0.dev1-ai", "0.4.0.dev1-abc1234-ai", "dev-ai"],
    ("local", "stable"): ["0.4.0-local", "0.4-local", "latest-local"],
    ("local", "dev"): ["0.4.0.dev1-local", "0.4.0.dev1-abc1234-local", "dev-local"],
}


def _passes() -> dict[tuple[str, str], str]:
    matrix = yaml.safe_load(WORKFLOW.read_text())["jobs"]["cleanup"]["strategy"]["matrix"]
    passes = {}
    for entry in matrix["include"]:
        passes[entry["variant"], "dev"] = entry["not-dev"]
        passes[entry["variant"], "stable"] = entry["not-stable"]
    return passes


def _in_pass(pattern: str, tags: list[str], digest: str = DIGEST) -> bool:
    """Whether the action keeps an image in a pass: none of its tags nor its digest match."""
    return not any(re.search(pattern, t) for t in [*tags, digest])


PASSES = _passes()


def test_every_variant_has_a_dev_and_a_stable_pass() -> None:
    assert set(PASSES) == set(IMAGES)


@pytest.mark.parametrize("pass_", sorted(IMAGES), ids="-".join)
def test_a_pass_holds_exactly_its_own_images(pass_: tuple[str, str]) -> None:
    held = {image for image, tags in IMAGES.items() if _in_pass(PASSES[pass_], tags)}

    assert held == {pass_}


@pytest.mark.parametrize("pass_", sorted(IMAGES), ids="-".join)
def test_no_pattern_excludes_digests_or_signature_tags(pass_: tuple[str, str]) -> None:
    """A pattern matching every digest would drop every image, and the pass would delete none."""
    pattern = PASSES[pass_]

    assert not re.search(pattern, DIGEST)
    assert not re.search(pattern, SIGNATURE)


def test_untagged_images_of_a_running_release_are_kept() -> None:
    """A release pushes untagged platform images before it tags them (#607)."""
    jobs = yaml.safe_load(WORKFLOW.read_text())["jobs"]
    (leftovers,) = jobs["leftovers"]["steps"]

    assert "github.event.workflow_run.conclusion == 'success'" in jobs["cleanup"]["if"]
    assert leftovers["with"]["delete-untagged"] is True
    assert leftovers["with"]["older-than"] == "1 day"
