"""Constants that repeat enum values by hand stay in step with their enums."""

from exactdocs.ingestion.constants import (
    ACTIVE_JOB_STATES,
    CHANGE_JOBS,
    CHECKED_KINDS,
    KNOWN_HOSTS,
    LEGACY_CODES,
)
from exactdocs.ingestion.models import (
    JobState,
    ProblemCode,
    RefKind,
    RepositoryHost,
    SettingsChange,
)
from exactdocs.retrieval.constants import TAG_CONDITIONS
from exactdocs.retrieval.models import TagMatch


def test_active_job_states_are_the_unfinished_states() -> None:
    assert {JobState.QUEUED, JobState.RUNNING} == ACTIVE_JOB_STATES


def test_a_sync_checks_branches_and_tags() -> None:
    assert {RefKind.BRANCH, RefKind.TAG} == CHECKED_KINDS


def test_known_hosts_name_repository_hosts() -> None:
    assert {RepositoryHost(host) for host in KNOWN_HOSTS.values()} <= set(RepositoryHost)


def test_legacy_codes_are_problem_codes() -> None:
    assert {ProblemCode(code) for code in LEGACY_CODES.values()} <= set(ProblemCode)


def test_every_settings_change_has_its_job() -> None:
    assert set(CHANGE_JOBS) == set(SettingsChange)


def test_every_tag_match_has_its_condition() -> None:
    assert set(TAG_CONDITIONS) == {None, *TagMatch}
