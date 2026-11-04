"""Wiring of the ingestion domain: driven adapters in, driving ports out.

It does not pick adapters itself; the composition root (``exactdocs.bootstrap``) passes them in,
together with the job kinds it supports. The import use cases arrive with E3-05a.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Self

from exactdocs.ingestion.models import JobKind
from exactdocs.ingestion.ports.driven import JobHandler, JobRepository, RecoveryHook
from exactdocs.ingestion.ports.driving import (
    EnqueueJob,
    GetJob,
    ListLibraryJobs,
    RecoverJobs,
    RunNextJob,
)
from exactdocs.ingestion.use_cases import (
    EnqueueJobUseCase,
    GetJobUseCase,
    ListLibraryJobsUseCase,
    RecoverJobsUseCase,
    RunNextJobUseCase,
)
from exactdocs_kernel import Clock


@dataclass(frozen=True, slots=True, kw_only=True)
class IngestionModule:
    """The ingestion's driving ports, ready to be exposed by driving adapters."""

    enqueue_job: EnqueueJob
    get_job: GetJob
    list_library_jobs: ListLibraryJobs
    recover_jobs: RecoverJobs
    run_next_job: RunNextJob

    @classmethod
    def build(
        cls,
        *,
        jobs: JobRepository,
        clock: Clock,
        handlers: Mapping[JobKind, JobHandler] = MappingProxyType({}),
        recovery_hooks: Mapping[JobKind, RecoveryHook] = MappingProxyType({}),
    ) -> Self:
        """Assemble the use cases around the given driven adapters.

        ``handlers`` maps each job kind to what runs it; ``recovery_hooks`` maps a kind to its
        clean-up after an interrupted run (a kind without one needs none).
        """
        return cls(
            enqueue_job=EnqueueJobUseCase(jobs, clock, handlers),
            get_job=GetJobUseCase(jobs),
            list_library_jobs=ListLibraryJobsUseCase(jobs),
            recover_jobs=RecoverJobsUseCase(jobs, clock, recovery_hooks),
            run_next_job=RunNextJobUseCase(jobs, clock, handlers),
        )
