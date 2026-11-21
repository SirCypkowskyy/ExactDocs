"""Steps for cancelling jobs (#432).

Embedding runs against the fake gateway (``fake_llm``) with a gate that holds the batches of
chunks (never the one-text calls that measure a model), so a scenario can cancel while a batch is
in flight. Imports are queued straight into the job repository (the worker is never told), so
they wait until the scenario hands them over.
"""

import asyncio
import threading
import time
import uuid
from collections import Counter
from datetime import UTC, datetime
from http import HTTPStatus

from behave import given, then, when
from behave.runner import Context

from exactdocs.bootstrap.settings import AiSettings
from exactdocs.ingestion.adapters.driven.sqlite import SqliteJobRepository
from exactdocs.ingestion.constants import JobKind
from exactdocs.ingestion.dtos import QueueEmbeddingCommand
from exactdocs.ingestion.models import Job, JobId, RefKind
from steps.embedding_steps import EMBEDDING_SECONDS, embedding_ai, serve_embedding, start_gateway
from steps.http_steps import step_running
from steps.library_roles_steps import get_person, send_as
from steps.search_steps import LIBRARY, import_versions

FAKE_COMMIT = "0" * 40


class BatchGate(threading.Event):
    """The gateway's ``hold``: holds its embedding calls of more than one text until it is set."""

    def __init__(self) -> None:
        super().__init__()
        self.held = threading.Event()
        self.seen: list = []

    def wait(self, timeout: float | None = None) -> bool:
        texts = self.seen[-1].body.get("input") if self.seen else None
        if isinstance(texts, list) and len(texts) > 1:
            self.held.set()
            return super().wait(timeout)
        return True


def _embeddings(context: Context) -> list[list[str]]:
    return [
        seen.body["input"]
        for seen in context.endpoint.seen
        if seen.path.endswith("/embeddings")
        and isinstance(seen.body.get("input"), list)
        and len(seen.body["input"]) > 1
    ]


def _embed_jobs(context: Context) -> list[dict]:
    response = context.client.get(f"/api/v1/libraries{LIBRARY}/jobs", params={"limit": 100})
    assert response.status_code == HTTPStatus.OK, response.text
    return [job for job in response.json()["jobs"] if job["kind"] == "embed"]


def _job(context: Context, job_id: str) -> dict:
    response = context.client.get(f"/api/v1/jobs/{job_id}")
    assert response.status_code == HTTPStatus.OK, response.text
    return response.json()


def _wait_for(context: Context, job_id: str, states: set[str]) -> dict:
    deadline = time.monotonic() + EMBEDDING_SECONDS
    while time.monotonic() < deadline:
        job = _job(context, job_id)
        if job["state"] in states:
            return job
        time.sleep(0.05)
    message = f"job {job_id} did not reach {states}: {_job(context, job_id)}"
    raise AssertionError(message)


def _cancel(context: Context, job_id: str) -> None:
    context.response = context.client.post(f"/api/v1/jobs/{job_id}/cancel")


@given('ExactDocs embeds the fixture docs repository at "{ref}" in batches of {size:d} chunks')
def step_embeds(context: Context, ref: str, size: int) -> None:
    step_running(context)
    asyncio.run(import_versions(context, [ref]))
    context.gate = BatchGate()
    context.add_cleanup(context.gate.set)
    context.endpoint = start_gateway(context, hold=context.gate)
    context.gate.seen = context.endpoint.seen
    ai = embedding_ai(context.endpoint, "e5").model_dump()
    ai["embedding"]["batch_size"] = size
    context.batch_size = size
    serve_embedding(context, AiSettings.model_validate(ai))  # its start queues the embedding


@given("its embedding job is running a batch")
def step_running_batch(context: Context) -> None:
    assert context.gate.held.wait(EMBEDDING_SECONDS), "no batch reached the provider"
    (job,) = _embed_jobs(context)
    assert job["state"] == "running", job
    context.job_id = job["id"]


@when("the operator cancels the embedding job")
def step_cancel_embedding(context: Context) -> None:
    _cancel(context, context.job_id)


@then('the answer shows the job is being cancelled by "{who}"')
def step_being_cancelled(context: Context, who: str) -> None:
    assert context.response.status_code == HTTPStatus.OK, context.response.text
    body = context.response.json()
    assert (body["state"], body["cancelled_by"]) == ("running", who), body
    assert body["cancelled_at"], body


@then("once the batch in flight ends, no other batch is sent to the provider")
def step_no_more_batches(context: Context) -> None:
    context.gate.set()
    context.job = _wait_for(context, context.job_id, {"cancelled", "succeeded", "failed"})
    assert len(_embeddings(context)) == 1, _embeddings(context)


@then('the embedding job ends "{state}" by "{who}" with the vectors of that batch kept')
def step_ended(context: Context, state: str, who: str) -> None:
    job = context.job
    assert (job["state"], job["cancelled_by"]) == (state, who), job
    assert job["finished_at"], job
    assert job["done"] == context.batch_size, job


@given("its embedding job was cancelled after one batch")
def step_cancelled_after_one(context: Context) -> None:
    step_running_batch(context)
    _cancel(context, context.job_id)
    assert context.response.status_code == HTTPStatus.OK, context.response.text
    context.gate.set()
    context.job = _wait_for(context, context.job_id, {"cancelled"})


@when("the operator queues the embedding of the library again")
def step_queue_again(context: Context) -> None:
    command = QueueEmbeddingCommand(library=LIBRARY, retry_cancelled=True)
    queued = context.client.portal.call(context.container.ingestion.queue_embedding, command)
    assert queued.queued == 1, queued


@then("the new embedding job succeeds")
def step_new_job_succeeds(context: Context) -> None:
    newest, *_ = _embed_jobs(context)
    assert newest["id"] != context.job_id, newest
    job = _wait_for(context, newest["id"], {"succeeded", "failed", "cancelled"})
    assert job["state"] == "succeeded", job
    assert job["total"] == context.job["total"] - context.batch_size, (job, context.job)


@then("no chunk was sent to the provider twice")
def step_none_twice(context: Context) -> None:
    # Every text of every embedding call, a version's last (one-chunk) batch included; a call
    # that measures the model's dimensions sends one fixed text, at most once per space.
    sent = Counter(
        text
        for seen in context.endpoint.seen
        if seen.path.endswith("/embeddings") and isinstance(seen.body.get("input"), list)
        for text in seen.body["input"]
    )
    assert max(sent.values()) == 1, sent.most_common(3)
    assert context.job["total"] <= sum(sent.values()) <= context.job["total"] + 1, sent


def _store(context: Context, job: Job) -> None:
    serve_embedding(context, AiSettings())  # the same app, with its container at hand
    repository = SqliteJobRepository(engine=context.container.engine)
    context.client.portal.call(repository.add, job)
    context.job_id = job.id


def _queued_import(ref: str, library: str) -> Job:
    return Job.queued(
        job_id=JobId(str(uuid.uuid7())),
        kind=JobKind("import"),
        library=library,
        version=ref,
        commit_sha=FAKE_COMMIT,
        ref_kind=RefKind.TAG,
        now=datetime.now(UTC),
    )


@given('an import of "{ref}" of "{library}" is queued')
def step_queued_import(context: Context, ref: str, library: str) -> None:
    _store(context, _queued_import(ref, library))


@given('an import of "{ref}" of "{library}" that already failed')
def step_failed_import(context: Context, ref: str, library: str) -> None:
    now = datetime.now(UTC)
    _store(context, _queued_import(ref, library).started(now).failed("no such tag", now))


@when("the operator cancels that job")
def step_cancel(context: Context) -> None:
    _cancel(context, context.job_id)


@when('"{username}" cancels that job')
def step_cancel_as(context: Context, username: str) -> None:
    person = get_person(context, username)
    context.response = send_as(
        context, "POST", f"/api/v1/jobs/{context.job_id}/cancel", session=person["session"]
    )


@then('the job is "{state}" by "{who}"')
def step_job_cancelled(context: Context, state: str, who: str) -> None:
    body = context.response.json()
    assert (body["state"], body["cancelled_by"]) == (state, who), body
    assert body["cancelled_at"], body
    assert body["finished_at"], body


@then("when the worker picks the job up, it never starts")
def step_never_starts(context: Context) -> None:
    context.client.portal.call(context.container.ingestion.run_job, context.job_id)
    job = _job(context, context.job_id)
    assert (job["state"], job["started_at"]) == ("cancelled", None), job


@then('"{library}" has no version "{ref}"')
def step_no_version(context: Context, library: str, ref: str) -> None:
    response = context.client.get(f"/api/v1/libraries{library}")
    assert response.status_code == HTTPStatus.OK, response.text
    assert ref not in response.text, response.text


@then('the refusal says the job is already "{state}"')
def step_error_state(context: Context, state: str) -> None:
    body = context.response.json()
    assert (body["error"], body["job_state"]) == ("job_finished", state), body
