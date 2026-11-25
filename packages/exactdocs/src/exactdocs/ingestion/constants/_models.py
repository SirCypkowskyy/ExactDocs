"""Constants of the models: limits, patterns and defaults of libraries, versions and jobs."""

import re
from datetime import timedelta
from typing import Final, Literal, NewType

from exactdocs.ingestion.constants._restructuredtext import (
    MARKDOWN_SUFFIXES,
    RESTRUCTUREDTEXT_SUFFIXES,
)

type ChunkerName = Literal["markdown"]
"""The chunkers ExactDocs has."""
PARSER_VERSION: Final[int] = 3
"""Bump on any change to the sanitizer or the parser. It feeds the chunking-config hash (E4-02), so
a fix here re-chunks stored articles instead of reusing stale chunk sets.
"""
CHUNKER_VERSION: Final[int] = 2
"""Bump on any change to how a chunker cuts articles. Like PARSER_VERSION it feeds the config hash.
"""
MERGED_HEADINGS_VERSION: Final[int] = 1
"""Bump on any change to the heading records of chunks that hold more than one heading (#251). It
feeds the hash of the configs that can merge headings (a split level above h6, or ``min_chars``),
so those libraries' chunk sets are cut again when they are next imported or re-chunked.
"""
MAX_HEADING_LEVEL: Final[int] = 6
"""Deepest Markdown heading level a chunking config may split at."""
DEFAULT_SPLIT_LEVEL: Final[int] = 3
"""The split level a library gets unless its settings name one: ``#`` to ``###`` start a chunk
(#381, after the retrieval benchmark: BM25's recall@5 81.7% against 79.8% at every heading). It
was ``MAX_HEADING_LEVEL`` before; libraries store their chunking, so changing it changes no
existing library."""
DEFAULT_MAX_CHARS: Final[int] = 4_000
"""The ``max_chars`` a library gets unless its settings name one: a chunk longer than this is cut
again at its deeper headings (#381). It was no bound before."""
_ALWAYS_INVISIBLE: Final[re.Pattern[str]] = re.compile(
    # a subdivision flag (England, Scotland, Wales...) is visible text, keep it whole
    r"(?P<flag>\N{WAVING BLACK FLAG}"
    r"[\N{TAG DIGIT ZERO}-\N{TAG DIGIT NINE}"
    r"\N{TAG LATIN SMALL LETTER A}-\N{TAG LATIN SMALL LETTER Z}]"
    r"{2,7}\N{CANCEL TAG})"
    r"|[\N{ZERO WIDTH SPACE}\N{WORD JOINER}\N{ZERO WIDTH NO-BREAK SPACE}"
    r"\N{MONGOLIAN VOWEL SEPARATOR}"
    r"\N{ARABIC LETTER MARK}\N{LEFT-TO-RIGHT MARK}\N{RIGHT-TO-LEFT MARK}"
    r"\N{LEFT-TO-RIGHT EMBEDDING}-\N{RIGHT-TO-LEFT OVERRIDE}"  # embeddings, pop, overrides
    r"\N{LEFT-TO-RIGHT ISOLATE}-\N{POP DIRECTIONAL ISOLATE}"
    r"\N{FUNCTION APPLICATION}-\N{INVISIBLE PLUS}"  # invisible math operators
    r"\N{COMBINING GRAPHEME JOINER}"
    r"\N{HANGUL CHOSEONG FILLER}\N{HANGUL JUNGSEONG FILLER}\N{HANGUL FILLER}"
    r"\N{HALFWIDTH HANGUL FILLER}\N{KHMER VOWEL INHERENT AQ}\N{KHMER VOWEL INHERENT AA}"
    r"\N{BRAILLE PATTERN BLANK}"
    r"\N{VARIATION SELECTOR-17}-\N{VARIATION SELECTOR-256}"
    r"\N{LANGUAGE TAG}-\N{CANCEL TAG}"  # Unicode tag characters
    r"\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]"  # C0 and C1 controls, not \t \n \r
)
"""Characters that render as nothing (or as a control) but reach an LLM as text: zero-width space
and friends, the byte order mark, bidi controls (Trojan Source), Unicode "tag" characters and
supplementary variation selectors (byte smuggling), invisible math operators, fillers, the blank
Braille cell, and C0/C1 controls except tab, newline and carriage return (ANSI escapes, NUL).
Everything else, including every visible character and the regular variation selectors next to
emoji, is left alone. Known cost: LRM/RLM/ALM and the Mongolian vowel separator also have
typographic uses, so punctuation placement in RTL text can change. embeddings, pop, overrides
invisible math operators Unicode tag characters C0 and C1 controls, not.
"""
_JOINERS: Final[str] = r"\N{ZERO WIDTH NON-JOINER}\N{ZERO WIDTH JOINER}"
"""ZWJ and ZWNJ also carry meaning (emoji sequences, Persian and Indic scripts), so a single one
between two non-ASCII characters is kept. Next to ASCII or another joiner it can only be a hidden
channel, and it goes.
"""
_STRAY_JOINER: Final[re.Pattern[str]] = re.compile(
    rf"(?<![^\x00-\x7f{_JOINERS}])[{_JOINERS}]|[{_JOINERS}](?![^\x00-\x7f{_JOINERS}])"
)
"""Zero-width (non-)joiners left over once the invisible characters around them are removed."""
_FRONT_MATTER: Final[re.Pattern[str]] = re.compile(
    r"\A---[ \t]*\r?\n(?:(?P<yaml>.*?)\r?\n)?---[ \t]*(?:\r?\n|\Z)", re.DOTALL
)
"""A YAML front matter block at the start of an article."""
_NO_ALIASES: Final[str] = "anchors and aliases are not allowed"
"""Why front matter with YAML anchors or aliases is refused (they can blow up in size)."""
MAX_TAG_RULES: Final[int] = 64
"""Tag rules a library's settings may hold."""
_MAX_RAW_TAGS: Final[int] = 100
"""Front matter tags read per article; the rest are skipped without being normalized."""
MAX_IMAGES_PER_ARTICLE: Final[int] = 100
"""Images one article may reference; the rest are not imported."""
_MAX_IMAGE_DEPTH: Final[int] = 64
"""Most path segments an image reference may have."""
_SCHEME: Final[re.Pattern[str]] = re.compile(r"[a-z][a-z0-9+.-]*:", re.IGNORECASE)
"""A URL scheme (``https:``, ``data:``...): such a reference is not a repository path."""
README_TITLE_MAX: Final[int] = 120
"""Longest library title taken from a README, in characters."""
README_DESCRIPTION_MAX: Final[int] = 500
"""Longest library description taken from a README, in characters."""
_README_LABEL: Final[re.Pattern[str]] = re.compile(
    r"^\s*[\w-]+(?:\s+[\w-]+){0,2}\s*:", re.MULTILINE
)
"""A short label opening a README line (``Documentation:``): with the links after it, a nav line."""
_README_NAV_CHARS: Final[str] = " \n|-*.,;:·•"
"""What may sit between the links of a README nav line."""
_LOGO_WORDS: Final[re.Pattern[str]] = re.compile(r"\b(?:logo|banner)\b", re.IGNORECASE)
"""Words an image ``alt`` adds to the project's name (``Acme logo``)."""
_BADGE_SOURCES: Final[tuple[str, ...]] = ("badge", "shields.io", "badgen.net")
"""An image whose source holds one of these is a badge, not a logo."""
DEFAULT_GRACE_SECONDS: Final[int] = 7 * 24 * 3600
"""How long a replaced manifest is kept so that its chunk IDs can still be recognized as stale."""
PERMANENT_IMPORT_FAILURES: Final[frozenset[str]] = frozenset({"no_articles", "import_too_large"})
"""Codes of an import that fails again at the same commit; anything else may pass next time. Not
``checkout_unreadable``: a folder that cannot be listed is the disk's state (full, out of file
handles, permissions), not the commit's.
"""
UNEXPECTED_BACKOFF_CAP: Final[timedelta] = timedelta(days=1)
"""The longest wait before an auto import that failed ``unexpected`` again is retried."""
UNEXPECTED_ERROR: Final[str] = "unexpected"
"""The ``error_code`` of a job that failed on something no domain error describes (a bug)."""
_GIT_SUFFIX: Final[re.Pattern[str]] = re.compile(r"\.git\Z", re.IGNORECASE)
"""The ``.git`` a repository URL may end with."""
_SCHEMES: Final[frozenset[str]] = frozenset({"https", "http", "ssh", "file"})
"""URL schemes a repository may be imported over."""
_HOST: Final[re.Pattern[str]] = re.compile(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?")
"""A host name, lower-case."""
_SSH_USER: Final[re.Pattern[str]] = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._-]*")
"""The user part of an SSH repository URL."""
_SCP_LIKE: Final[re.Pattern[str]] = re.compile(
    r"(?P<user>[A-Za-z0-9_][A-Za-z0-9._-]*)@(?P<host>[A-Za-z0-9][A-Za-z0-9.-]*):(?P<path>[^:].*)"
)
"""`user@host:path`, git's scp-like syntax. The path cannot start with `:` (`ext::...`)."""
_UNSAFE_ID_CHARS: Final[re.Pattern[str]] = re.compile(r"[^A-Za-z0-9._-]+")
"""Runs of characters a library ID cannot contain; they become ``-``."""
_ID_SEGMENTS: Final[int] = 2
"""Path segments of a library ID (``owner/repo``)."""
_LOOPBACK: Final[frozenset[str]] = frozenset({"localhost", "127.0.0.1", "::1"})
"""Host names of this machine, refused as repository hosts."""
_MAX_TOKEN: Final[int] = 4096
"""Longest access token, in characters."""
_MAX_KEY: Final[int] = 16 * 1024
"""Largest deploy key, in characters."""
_TOKEN_USER: Final[re.Pattern[str]] = re.compile(r"[A-Za-z0-9._-]{1,100}")
"""The user name that goes with an access token."""
_BAD_REF_CHARS: Final[re.Pattern[str]] = re.compile(r"[\x00-\x20\x7f~^:?*\[\\]")
"""Characters git does not allow in a ref name."""
_MAX_BRANCH: Final[int] = 255
"""Longest branch name, in characters."""
DEFAULT_CHUNKER: Final[ChunkerName] = "markdown"
"""The chunker a library uses unless its settings name another."""
CHUNKERS: Final[frozenset[str]] = frozenset({DEFAULT_CHUNKER})
"""The chunkers a library can choose: ``markdown`` cuts at headings with markdown-it-py. Chonkie was
dropped (#27: its Markdown recipe needs the Hugging Face Hub and the network).
"""
MAX_CHUNK_CHARS: Final[int] = 1_000_000
"""Upper bound of ``min_chars``, ``max_chars`` and ``max_section_chars``: bigger is no bound at
all (a whole article)."""
DEFAULT_MAX_SECTION_CHARS: Final[int] = 8_000
"""Longest chunk the chunking makes by default, in characters, unless a single block is longer
(#141). About 2,000 tokens at retrieval's estimate of 4 characters per token, and the most of a
chunk retrieval sends a reranker or gives the search agent (``MAX_RERANK_DOCUMENT_CHARS``,
``AGENT_CHUNK_CHARS``), so neither cuts a default chunk. Dense text (1.5 characters per token)
stays within hosted embedding models' input (8,191 tokens for OpenAI's). It is in the config hash,
so changing it cuts every library again at its next import or re-chunk."""
_SHA_PREFIX: Final[re.Pattern[str]] = re.compile(r"[0-9a-f]{7,64}")
"""An abbreviated or full commit SHA."""
ARTICLE_SUFFIXES: Final[tuple[str, ...]] = (*MARKDOWN_SUFFIXES, *RESTRUCTUREDTEXT_SUFFIXES)
"""File suffixes of articles (Markdown, reStructuredText): everything else in a repository is
ignored."""
_MAX_PATTERNS: Final[int] = 64
"""Path patterns a library's settings may hold."""
_MAX_PATTERN: Final[int] = 256
"""Longest path pattern, in characters."""
_MAX_PATH: Final[int] = 1024
"""Longest path a pattern is matched against, in characters."""
_MAX_SEGMENT: Final[int] = 255
"""Longest segment of such a path, in characters."""
CONTEXT7_FILE: Final[str] = "context7.json"
"""The root file context7 reads a repository's docs settings from (LIB-06)."""
CONTEXT7_MAX_BYTES: Final[int] = 64 * 2**10
"""A bigger ``context7.json`` is ignored with a warning, unread."""
INSTRUCTION_FILE_NAMES: Final[tuple[str, ...]] = ("AGENTS.md", "CLAUDE.md")
"""The instruction files kept per folder for agentic retrieval when repo guidance is on (RET-08)."""
MAX_INSTRUCTION_DIRS: Final[int] = 32
"""Folders looked in for instruction files: the root, then the selected files' folders, shallowest
first (so at most twice as many files)."""
MAX_INSTRUCTION_FILE_BYTES: Final[int] = 32 * 2**10
"""A bigger instruction file is left out with a problem (cut off while it downloads)."""
INSTRUCTIONS_NOT_READ: Final[str] = "the instruction files could not be read; the version has none"
"""The job problem when no instruction file could be read (the error's class is added)."""
MAX_CONTEXT7_RULES: Final[int] = 20
"""Rules read from a repository's ``context7.json``."""
MAX_CONTEXT7_RULE_CHARS: Final[int] = 500
"""Longest rule read from ``context7.json``, in characters."""
MAX_PREVIOUS_VERSIONS: Final[int] = 50
"""Previous versions read from ``context7.json``."""
MAX_PREVIOUS_VERSION_CHARS: Final[int] = 255
"""Longest previous-version entry of ``context7.json``, in characters."""
DEFAULT_MAX_ARTICLE_BYTES: Final[int] = 2 * 2**20
"""Files above this many bytes are skipped without being read."""
DEFAULT_MAX_IMPORT_BYTES: Final[int] = 256 * 2**20
"""An import whose selected articles add up to more than this many bytes fails."""
DEFAULT_IMPORT_BATCH_FILES: Final[int] = 100
"""Files an import parses and chunks per durable step: a resumed import loses at most these."""
DEFAULT_MAX_IMAGE_BYTES: Final[int] = 2 * 2**20
"""Referenced images above this many bytes are skipped without being read."""
DEFAULT_MAX_IMAGES_BYTES: Final[int] = 32 * 2**20
"""The images of one version are kept until they add up to this many bytes, then skipped."""
MAX_IMAGES: Final[int] = 1000
"""At most this many distinct images are imported per version; later ones are skipped."""
MAX_JOB_PROBLEMS: Final[int] = 1000
"""File problems one job records; more are counted, not kept."""
MAX_JOB_NOTES: Final[int] = 200
"""Front matter notes one job records (below ``MAX_JOB_PROBLEMS``); more are dropped."""
IMAGE_TYPES: Final[tuple[str, ...]] = (
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
    "image/svg+xml",
)
"""Media types of the images an import keeps."""
_SVG: Final[re.Pattern[bytes]] = re.compile(
    # Atomic group + tempered comment: no backtracking, so a hostile file cannot stall the loop.
    rb"\A(?:\xef\xbb\xbf)?\s*(?>(?:<\?xml[^>]*\?>|<!--(?:(?!-->).)*-->)\s*)*"
    rb"(?:<!DOCTYPE\s+svg[^>\[]*>\s*)?<svg[\s/>]",
    re.DOTALL | re.IGNORECASE,
)
"""The start of an SVG document, to tell one from other XML."""
MAX_SIMILARITY: Final[int] = 100
"""Highest rename similarity git reports, in percent."""
MAX_RENAMES: Final[int] = 10_000
"""Renames kept per version; git lists more only for a rewrite of the whole tree."""
_NUMERIC_REF: Final[re.Pattern[str]] = re.compile(r"[vV]?(\d{1,9}(?:\.\d{1,9}){0,7})")
"""A version-like ref (``v1.4.2``) and its numbers, for sorting refs."""
MAX_TAG_PATTERN: Final[int] = 200
"""Longest tag pattern of an auto-sync, in characters."""
MAX_KEEP_LAST: Final[int] = 100
"""Most versions an auto-sync may keep."""
MIN_INTERVAL_MINUTES: Final[int] = 1
"""Shortest time between two auto-sync checks."""
MAX_INTERVAL_MINUTES: Final[int] = 7 * 24 * 60
"""Longest time between two auto-sync checks (a week)."""
DEFAULT_KEEP_LAST: Final[int] = 5
"""Versions an auto-sync keeps when its settings name no number."""
DEFAULT_INTERVAL_MINUTES: Final[int] = 60
"""Time between two auto-sync checks when the settings name none."""
MAX_CHECK_ERROR: Final[int] = 500
"""Longest error kept of an auto-sync check, in characters."""
_ORDER_WIDTH: Final[int] = 8
"""What ``_NUMERIC_REF`` allows: ``1.4`` ranks as ``1.4.0.0.0.0.0.0``"""

# ---------------------------------------------------------------- job kinds
JobKind = NewType("JobKind", str)
"""What a job does; the kinds below are the ones the ingestion domain runs."""
IMPORT_JOB: Final[JobKind] = JobKind("import")
"""The kind of job that imports one version of a library."""
REFRESH_JOB: Final[JobKind] = JobKind("refresh")
"""Imports a version the catalog has; fails if it was removed meanwhile (no resurrection)."""
IMPORT_KINDS: Final[frozenset[JobKind]] = frozenset({IMPORT_JOB, REFRESH_JOB})
"""Kinds of job that import; removal waits for them and the sync state counts them."""
REPROCESS_JOB: Final[JobKind] = JobKind("reprocess")
"""Re-imports every version of a library at its commit after its paths changed (one job)."""
RETAG_JOB: Final[JobKind] = JobKind("retag")
"""Re-tags every version of a library from its stored articles after its tag rules changed."""
RECHUNK_JOB: Final[JobKind] = JobKind("rechunk")
"""Re-chunks (and re-tags) every version from its stored articles after its chunking changed."""
LIBRARY_KINDS: Final[frozenset[JobKind]] = frozenset({REPROCESS_JOB, RECHUNK_JOB, RETAG_JOB})
"""Kinds of job that touch every version of the library (their ``version`` is ``None``)."""
COLLECT_JOB: Final[JobKind] = JobKind("collect")
"""The kind of job that frees what removed or replaced versions left on disk."""
EMBED_JOB: Final[JobKind] = JobKind("embed")
"""Embeds one version with the instance's embedding model, a durable step per batch (RET-01)."""
PUSH_JOB: Final[JobKind] = JobKind("push")
"""Syncs one pushed branch, or auto-imports after one pushed tag, when a forge's webhook said so."""
QUEUED_PUSH_SQL: Final[str] = "state = 'queued' AND kind = 'push'"
"""The rows of the unique index that keeps one queued ``push`` job per (library, ref, kind)."""
EMBED_AFTER_KINDS: Final[frozenset[JobKind]] = frozenset(
    {IMPORT_JOB, REFRESH_JOB, REPROCESS_JOB, RECHUNK_JOB}
)
"""Kinds of job whose new chunks need embedding: each queues ``embed`` jobs when it succeeds."""
CHANGE_JOBS: Final[dict[str, JobKind]] = {
    "paths": REPROCESS_JOB,
    "chunking": RECHUNK_JOB,
    "tags": RETAG_JOB,
}
"""The job that applies each kind of settings change (keyed by ``SettingsChange`` value)."""
ACTIVE_JOB_STATES: Final[frozenset[str]] = frozenset({"queued", "running"})
"""A job in one of these states (``JobState`` values) is unfinished: at most one import per
(library, ref) may be.
"""
UNFINISHED_JOBS_SQL: Final[str] = (
    "state IN (" + ", ".join(f"'{state}'" for state in sorted(ACTIVE_JOB_STATES)) + ")"
)
"""``ACTIVE_JOB_STATES`` as a literal SQL condition: the partial index of unfinished jobs and the
query that reads it say the same, which a bound parameter could not prove to SQLite's planner.

It must match ``UNFINISHED`` in the migration ``97095cfef767`` (which creates that index) byte for
byte: SQLite uses a partial index only for a query that spells its condition exactly like the
index's, so a condition that differs (another state, another order) silently stops the index
being used.
"""
JOB_SORT_FIELDS: Final[tuple[str, ...]] = ("id", "created_at", "state", "kind", "library")
"""What the jobs lists can be sorted by (columns that are never null); `-id` is the default, which
is newest first."""
JOB_KINDS: Final[tuple[JobKind, ...]] = (
    IMPORT_JOB,
    REFRESH_JOB,
    REPROCESS_JOB,
    RETAG_JOB,
    RECHUNK_JOB,
    COLLECT_JOB,
    EMBED_JOB,
    PUSH_JOB,
)
"""Every kind of job, in the order the job statistics list them (each day counts every one)."""
DEFAULT_STATS_DAYS: Final[int] = 30
"""Days the job statistics cover when the request names no start: the last 30, today included."""
MAX_STATS_DAYS: Final[int] = 366
"""The most days one request for job statistics may cover (a leap year): the range is bounded."""
ABOVE_EVERY_JOB_ID: Final[str] = "\U0010ffff"
"""The first page's cursor in the SQL job repository: the last Unicode code point sorts after
every job ID (a UUID string), by code point in Python and SQLite and byte-wise in PostgreSQL's
``C`` collation alike, so the first page is bounded like the pages after it (#330).
"""

# ---------------------------------------------------------------- hosts and refs
KNOWN_HOSTS: Final[dict[str, str]] = {
    "github.com": "github",
    "gitlab.com": "gitlab",
    "bitbucket.org": "bitbucket",
    "gitea.com": "gitea",
    "codeberg.org": "gitea",
}
"""The ``RepositoryHost`` of each host name ExactDocs knows; any other server is ``git``."""
FLAT_HOSTS: Final[frozenset[str]] = frozenset(
    {"github.com", "bitbucket.org", "gitea.com", "codeberg.org"}
)
"""Hosts without nested groups: a longer path is a page (``/tree/main/docs``), not a repository."""
HEADS: Final[str] = "refs/heads/"
"""Prefix of branch refs."""
TAGS: Final[str] = "refs/tags/"
"""Prefix of tag refs."""
PEELED: Final[str] = "^{}"
"""Suffix of a peeled annotated tag in a ref listing: the commit it points to."""
CHECKED_KINDS: Final[frozenset[str]] = frozenset({"branch", "tag"})
"""What a sync asks the remote about (``RefKind`` values): a commit names itself and cannot move
or go.
"""

# ---------------------------------------------------------------- path patterns
GLOB_CHARS: Final[frozenset[str]] = frozenset("*?{")
"""Characters that make a path pattern a glob rather than a plain path.

``[`` is not one: there are no character classes, so ``app/[locale]`` is a folder name (#234).
"""
ANY: Final[str] = "*"
"""Matches any run of characters in a path segment; as a token it is the 1-tuple ``("*",)``."""
ONE: Final[str] = "?"
"""Matches one character of a path segment; as a token it is the 1-tuple ``("?",)``."""

# ---------------------------------------------------------------- project logos (#504)
LOGO_TYPES: Final[frozenset[str]] = frozenset(
    {"image/png", "image/jpeg", "image/webp", "image/svg+xml"}
)
"""Media types a library logo may have; any other image (a GIF too) is not a logo."""
MAX_LOGO_BYTES: Final[int] = 512 * 2**10
"""Most bytes a logo file may have; a bigger one is cut off while it downloads and ignored."""
MIN_LOGO_SIDE: Final[int] = 16
"""Shortest side of a raster logo, in pixels: a smaller image is a spacer or a tracking pixel."""
MAX_LOGO_SIDE: Final[int] = 4096
"""Longest side of a raster logo, in pixels."""
MAX_LOGO_PIXELS: Final[int] = 2048 * 2048
"""Most pixels (width times height) of a raster logo: bounds what a browser decodes to show it."""
MAX_LOGO_SVG_ELEMENTS: Final[int] = 10_000
"""Most elements an SVG logo may have; a bigger drawing is not a logo."""
MAX_README_LOGOS: Final[int] = 4
"""Images the top of a README offers as logos, tried in order before the conventional files."""
_README_LOGO_TOKENS: Final[int] = 200
"""Tokens of a parsed README looked through for a logo: the logo sits at the top."""
_MAX_LOGO_SOURCE: Final[int] = 2048
"""Longest image ``src`` kept from a README as a logo; a longer one is not a logo."""
_LOGO_NAME: Final[re.Pattern[str]] = re.compile(r"(?<![a-z])logos?(?![a-z])", re.IGNORECASE)
"""Says "logo" in an image's path or ``alt`` (``logo-dark.svg``, ``acme_logo.png``, ``Acme logo``),
not inside another word (``catalogo``, ``logout``)."""
LOGO_FILES: Final[tuple[str, ...]] = (
    "logo.svg",
    "logo.png",
    ".github/logo.svg",
    ".github/logo.png",
    ".github/assets/logo.svg",
    ".github/assets/logo.png",
    "assets/logo.svg",
    "assets/logo.png",
    "assets/logo.webp",
    "assets/logo.jpg",
    "docs/public/logo.svg",
    "docs/public/logo.png",
    "docs/logo.svg",
    "docs/logo.png",
    "docs/assets/logo.svg",
    "docs/assets/logo.png",
    "docs/static/img/logo.svg",
    "website/static/img/logo.svg",
    "static/img/logo.svg",
    "public/logo.svg",
)
"""Where projects conventionally keep their logo (the root, the GitHub folder, ``assets``,
VitePress' ``docs/public``, MkDocs' ``docs/assets``, Docusaurus' ``static/img``), tried in this
order after the README's own logo images."""
_SVG_NAMESPACE: Final[str] = "http://www.w3.org/2000/svg"
"""The SVG namespace: an SVG logo's root and every element it keeps are in it."""
_XLINK_NAMESPACE: Final[str] = "http://www.w3.org/1999/xlink"
"""The XLink namespace of SVG 1.1's ``xlink:href``, written as plain ``href`` when kept."""
_XML_NAMESPACE: Final[str] = "http://www.w3.org/XML/1998/namespace"
"""The ``xml:`` namespace (``xml:space``, ``xml:lang``): its attributes are kept."""
_SVG_ELEMENTS: Final[frozenset[str]] = frozenset(
    {
        "svg", "g", "defs", "symbol", "use", "title", "desc", "style", "switch", "a",
        "path", "rect", "circle", "ellipse", "line", "polyline", "polygon",
        "text", "tspan", "textPath",
        "linearGradient", "radialGradient", "stop", "pattern", "clipPath", "mask", "marker",
        "filter", "feBlend", "feColorMatrix", "feComponentTransfer", "feComposite",
        "feConvolveMatrix", "feDiffuseLighting", "feDisplacementMap", "feDistantLight",
        "feDropShadow", "feFlood", "feFuncA", "feFuncB", "feFuncG", "feFuncR",
        "feGaussianBlur", "feMerge", "feMergeNode", "feMorphology", "feOffset",
        "fePointLight", "feSpecularLighting", "feSpotLight", "feTile", "feTurbulence",
    }
)  # fmt: skip
"""The SVG elements a logo keeps: shapes, text, paint servers, clipping, masks and filters. Any
other element is dropped with everything inside it: ``script``, ``foreignObject``, ``image`` and
``feImage`` (they run or embed other content), the animation elements (they can turn an attribute
into a ``javascript:`` link), ``metadata`` and editors' own elements."""
_UNSAFE_CSS: Final[re.Pattern[str]] = re.compile(
    r"\\|@import|expression\s*\(|javascript:|url\s*\(\s*(?![\"']?\s*#)", re.IGNORECASE
)
"""CSS or an attribute value an SVG logo does not keep: an escape (it could spell any of the rest),
an import, an IE expression, a ``javascript:`` URL, or a ``url()`` that is not a ``#fragment``
of the same document."""
_PNG_SIGNATURE: Final[bytes] = b"\x89PNG\r\n\x1a\n"
"""The first bytes of every PNG file; its ``IHDR`` chunk follows with the size."""
_PNG_HEADER: Final[int] = 24
"""Bytes of a PNG up to the end of its size: signature, ``IHDR`` length and type, width, height."""
_WEBP_HEADER: Final[int] = 30
"""Bytes of a WebP up to the end of its size, whichever of the three formats it is."""
_VP8L_SIGNATURE: Final[int] = 0x2F
"""The byte a lossless WebP bitstream (``VP8L``) starts with, before its packed size."""
_JPEG_MARKER: Final[int] = 0xFF
"""The byte every JPEG marker starts with (also the fill byte between segments)."""
_JPEG_SIZE_SEGMENT: Final[int] = 7
"""Shortest start-of-frame segment that holds the image's size (length, precision, height, width).
"""
_JPEG_LENGTH_FIELD: Final[int] = 2
"""Bytes of a JPEG segment's length field, which the length counts: a smaller length is broken."""
_JPEG_STOP: Final[frozenset[int]] = frozenset({0xD9, 0xDA})
"""JPEG end of image and start of scan: with no frame header before them, the size is unknown."""
_JPEG_FRAMES: Final[frozenset[int]] = frozenset(
    {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
)
"""JPEG start-of-frame markers: the segment that holds the image's height and width."""
_JPEG_STANDALONE: Final[frozenset[int]] = frozenset(
    {0x01, 0xD0, 0xD1, 0xD2, 0xD3, 0xD4, 0xD5, 0xD6, 0xD7, 0xD8}
)
"""JPEG markers without a length (``TEM``, the restart markers, start of image)."""
_GITHUB_RAW_HOSTS: Final[frozenset[str]] = frozenset(
    {"raw.githubusercontent.com", "github.com", "www.github.com"}
)
"""Hosts of the absolute URLs a GitHub README gives its own images with (so that they show on
package indexes too): such a URL into the library's own repository names a file of the imported
commit, which is read from git like any other; nothing is fetched from the URL."""
