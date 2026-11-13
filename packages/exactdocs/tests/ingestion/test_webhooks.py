"""Push webhooks (TEAM-03): verification, payloads, routing, the receiving use case, the job."""

import asyncio
import hashlib
import hmac
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime

import pytest

from exactdocs.ingestion.adapters.driven.memory import (
    InMemoryAutoSyncStore,
    InMemoryJobRepository,
    InMemoryLibrarySources,
    InMemoryWebhookDeliveries,
    InMemoryWebhookSecrets,
    NoIndex,
    NoRemovals,
)
from exactdocs.ingestion.constants import IMPORT_JOB, PUSH_JOB, REFRESH_JOB, JobKind
from exactdocs.ingestion.dtos import ReceiveWebhookCommand, WebhookQuery
from exactdocs.ingestion.errors import (
    InvalidWebhookPayloadError,
    InvalidWebhookSignatureError,
    MissingDeliveryIdError,
    WebhookSecretUnreadableError,
)
from exactdocs.ingestion.models import (
    AutoSync,
    Credential,
    ImportedRef,
    ImportSource,
    Job,
    JobState,
    PathSelection,
    ProposedId,
    PushedRef,
    PushEvent,
    RefKind,
    RemoteRef,
    RemoteRefs,
    RepositoryHost,
    RepositoryUrl,
    SyncErrorCode,
    VersionOrigin,
    Webhook,
    WebhookProvider,
    parse_push,
    route_push,
    verify_webhook,
    webhook_provider,
)
from exactdocs.ingestion.module import IngestionModule
from exactdocs.ingestion.ports.driven import JobHandler, JobProgress
from exactdocs_kernel import NotFoundError

GITHUB, GITLAB, BITBUCKET = (
    WebhookProvider.GITHUB,
    WebhookProvider.GITLAB,
    WebhookProvider.BITBUCKET,
)
# GitHub's documented example (docs.github.com, "Validating webhook deliveries").
VECTOR_SECRET = "It's a Secret to Everybody"
VECTOR_BODY = b"Hello, World!"
VECTOR_SIGNATURE = "sha256=757107ea0eb2509fc211221cce984b8a37570b6d7586c22c46f4379c8b043e17"

LIBRARY = "/acme/docs"
OLD, NEW, TAG_SHA = "a" * 40, "b" * 40, "c" * 40
URL = RepositoryUrl(
    url="https://example.com/acme/docs",
    host_kind=RepositoryHost.GIT,
    library_id=ProposedId(LIBRARY),
)
SOURCE = ImportSource(url=URL, selection=PathSelection.of([]), tag_rules=())


def signed(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


# ---------------------------------------------------------------- verify_webhook


def test_githubs_documented_vector_verifies() -> None:
    headers = {"X-Hub-Signature-256": VECTOR_SIGNATURE}

    assert verify_webhook(GITHUB, headers, VECTOR_BODY, VECTOR_SECRET)
    assert verify_webhook(
        GITHUB, {"x-hub-signature-256": VECTOR_SIGNATURE}, VECTOR_BODY, VECTOR_SECRET
    )


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"X-Hub-Signature-256": VECTOR_SIGNATURE[:-1]},  # truncated
        {"X-Hub-Signature-256": VECTOR_SIGNATURE.replace("sha256=", "sha1=")},  # wrong scheme
        {"X-Hub-Signature-256": VECTOR_SIGNATURE.removeprefix("sha256=")},  # no scheme
        {"X-Hub-Signature-256": VECTOR_SIGNATURE.upper()},
        {
            "X-Hub-Signature": "sha1="
            + hmac.new(VECTOR_SECRET.encode(), VECTOR_BODY, "sha1").hexdigest()
        },
    ],
)
def test_a_wrong_or_sha1_github_signature_is_refused(headers: dict[str, str]) -> None:
    assert not verify_webhook(GITHUB, headers, VECTOR_BODY, VECTOR_SECRET)


def test_a_one_byte_change_breaks_the_signature() -> None:
    headers = {"X-Hub-Signature-256": VECTOR_SIGNATURE}

    assert not verify_webhook(GITHUB, headers, b"Hello, World?", VECTOR_SECRET)
    assert not verify_webhook(GITHUB, headers, VECTOR_BODY, VECTOR_SECRET + " ")


def test_bitbucket_signs_with_sha256_in_x_hub_signature() -> None:
    body = b'{"push": {"changes": []}}'

    assert verify_webhook(BITBUCKET, {"X-Hub-Signature": signed(body, "s3")}, body, "s3")
    assert not verify_webhook(BITBUCKET, {"X-Hub-Signature-256": signed(body, "s3")}, body, "s3")
    sha1 = "sha1=" + hmac.new(b"s3", body, "sha1").hexdigest()
    assert not verify_webhook(BITBUCKET, {"X-Hub-Signature": sha1}, body, "s3")


def test_gitlab_sends_the_secret_itself() -> None:
    assert verify_webhook(GITLAB, {"X-Gitlab-Token": "s3cret"}, b"{}", "s3cret")
    assert not verify_webhook(GITLAB, {"X-Gitlab-Token": "s3cre"}, b"{}", "s3cret")
    assert not verify_webhook(GITLAB, {}, b"{}", "s3cret")
    # A GitHub-style signature is no GitLab token.
    assert not verify_webhook(
        GITLAB, {"X-Hub-Signature-256": signed(b"{}", "s3cret")}, b"{}", "s3cret"
    )


def test_the_forge_is_told_by_its_event_header() -> None:
    assert webhook_provider({"X-GitHub-Event": "push"}) is GITHUB
    assert webhook_provider({"X-Gitlab-Event": "Push Hook"}) is GITLAB
    assert webhook_provider({"X-Event-Key": "repo:push"}) is BITBUCKET
    assert webhook_provider({"X-Gitea-Event": "push"}) is None
    assert webhook_provider({}) is None


# ---------------------------------------------------------------- parse_push


def github(event: str = "push", delivery: str = "d-1") -> dict[str, str]:
    return {"X-GitHub-Event": event, "X-GitHub-Delivery": delivery}


def branch(name: str, *, deleted: bool = False) -> PushedRef:
    return PushedRef(kind=RefKind.BRANCH, name=name, deleted=deleted)


def tag(name: str, *, deleted: bool = False) -> PushedRef:
    return PushedRef(kind=RefKind.TAG, name=name, deleted=deleted)


def body(payload: object) -> bytes:
    return json.dumps(payload).encode()


def test_a_github_push_names_its_branch_or_tag_and_deletion() -> None:
    pushed = body({"ref": "refs/heads/main", "before": OLD, "after": NEW, "deleted": False})
    tagged = body({"ref": "refs/tags/v2.1.0", "after": TAG_SHA, "created": True})
    gone = body({"ref": "refs/heads/old", "after": "0" * 40, "deleted": True})

    assert parse_push(GITHUB, github(), pushed) == PushEvent(
        delivery_id="d-1", refs=(branch("main"),)
    )
    assert parse_push(GITHUB, github(), tagged).refs == (tag("v2.1.0"),)
    assert parse_push(GITHUB, github(), gone).refs == (branch("old", deleted=True),)


def test_a_ping_or_another_event_has_no_refs_and_is_not_parsed() -> None:
    assert parse_push(GITHUB, github("ping"), b"not even json") == PushEvent(delivery_id="d-1")
    assert parse_push(GITHUB, github("pull_request"), body({"ref": "refs/heads/x"})).refs == ()
    headers = {"X-Event-Key": "diagnostics:ping", "X-Request-Id": "r-1"}
    assert parse_push(BITBUCKET, headers, b"{}") == PushEvent(delivery_id="r-1")


def test_a_ref_that_is_no_branch_or_tag_is_left_out() -> None:
    refs = [body({"ref": "refs/pull/7/head"}), body({"ref": "refs/heads/../x"}), body({"ref": 7})]

    assert all(parse_push(GITHUB, github(), r).refs == () for r in refs)


def test_gitlab_pushes_and_tag_pushes_with_their_delivery_ids() -> None:
    pushed = body({"object_kind": "push", "ref": "refs/heads/main", "after": NEW})
    tagged = body({"object_kind": "tag_push", "ref": "refs/tags/v2.1.0", "after": TAG_SHA})
    gone = body({"object_kind": "push", "ref": "refs/heads/main", "after": "0" * 40})
    uuid_only = {"X-Gitlab-Event": "Push Hook", "X-Gitlab-Event-UUID": "u-1"}
    both = {**uuid_only, "Idempotency-Key": "k-1"}

    assert parse_push(GITLAB, uuid_only, pushed) == PushEvent(
        delivery_id="u-1", refs=(branch("main"),)
    )
    assert parse_push(GITLAB, both, pushed).delivery_id == "k-1"
    tag_headers = {"X-Gitlab-Event": "Tag Push Hook", "X-Gitlab-Event-UUID": "u-2"}
    assert parse_push(GITLAB, tag_headers, tagged).refs == (tag("v2.1.0"),)
    assert parse_push(GITLAB, uuid_only, gone).refs == (branch("main", deleted=True),)


def test_bitbucket_cloud_routes_every_change_of_a_push() -> None:
    payload = {
        "push": {
            "changes": [
                {
                    "new": {"type": "branch", "name": "main"},
                    "old": {"type": "branch", "name": "main"},
                },
                {"new": {"type": "tag", "name": "v2.1.0"}, "old": None},
                {"new": None, "old": {"type": "branch", "name": "old"}, "closed": True},
                {"new": {"type": "bookmark", "name": "hg"}, "old": None},
            ]
        }
    }
    headers = {"X-Event-Key": "repo:push", "X-Request-UUID": "{b-1}"}

    event = parse_push(BITBUCKET, headers, body(payload))

    assert event == PushEvent(
        delivery_id="{b-1}", refs=(branch("main"), tag("v2.1.0"), branch("old", deleted=True))
    )


def test_bitbucket_data_center_refs_changed() -> None:
    payload = {
        "eventKey": "repo:refs_changed",
        "changes": [
            {
                "ref": {"id": "refs/heads/main", "displayId": "main", "type": "BRANCH"},
                "type": "UPDATE",
            },
            {
                "ref": {"id": "refs/tags/v2.1.0", "displayId": "v2.1.0", "type": "TAG"},
                "type": "ADD",
            },
            {
                "ref": {"id": "refs/heads/old", "displayId": "old", "type": "BRANCH"},
                "type": "DELETE",
            },
        ],
    }
    headers = {"X-Event-Key": "repo:refs_changed", "X-Request-Id": "dc-1"}

    assert parse_push(BITBUCKET, headers, body(payload)).refs == (
        branch("main"),
        tag("v2.1.0"),
        branch("old", deleted=True),
    )


def test_a_signed_delivery_without_an_id_is_refused() -> None:
    with pytest.raises(MissingDeliveryIdError):
        parse_push(GITHUB, {"X-GitHub-Event": "push"}, body({"ref": "refs/heads/main"}))
    with pytest.raises(MissingDeliveryIdError):
        parse_push(GITHUB, github(delivery="  "), body({"ref": "refs/heads/main"}))
    with pytest.raises(MissingDeliveryIdError):
        parse_push(BITBUCKET, {"X-Event-Key": "repo:push"}, b"{}")


@pytest.mark.parametrize("raw", [b"{not json", b"[1, 2]", b'"text"'])
def test_a_push_body_that_is_no_json_object_is_refused(raw: bytes) -> None:
    with pytest.raises(InvalidWebhookPayloadError):
        parse_push(GITHUB, github(), raw)


def test_a_bitbucket_push_without_changes_is_refused() -> None:
    with pytest.raises(InvalidWebhookPayloadError):
        parse_push(
            BITBUCKET, {"X-Event-Key": "repo:push", "X-Request-UUID": "x"}, body({"push": {}})
        )


# ---------------------------------------------------------------- route_push

VERSIONS = [
    ImportedRef(ref="main", kind=RefKind.BRANCH, commit_sha=OLD),
    ImportedRef(ref="v1.0.0", kind=RefKind.TAG, commit_sha=TAG_SHA),
]
TAGS = AutoSync(library=LIBRARY, tag_pattern="v*")


def routed(*refs: PushedRef, auto_sync: AutoSync | None = TAGS) -> tuple[PushedRef, ...]:
    return route_push(PushEvent(delivery_id="d", refs=refs), VERSIONS, auto_sync)


def test_a_tracked_branch_is_routed_deleted_or_not() -> None:
    assert routed(branch("main")) == (branch("main"),)
    assert routed(branch("main", deleted=True)) == (branch("main", deleted=True),)


def test_an_untracked_branch_or_a_tag_name_is_not() -> None:
    assert routed(branch("feature")) == ()
    assert routed(branch("v1.0.0")) == ()  # a tag version is no branch version


def test_a_tag_is_routed_only_when_the_auto_sync_pattern_matches() -> None:
    assert routed(tag("v2.1.0")) == (tag("v2.1.0"),)
    assert routed(tag("release-2")) == ()
    assert routed(tag("v2.1.0"), auto_sync=None) == ()
    assert routed(tag("v2.1.0"), auto_sync=AutoSync(library=LIBRARY, sync_branches=True)) == ()
    assert routed(tag("v2.1.0", deleted=True)) == ()


def test_a_ping_routes_nothing() -> None:
    assert routed() == ()


# ---------------------------------------------------------------- the use cases


@dataclass
class Remote:
    heads: dict[str, str] = field(default_factory=dict)
    tags: dict[str, str] = field(default_factory=dict)
    listed: int = 0

    async def host_key_fingerprint(self, repository: RepositoryUrl) -> str | None:
        del repository

    async def list_refs(
        self, repository: RepositoryUrl, *patterns: str, credential: Credential | None = None
    ) -> RemoteRefs:
        del repository, patterns, credential
        self.listed += 1
        return RemoteRefs(
            default_branch="main",
            refs=(
                *(RemoteRef(name=f"refs/heads/{n}", sha=s) for n, s in self.heads.items()),
                *(RemoteRef(name=f"refs/tags/{n}", sha=s) for n, s in self.tags.items()),
            ),
        )


async def _noop(job: object, progress: object, /) -> None: ...


@dataclass
class World:
    module: IngestionModule
    jobs: InMemoryJobRepository
    remote: Remote
    secrets: InMemoryWebhookSecrets
    deliveries: InMemoryWebhookDeliveries
    schedules: InMemoryAutoSyncStore
    versions: list[ImportedRef]


@pytest.fixture
def world(clock) -> World:
    jobs = InMemoryJobRepository()
    remote = Remote(heads={"main": OLD, "next": OLD})
    versions = [
        ImportedRef(ref="main", kind=RefKind.BRANCH, commit_sha=OLD),
        ImportedRef(ref="next", kind=RefKind.BRANCH, commit_sha=OLD),
    ]
    secrets, deliveries = InMemoryWebhookSecrets(), InMemoryWebhookDeliveries()
    schedules = InMemoryAutoSyncStore()
    module = IngestionModule.build(
        jobs=jobs,
        clock=clock,
        remote=remote,
        library_ids=None,  # ty: ignore[invalid-argument-type]
        libraries=None,  # ty: ignore[invalid-argument-type]
        sources=InMemoryLibrarySources(sources={LIBRARY: SOURCE}, versions={LIBRARY: versions}),
        removals=NoRemovals(),
        index=NoIndex(),
        handlers={IMPORT_JOB: _noop, REFRESH_JOB: _noop},
        auto_syncs=schedules,
        webhooks=secrets,
        webhook_deliveries=deliveries,
    )
    return World(module, jobs, remote, secrets, deliveries, schedules, versions)


async def secret_of(world: World) -> str:
    return (await world.module.set_webhook(WebhookQuery(library=LIBRARY))).secret


def push(
    secret: str, ref: str = "refs/heads/main", *, delivery: str = "d-1", library: str = LIBRARY
) -> ReceiveWebhookCommand:
    raw = body({"ref": ref, "deleted": False})
    return ReceiveWebhookCommand(
        library=library,
        headers={**github(delivery=delivery), "X-Hub-Signature-256": signed(raw, secret)},
        body=raw,
    )


def of_kind(world: World, kind: str) -> list[Job]:
    return [j for j in world.jobs.jobs.values() if j.kind == kind]


async def test_a_secret_is_shown_once_and_rotation_replaces_it(world: World) -> None:
    query = WebhookQuery(library=LIBRARY)
    assert (await world.module.get_webhook(query)).enabled is False

    created = await world.module.set_webhook(query)

    assert len(created.secret) == 43  # 32 bytes, URL-safe base64 without padding
    assert created.secret.replace("-", "").replace("_", "").isalnum()
    read = await world.module.get_webhook(query)
    assert (read.enabled, read.created_at) == (True, created.created_at)
    assert "secret" not in read.model_dump()
    rotated = await world.module.set_webhook(query)
    assert rotated.secret != created.secret
    with pytest.raises(InvalidWebhookSignatureError):
        await world.module.receive_webhook(push(created.secret))
    assert (await world.module.receive_webhook(push(rotated.secret))).status == "queued"
    off = await world.module.disable_webhook(query)
    assert off.enabled is False
    with pytest.raises(InvalidWebhookSignatureError):
        await world.module.receive_webhook(push(rotated.secret, delivery="d-2"))


async def test_the_secret_routes_need_a_known_library(world: World) -> None:
    for call in (world.module.get_webhook, world.module.set_webhook, world.module.disable_webhook):
        with pytest.raises(NotFoundError):
            await call(WebhookQuery(library="/acme/unknown"))


async def test_a_signed_push_to_a_branch_version_queues_one_push_job(world: World) -> None:
    receipt = await world.module.receive_webhook(push(await secret_of(world)))

    (job,) = world.jobs.jobs.values()
    assert (receipt.status, receipt.job_ids) == ("queued", [job.id])
    assert (job.kind, job.library, job.version, job.ref_kind, job.state, job.commit_sha) == (
        PUSH_JOB,
        LIBRARY,
        "main",
        RefKind.BRANCH,
        JobState.QUEUED,
        None,  # the payload's commit is never trusted
    )


async def test_the_library_id_is_matched_in_any_case(world: World) -> None:
    secret = await secret_of(world)

    assert (
        await world.module.receive_webhook(push(secret, library="/ACME/Docs"))
    ).status == "queued"


async def test_a_redelivery_is_a_duplicate_and_queues_nothing(world: World) -> None:
    secret = await secret_of(world)
    await world.module.receive_webhook(push(secret))

    again = await world.module.receive_webhook(push(secret))

    assert again.status == "duplicate"
    assert len(world.jobs.jobs) == 1


async def test_a_burst_of_pushes_coalesces_into_one_queued_job(world: World) -> None:
    secret = await secret_of(world)

    receipts = [
        await world.module.receive_webhook(push(secret, delivery=f"d-{i}")) for i in range(5)
    ]

    assert {r.status for r in receipts} == {"queued"}
    assert [len(r.job_ids) for r in receipts] == [1, 0, 0, 0, 0]
    assert len(of_kind(world, PUSH_JOB)) == 1


async def test_another_ref_is_ignored_but_remembered(world: World) -> None:
    secret = await secret_of(world)

    untracked = await world.module.receive_webhook(push(secret, "refs/heads/feature"))
    no_auto_import = await world.module.receive_webhook(
        push(secret, "refs/tags/v2.0.0", delivery="d-2")
    )

    assert (untracked.status, no_auto_import.status) == ("ignored", "ignored")
    assert not world.jobs.jobs
    assert len(world.deliveries.deliveries) == 2
    assert (await world.module.receive_webhook(push(secret, "refs/heads/feature"))).status == (
        "duplicate"
    )


async def test_a_ping_is_ignored(world: World) -> None:
    secret = await secret_of(world)
    raw = body({"zen": "Keep it logically awesome.", "hook_id": 1})
    headers = {**github("ping"), "X-Hub-Signature-256": signed(raw, secret)}

    receipt = await world.module.receive_webhook(
        ReceiveWebhookCommand(library=LIBRARY, headers=headers, body=raw)
    )

    assert receipt.status == "ignored"


@pytest.mark.parametrize(
    "case", ["unsigned", "wrong secret", "unknown forge", "no secret", "unknown library"]
)
async def test_every_refusal_is_the_same_and_writes_nothing(world: World, case: str) -> None:
    secret = await secret_of(world)
    command = push(secret)
    if case == "unsigned":
        command = command.model_copy(update={"headers": github()})
    elif case == "wrong secret":
        command = push(secret[::-1])
    elif case == "unknown forge":
        headers = {k: v for k, v in command.headers.items() if k != "X-GitHub-Event"}
        command = command.model_copy(update={"headers": headers})
    elif case == "no secret":
        await world.module.disable_webhook(WebhookQuery(library=LIBRARY))
    else:
        command = push(secret, library="/acme/unknown")

    with pytest.raises(InvalidWebhookSignatureError) as refused:
        await world.module.receive_webhook(command)

    assert (refused.value.code, str(refused.value)) == (
        "invalid_signature",
        "the webhook signature is missing or invalid",
    )
    assert not world.jobs.jobs
    assert not world.deliveries.deliveries


async def test_an_unknown_library_still_costs_one_hmac(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    command = push("whatever", library="/acme/unknown")
    computed: list[bytes] = []
    real = hmac.new

    def counting(key: bytes, msg: bytes, digestmod: str) -> hmac.HMAC:
        computed.append(key)
        return real(key, msg, digestmod)

    monkeypatch.setattr(hmac, "new", counting)
    with pytest.raises(InvalidWebhookSignatureError):
        await world.module.receive_webhook(command)

    assert len(computed) == 1
    assert computed[0] != b"whatever"


class UnreadableSecrets:
    """A ``WebhookSecrets`` whose one secret was sealed with another key."""

    async def save(self, webhook: Webhook) -> None:
        raise NotImplementedError

    async def get(self, library: str) -> Webhook | None:
        raise WebhookSecretUnreadableError(library)

    async def created_at(self, library: str) -> datetime | None:
        raise NotImplementedError

    async def delete(self, library: str) -> None:
        raise NotImplementedError


async def test_an_unreadable_secret_is_refused_alike_and_logged(
    clock, caplog: pytest.LogCaptureFixture
) -> None:
    module = IngestionModule.build(
        jobs=InMemoryJobRepository(),
        clock=clock,
        remote=Remote(),
        library_ids=None,  # ty: ignore[invalid-argument-type]
        libraries=None,  # ty: ignore[invalid-argument-type]
        sources=InMemoryLibrarySources(sources={LIBRARY: SOURCE}),
        removals=NoRemovals(),
        index=NoIndex(),
        webhooks=UnreadableSecrets(),
    )

    with caplog.at_level(logging.WARNING), pytest.raises(InvalidWebhookSignatureError):
        await module.receive_webhook(push("whatever"))

    assert "cannot be read" in caplog.text
    assert "whatever" not in caplog.text


async def test_a_signed_delivery_without_an_id_records_nothing(world: World) -> None:
    secret = await secret_of(world)
    command = push(secret)
    headers = {k: v for k, v in command.headers.items() if k != "X-GitHub-Delivery"}

    with pytest.raises(MissingDeliveryIdError):
        await world.module.receive_webhook(command.model_copy(update={"headers": headers}))

    assert not world.deliveries.deliveries


class FailingOnce:
    """An ``AutoSyncStore`` with no schedule whose first read fails, as a locked database would.

    Or is cancelled there, as a request whose client went away is.
    """

    def __init__(self, error: BaseException) -> None:
        self.error: BaseException | None = error

    async def get(self, library: str) -> AutoSync | None:
        del library
        if self.error is not None:
            error, self.error = self.error, None
            raise error
        return None

    async def save(self, auto_sync: AutoSync) -> None:
        raise NotImplementedError

    async def record_check(self, read: AutoSync, checked: AutoSync) -> bool:
        raise NotImplementedError

    async def delete(self, library: str) -> None:
        raise NotImplementedError

    async def list_all(self) -> list[AutoSync]:
        return []


@pytest.mark.parametrize(
    "error", [RuntimeError("database is locked"), asyncio.CancelledError()], ids=type
)
async def test_a_delivery_that_could_not_be_queued_is_forgotten_for_the_retry(
    clock, error: BaseException
) -> None:
    jobs = InMemoryJobRepository()
    secrets = InMemoryWebhookSecrets()
    deliveries = InMemoryWebhookDeliveries()
    module = IngestionModule.build(
        jobs=jobs,
        clock=clock,
        remote=Remote(),
        library_ids=None,  # ty: ignore[invalid-argument-type]
        libraries=None,  # ty: ignore[invalid-argument-type]
        sources=InMemoryLibrarySources(
            sources={LIBRARY: SOURCE},
            versions={LIBRARY: [ImportedRef(ref="main", kind=RefKind.BRANCH, commit_sha=OLD)]},
        ),
        removals=NoRemovals(),
        index=NoIndex(),
        auto_syncs=FailingOnce(error),
        webhooks=secrets,
        webhook_deliveries=deliveries,
    )
    secret = (await module.set_webhook(WebhookQuery(library=LIBRARY))).secret

    with pytest.raises(type(error)):
        await module.receive_webhook(push(secret))
    assert not deliveries.deliveries

    assert (await module.receive_webhook(push(secret))).status == "queued"
    assert len(jobs.jobs) == 1


async def test_deliveries_are_remembered_per_forge(world: World) -> None:
    secret = await secret_of(world)
    await world.module.receive_webhook(push(secret, delivery="same"))
    raw = body({"ref": "refs/heads/next", "after": NEW})
    gitlab = ReceiveWebhookCommand(
        library=LIBRARY,
        headers={
            "X-Gitlab-Event": "Push Hook",
            "X-Gitlab-Token": secret,
            "Idempotency-Key": "same",
        },
        body=raw,
    )

    assert (await world.module.receive_webhook(gitlab)).status == "queued"


# ---------------------------------------------------------------- the push job


async def run_all(world: World) -> None:
    while await world.module.run_next_job():
        pass


async def test_the_push_job_syncs_the_pushed_branch_only(world: World) -> None:
    world.remote.heads.update(main=NEW, next=NEW)  # both moved; only main was pushed
    await world.module.receive_webhook(push(await secret_of(world)))

    assert await world.module.run_next_job()  # the push job

    (pushed,) = of_kind(world, PUSH_JOB)
    assert pushed.state is JobState.SUCCEEDED, pushed
    (refresh,) = of_kind(world, REFRESH_JOB)
    assert (refresh.version, refresh.commit_sha, refresh.state) == ("main", NEW, JobState.QUEUED)
    assert world.remote.listed == 1


async def test_the_push_handler_runs_inside_the_given_wrapper(world: World, clock) -> None:
    ran: list[tuple[JobKind, str]] = []

    def wrap(kind: JobKind, handler: JobHandler) -> JobHandler:
        async def wrapped(job: Job, progress: JobProgress, /) -> None:
            ran.append((kind, job.id))
            await handler(job, progress)

        return wrapped

    module = IngestionModule.build(
        jobs=world.jobs,
        clock=clock,
        remote=world.remote,
        library_ids=None,  # ty: ignore[invalid-argument-type]
        libraries=None,  # ty: ignore[invalid-argument-type]
        sources=InMemoryLibrarySources(
            sources={LIBRARY: SOURCE}, versions={LIBRARY: world.versions}
        ),
        removals=NoRemovals(),
        index=NoIndex(),
        handlers={IMPORT_JOB: _noop, REFRESH_JOB: _noop},
        webhooks=world.secrets,
        webhook_deliveries=world.deliveries,
        wrap_handler=wrap,
    )
    secret = (await module.set_webhook(WebhookQuery(library=LIBRARY))).secret
    await module.receive_webhook(push(secret))

    assert await module.run_next_job()

    (pushed,) = of_kind(world, PUSH_JOB)
    assert ran == [(PUSH_JOB, pushed.id)]
    assert pushed.state is JobState.SUCCEEDED


async def test_a_push_of_a_branch_that_did_not_move_queues_nothing(world: World) -> None:
    await world.module.receive_webhook(push(await secret_of(world)))

    await run_all(world)

    assert [j.kind for j in world.jobs.jobs.values()] == [PUSH_JOB]


async def test_a_deleted_branch_records_ref_deleted_on_its_version(world: World) -> None:
    del world.remote.heads["main"]
    secret = await secret_of(world)
    raw = body({"ref": "refs/heads/main", "deleted": True})
    headers = {**github(), "X-Hub-Signature-256": signed(raw, secret)}
    await world.module.receive_webhook(
        ReceiveWebhookCommand(library=LIBRARY, headers=headers, body=raw)
    )

    await run_all(world)

    (recorded,) = of_kind(world, REFRESH_JOB)
    assert (recorded.version, recorded.state, recorded.error_code) == (
        "main",
        JobState.FAILED,
        SyncErrorCode.REF_DELETED,
    )
    assert of_kind(world, PUSH_JOB)[0].state is JobState.SUCCEEDED


async def test_a_pushed_tag_queues_the_auto_import_without_recording_a_check(world: World) -> None:
    schedule = AutoSync(library=LIBRARY, tag_pattern="v*", keep_last=3, revision="r1")
    await world.schedules.save(schedule)
    world.remote.tags["v2.1.0"] = TAG_SHA
    world.remote.tags["release-1"] = TAG_SHA
    secret = await secret_of(world)
    raw = body({"object_kind": "tag_push", "ref": "refs/tags/v2.1.0", "after": TAG_SHA})
    gitlab = ReceiveWebhookCommand(
        library=LIBRARY,
        headers={
            "X-Gitlab-Event": "Tag Push Hook",
            "X-Gitlab-Token": secret,
            "X-Gitlab-Event-UUID": "u",
        },
        body=raw,
    )

    receipt = await world.module.receive_webhook(gitlab)
    assert receipt.status == "queued"
    (pushed,) = of_kind(world, PUSH_JOB)
    assert (pushed.version, pushed.ref_kind) == ("v2.1.0", RefKind.TAG)
    assert await world.module.run_next_job()

    imports = of_kind(world, IMPORT_JOB)
    assert [(j.version, j.origin, j.commit_sha, j.ref_kind) for j in imports] == [
        ("v2.1.0", VersionOrigin.AUTO, TAG_SHA, RefKind.TAG)
    ]
    assert await world.schedules.get(LIBRARY) == schedule  # checked_at did not move


async def test_a_tag_push_after_auto_import_was_turned_off_does_nothing(world: World) -> None:
    await world.schedules.save(AutoSync(library=LIBRARY, tag_pattern="v*"))
    world.remote.tags["v2.1.0"] = TAG_SHA
    secret = await secret_of(world)
    await world.module.receive_webhook(push(secret, "refs/tags/v2.1.0"))
    await world.schedules.delete(LIBRARY)

    await run_all(world)

    assert [j.kind for j in world.jobs.jobs.values()] == [PUSH_JOB]
    assert world.remote.listed == 0


async def test_the_scheduled_check_still_imports_tags_through_the_shared_part(
    world: World,
) -> None:
    await world.schedules.save(AutoSync(library=LIBRARY, tag_pattern="v*"))
    world.remote.tags["v2.1.0"] = TAG_SHA

    checks = await world.module.run_scheduled_checks()

    assert checks.checked == [LIBRARY]
    assert [j.version for j in of_kind(world, IMPORT_JOB)] == ["v2.1.0"]
    stored = await world.schedules.get(LIBRARY)
    assert stored is not None
    assert isinstance(stored.checked_at, datetime)
