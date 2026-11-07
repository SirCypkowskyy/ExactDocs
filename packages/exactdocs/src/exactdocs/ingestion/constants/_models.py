"""Constants of the models: limits, patterns and defaults of libraries, versions and jobs."""

import re
from datetime import timedelta
from typing import Final, Literal, NewType

type ChunkerName = Literal["markdown"]
"""The chunkers ExactDocs has."""
PARSER_VERSION: Final[int] = 3
"""Bump on any change to the sanitizer or the parser. It feeds the chunking-config hash (E4-02), so
a fix here re-chunks stored articles instead of reusing stale chunk sets.
"""
CHUNKER_VERSION: Final[int] = 1
"""Bump on any change to how a chunker cuts articles. Like PARSER_VERSION it feeds the config hash.
"""
MERGED_HEADINGS_VERSION: Final[int] = 1
"""Bump on any change to the heading records of chunks that hold more than one heading (#251). It
feeds the hash of the configs that can merge headings (a split level above h6, or ``min_chars``),
so those libraries' chunk sets are cut again when they are next imported or re-chunked.
"""
MAX_HEADING_LEVEL: Final[int] = 6
"""Deepest Markdown heading level a chunking config may split at."""
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
"""Upper bound of ``min_chars`` and ``max_chars``: bigger is no bound at all (a whole article)."""
_SHA_PREFIX: Final[re.Pattern[str]] = re.compile(r"[0-9a-f]{7,64}")
"""An abbreviated or full commit SHA."""
ARTICLE_SUFFIXES: Final[tuple[str, ...]] = (".md", ".mdx")
"""File suffixes of articles: everything else in a repository is ignored."""
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
