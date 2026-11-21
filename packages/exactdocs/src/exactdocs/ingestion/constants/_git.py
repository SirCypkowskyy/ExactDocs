"""Constants of the git command-line adapter: timeouts, limits, git configuration."""

import os
import re
from typing import Final

from exactdocs.ingestion.constants._models import CONTEXT7_FILE

TIMEOUT_SECONDS: Final[float] = 15.0
"""How long a quick git command (listing refs) may take."""
MAX_PROCESSES: Final[int] = 4
"""Git processes that may run at once."""
ALLOWED_PROTOCOLS: Final[str] = "file:http:https:ssh"
"""Transports git may use (``GIT_ALLOW_PROTOCOL``)."""
MAX_STDOUT: Final[int] = 16 * 1024 * 1024
"""Most output read from one git command, in bytes."""
MAX_STDERR: Final[int] = 64 * 1024
"""Most error output read from one git command, in bytes."""
FETCH_TIMEOUT_SECONDS: Final[float] = 300.0
"""How long fetching one version may take."""
MAX_FETCHES: Final[int] = 2
"""Fetches that may run at once."""
MAX_PREVIEWS: Final[int] = 2
"""Repository previews that may run at once."""
PREVIEW_WAIT_SECONDS: Final[float] = 5.0
"""How long a preview waits for a free slot before it reports the server busy."""
MAX_FETCH_FILES: Final[int] = 100_000
"""Most files one fetch may check out."""
WATCH_SECONDS: Final[float] = 1.0
"""How often a running fetch checks its size on disk."""
STALE_MARGIN_SECONDS: Final[float] = 60.0
"""Extra time after the fetch timeout before a left-over work folder counts as abandoned."""
MAX_FETCH_BYTES: Final[int] = 512 * 2**20
"""Most bytes one fetch may write to disk."""
RENAME_TIMEOUT_SECONDS: Final[float] = 60.0
"""How long finding the renames between two versions may take."""
RENAME_LIMIT: Final[int] = 400
"""Git's ``-l``: above this many files on each side, renames are not searched by similarity."""
_MAX_STEP_OUTPUT: Final[int] = 1024 * 1024
"""Most output read from one step of a fetch, in bytes."""
_MAX_BRACE_EXPANSIONS: Final[int] = 64
"""Most paths one ``{a,b}`` pattern may expand to for a sparse checkout."""
_DRAIN_SECONDS: Final[float] = (
    2.0  # for a killed process's pipes to reach EOF and its exit to be seen
)
"""For a killed process's pipes to reach EOF and its exit to be seen."""
_KEYGEN_SECONDS: Final[float] = 5.0
"""How long checking a deploy key with ``ssh-keygen`` may take."""
_PREFIX: Final[str] = "fetch-"
"""Name prefix of a fetch's work folder."""
_ROOT_README: Final[tuple[str, ...]] = ("/README.md", "/README.mdx")
"""Paths of a repository's root README."""
_ROOT_CONTEXT7: Final[str] = f"/{CONTEXT7_FILE}"
"""Last: no exclusion can drop it."""
_ROOT_NAME: Final[re.Pattern[str]] = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._-]*")
"""One plain name, never an option or glob."""
_ARTICLE_PATHSPEC: Final[tuple[str, ...]] = (
    ":(icase)*.md",
    ":(icase)*.mdx",
    ":(icase)*.rst",
    ":(icase)*.txt",
)
"""Models.ARTICLE_SUFFIXES, whatever the letter case: never fetch the blobs of other files."""
_GONE: Final[re.Pattern[str]] = re.compile(
    r"not our ref|unadvertised object|couldn't find remote ref|no such remote ref"
)
"""What servers say when they will not serve a bare SHA (or the ref we named instead)."""
_CONFIG: Final[str] = """\
[core]
\trepositoryformatversion = 1
\tsymlinks = false
\thooksPath = {null}
\tfsmonitor = false
\tprotectNTFS = true
\tprotectHFS = true
\tsparseCheckout = true
\tsparseCheckoutCone = false
[extensions]
\tpartialClone = origin
[gc]
\tauto = 0
[maintenance]
\tauto = false
[protocol]
\tversion = 2
[submodule]
\trecurse = false
[remote "origin"]
\turl = {url}
\tpromisor = true
\tpartialclonefilter = blob:none
"""
"""Git config of a fetch's repository: no hooks, no automatic maintenance, partial clone."""
_ATTRIBUTES: Final[str] = "* -text -filter -ident !eol !working-tree-encoding\n"
"""Git attributes that keep every file byte for byte as committed."""
_TOO_BIG: Final[str] = "the repository advertises too many refs"
"""Why a repository whose ref listing is too large is refused."""
_SHA: Final[re.Pattern[str]] = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
"""A full git object ID: SHA-1 (40) or SHA-256 (64) hex digits."""
_COMMIT: Final[re.Pattern[str]] = re.compile(r"[0-9a-f]{40}")
"""Fetches are SHA-1 only: no objectformat extension."""
_REF: Final[re.Pattern[str]] = re.compile(r"refs/[A-Za-z0-9._/+@-]+")
"""A ref name as git lists it."""
_NO_CONNECTION: Final[str] = "could not connect to it"
"""Why a repository that could not be reached is refused."""
_SYMREF: Final[str] = "ref: "
"""How ``ls-remote --symref`` marks the ref ``HEAD`` points to."""
_HEADS: Final[str] = "refs/heads/"
"""Prefix of branch refs."""
_PASSTHROUGH: Final[frozenset[str]] = frozenset(
    {
        "path",
        "systemroot",
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "no_proxy",
        "ssl_cert_file",
        "ssl_cert_dir",
        "curl_ca_bundle",
        "git_ssl_cainfo",
        "git_ssl_capath",
    }
)
"""Not secrets: where certificates live and which proxy to use, so corporate networks keep working.
fmt: skip.
"""
_SSH_BASE: Final[tuple[str, ...]] = (
    "ssh",
    "-F",
    os.devnull,
    "-o",
    "BatchMode=yes",
    "-o",
    "ConnectTimeout=10",
    "-o",
    "GSSAPIAuthentication=no",
    "-o",
    "HostbasedAuthentication=no",
    "-o",
    "KbdInteractiveAuthentication=no",
    "-o",
    "PasswordAuthentication=no",
    "-o",
    "StrictHostKeyChecking=accept-new",
    "-o",
    "GlobalKnownHostsFile=" + os.devnull,
    "-o",
    "UpdateHostKeys=no",
    "-o",
    "HashKnownHosts=no",
    "-o",
    "VerifyHostKeyDNS=no",
)
"""Ssh reads keys from the passwd-entry home (not $HOME) and from any agent, so every authentication
method is off unless a deploy key is given: a check must not borrow the server user's identity.
Host keys: remembered on first sight (`accept-new`), a changed one is refused; only our own file
is consulted, and the server cannot add keys to it (`UpdateHostKeys=no`). fmt: skip.
"""
_ASKPASS: Final[str] = """\
#!/bin/sh
d=$(dirname "$0")
base=$(cat "$d/askpass.base")
user=$(cat "$d/askpass.user" | tr '[:upper:]' '[:lower:]')
prompt=$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')
case "$prompt" in
  "username for '$base': ") cat "$d/askpass.user" ;;
  "password for '$base': ") cat "$d/askpass.secret" ;;
  "password for '${base%%://*}://$user@${base#*://}': ") cat "$d/askpass.secret" ;;
  *) exit 1 ;;
esac
"""
"""Git prints the prompt as `Username for 'scheme://host[:port]': ` and then `Password for
'scheme://user@host[:port]': `, with the host as typed in the URL. Only those two prompts, for
the library's own scheme and host (compared in lower case), are answered; a redirect to any other
host makes git ask for that host, which gets nothing. The values are read from files of the
call's private directory, so they are in no environment.
"""
_KEY_FILE: Final[str] = "deploy_key"
"""File a deploy key is written to for one git call."""
_ASKPASS_FILE: Final[str] = "askpass.sh"
"""Script that hands git a token for one call."""
_RUN_PREFIX: Final[str] = "exactdocs-git-"
"""Name prefix of one git call's private folder (credentials, home)."""
_HOST_KEY_CHANGED: Final[re.Pattern[str]] = re.compile(
    r"remote host identification has changed|host key verification failed"
    r"|offending (?:\w+ )?key in"
)
"""Wording of `git` (LC_ALL=C) and of the transports behind it. Narrow on purpose: a local error
("Permission denied" on a directory, a shell "not found") must not read as a remote verdict.
"""
_AUTH: Final[re.Pattern[str]] = re.compile(
    r"terminal prompts disabled|could not read (?:username|password)|authentication failed"
    r"|permission denied \(|error: 40[13]\b"
)
"""Git errors that mean the credential is missing or refused."""
_NOT_A_REPO: Final[re.Pattern[str]] = re.compile(
    r"does not appear to be a git repository|repository (?:'[^']*' )?not found|error: 404\b"
)
"""Git errors that mean the URL is not a git repository."""
_LINK_MODE: Final[str] = "120000"
"""A symlink's tree mode."""
_FILE_MODES: Final[frozenset[str]] = frozenset({"100644", "100755"})
"""A regular file's tree modes."""
_ENTRY_FIELDS: Final[int] = 3
"""``ls-tree``'s fields before the tab: mode, type, object."""
_MAX_LINK_BYTES: Final[int] = 1024
"""The longest link target followed."""
_GIT_OVERHEAD: Final[int] = 4 * 2**20
""".git of a one-commit, blob-less fetch: trees, refs, config."""
