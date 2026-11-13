"""Steps for a section longer than the chunk size limit, served in parts (#141)."""

from http import HTTPStatus

from behave import given, then
from behave.runner import Context

from exactdocs.ingestion.constants import DEFAULT_MAX_SECTION_CHARS
from steps.read_steps import outline_nodes

PARAGRAPH = "Every option of the reference is described in this paragraph, word for word. " * 4
PARAGRAPHS = 3 * DEFAULT_MAX_SECTION_CHARS // len(PARAGRAPH)  # three times the limit


def _git(context: Context, *args: str) -> str:
    return context.fixture_git(*args, cwd=context.fixture_repo.path)


def _section() -> tuple[str, str]:
    """The long section, and the code block in its middle (longer than the limit on its own)."""
    fence = (
        "```python\n"
        + "".join(
            f"OPTION_{i} = {i}  # a line of the generated options table\n\n"
            for i in range(DEFAULT_MAX_SECTION_CHARS // 40)
        )
        + "```\n"
    )
    text = "".join(f"Paragraph {i}: {PARAGRAPH}\n\n" for i in range(PARAGRAPHS // 2))
    after = "".join(f"Note {i}: {PARAGRAPH}\n\n" for i in range(PARAGRAPHS // 2))
    return f"## Reference\n\n{text}{fence}\n{after}", fence


@given(
    'a branch "{branch}" adds "{path}" whose section "Long > Reference" is several times the '
    "chunk size limit, with a code block longer than the limit"
)
def step_long_article(context: Context, branch: str, path: str) -> None:
    section, fence = _section()
    assert len(fence) > DEFAULT_MAX_SECTION_CHARS
    context.long_section, context.long_fence = section, fence
    _git(context, "checkout", "-q", "-b", branch, "main")
    target = context.fixture_repo.path / path
    target.write_text(f"# Long\n\nIntro.\n\n{section}## After\n\nThe end.\n", encoding="utf-8")
    _git(context, "add", "-A")
    _git(context, "-c", "user.name=Fixture", "-c", "user.email=f@exactdocs.invalid",
         "commit", "-q", "-m", "docs: a long reference")  # fmt: skip
    _git(context, "checkout", "-q", "main")


@then('the outline lists the heading "{heading}" once')
def step_outline_once(context: Context, heading: str) -> None:
    response = context.response
    assert response.status_code == HTTPStatus.OK, response.text
    wanted = tuple(heading.split(" > "))
    entries = [s for p, s in outline_nodes(response.json()["sections"]) if p == wanted]
    assert len(entries) == 1, entries
    context.long_heading, context.long_chunk_id = list(wanted), entries[0]["chunk_id"]


@then(
    "reading that heading's chunk and the next ones of the same heading gives the whole "
    "section, in order"
)
def step_parts(context: Context) -> None:
    parts, chunk_id = [], context.long_chunk_id
    while chunk_id:
        response = context.client.get(f"/api/v1/chunks/{chunk_id}")
        assert response.status_code == HTTPStatus.OK, response.text
        chunk = response.json()
        if chunk["heading_path"] != context.long_heading:
            break
        parts.append(chunk)
        chunk_id = chunk["next_chunk_id"]
    assert len(parts) > 1, parts
    assert "".join(p["content"] for p in parts) == context.long_section
    assert len({p["chunk_id"] for p in parts}) == len(parts)
    assert {p["anchor"] for p in parts} == {"reference"}
    context.long_parts = parts


@then("every part is within the chunk size limit except the one that holds the whole code block")
def step_bounded(context: Context) -> None:
    holding = [p for p in context.long_parts if "```" in p["content"]]
    assert len(holding) == 1, holding
    assert context.long_fence in holding[0]["content"]
    others = [p for p in context.long_parts if p is not holding[0]]
    assert all(len(p["content"]) <= DEFAULT_MAX_SECTION_CHARS for p in others), [
        len(p["content"]) for p in others
    ]
