"""A company CA and HTTPS servers signed by it, for the outbound tests (#538).

``company_ca`` writes a throw-away CA (the kind a TLS-re-signing proxy uses) and a server
certificate for the names a test asks for; ``https_server`` serves a handler over TLS with that
certificate on 127.0.0.1. A client trusts the server only when it is given the CA bundle: the
system's certificates know nothing of it.
"""

import contextlib
import datetime as dt
import http.server
import ipaddress
import ssl
import threading
from collections.abc import Generator, Sequence
from dataclasses import dataclass
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

VALID = dt.timedelta(days=2)
"""How long the certificates are valid (from a day ago)."""


@dataclass(frozen=True, slots=True)
class CompanyCa:
    """A CA bundle and a server certificate it signed."""

    bundle: Path
    """The CA certificate (PEM): what ``EXACTDOCS_CA_BUNDLE`` names."""
    certificate: Path
    """The server's certificate (PEM)."""
    key: Path
    """The server's private key (PEM)."""


def _name(common: str) -> x509.Name:
    """Make a subject or issuer name.

    Args:
        common: Its common name.

    Returns:
        The name.
    """
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common)])


def company_ca(folder: Path, names: Sequence[str]) -> CompanyCa:
    """Write a CA and a server certificate for ``names`` (host names or IP addresses).

    Args:
        folder: Where the PEM files go.
        names: What the server certificate is valid for.

    Returns:
        The files.
    """
    now = dt.datetime.now(dt.UTC) - dt.timedelta(days=1)
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = _name("ExactDocs test company CA")
    ca = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + VALID)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_cert_sign=True,
                crl_sign=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), False)
        .sign(ca_key, hashes.SHA256())
    )
    key = ec.generate_private_key(ec.SECP256R1())
    alternatives: list[x509.GeneralName] = []
    for name in names:
        try:
            alternatives.append(x509.IPAddress(ipaddress.ip_address(name)))
        except ValueError:
            alternatives.append(x509.DNSName(name))
    leaf = (
        x509.CertificateBuilder()
        .subject_name(_name(names[0]))
        .issuer_name(ca_name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + VALID)
        .add_extension(x509.SubjectAlternativeName(alternatives), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), False
        )
        .sign(ca_key, hashes.SHA256())
    )
    folder.mkdir(parents=True, exist_ok=True)
    files = CompanyCa(
        bundle=folder / "company-ca.pem",
        certificate=folder / "server.pem",
        key=folder / "server-key.pem",
    )
    files.bundle.write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    files.certificate.write_bytes(leaf.public_bytes(serialization.Encoding.PEM))
    files.key.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return files


@contextlib.contextmanager
def https_server(
    ca: CompanyCa, handler: type[http.server.BaseHTTPRequestHandler]
) -> Generator[tuple[str, int]]:
    """Serve a handler over TLS on 127.0.0.1 with the CA's server certificate.

    Args:
        ca: The certificate and key to serve with.
        handler: The request handler.

    Yields:
        The server's address.
    """
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(ca.certificate, ca.key)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield ("127.0.0.1", server.server_address[1])
    finally:
        server.shutdown()
        server.server_close()
