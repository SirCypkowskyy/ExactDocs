"""Who queued a job (#512): the account of the request, over REST or MCP, and nothing more."""

import asyncio

import pytest
from fastmcp.server.auth import AccessToken

from exactdocs.bootstrap import caller
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.settings import Settings
from exactdocs.ingestion.dtos import EnqueueJobCommand, PersonSummary
from exactdocs.ingestion.models import Person, VersionOrigin

REQUESTER = caller.current_person


async def test_a_rest_request_names_its_account_and_user_name() -> None:
    async def request() -> Person | None:
        caller.bind_caller("acc-1", username="ada")
        return await REQUESTER()

    assert await asyncio.create_task(request()) == Person(id="acc-1", username="ada")
    assert await REQUESTER() is None  # outside the request: the instance's own work


async def test_the_binding_is_undone_when_the_request_ends() -> None:
    binding = caller.bind_caller("acc-1", username="ada")
    caller.reset_caller(binding)

    assert (caller.current_account_id(), caller.current_account_name()) == (None, None)


def test_an_mcp_request_names_the_user_name_its_token_carries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = AccessToken(
        token="never-stored", client_id="acc-2", scopes=[], claims={"username": "bob"}
    )
    monkeypatch.setattr(caller, "get_access_token", lambda: token)

    assert asyncio.run(REQUESTER()) == Person(id="acc-2", username="bob")


def test_an_account_without_a_known_name_is_named_by_its_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = AccessToken(token="", client_id="acc-3", scopes=[], claims={})
    monkeypatch.setattr(caller, "get_access_token", lambda: token)

    assert asyncio.run(REQUESTER()) == Person(id="acc-3", username="acc-3")


async def test_the_container_records_the_person_of_the_request_on_the_jobs_it_queues() -> None:
    container = Container.build(Settings())
    async with container.running(jobs=False):

        async def request(origin: VersionOrigin) -> tuple[object, VersionOrigin]:
            caller.bind_caller("acc-1", username="ada")
            job = await container.ingestion.enqueue_job(
                EnqueueJobCommand(kind="collect", library="/acme/payments", origin=origin)
            )
            return job.created_by, job.origin

        manual = await asyncio.create_task(request(VersionOrigin.MANUAL))
        auto = await asyncio.create_task(request(VersionOrigin.AUTO))
        instance = await container.ingestion.enqueue_job(
            EnqueueJobCommand(kind="collect", library="/acme/payments")
        )

    created_by, origin = manual
    assert origin is VersionOrigin.MANUAL
    assert isinstance(created_by, PersonSummary)
    assert created_by.model_dump() == {"id": "acc-1", "username": "ada"}
    assert auto == (None, VersionOrigin.AUTO)  # the instance's own job names nobody
    assert instance.created_by is None  # the command line: nobody bound
