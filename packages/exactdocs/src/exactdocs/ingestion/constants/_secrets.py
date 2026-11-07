"""Constants of credential encryption."""

from typing import Final

KEY_FILE: Final[str] = "secret.key"
"""File in the data directory that holds the generated secret key."""
MIN_SECRET_KEY_LENGTH: Final[int] = 32
"""Shortest ``EXACTDOCS_SECRET_KEY`` accepted, in characters."""
_HKDF_INFO: Final[bytes] = b"exactdocs credentials v1"
"""HKDF context of the credential encryption key, so the key serves nothing else."""
_OWNER_ONLY: Final[int] = 0o600
"""File mode of the secret key file: readable by its owner only."""
OPENSSH_MAGIC: Final[bytes] = b"openssh-key-v1\0"
"""How the binary body of an OpenSSH private key starts; its cipher name follows."""
