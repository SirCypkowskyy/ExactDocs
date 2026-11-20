import copy
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Self, cast

from exactdocs.ingestion.constants import ACTIVE_JOB_STATES, IMPORT_KINDS, PUSH_JOB
from exactdocs.ingestion.errors import (
    CredentialsRequiredError,
    PushQueuedError,
    VersionImportingError,
)
from exactdocs.ingestion.models import (
    ArticleChunk,
    AutoSync,
    CopiedVersion,
    Credential,
    GitRename,
    ImportedRef,
    ImportedTags,
    ImportedVersion,
    ImportSource,
    Job,
    JobFilter,
    JobId,
    JobState,
    Removed,
    StoredTags,
    Webhook,
    WebhookDelivery,
)
from exactdocs_kernel import NotFoundError, Sort, SortValue, is_after


@dataclass(frozen=True, slots=True, kw_only=True)
class InMemoryJobRepository:
    """Implements ``ports.driven.JobRepository``. For tests."""

    jobs: dict[JobId, Job] = field(default_factory=dict)
    """The stored jobs, by ID."""

    @classmethod
    def of(cls, jobs: Iterable[Job]) -> Self:
        """Create a repository pre-filled with ``jobs``.

        Args:
            jobs: The jobs to store.

        Returns:
            The repository.
        """
        return cls(jobs={job.id: job for job in jobs})

    async def add(self, job: Job) -> None:
        """Store a new job; a second unfinished import, or queued push, of one ref is refused.

        Args:
            job: The new job.

        Raises:
            VersionImportingError: ``job`` is an unfinished import of a ref that has one.
            PushQueuedError: ``job`` is a queued push of a ref that has one queued.
        """
        if job.kind in IMPORT_KINDS and job.state in ACTIVE_JOB_STATES and job.version:
            for other in self.jobs.values():
                same = (other.library, other.version) == (job.library, job.version)
                if same and other.kind in IMPORT_KINDS and other.state in ACTIVE_JOB_STATES:
                    raise VersionImportingError(job.library, job.version or "")
        if job.kind == PUSH_JOB and job.state is JobState.QUEUED:
            key = (job.library, job.version, job.ref_kind)
            for other in self.jobs.values():
                queued = other.kind == PUSH_JOB and other.state is JobState.QUEUED
                if queued and (other.library, other.version, other.ref_kind) == key:
                    raise PushQueuedError(job.library, job.version or "", job.ref_kind or "ref")
        self.jobs[job.id] = job

    async def save(self, job: Job) -> None:
        """Replace the stored job that has the same ID.

        Args:
            job: The job as it is now.
        """
        self.jobs[job.id] = job

    async def get(self, job_id: JobId) -> Job | None:
        """Return the job, or ``None``.

        Args:
            job_id: The job's ID.

        Returns:
            The job, or ``None``.
        """
        return self.jobs.get(job_id)

    async def list_for_library(self, library: str) -> Sequence[Job]:
        """Return the library's jobs, newest first (job IDs are time-ordered).

        Args:
            library: The library ID.

        Returns:
            Every job of the library.
        """
        mine = [job for job in self.jobs.values() if job.library == library]
        return sorted(mine, key=lambda job: job.id, reverse=True)

    async def list_unfinished_for_library(self, library: str) -> Sequence[Job]:
        """Return the library's ``queued`` and ``running`` jobs, newest first.

        Args:
            library: The library ID.

        Returns:
            The library's unfinished jobs, highest ID first.
        """
        mine = [
            job
            for job in self.jobs.values()
            if job.library == library and job.state in ACTIVE_JOB_STATES
        ]
        return sorted(mine, key=lambda job: job.id, reverse=True)

    async def list_page_for_library(
        self, library: str, *, before: str | None, limit: int
    ) -> Sequence[Job]:
        """Return up to ``limit`` of the library's jobs with an ID below ``before``, newest first.

        Args:
            library: The library whose jobs are listed.
            before: Only jobs whose ID sorts before this one; ``None`` starts at the newest.
            limit: At most this many jobs.

        Returns:
            The page, highest ID first.
        """
        mine = [
            job
            for job in self.jobs.values()
            if job.library == library and (before is None or job.id < before)
        ]
        return sorted(mine, key=lambda job: job.id, reverse=True)[:limit]

    def _matching(self, job_filter: JobFilter) -> list[Job]:
        """Return the jobs that pass the filter, in no particular order.

        Args:
            job_filter: Which jobs.

        Returns:
            The matching jobs.
        """
        needle = job_filter.text.lower() if job_filter.text else None
        floor = job_filter.created_after
        ceiling = job_filter.created_before
        return [
            job
            for job in self.jobs.values()
            if (job_filter.libraries is None or job.library in job_filter.libraries)
            and (not job_filter.states or job.state in job_filter.states)
            and (not job_filter.kinds or job.kind in job_filter.kinds)
            and (job_filter.version is None or job.version == job_filter.version)
            and (floor is None or job.created_at >= floor)
            and (ceiling is None or job.created_at < ceiling)
            and (
                needle is None
                or any(
                    needle in (text or "").lower() for text in (job.version, job.library, job.error)
                )
            )
        ]

    async def search(
        self,
        job_filter: JobFilter,
        *,
        sort: Sort,
        after: tuple[SortValue, str] | None,
        limit: int,
    ) -> Sequence[Job]:
        """Return up to ``limit`` of the jobs that pass the filter, in ``sort`` order.

        Args:
            job_filter: Which jobs.
            sort: The order.
            after: The sort value and ID of the last job of the previous page.
            limit: At most this many jobs.

        Returns:
            The jobs in order.
        """

        def value(job: Job) -> SortValue:
            """Return the job's value of the sort field.

            Args:
                job: The job.

            Returns:
                The ID, the stored form of the creation time, the state, the kind or the library.
            """
            return {
                "id": job.id,
                "created_at": job.created_at.isoformat(timespec="microseconds"),
                "state": job.state.value,
                "kind": job.kind,
                "library": job.library,
            }[sort.field]

        ordered = sorted(
            self._matching(job_filter), key=lambda j: (value(j), j.id), reverse=sort.descending
        )
        if after is not None:
            ordered = [j for j in ordered if is_after((value(j), j.id), after, sort=sort)]
        return ordered[:limit]

    async def count(self, job_filter: JobFilter) -> int:
        """Count the jobs that pass the filter.

        Args:
            job_filter: Which jobs.

        Returns:
            How many there are.
        """
        return len(self._matching(job_filter))

    async def libraries(self) -> Sequence[str]:
        """Return every library that has a job, as spelled in the jobs.

        Returns:
            The distinct library IDs.
        """
        return sorted({job.library for job in self.jobs.values()})

    async def list_latest(self) -> Sequence[Job]:
        """Return the newest job of every (library, version), ordered by library and version.

        ``push`` jobs are left out: they name a ref but say nothing about how its version fared.

        Returns:
            One job per pair; the jobs without a version count as one pair per library.
        """
        newest: dict[tuple[str, str | None], Job] = {}
        for job in sorted(self.jobs.values(), key=lambda job: job.id):
            if job.kind != PUSH_JOB:  # names a ref, says nothing about how the version fared
                newest[job.library, job.version] = job
        return sorted(newest.values(), key=lambda job: (job.library, job.version or ""))

    async def delete_for(self, library: str, version: str | None = None) -> None:
        """Delete the library's jobs (only those of ``version`` when given), never a running one.

        Args:
            library: The library ID.
            version: Only the jobs of this ref; ``None`` deletes every job of the library.
        """
        for job in list(self.jobs.values()):
            if (
                job.library == library
                and job.state is not JobState.RUNNING
                and (version is None or job.version == version)
            ):
                del self.jobs[job.id]

    async def list_running(self) -> Sequence[Job]:
        """Return every job in the ``running`` state.

        Returns:
            The running jobs.
        """
        return [job for job in self.jobs.values() if job.state is JobState.RUNNING]

    async def list_queued(self) -> Sequence[Job]:
        """Return every job in the ``queued`` state, oldest first.

        Returns:
            The queued jobs.
        """
        waiting = [job for job in self.jobs.values() if job.state is JobState.QUEUED]
        return sorted(waiting, key=lambda job: (job.created_at, job.id))

    async def claim_next(self, now: datetime) -> Job | None:
        """Atomically start the oldest queued job whose library has no running job.

        Args:
            now: The time recorded as the job's ``started_at``.

        Returns:
            The started job, or ``None`` when no queued job may start.
        """
        busy = {job.library for job in self.jobs.values() if job.state is JobState.RUNNING}
        waiting = [job for job in self.jobs.values() if job.state is JobState.QUEUED]
        for job in sorted(waiting, key=lambda job: (job.created_at, job.id)):
            if job.library not in busy:
                started = job.started(now)
                self.jobs[job.id] = started
                return started
        return None


@dataclass(frozen=True, slots=True, kw_only=True)
class InMemoryLibrarySources:
    """Implements ``ports.driven.LibrarySources``. For tests."""

    sources: dict[str, ImportSource] = field(default_factory=dict)
    """Each library's source, by library ID."""
    versions: dict[str, list[ImportedRef]] = field(default_factory=dict)
    """Each library's imported versions, by library ID."""
    renames: dict[tuple[str, str], list[GitRename]] = field(default_factory=dict)
    """Each version's rename map, by (library ID, ref)."""

    async def renames_of(self, library: str, ref: str) -> Sequence[GitRename]:
        """Return the rename map of the version (empty when it has none).

        Args:
            library: The library ID.
            ref: The version's ref.

        Returns:
            The renames.
        """
        return self.renames.get((library, ref), [])

    async def imported_versions(self, library: str) -> Sequence[ImportedRef]:
        """Return the library's versions; raises ``NotFoundError`` if unknown.

        Args:
            library: The library ID.

        Returns:
            The versions.
        """
        await self.get(library)
        return self.versions.get(library, [])

    async def get(self, library: str) -> ImportSource:
        """Return the library's source; raises ``NotFoundError`` for an unknown library.

        Args:
            library: The library ID.

        Returns:
            The source.

        Raises:
            NotFoundError: The library has no source.
        """
        if library not in self.sources:
            message = f"library {library!r} not found"
            raise NotFoundError(message)
        return self.sources[library]


class NoRemovals:
    """Implements ``ports.driven.Removals``; any call is a test bug. For tests."""

    async def remove_version(self, library: str, ref: str) -> Removed:
        """Not expected to be called.

        Args:
            library: The library ID.
            ref: The version's ref.

        Returns:
            Nothing: it always raises.
        """
        raise NotImplementedError

    async def remove_library(self, library: str) -> Removed:
        """Not expected to be called.

        Args:
            library: The library ID.

        Returns:
            Nothing: it always raises.
        """
        raise NotImplementedError


class NoIndex:
    """Implements ``ports.driven.ChunkIndex``; any call is a test bug. For tests."""

    async def known(
        self, config_hash: str, blob_shas: Sequence[str]
    ) -> Mapping[str, tuple[ArticleChunk, ...]]:
        """Not expected to be called.

        Args:
            config_hash: The chunker's config hash.
            blob_shas: Blob SHAs.

        Returns:
            Nothing: it always raises.
        """
        raise NotImplementedError

    async def index(self, manifest_id: str, version: ImportedVersion) -> None:
        """Not expected to be called.

        Args:
            manifest_id: The pending manifest.
            version: The imported version.
        """
        raise NotImplementedError

    async def discard(self, *, manifest_id: str | None, library: str) -> None:
        """Not expected to be called.

        Args:
            manifest_id: The pending manifest, or ``None``.
            library: The library ID.
        """
        raise NotImplementedError

    async def remove(self, manifest_ids: Sequence[str]) -> None:
        """Not expected to be called.

        Args:
            manifest_ids: The deleted manifests.
        """
        raise NotImplementedError

    async def retag(self, manifest_id: str, tags: Mapping[str, tuple[str, ...]]) -> None:
        """Not expected to be called.

        Args:
            manifest_id: The manifest.
            tags: Tags by article path.
        """
        raise NotImplementedError


class NoCopier:
    """Implements ``ports.driven.VersionCopier``; any call is a test bug. For tests."""

    async def copy(self, library: str, ref: str, *, content_version: int) -> CopiedVersion | None:
        """Not expected to be called.

        Args:
            library: The library ID.
            ref: The version's ref.
            content_version: The parser version.

        Returns:
            Nothing: it always raises.
        """
        raise NotImplementedError


class NoStoredTags:
    """Implements ``ports.driven.ImportedTagStore``; any call is a test bug. For tests."""

    async def stored_tags(self, library: str, ref: str) -> StoredTags | None:
        """Not expected to be called.

        Args:
            library: The library ID.
            ref: The version's ref.

        Returns:
            Nothing: it always raises.
        """
        raise NotImplementedError

    async def set_imported_tags(
        self, manifest_id: str, tags: Mapping[str, ImportedTags]
    ) -> Mapping[str, tuple[str, ...]]:
        """Not expected to be called.

        Args:
            manifest_id: The manifest.
            tags: Imported tags with their sources, by article path.

        Returns:
            Nothing: it always raises.
        """
        raise NotImplementedError


@dataclass(frozen=True, slots=True, kw_only=True)
class InMemoryCredentialVault:
    """Implements ``ports.driven.CredentialVault``. For tests; nothing is encrypted."""

    credentials: dict[str, Credential] = field(default_factory=dict)
    """The stored credentials, by library ID, as given."""
    scopes: dict[str, str] = field(default_factory=dict)
    """Of the credentials saved through here."""

    async def save(self, library: str, scope: str, credential: Credential) -> None:
        """Store the library's credential.

        Args:
            library: The library ID.
            scope: Where the credential may be offered.
            credential: The token or deploy key.
        """
        self.credentials[library] = credential
        self.scopes[library] = scope

    async def load(self, library: str, scope: str) -> Credential | None:
        """Return the library's credential, or ``None``; one saved for another scope is refused.

        Args:
            library: The library ID.
            scope: The library's ``credential_scope`` now.

        Returns:
            The credential, or ``None``.

        Raises:
            CredentialsRequiredError: The credential was saved for another scope.
        """
        if self.scopes.get(library, scope) != scope:
            raise CredentialsRequiredError
        return self.credentials.get(library)

    async def delete(self, library: str) -> None:
        """Forget the library's credential.

        Args:
            library: The library ID.
        """
        self.credentials.pop(library, None)
        self.scopes.pop(library, None)

    async def has(self, library: str) -> bool:
        """Whether the library has a credential.

        Args:
            library: The library ID.

        Returns:
            True when one is stored.
        """
        return library in self.credentials


@dataclass(slots=True, kw_only=True)  # conventions: allow-mutable-dataclass -- replay position
class InMemoryCheckpoints:
    """``Checkpoints`` that keep the results of one job's completed steps, as DBOS does.

    ``resumed()`` returns the checkpoints of the next run of the same job: it replays the
    completed steps in order, then runs the rest. Results are copied, as a stored result would
    be, so nothing a later step changes reaches them.
    """

    completed: list[tuple[str, object]] = field(default_factory=list)
    """Name and result of each completed step, in order."""
    ran: list[str] = field(default_factory=list)
    """The steps that really ran (not replayed), in order."""
    _next: int = 0
    """Index of the next step to replay; past the end, steps run."""

    async def step[T](self, name: str, run: Callable[[], Awaitable[T]], /) -> T:
        """Replay the step if this job completed it before, else run and record it.

        Args:
            name: The step's name.
            run: Runs the step.

        Returns:
            A copy of the recorded result, or what ``run`` returned.

        Raises:
            AssertionError: The job took another step than on its earlier run.
        """
        if self._next < len(self.completed):
            recorded, result = self.completed[self._next]
            if recorded != name:
                message = f"step {self._next} was {recorded!r}, not {name!r}"
                raise AssertionError(message)
            self._next += 1
            # The step of this name recorded a T: a job takes the same steps on every run.
            return cast("T", copy.deepcopy(result))
        self.ran.append(name)
        value = await run()
        self.completed.append((name, copy.deepcopy(value)))
        self._next += 1
        return value

    def resumed(self) -> Self:
        """Return the checkpoints of the job's next run, after a crash.

        Returns:
            Checkpoints that replay the steps completed so far.
        """
        return type(self)(completed=list(self.completed))


@dataclass(frozen=True, slots=True, kw_only=True)
class InMemoryAutoSyncStore:
    """Implements ``ports.driven.AutoSyncStore``. For tests."""

    schedules: dict[str, AutoSync] = field(default_factory=dict)
    """The stored schedules, by library ID."""

    async def get(self, library: str) -> AutoSync | None:
        """Return the library's schedule, or ``None``.

        Args:
            library: The library ID.

        Returns:
            The schedule, or ``None``.
        """
        return self.schedules.get(library)

    async def save(self, auto_sync: AutoSync) -> None:
        """Store the schedule.

        Args:
            auto_sync: The schedule.
        """
        self.schedules[auto_sync.library] = auto_sync

    async def delete(self, library: str) -> None:
        """Forget the library's schedule.

        Args:
            library: The library ID.
        """
        self.schedules.pop(library, None)

    async def record_check(self, read: AutoSync, checked: AutoSync) -> bool:
        """Store the check if the schedule is still the one it read.

        Args:
            read: The schedule as the check read it.
            checked: The same schedule with the check's result.

        Returns:
            True when it was stored.
        """
        stored = self.schedules.get(read.library)
        if stored is None or (stored.revision, stored.checked_at) != (
            read.revision,
            read.checked_at,
        ):
            return False
        self.schedules[read.library] = checked
        return True

    async def list_all(self) -> Sequence[AutoSync]:
        """Return every schedule, by library.

        Returns:
            The schedules.
        """
        return [self.schedules[k] for k in sorted(self.schedules)]


@dataclass(frozen=True, slots=True, kw_only=True)
class InMemoryWebhookSecrets:
    """Implements ``ports.driven.WebhookSecrets``. For tests; nothing is sealed."""

    webhooks: dict[str, Webhook] = field(default_factory=dict)
    """The stored webhooks, by library ID."""

    async def save(self, webhook: Webhook) -> None:
        """Store the webhook, replacing the library's earlier one.

        Args:
            webhook: The webhook.
        """
        self.webhooks[webhook.library] = webhook

    async def get(self, library: str) -> Webhook | None:
        """Return the library's webhook, or ``None``.

        Args:
            library: The library ID.

        Returns:
            The webhook, or ``None``.
        """
        return self.webhooks.get(library)

    async def created_at(self, library: str) -> datetime | None:
        """Say when the library's webhook was created.

        Args:
            library: The library ID.

        Returns:
            When, or ``None`` without one.
        """
        found = self.webhooks.get(library)
        return None if found is None else found.created_at

    async def delete(self, library: str) -> None:
        """Forget the library's webhook.

        Args:
            library: The library ID.
        """
        self.webhooks.pop(library, None)


@dataclass(frozen=True, slots=True, kw_only=True)
class InMemoryWebhookDeliveries:
    """Implements ``ports.driven.WebhookDeliveries``. For tests (one event loop: atomic)."""

    deliveries: dict[tuple[str, str, str], WebhookDelivery] = field(default_factory=dict)
    """The remembered deliveries, by (library, provider, delivery ID)."""

    async def record(self, delivery: WebhookDelivery, *, prune_before: datetime) -> bool:
        """Remember the delivery unless known, after forgetting the old ones.

        Args:
            delivery: The delivery.
            prune_before: Older deliveries are forgotten.

        Returns:
            True when it was not known.
        """
        for key, known in list(self.deliveries.items()):
            if known.received_at < prune_before:
                del self.deliveries[key]
        key = (delivery.library, delivery.provider.value, delivery.delivery_id)
        if key in self.deliveries:
            return False
        self.deliveries[key] = delivery
        return True

    async def forget(self, delivery: WebhookDelivery) -> None:
        """Forget the delivery.

        Args:
            delivery: The delivery.
        """
        self.deliveries.pop((delivery.library, delivery.provider.value, delivery.delivery_id), None)

    async def delete_for(self, library: str) -> None:
        """Forget every delivery of the library.

        Args:
            library: The library ID.
        """
        for key in [k for k in self.deliveries if k[0] == library]:
            del self.deliveries[key]
