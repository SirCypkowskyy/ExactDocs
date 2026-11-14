"""Steps for repo guidance (#101): the real import, catalog and agent; a scripted LLM.

The library is imported with only ``docs/`` selected, so the root ``AGENTS.md`` of the fixture
repository lies outside the selection. Repo guidance is set over REST, which re-imports the
version at the same commit (a queued ``reprocess``) so that it keeps the file; the agent's model
records every request it receives.
"""

from contextlib import ExitStack
from http import HTTPStatus
from typing import Any

from behave import given, then, when
from behave.runner import Context
from fastapi.testclient import TestClient

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import AiSettings
from scripted_explorer import Request, ScriptedModels, guided, scripted_ai
from steps.http_steps import DEMO_COOKIE, SESSION_COOKIE
from steps.import_steps import LIBRARY, articles_of, import_version, wait_for_job

REF = "v1.4.0"
QUESTION = "how do I install the client"
LAYOUT = "Documentation lives in `docs/`"
"""A line of the fixture repository's root AGENTS.md."""
OPEN_ROOT = """\
hits = await search_docs(query='install', limit=3)
await list_articles()
hits
"""
"""The scripted agent searches, then opens the repository's root folder."""


def _serve_guided(context: Context) -> None:
    """Serve the same data again with the recording scripted model as the ``llm`` role.

    Args:
        context: The behave context.
    """
    context.client.__exit__(None, None, None)  # one job worker per process
    stack = ExitStack()
    context.add_cleanup(stack.close)
    ai: dict[str, Any] = scripted_ai("agentic")
    settings = context.settings.model_copy(update={"ai": AiSettings.model_validate(ai)})
    context.seen = []
    container = Container.build(
        settings, model_factory=ScriptedModels(model=guided(OPEN_ROOT, context.seen))
    )
    context.container = container
    context.client = stack.enter_context(
        TestClient(
            create_app(container),
            base_url="http://localhost",
            cookies={SESSION_COOKIE: DEMO_COOKIE},
        )
    )


def _set_guidance(context: Context, guidance: str) -> None:
    """Set the library's repo guidance; turning it on re-imports the versions by itself.

    No new commit and no re-import by hand: the ``reprocess`` the setting queued must bring the
    already-imported version its instruction files.

    Args:
        context: The behave context.
        guidance: ``off``, ``notes`` or ``trusted``.
    """
    owner, repo = LIBRARY.removeprefix("/").split("/")
    response = context.client.put(
        f"/api/v1/libraries/{owner}/{repo}/retrieval", json={"repo_guidance": guidance}
    )
    assert response.status_code == HTTPStatus.OK, response.text
    assert response.json()["repo_guidance"] == guidance
    jobs = context.client.get(f"/api/v1/libraries{LIBRARY}/jobs").json()["jobs"]
    reprocesses = [job for job in jobs if job["kind"] == "reprocess"]
    if guidance == "off":
        assert reprocesses == [], jobs
        return
    (queued,) = reprocesses
    job = wait_for_job(context, queued["id"])
    assert job["state"] == "succeeded", job


@given("the library's repository has an AGENTS.md describing its docs layout")
def step_has_agents_md(context: Context) -> None:
    shown = context.fixture_git("show", f"{REF}:AGENTS.md", cwd=context.fixture_repo.path)
    assert LAYOUT in shown, shown
    import_version(context, REF, include_paths=["docs/"])
    assert context.job["state"] == "succeeded", context.job
    paths = [a["path"] for a in articles_of(context, REF)]
    assert "AGENTS.md" not in paths, paths  # outside the selection: never an article
    _serve_guided(context)


@given("the owner enabled repo guidance without marking the library trusted")
def step_notes(context: Context) -> None:
    _set_guidance(context, "notes")


@given("the owner enabled repo guidance and marked the library trusted")
def step_trusted(context: Context) -> None:
    _set_guidance(context, "trusted")


@given("the owner left repo guidance off")
def step_off(context: Context) -> None:
    _set_guidance(context, "off")


@when("the agent opens a directory")
def step_open_directory(context: Context) -> None:
    owner, repo = LIBRARY.removeprefix("/").split("/")
    response = context.client.get(
        f"/api/v1/libraries/{owner}/{repo}/search",
        params={"q": QUESTION, "ref": REF, "mode": "agentic"},
    )
    assert response.status_code == HTTPStatus.OK, response.text
    body = response.json()
    assert (body["retrieval_mode"], body["fallback_reason"]) == ("agentic", None), body
    assert body["results"], body
    context.result = body


def _requests(context: Context) -> list[Request]:
    seen: list[Request] = context.seen
    assert seen, "the scripted model was called"
    return seen


def _notes(context: Context) -> list[str]:
    return [text for text in _requests(context)[-1].user if text != QUESTION]


def _system(context: Context) -> str:
    return "\n".join(r.instructions + "\n".join(r.system) for r in _requests(context))


@then("the file reaches it as a user-channel note, not as system instructions")
def step_user_note(context: Context) -> None:
    notes = _notes(context)
    assert len(notes) == 1, notes
    assert notes[0].startswith('<context-file path="AGENTS.md">\n'), notes
    assert LAYOUT in notes[0], notes
    assert LAYOUT not in _system(context)


@then("the file is part of its system instructions")
def step_system(context: Context) -> None:
    first = _requests(context)[0].instructions
    assert '<context-file path="AGENTS.md">' in first, first
    assert LAYOUT in first, first
    assert _notes(context) == []  # not repeated on the user channel


@then("no instruction file reaches it")
def step_no_file(context: Context) -> None:
    assert _notes(context) == []
    assert LAYOUT not in _system(context)
    assert "AGENTS.md" not in _system(context)
