"""Credentials: validation, use cases and the vault (encryption: bootstrap/test_secret_box)."""

import asyncio
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from exactdocs.ingestion.adapters.driven.memory import (
    InMemoryCredentialVault,
    InMemoryJobRepository,
    InMemoryLibrarySources,
    NoIndex,
    NoRemovals,
)
from exactdocs.ingestion.constants import JobKind
from exactdocs.ingestion.dtos import (
    AccessTokenIn,
    AddLibraryCommand,
    AddVersionCommand,
    CheckRepositoryCommand,
    DeployKeyIn,
    GetLibraryAccessQuery,
)
from exactdocs.ingestion.errors import (
    CredentialsRequiredError,
    InvalidCredentialError,
    RepositoryAuthRequiredError,
    UnknownLibraryError,
)
from exactdocs.ingestion.models import (
    AccessToken,
    Credential,
    DeployKey,
    ImportSource,
    NewLibrary,
    PathSelection,
    RemoteRef,
    RemoteRefs,
    RepositoryUrl,
    check_credential_fits,
    dump_credential,
    load_credential,
)
from exactdocs.ingestion.module import IngestionModule
from exactdocs_kernel import SystemClock
from library_access import FakeAccess

KEY = "-----BEGIN OPENSSH PRIVATE KEY-----\nAAAA\n-----END OPENSSH PRIVATE KEY-----"
TOKEN = "ghp_s3cretvalue"
HEAD = "a" * 40
SCOPE = "https://git.example.com"
REFS = RemoteRefs(default_branch="main", refs=(RemoteRef(name="refs/heads/main", sha=HEAD),))


def test_a_token_and_a_key_are_validated_and_never_shown() -> None:
    assert TOKEN not in repr(AccessToken(token=TOKEN))
    assert "AAAA" not in repr(DeployKey(private_key=KEY))
    assert DeployKey(private_key=KEY.replace("\n", "\r\n")).private_key == KEY + "\n"
    assert TOKEN not in repr(AccessTokenIn(kind="token", token=TOKEN))
    for bad in ("", "two\nlines", " padded ", "x" * 5000):
        with pytest.raises(InvalidCredentialError) as raised:
            AccessToken(token=bad)
        assert bad.strip() not in str(raised.value) or not bad.strip()
    with pytest.raises(InvalidCredentialError):
        AccessToken(token=TOKEN, username="a b")
    for bad in ("", "not a key", KEY.replace("OPENSSH", "ENCRYPTED PRIVATE KEY", 1)):
        with pytest.raises(InvalidCredentialError):
            DeployKey(private_key=bad)


async def _keygen(tmp_path: Path, name: str, *args: str) -> str:
    """A throwaway private key made by the real ssh-keygen."""
    keygen = shutil.which("ssh-keygen")
    if keygen is None:
        pytest.skip("needs OpenSSH's ssh-keygen")
    key = tmp_path / name
    process = await asyncio.create_subprocess_exec(
        keygen, "-q", "-f", str(key), *args, stdin=asyncio.subprocess.DEVNULL
    )
    assert await process.wait() == 0
    return key.read_text(encoding="ascii")


@pytest.mark.parametrize(
    ("args", "passphrase"),
    [
        (("-t", "ed25519", "-N", ""), False),
        (("-t", "ed25519", "-N", "pass phrase"), True),
        (("-t", "rsa", "-b", "2048", "-m", "PEM", "-N", ""), False),
        (("-t", "rsa", "-b", "2048", "-m", "PEM", "-N", "pass phrase"), True),
        (("-t", "ecdsa", "-m", "PKCS8", "-N", ""), False),
        (("-t", "ecdsa", "-m", "PKCS8", "-N", "pass phrase"), True),
    ],
)
async def test_a_deploy_key_with_a_passphrase_is_refused_with_words_that_say_so(
    tmp_path: Path, args: tuple[str, ...], passphrase: bool
) -> None:
    key = await _keygen(tmp_path, "key", *args)

    if not passphrase:
        assert DeployKey(private_key=key).private_key == key
        return
    with pytest.raises(InvalidCredentialError, match="has a passphrase") as raised:
        DeployKey(private_key=key)
    body = key.splitlines()[2]
    assert body not in str(raised.value)


def test_a_deploy_key_sent_on_one_line_is_refused_naming_the_lost_line_breaks() -> None:
    flat = KEY.replace("\n", "")

    with pytest.raises(InvalidCredentialError, match="lost its line breaks") as raised:
        DeployKey(private_key=flat)

    assert "AAAA" not in str(raised.value)
    with pytest.raises(InvalidCredentialError, match="OpenSSH or PEM"):
        DeployKey(private_key="-----BEGIN OPENSSH PRIVATE KEY-----AAAA")  # no END: not a key


@pytest.mark.parametrize(
    ("url", "credential", "fits"),
    [
        ("https://github.com/acme/x", AccessToken(token=TOKEN), True),
        ("http://127.0.0.1:8000/acme/x.git", AccessToken(token=TOKEN), True),
        ("http://localhost/acme/x.git", AccessToken(token=TOKEN), True),
        ("http://git.example.com/acme/x.git", AccessToken(token=TOKEN), False),
        ("ssh://git@github.com/acme/x", AccessToken(token=TOKEN), False),
        ("file:///srv/acme/x", AccessToken(token=TOKEN), False),
        ("git@github.com:acme/x.git", DeployKey(private_key=KEY), True),
        ("ssh://git@host:2222/acme/x.git", DeployKey(private_key=KEY), True),
        ("https://github.com/acme/x", DeployKey(private_key=KEY), False),
    ],
)
def test_a_credential_must_suit_the_transport(url: str, credential: Credential, fits: bool) -> None:
    if fits:
        check_credential_fits(RepositoryUrl.parse(url), credential)
    else:
        with pytest.raises(InvalidCredentialError):
            check_credential_fits(RepositoryUrl.parse(url), credential)


def test_a_dumped_credential_is_that_librarys_only() -> None:
    dumped = dump_credential("/acme/x", SCOPE, AccessToken(token=TOKEN, username="bot"))

    assert load_credential("/acme/x", SCOPE, dumped) == AccessToken(token=TOKEN, username="bot")
    with pytest.raises(ValueError, match="/acme/y"):
        load_credential("/acme/y", SCOPE, dumped)
    assert load_credential(
        "/a/b", SCOPE, dump_credential("/a/b", SCOPE, DeployKey(private_key=KEY))
    ) == (DeployKey(private_key=KEY))


@dataclass
class FakeRemote:
    seen: list[Credential | None] = field(default_factory=list)
    error: Exception | None = None

    async def host_key_fingerprint(self, repository: RepositoryUrl) -> str | None:
        return "SHA256:abc" if repository.transport == "ssh" else None

    async def list_refs(
        self, repository: RepositoryUrl, *patterns: str, credential: Credential | None = None
    ) -> RemoteRefs:
        del repository, patterns
        self.seen.append(credential)
        if self.error:
            raise self.error
        return REFS


@dataclass
class Catalog:
    added: list[NewLibrary] = field(default_factory=list)
    discarded: list[str] = field(default_factory=list)
    known: set[str] = field(default_factory=set)

    async def is_taken(self, library_id: str) -> bool:
        return library_id in self.known

    async def add(self, library: NewLibrary) -> str:
        self.added.append(library)
        return library.library_id

    async def discard(self, library_id: str) -> None:
        self.discarded.append(library_id)


async def _run(job: object, progress: object, /) -> None: ...


class FailingVault(InMemoryCredentialVault):
    async def save(self, library: str, scope: str, credential: Credential) -> None:
        raise OSError(library, scope, credential)


class UnreadableVault(InMemoryCredentialVault):
    async def load(self, library: str, scope: str) -> Credential | None:
        del library, scope
        raise CredentialsRequiredError


def build(
    remote: FakeRemote,
    vault: InMemoryCredentialVault,
    catalog: Catalog | None = None,
    access: FakeAccess | None = None,
) -> IngestionModule:
    catalog = catalog or Catalog()
    source = ImportSource(
        url=RepositoryUrl.parse("https://git.example.com/acme/orders.git"),
        selection=PathSelection(),
    )
    return IngestionModule.build(
        jobs=InMemoryJobRepository(),
        clock=SystemClock(),
        remote=remote,
        library_ids=catalog,
        libraries=catalog,
        sources=InMemoryLibrarySources(sources={"/acme/orders": source}),
        vault=vault,
        removals=NoRemovals(),
        index=NoIndex(),
        handlers={JobKind("import"): _run},
        **({} if access is None else {"access": access}),
    )


async def test_a_new_library_stores_its_credential_and_reads_the_repository_with_it() -> None:
    remote, vault = FakeRemote(), InMemoryCredentialVault()
    command = AddLibraryCommand(
        url="https://github.com/acme/orders",
        credential=AccessTokenIn(kind="token", token=TOKEN),
    )

    added = await build(remote, vault).add_library(command)

    assert remote.seen == [AccessToken(token=TOKEN)]
    assert vault.credentials == {added.library_id: AccessToken(token=TOKEN)}
    assert TOKEN not in added.model_dump_json()


async def test_a_credential_that_does_not_suit_the_url_is_refused_before_any_contact() -> None:
    remote, vault = FakeRemote(), InMemoryCredentialVault()
    command = AddLibraryCommand(
        url="http://git.example.com/acme/orders.git",
        credential=AccessTokenIn(kind="token", token=TOKEN),
    )

    with pytest.raises(InvalidCredentialError):
        await build(remote, vault).add_library(command)

    assert remote.seen == [] == list(vault.credentials)


async def test_a_library_whose_credential_cannot_be_stored_is_not_left_behind() -> None:
    catalog = Catalog()
    command = AddLibraryCommand(
        url="git@github.com:acme/orders.git",
        credential=DeployKeyIn(kind="ssh_key", private_key=KEY),
    )

    with pytest.raises(OSError, match="/acme/orders"):
        await build(FakeRemote(), FailingVault(), catalog).add_library(command)

    assert catalog.discarded == ["/acme/orders"]


async def test_a_public_library_needs_no_credential() -> None:
    remote, vault = FakeRemote(), InMemoryCredentialVault()

    await build(remote, vault).add_library(AddLibraryCommand(url="https://github.com/acme/orders"))

    assert remote.seen == [None]
    assert vault.credentials == {}


async def test_check_offers_the_credential_and_reports_the_ssh_host_key() -> None:
    remote = FakeRemote()
    module = build(remote, InMemoryCredentialVault())

    checked = await module.check_repository(
        CheckRepositoryCommand(
            url="git@github.com:acme/orders.git",
            credential=DeployKeyIn(kind="ssh_key", private_key=KEY),
        )
    )

    assert remote.seen == [DeployKey(private_key=KEY + "\n")]
    assert checked.host_key_fingerprint == "SHA256:abc"
    assert KEY not in checked.model_dump_json()


async def test_adding_a_version_uses_the_stored_credential() -> None:
    remote = FakeRemote()
    vault = InMemoryCredentialVault(credentials={"/acme/orders": AccessToken(token=TOKEN)})

    await build(remote, vault).add_version(AddVersionCommand(library="/acme/orders", ref="main"))

    assert remote.seen == [AccessToken(token=TOKEN)]


async def test_adding_a_version_with_an_unreadable_credential_says_credentials_required() -> None:
    remote = FakeRemote()

    with pytest.raises(CredentialsRequiredError) as raised:
        await build(remote, UnreadableVault()).add_version(
            AddVersionCommand(library="/acme/orders", ref="main")
        )

    assert raised.value.code == "credentials_required"
    assert remote.seen == []


async def test_sending_the_credential_again_replaces_the_stored_one() -> None:
    remote = FakeRemote()
    vault = InMemoryCredentialVault(credentials={"/acme/orders": AccessToken(token="old-" + TOKEN)})
    command = AddVersionCommand(
        library="/acme/orders", ref="main", credential=AccessTokenIn(kind="token", token=TOKEN)
    )

    await build(remote, vault).add_version(command)

    assert remote.seen == [AccessToken(token=TOKEN)]
    assert vault.credentials["/acme/orders"] == AccessToken(token=TOKEN)


async def test_a_rejected_new_credential_does_not_replace_the_stored_one() -> None:
    old = AccessToken(token="old-" + TOKEN)
    vault = InMemoryCredentialVault(credentials={"/acme/orders": old})
    command = AddVersionCommand(
        library="/acme/orders", ref="main", credential=AccessTokenIn(kind="token", token=TOKEN)
    )

    with pytest.raises(RepositoryAuthRequiredError):
        await build(FakeRemote(error=RepositoryAuthRequiredError()), vault).add_version(command)

    assert vault.credentials["/acme/orders"] == old


async def test_re_adding_a_library_without_a_credential_forgets_the_old_one() -> None:
    vault = InMemoryCredentialVault(credentials={"/acme/orders": AccessToken(token="old-" + TOKEN)})

    await build(FakeRemote(), vault).add_library(
        AddLibraryCommand(url="https://other.example.com/acme/orders")
    )

    assert vault.credentials == {}


async def test_a_credential_stored_for_another_host_is_not_used() -> None:
    remote = FakeRemote()
    vault = InMemoryCredentialVault()
    await vault.save("/acme/orders", "https://github.com", AccessToken(token=TOKEN))
    # the library's source is https://git.example.com/acme/orders.git (see ``build``)

    with pytest.raises(CredentialsRequiredError):
        await build(remote, vault).add_version(
            AddVersionCommand(library="/acme/orders", ref="main")
        )

    assert remote.seen == []


async def test_a_new_library_stores_the_host_its_credential_is_for() -> None:
    vault = InMemoryCredentialVault()

    await build(FakeRemote(), vault).add_library(
        AddLibraryCommand(
            url="https://GitHub.com/acme/orders",
            credential=AccessToken_in(),
        )
    )

    assert vault.scopes == {"/acme/orders": "https://github.com"}


def AccessToken_in() -> AccessTokenIn:  # ruff: ignore[invalid-function-name]
    return AccessTokenIn(kind="token", token=TOKEN)


async def test_a_library_is_private_exactly_when_it_has_a_stored_credential() -> None:
    vault = InMemoryCredentialVault()
    module = IngestionModule.build(
        jobs=InMemoryJobRepository(),
        clock=SystemClock(),
        remote=FakeRemote(),
        library_ids=Catalog(known={"/acme/x"}),
        libraries=Catalog(),
        removals=NoRemovals(),
        index=NoIndex(),
        vault=vault,
    )
    query = GetLibraryAccessQuery(library="/acme/x")

    assert (await module.get_library_access(query)).private is False
    await vault.save("/acme/x", SCOPE, AccessToken(token=TOKEN))
    assert (await module.get_library_access(query)).private is True
    # IDs are case-insensitive: the vault is keyed by the lower-case one
    assert (await module.get_library_access(GetLibraryAccessQuery(library="/ACME/X"))).private
    await vault.delete("/acme/x")
    assert (await module.get_library_access(query)).private is False


async def test_an_unknown_library_has_no_access_answer() -> None:
    module = IngestionModule.build(
        jobs=InMemoryJobRepository(),
        clock=SystemClock(),
        remote=FakeRemote(),
        library_ids=Catalog(),
        libraries=Catalog(),
        removals=NoRemovals(),
        index=NoIndex(),
    )

    with pytest.raises(UnknownLibraryError):
        await module.get_library_access(GetLibraryAccessQuery(library="/no/such"))


@dataclass(frozen=True, slots=True, kw_only=True)
class _PrivateBeforeStored(InMemoryCredentialVault):
    """Fails unless identity heard the library is private before its credential landed."""

    access: FakeAccess

    async def save(self, library: str, scope: str, credential: Credential) -> None:
        assert library in self.access.private
        await InMemoryCredentialVault.save(self, library, scope, credential)


async def test_a_library_is_said_private_before_its_credential_is_stored() -> None:
    access = FakeAccess(role="creator")
    vault = _PrivateBeforeStored(access=access)
    command = AddLibraryCommand(
        url="https://github.com/acme/orders",
        credential=AccessTokenIn(kind="token", token=TOKEN),
    )

    added = await build(FakeRemote(), vault, access=access).add_library(command)
    await build(FakeRemote(), vault, access=access).add_version(
        AddVersionCommand(
            library="/acme/orders", ref="main", credential=AccessTokenIn(kind="token", token=TOKEN)
        )
    )

    assert access.private == {added.library_id, "/acme/orders"}


async def test_a_public_library_is_said_not_private() -> None:
    access = FakeAccess(role="creator", private={"/acme/orders"})

    await build(FakeRemote(), InMemoryCredentialVault(), access=access).add_library(
        AddLibraryCommand(url="https://other.example.com/acme/orders")
    )

    assert access.private == set()
