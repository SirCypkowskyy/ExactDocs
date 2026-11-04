"""Driven adapter for ``SecretBox``: Fernet (AES-128-CBC with HMAC-SHA256) from ``cryptography``.

The key comes from ``EXACTDOCS_SECRET_KEY`` when set; any text of 32 characters or more works,
and the Fernet key is derived from it with HKDF-SHA256 (so a pasted ``openssl rand -base64 32``
is fine). Otherwise a random key is generated once into a file of the data directory, mode 0600,
and read back on later runs. Nothing here logs or raises with a key, a plaintext or a token.
"""

import base64
import logging
import os
import secrets
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Self

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from exactdocs.ingestion.errors import CredentialsRequiredError

log = logging.getLogger(__name__)

KEY_FILE = "secret.key"
MIN_SECRET_KEY_LENGTH = 32
_HKDF_INFO = b"exactdocs credentials v1"
_OWNER_ONLY = 0o600


@dataclass(frozen=True, slots=True)
class FernetSecretBox:
    """Implements ``ports.driven.SecretBox``.

    Sealing uses the first key; opening tries all of them, so a key can be rotated by listing
    the new one first and the old one as a previous key until the credentials are sent again.
    """

    fernet: MultiFernet = field(repr=False)

    @classmethod
    def from_secrets(cls, secret: str, *previous: str) -> Self:
        """Derive the keys from ``EXACTDOCS_SECRET_KEY`` (and ``_PREVIOUS``), 32+ characters."""
        return cls(MultiFernet([_derive(text) for text in (secret, *previous)]))

    @classmethod
    def from_secret(cls, secret: str) -> Self:
        """Derive the key from one secret text (at least 32 characters)."""
        return cls.from_secrets(secret)

    @classmethod
    def from_file(cls, path: Path) -> Self:
        """Read the key file; a missing one is created first (mode 0600, atomically).

        A symlink or a file of another user is refused. One that others could read is made
        private again, but its key must be treated as exposed (logged as an error).
        """
        if not path.is_symlink() and not path.exists():
            _create_key_file(path)
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            message = f"the secret key file {path} must be a regular file, not a link"
            raise ValueError(message)
        if hasattr(os, "getuid") and info.st_uid != os.getuid():
            message = f"the secret key file {path} belongs to another user"
            raise ValueError(message)
        if stat.S_IMODE(info.st_mode) & 0o077:  # a copy or a restore may have loosened it
            log.error(
                "the secret key file %s was readable by other users: it is private again, but "
                "treat the key as exposed and rotate it (see EXACTDOCS_SECRET_KEY_PREVIOUS)",
                path,
            )
            path.chmod(_OWNER_ONLY)
        try:
            return cls.from_secret(path.read_text("utf-8").strip())
        except ValueError:
            message = f"the secret key file {path} is empty or too short: delete it to generate one"
            raise ValueError(message) from None

    def seal(self, plaintext: str) -> str:
        """Encrypt and authenticate ``plaintext``."""
        return self.fernet.encrypt(plaintext.encode()).decode()

    def open(self, sealed: str) -> str:
        """Decrypt; a token made with another key (or tampered with) is ``credentials_required``."""
        try:
            return self.fernet.decrypt(sealed.encode()).decode()
        except InvalidToken:
            raise CredentialsRequiredError from None


def _derive(secret: str) -> Fernet:
    # The secret must be random (HKDF stretches nothing): `openssl rand -base64 32`.
    if len(secret) < MIN_SECRET_KEY_LENGTH:
        message = f"the secret key must have at least {MIN_SECRET_KEY_LENGTH} characters"
        raise ValueError(message)
    raw = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=_HKDF_INFO).derive(
        secret.encode()
    )
    return Fernet(base64.urlsafe_b64encode(raw))


def _create_key_file(path: Path) -> None:
    """Publish a fresh random key atomically: a reader never sees a half-written file.

    The key is written to a private temporary file, then hard-linked to ``path``, which fails
    when another process got there first (its key wins). Where hard links do not exist the
    file is created in place with ``O_EXCL`` instead.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    key = secrets.token_urlsafe(48) + "\n"
    temporary = path.with_name(f"{path.name}.{secrets.token_hex(4)}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, _OWNER_ONLY)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(key)
        try:
            os.link(temporary, path)
        except FileExistsError:
            return
        except OSError:  # no hard links on this volume
            _create_in_place(path, key)
    finally:
        temporary.unlink(missing_ok=True)


def _create_in_place(path: Path, key: str) -> None:
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, _OWNER_ONLY)
    except FileExistsError:
        return
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(key)
