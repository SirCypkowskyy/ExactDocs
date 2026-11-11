"""Encryption at rest: the secret key, the key file and the encrypted vault."""

import errno
import logging
import os
import stat
import subprocess  # ruff: ignore[suspicious-subprocess-import]
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from pydantic import SecretStr
from sqlalchemy import text

from databases import SQL_BACKENDS
from exactdocs.bootstrap import secret_box
from exactdocs.bootstrap.constants import CREDENTIALS_KEY_PURPOSE as CREDENTIALS
from exactdocs.bootstrap.constants import HYDE_CACHE_PURPOSE, KEY_FILE
from exactdocs.bootstrap.container import Container, _hyde_cache_key
from exactdocs.bootstrap.database import StartupError, migrate, open_database
from exactdocs.bootstrap.secret_box import FernetSecretBox, derived_key
from exactdocs.bootstrap.settings import Settings
from exactdocs.ingestion.adapters.driven.known_hosts import seed_known_hosts
from exactdocs.ingestion.adapters.driven.memory import InMemoryCredentialVault
from exactdocs.ingestion.adapters.driven.sqlite import SqliteCredentialVault
from exactdocs.ingestion.constants import PINNED
from exactdocs.ingestion.errors import CredentialsRequiredError
from exactdocs.ingestion.models import AccessToken, DeployKey
from exactdocs.ingestion.ports import CredentialVault
from exactdocs_kernel import SealedTextUnreadableError

SECRET = "k" * 40
SCOPE = "https://git.example.com"
TOKEN = "ghp_s3cretvalue"
KEY = "-----BEGIN OPENSSH PRIVATE KEY-----\nQmFkZ2VyS2V5Qm9keQ\n-----END OPENSSH PRIVATE KEY-----"
# `AccessToken(token=TOKEN)` for "/a/b" at SCOPE, sealed with SECRET by the box while it still
# lived in `ingestion/adapters/driven/secret_box.py` (#248): moving it must not change the format.
SEALED_BEFORE_THE_MOVE = (
    "gAAAAABq7yxHapAXhys2EiIKLC_CyR-4NhnfJaQ1rBFmRTyGBYfJtcw7j-2qQQJwoTfFuEJ8tlXI6KDw6yofK0cA950a"
    "pkQK2D8Ofs4rTnpa890rpi0l3O3yunVN6DwEyaWnmcQVK3alH725Q6TDBuxzNuDsgG_FAthItDoq3BgrYMJfEFK11FnB"
    "l5JcWqaSFBy0DyFeXhSngO2D4ltGfLa_FRvBLAcztE6vH6oH2N71s8qwJJaBnqlOE15bVoQh-GCa2VVB9HJc"
)
SECRET_ONLY = FernetSecretBox.from_secret(SECRET, purpose=CREDENTIALS)
WITH_A_NEWER_KEY = FernetSecretBox.from_secrets("n" * 40, SECRET, purpose=CREDENTIALS)


def test_a_sealed_text_opens_with_the_same_key_only() -> None:
    box = FernetSecretBox.from_secret(SECRET, purpose=CREDENTIALS)

    sealed = box.seal(TOKEN)

    assert TOKEN not in sealed
    assert box.open(sealed) == TOKEN
    assert FernetSecretBox.from_secret(SECRET, purpose=CREDENTIALS).open(sealed) == TOKEN
    with pytest.raises(SealedTextUnreadableError):
        FernetSecretBox.from_secret("z" * 40, purpose=CREDENTIALS).open(sealed)
    with pytest.raises(SealedTextUnreadableError):
        box.open(sealed[:-4] + "AAAA")  # tampered
    assert TOKEN not in repr(box)


def test_a_short_secret_key_is_refused_without_echoing_it() -> None:
    with pytest.raises(ValueError, match="at least 32") as raised:
        FernetSecretBox.from_secret("short", purpose=CREDENTIALS)
    assert "short" not in str(raised.value).replace("at least 32 characters", "")
    assert Settings(secret_key="short").secret_key is not None  # judged at startup, see below
    assert Settings(secret_key="  ").secret_key is None
    assert SECRET not in repr(Settings(secret_key=SECRET))


def test_a_missing_key_file_is_generated_with_mode_0600_and_reused(tmp_path: Path) -> None:
    path = tmp_path / "data" / "secret.key"

    first = FernetSecretBox.from_file(path, purpose=CREDENTIALS)

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert not list(path.parent.glob("*.tmp"))
    assert FernetSecretBox.from_file(path, purpose=CREDENTIALS).open(first.seal(TOKEN)) == TOKEN


def test_a_key_file_that_others_could_read_is_restricted(tmp_path: Path) -> None:
    path = tmp_path / "secret.key"
    FernetSecretBox.from_file(path, purpose=CREDENTIALS)
    path.chmod(0o644)

    FernetSecretBox.from_file(path, purpose=CREDENTIALS)

    assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.fixture(params=["memory", *SQL_BACKENDS])
async def vault(request: pytest.FixtureRequest) -> AsyncIterator[CredentialVault]:
    if request.param == "memory":
        yield InMemoryCredentialVault()
        return
    if request.param == "postgres":
        request.getfixturevalue("on_postgres")
    engine = open_database(Settings())
    await migrate(engine)
    yield SqliteCredentialVault(
        engine=engine, box=FernetSecretBox.from_secret(SECRET, purpose=CREDENTIALS)
    )
    await engine.dispose()


async def test_the_vault_round_trips_and_forgets(vault: CredentialVault) -> None:
    assert await vault.load("/a/b", SCOPE) is None
    await vault.save("/a/b", SCOPE, AccessToken(token=TOKEN, username="bot"))
    await vault.save("/c/d", SCOPE, DeployKey(private_key=KEY))

    assert await vault.load("/a/b", SCOPE) == AccessToken(token=TOKEN, username="bot")
    assert await vault.load("/c/d", SCOPE) == DeployKey(private_key=KEY + "\n")
    await vault.save("/a/b", SCOPE, AccessToken(token="other-" + TOKEN))
    assert await vault.load("/a/b", SCOPE) == AccessToken(token="other-" + TOKEN)
    assert await vault.has("/a/b")
    assert await vault.has("/c/d")
    assert not await vault.has("/e/f")
    assert not await vault.has("/A/B")  # keys are the canonical lower-case IDs
    await vault.delete("/a/b")
    await vault.delete("/a/b")
    assert await vault.load("/a/b", SCOPE) is None
    assert not await vault.has("/a/b")


async def test_the_database_holds_no_plaintext_and_a_new_key_cannot_read_it() -> None:
    engine = open_database(Settings())
    await migrate(engine)
    vault = SqliteCredentialVault(
        engine=engine, box=FernetSecretBox.from_secret(SECRET, purpose=CREDENTIALS)
    )
    await vault.save("/a/b", SCOPE, AccessToken(token=TOKEN))
    await vault.save("/c/d", SCOPE, DeployKey(private_key=KEY))

    async with engine.connect() as connection:
        rows = (
            await connection.execute(
                text("SELECT library, sealed FROM ingestion_library_credentials")
            )
        ).all()
    assert {r.library for r in rows} == {"/a/b", "/c/d"}
    assert all(TOKEN not in r.sealed and "QmFkZ2VyS2V5" not in r.sealed for r in rows)
    other = SqliteCredentialVault(
        engine=engine, box=FernetSecretBox.from_secret("z" * 40, purpose=CREDENTIALS)
    )
    with pytest.raises(CredentialsRequiredError):
        await other.load("/a/b", SCOPE)
    # a row copied to another library is not accepted either
    async with engine.begin() as connection:
        await connection.execute(
            text("UPDATE ingestion_library_credentials SET library = '/x/y' WHERE library = '/a/b'")
        )
    with pytest.raises(CredentialsRequiredError):
        await vault.load("/x/y", SCOPE)
    await engine.dispose()


# Published fingerprints (GitHub, GitLab and Bitbucket docs): a typo in the pinned keys shows here.
FINGERPRINTS = {
    "github.com": {
        "SHA256:+DiY3wvvV6TuJJhbpZisF/zLDA0zPMSvHdkr4UvCOqU",
        "SHA256:p2QAMXNIC1TJYWeIOttrVc98/R1BUFWu3/LiyKgUfQM",
        "SHA256:uNiVztksCsDhcc0u9e8BujQXVUpKZIDTMczCvj3tD2s",
    },
    "gitlab.com": {
        "SHA256:eUXGGm1YGsMAS7vkcx6JOJdOGHPem5gQp4taiCfCLB8",
        "SHA256:HbW3g8zUjNSksFbqTiUWPWg2Bq1x8xdGUrliXFzSnUw",
        "SHA256:ROQFvPThGrW4RuWLoL9tq9I9zJ42fK4XywyRtbOz/EQ",
    },
    "bitbucket.org": {
        "SHA256:ybgmFkzwOSotHTHLJgHO0QN8L0xErw6vd0VhFA9m3SM",
        "SHA256:FC73VB6C4OQLSCrjEayhMp9UMxS97caD/Yyi2bhW/J0",
        "SHA256:46OSHA1Rmj8E8ERTC6xkNcmGOw9oFxYr0WF6zWW8l1E",
    },
}


def test_the_big_three_hosts_are_pinned_with_their_published_keys(tmp_path: Path) -> None:
    known = tmp_path / "data" / "known_hosts"

    seed_known_hosts(known)

    assert stat.S_IMODE(known.stat().st_mode) == 0o600
    for host, expected in FINGERPRINTS.items():
        out = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
            ["ssh-keygen", "-l", "-F", host, "-f", str(known)],  # ruff: ignore[start-process-with-partial-path]
            capture_output=True, text=True, check=True,
        ).stdout  # fmt: skip
        found = {
            part for line in out.splitlines() for part in line.split() if part.startswith("SHA256:")
        }
        assert found == expected, host
    assert {line.split()[0] for line in PINNED} == {
        "github.com", "ssh.github.com", "[ssh.github.com]:443",
        "gitlab.com", "bitbucket.org", "ssh.bitbucket.org",
    }  # fmt: skip


def test_seeding_is_idempotent_and_keeps_entries_ssh_added(tmp_path: Path) -> None:
    known = tmp_path / "known_hosts"
    known.write_text("git.example.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIMine")  # no newline

    seed_known_hosts(known)
    once = known.read_text()
    seed_known_hosts(known)

    assert known.read_text() == once
    assert once.splitlines()[0].startswith("git.example.com ")
    assert len(once.splitlines()) == 1 + len(PINNED)
    assert known.stat().st_size == len(once)


async def test_a_credential_is_only_opened_for_the_host_it_was_stored_for() -> None:
    engine = open_database(Settings())
    await migrate(engine)
    vault = SqliteCredentialVault(
        engine=engine, box=FernetSecretBox.from_secret(SECRET, purpose=CREDENTIALS)
    )
    await vault.save("/a/b", "https://github.com", AccessToken(token=TOKEN))

    assert await vault.load("/a/b", "https://github.com") == AccessToken(token=TOKEN)
    with pytest.raises(CredentialsRequiredError):
        await vault.load("/a/b", "https://evil.example.com")
    await engine.dispose()


def test_the_previous_key_still_opens_what_it_sealed() -> None:
    old = FernetSecretBox.from_secret("o" * 40, purpose=CREDENTIALS)
    new = FernetSecretBox.from_secrets("n" * 40, "o" * 40, purpose=CREDENTIALS)

    assert new.open(old.seal(TOKEN)) == TOKEN
    with pytest.raises(SealedTextUnreadableError):
        old.open(new.seal(TOKEN))  # sealed with the new key now
    with pytest.raises(SealedTextUnreadableError):
        FernetSecretBox.from_secrets("x" * 40, "y" * 40, purpose=CREDENTIALS).open(old.seal(TOKEN))


def test_a_text_sealed_for_one_purpose_does_not_open_for_another() -> None:
    credentials = FernetSecretBox.from_secret(SECRET, purpose=CREDENTIALS)
    other = FernetSecretBox.from_secret(SECRET, purpose=b"exactdocs another use v1")

    assert other.open(other.seal(TOKEN)) == TOKEN
    with pytest.raises(SealedTextUnreadableError):
        other.open(credentials.seal(TOKEN))
    with pytest.raises(SealedTextUnreadableError):
        credentials.open(other.seal(TOKEN))
    with pytest.raises(ValueError, match="purpose"):
        FernetSecretBox.from_secret(SECRET, purpose=b"")


def test_the_credentials_keep_the_context_they_were_always_sealed_with() -> None:
    # Changing it would make every stored credential unreadable (see the fixture below).
    assert CREDENTIALS == b"exactdocs credentials v1"


def test_the_secret_box_imports_no_domain() -> None:
    source = Path(secret_box.__file__).read_text("utf-8")
    domains = ("catalog", "identity", "ingestion", "retrieval")

    assert not [d for d in domains if f"exactdocs.{d}" in source]


@pytest.mark.parametrize("box", [SECRET_ONLY, WITH_A_NEWER_KEY], ids=["same key", "as previous"])
async def test_a_credential_sealed_before_the_box_moved_to_bootstrap_still_opens(
    box: FernetSecretBox,
) -> None:
    engine = open_database(Settings())
    await migrate(engine)
    async with engine.begin() as connection:
        await connection.execute(
            text("INSERT INTO ingestion_library_credentials (library, sealed) VALUES (:l, :s)"),
            {"l": "/a/b", "s": SEALED_BEFORE_THE_MOVE},
        )
    vault = SqliteCredentialVault(engine=engine, box=box)

    assert await vault.load("/a/b", SCOPE) == AccessToken(token=TOKEN)
    await engine.dispose()


def test_a_short_key_never_appears_in_the_startup_error(tmp_path: Path) -> None:
    short = "S3cretOfTwentyFiveChars!!"
    settings = Settings(data_dir=tmp_path / "d", secret_key=SecretStr(short))

    with pytest.raises(StartupError) as raised:
        Container.build(settings)

    assert short not in str(raised.value)
    assert short not in repr(raised.value)
    with pytest.raises(StartupError) as previous:
        Container.build(
            Settings(
                data_dir=tmp_path / "e",
                secret_key=SecretStr(SECRET),
                secret_key_previous=SecretStr(short),
            )
        )
    assert short not in str(previous.value)


def test_a_key_file_that_is_a_symlink_is_refused(tmp_path: Path) -> None:
    real = tmp_path / "real.key"
    real.write_text("r" * 48 + "\n")
    real.chmod(0o600)
    link = tmp_path / "secret.key"
    link.symlink_to(real)

    with pytest.raises(ValueError, match="not a link"):
        FernetSecretBox.from_file(link, purpose=CREDENTIALS)


def test_a_key_file_of_another_user_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "secret.key"
    FernetSecretBox.from_file(path, purpose=CREDENTIALS)
    monkeypatch.setattr(os, "getuid", lambda: path.stat().st_uid + 1)

    with pytest.raises(ValueError, match="another user"):
        FernetSecretBox.from_file(path, purpose=CREDENTIALS)


def test_a_loosened_key_file_is_logged_as_an_exposed_key(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    path = tmp_path / "secret.key"
    FernetSecretBox.from_file(path, purpose=CREDENTIALS)
    path.chmod(0o640)

    FernetSecretBox.from_file(path, purpose=CREDENTIALS)

    (record,) = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert "exposed" in record.message
    assert "rotate" in record.message
    assert path.read_text().strip() not in caplog.text


def test_a_volume_without_hard_links_still_gets_its_key_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_links(src: object, dst: object) -> None:
        del src, dst
        raise OSError(errno.EPERM, "Operation not permitted")

    monkeypatch.setattr(os, "link", no_links)
    path = tmp_path / "secret.key"

    box = FernetSecretBox.from_file(path, purpose=CREDENTIALS)

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert not list(tmp_path.glob("*.tmp"))
    assert FernetSecretBox.from_file(path, purpose=CREDENTIALS).open(box.seal(TOKEN)) == TOKEN


def test_a_short_key_file_names_the_file(tmp_path: Path) -> None:
    path = tmp_path / "secret.key"
    path.write_text("short\n")
    path.chmod(0o600)

    with pytest.raises(ValueError, match=r"secret\.key") as raised:
        FernetSecretBox.from_file(path, purpose=CREDENTIALS)

    assert "short\n" not in str(raised.value).replace("too short", "")


def test_the_alternative_names_of_github_and_bitbucket_are_pinned(tmp_path: Path) -> None:
    known = tmp_path / "known_hosts"
    seed_known_hosts(known)

    for name, fingerprint in (
        ("ssh.github.com", "SHA256:+DiY3wvvV6TuJJhbpZisF/zLDA0zPMSvHdkr4UvCOqU"),
        ("[ssh.github.com]:443", "SHA256:+DiY3wvvV6TuJJhbpZisF/zLDA0zPMSvHdkr4UvCOqU"),
        ("ssh.bitbucket.org", "SHA256:ybgmFkzwOSotHTHLJgHO0QN8L0xErw6vd0VhFA9m3SM"),
    ):
        out = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
            ["ssh-keygen", "-l", "-F", name, "-f", str(known)],  # ruff: ignore[start-process-with-partial-path]
            capture_output=True, text=True, check=True,
        ).stdout  # fmt: skip
        assert fingerprint in out, name


def test_the_hyde_cache_key_is_derived_for_its_own_purpose_and_never_created_read_only(
    tmp_path: Path,
) -> None:
    secret = "s" * 40
    keyed = Settings(data_dir=tmp_path / "a", secret_key=SecretStr(secret))
    assert _hyde_cache_key(keyed, create=False) == derived_key(secret, HYDE_CACHE_PURPOSE)
    assert derived_key(secret, HYDE_CACHE_PURPOSE) != derived_key(secret, CREDENTIALS)

    fresh = Settings(data_dir=tmp_path / "b")
    assert _hyde_cache_key(fresh, create=False) is None  # a read-only process creates no key
    assert not (tmp_path / "b" / KEY_FILE).exists()
    created = _hyde_cache_key(fresh, create=True)
    assert created is not None
    assert _hyde_cache_key(fresh, create=False) == created
