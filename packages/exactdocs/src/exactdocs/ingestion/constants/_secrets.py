"""Constants of credentials (the secret box and its key are in ``exactdocs.bootstrap``)."""

from typing import Final

OPENSSH_MAGIC: Final[bytes] = b"openssh-key-v1\0"
"""How the binary body of an OpenSSH private key starts; its cipher name follows."""
