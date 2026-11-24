"""What registers an external index backend (#352): one entry of ``INDEX_BACKENDS``.

Kept apart from ``index_backends.py`` so ``constants.py`` can hold the registry without an import
cycle.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True, kw_only=True)
class IndexBackendKind:
    """One external backend ExactDocs can put its search or vector index in.

    The adapter module is imported only when an operator names the backend, so its client
    library can live behind an optional extra (``packages`` may be imported by that module
    alone: an architecture test checks it).
    """

    name: str
    """What ``EXACTDOCS_SEARCH_BACKEND`` / ``EXACTDOCS_VECTOR_BACKEND`` and the
    ``[index_backends.<name>]`` table call it."""
    module: str
    """The adapter module, in ``exactdocs.retrieval.adapters.driven``."""
    search: str | None
    """The module's function that builds its ``SearchBackend`` from the options; ``None``: it
    cannot hold the search index."""
    vectors: str | None
    """The module's function that builds its ``VectorBackend`` from the options; ``None``: it
    cannot hold the vector index."""
    extra: str | None = None
    """The optional extra that installs its client (``pip install 'exactdocs[<extra>]'``)."""
    packages: tuple[str, ...] = ()
    """The top-level packages the extra installs; only ``module`` may import them."""
    production: bool = True
    """False for a backend that keeps nothing across a restart (``memory``): start logs it."""
    outbound: bool = False
    """It connects over the network: its factories take ``network=`` (the outbound proxy,
    ``NO_PROXY`` and CA bundle, #538) besides the options."""
