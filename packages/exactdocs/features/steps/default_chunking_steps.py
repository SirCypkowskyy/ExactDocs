"""Steps for the default chunking of a new library: headings 1 to 3, 4,000 characters (#381)."""

from http import HTTPStatus

from behave import given, then, when
from behave.runner import Context

from steps.import_steps import LIBRARY, import_version, start
from steps.read_steps import outline_nodes

REF = "deep"
ARTICLE = "docs/deep.md"
SPLIT_LEVEL = 3  # the default split level
BOUND = 4_000  # the default max_chars
SENTENCE = "Each option of the reference is described here, word for word, with its default. "
PARAGRAPH = SENTENCE * 18  # about 1,500 characters
SHORT_DETAIL = ("Deep", "Short", "Options", "Detail")
LONG_SECTION = ("Deep", "Long", "Reference")
LONG_PARTS = ("First", "Second", "Third")


def _article() -> str:
    """A short section holding a level-4 heading, and a long one made of level-4 sections."""
    parts = "".join(f"#### {name}\n\n{PARAGRAPH}\n\n" for name in LONG_PARTS)
    return (
        "# Deep\n\nIntro.\n\n"
        "## Short\n\nA short section.\n\n### Options\n\nA few options.\n\n"
        "#### Detail\n\nOne detail, too short to be a chunk of its own.\n\n"
        f"## Long\n\nA long section follows.\n\n### Reference\n\nThe reference.\n\n{parts}"
    )


def _outline(context: Context) -> list[tuple[tuple[str, ...], dict]]:
    response = context.client.get(
        f"/api/v1/libraries{LIBRARY}/outline", params={"path": ARTICLE, "ref": REF}
    )
    assert response.status_code == HTTPStatus.OK, response.text
    return outline_nodes(response.json()["sections"])


def _chunk(context: Context, chunk_id: str) -> dict:
    response = context.client.get(f"/api/v1/chunks/{chunk_id}")
    assert response.status_code == HTTPStatus.OK, response.text
    return response.json()


def _chunking(context: Context) -> dict:
    response = context.client.get(f"/api/v1/libraries{LIBRARY}")
    assert response.status_code == HTTPStatus.OK, response.text
    return response.json()["settings"]["chunking"]


@given(
    'a branch "{branch}" adds "{path}" with a "####" heading in a short section and several in '
    "a section longer than 4,000 characters"
)
def step_deep_article(context: Context, branch: str, path: str) -> None:
    repo = context.fixture_repo.path
    text = _article()
    assert len(text.split("### Reference", 1)[1]) > BOUND
    context.fixture_git("checkout", "-q", "-b", branch, "main", cwd=repo)
    (repo / path).write_text(text, encoding="utf-8")
    context.fixture_git("add", "-A", cwd=repo)
    context.fixture_git("-c", "user.name=Fixture", "-c", "user.email=f@exactdocs.invalid",
                        "commit", "-q", "-m", "docs: a deep article", cwd=repo)  # fmt: skip
    context.fixture_git("checkout", "-q", "main", cwd=repo)


@given("an instance with default settings")
def step_default_instance(context: Context) -> None:
    start(context)


@when("a library is added without chunking settings")
def step_add_default(context: Context) -> None:
    import_version(context, REF, include_paths=["docs/"])
    assert context.job["state"] == "succeeded", context.job


@when('a library is added with the split level "h6" and no size bound')
def step_add_own(context: Context) -> None:
    chunking = {"split_level": 6, "max_chars": None}
    import_version(context, REF, include_paths=["docs/"], chunking=chunking)
    assert context.job["state"] == "succeeded", context.job


@then("its articles start a chunk at headings of level 1 to 3")
def step_levels(context: Context) -> None:
    assert _chunking(context) == {
        "split_level": SPLIT_LEVEL,
        "min_chars": 0,
        "max_chars": BOUND,
        "chunker": "markdown",
    }
    nodes = dict(_outline(context))
    top = [node for path, node in nodes.items() if len(path) <= SPLIT_LEVEL]
    assert all(node["starts_chunk"] for node in top), nodes
    detail = nodes[SHORT_DETAIL]
    assert detail["starts_chunk"] is False, detail
    assert detail["chunk_id"] == nodes[SHORT_DETAIL[:-1]]["chunk_id"], nodes
    assert "#### Detail" in _chunk(context, detail["chunk_id"])["content"]


@then("a chunk longer than 4,000 characters is cut again at deeper headings")
def step_bounded(context: Context) -> None:
    nodes = dict(_outline(context))
    parts = [nodes[*LONG_SECTION, name] for name in LONG_PARTS]
    assert nodes[LONG_SECTION]["starts_chunk"], nodes[LONG_SECTION]
    assert any(part["starts_chunk"] for part in parts), parts  # the section is not one chunk
    chunk_ids = {node["chunk_id"] for node in nodes.values()}
    sizes = [len(_chunk(context, chunk_id)["content"]) for chunk_id in chunk_ids]
    assert max(sizes) <= BOUND, sizes


@then('its chunking settings are the split level "h6" and no size bound')
def step_own_settings(context: Context) -> None:
    chunking = _chunking(context)
    assert (chunking["split_level"], chunking["max_chars"]) == (6, None), chunking


@then('every heading of "docs/deep.md" starts a chunk')
def step_every_heading(context: Context) -> None:
    nodes = _outline(context)
    assert all(node["starts_chunk"] for _, node in nodes), nodes
    assert SHORT_DETAIL in dict(nodes), nodes
