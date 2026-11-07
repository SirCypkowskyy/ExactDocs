"""What the library, docs and token commands do through ``ApiClient``, and how they print it.

Kept apart from ``cli.py`` so the work can be tested against an in-process server. Everything a
server (or a repository) sends is untrusted: human output goes through ``printable``, and JSON
output is ``json.dumps`` with its default ASCII escaping, so no control character reaches a
terminal either way.

Exit codes (``exit_code``): 0 done, 1 other failure, 2 usage or a rejected input, 3 not found,
4 conflict (an import is running, the library exists), 5 not signed in or refused, 6 an import
or a sync failed.
"""

import asyncio
import json
import os
import stat
import sys
import time
from collections.abc import Callable, Collection, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote

from exactdocs.bootstrap.client import (
    ApiClient,
    ApiError,
    ClientError,
    printable,
    printable_text,
)
from exactdocs.bootstrap.constants import (
    CONFLICT_STATUS,
    EXIT_AUTH,
    EXIT_CONFLICT,
    EXIT_FAILED,
    EXIT_IMPORT,
    EXIT_NOT_FOUND,
    EXIT_USAGE,
    LIBRARY_ID,
    MAX_REFS_SHOWN,
    MAX_SECRET_BYTES,
    PAGE,
    POLL_RETRIES,
    POLL_SECONDS,
    SYNC_FAILED_STATUS,
    TAG_MOVED,
    WAIT_SECONDS,
)


class ImportFailedError(ClientError):
    """An import job (or a sync) ended badly; the library itself is fine."""


class UsageError(ClientError):
    """The command line asks for something that cannot work; nothing was sent."""


def exit_code(error: ClientError) -> int:
    """Map a failure to the process exit status."""
    if isinstance(error, ImportFailedError):
        return EXIT_IMPORT
    if isinstance(error, UsageError):
        return EXIT_USAGE
    if isinstance(error, ApiError):
        by_status = {
            401: EXIT_AUTH,
            403: EXIT_AUTH,
            404: EXIT_NOT_FOUND,
            409: EXIT_CONFLICT,
            400: EXIT_USAGE,
            422: EXIT_USAGE,
        }
        return by_status.get(error.status, EXIT_FAILED)
    return EXIT_FAILED


def dump(data: object) -> None:
    """Print ``data`` as JSON for scripts."""
    sys.stdout.write(json.dumps(data, indent=2) + "\n")


def say(text: str) -> None:
    """Print one line of human output."""
    sys.stdout.write(printable(text) + "\n")


def table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    """Render left-aligned columns; cells are made printable first."""
    cells = [[printable(c) for c in row] for row in [headers, *rows]]
    widths = [max(len(row[i]) for row in cells) for i in range(len(headers))]
    return "\n".join(
        "  ".join(c.ljust(w) for c, w in zip(row, widths, strict=True)).rstrip() for row in cells
    )


def split_target(target: str) -> tuple[str, str | None]:
    """Split ``owner/repo`` or ``/owner/repo/ref`` (a ref may hold slashes) into library and ref."""
    owner, _, rest = target.strip().strip("/").partition("/")
    repo, _, ref = rest.partition("/")
    if not owner or not repo:
        message = f"{printable(target)!r} is not a library; use /owner/repo or /owner/repo/ref"
        raise UsageError(message)
    return f"{owner}/{repo}", ref or None


def _library_path(library: str) -> str:
    name, ref = split_target(library)
    if ref:
        message = f"expected a library (/owner/repo), not a version: {printable(library)!r}"
        raise UsageError(message)
    owner, repo = name.split("/")
    return f"/libraries/{quote(owner, safe='')}/{quote(repo, safe='')}"


async def _poll(api: ApiClient, job_id: str, interval: float) -> dict[str, Any]:
    """Fetch a job; retry a few times when the server or network hiccups."""
    failures = 0
    while True:
        try:
            return await api.request("GET", f"/jobs/{quote(job_id, safe='')}")
        except ApiError as exc:
            transient = exc.status >= 500  # ruff: ignore[magic-value-comparison]
            failures += 1
            if not transient or failures > POLL_RETRIES:
                message = f"lost track of job {job_id} ({exc}); it may still be running"
                raise ImportFailedError(message) from None
        except ClientError as exc:
            failures += 1
            if failures > POLL_RETRIES:
                message = f"lost track of job {job_id} ({exc}); it may still be running"
                raise ImportFailedError(message) from None
        await asyncio.sleep(interval)


async def wait_for_job(
    api: ApiClient,
    job_id: str,
    *,
    label: str,
    progress: Callable[[str], None] | None = None,
    interval: float = POLL_SECONDS,
    give_up_after: float = WAIT_SECONDS,
) -> dict[str, Any]:
    """Poll a job until it ends; report each change of state or count. Failure raises.

    Gives up after ``give_up_after`` seconds (the job goes on in the server) and says so when
    interrupted: the CLI only watches, it never owns the import.
    """
    try:
        return await _watch(api, job_id, label, progress, interval, give_up_after)
    except asyncio.CancelledError, KeyboardInterrupt:
        sys.stderr.write(f"stopped waiting; job {job_id} keeps running on the server\n")
        raise


async def _watch(
    api: ApiClient,
    job_id: str,
    label: str,
    progress: Callable[[str], None] | None,
    interval: float,
    give_up_after: float,
) -> dict[str, Any]:
    shown = None
    deadline = time.monotonic() + give_up_after
    while True:
        job = await _poll(api, job_id, interval)
        seen = (job["state"], job["done"], job["total"])
        if progress and seen != shown:
            counted = f" {job['done']}/{job['total']} files" if job["total"] else ""
            progress(f"{label}: {job['state']}{counted}")
            shown = seen
        if job["state"] == "succeeded":
            return job
        if job["state"] == "failed":
            reason = job.get("error") or "no reason recorded"
            code = f" [{printable(job['error_code'])}]" if job.get("error_code") else ""
            message = f"importing {label} failed{code}: {printable(reason)} (job {job_id})"
            raise ImportFailedError(message)
        if job["state"] not in {"queued", "running"}:
            message = f"job {job_id} is in the unknown state {printable(str(job['state']))!r}"
            raise ClientError(message)
        if time.monotonic() >= deadline:
            message = (
                f"still not done after {give_up_after:g} seconds; job {job_id} keeps running on "
                "the server (see it in the web UI)"
            )
            raise ImportFailedError(message)
        await asyncio.sleep(interval)


def _read_capped(path: str) -> bytes:
    """Return the file's bytes (one more than the cap if it is longer); refuse non-regular files."""
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK)  # a FIFO must not block us
    with os.fdopen(descriptor, "rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode):
            message = f"{printable(path)} is not a regular file"
            raise UsageError(message)
        if os.name == "posix" and info.st_mode & 0o077:
            to_stderr(f"warning: {printable(path)} is readable by others; run chmod 600")
        return handle.read(MAX_SECRET_BYTES + 1)


def read_secret(path: str) -> str:
    """Read a token or key file; refuse what cannot be one, warn when others can read it.

    The content never appears in a message. A file over the cap is refused, not cut off.
    """
    try:
        data = _read_capped(path)
        text = data.decode("utf-8")
    except (OSError, UnicodeError) as exc:
        message = f"cannot read {printable(path)} ({exc.__class__.__name__})"
        raise UsageError(message) from None
    if len(data) > MAX_SECRET_BYTES:
        message = f"{printable(path)} is over {MAX_SECRET_BYTES // 1024} KB: not a token or key"
        raise UsageError(message)
    if not text.strip():
        message = f"{printable(path)} is empty"
        raise UsageError(message)
    return text


def to_stderr(line: str) -> None:
    """Progress goes to stderr so ``--json`` output on stdout stays parseable."""
    sys.stderr.write(printable(line) + "\n")


def _finished(job: dict[str, Any]) -> str:
    skipped = sum(1 for p in job["problems"] if p["is_skip"])
    return f"imported {job['done']} files" + (f", skipped {skipped}" if skipped else "")


def parse_tag_rules(tag_rules: Sequence[str]) -> list[dict[str, str]]:
    """Turn ``PATTERN=TAG`` arguments into the API's tag rules; a malformed one is a usage error."""
    rules = []
    for rule in tag_rules:
        pattern, _, tag = rule.rpartition("=")
        if not pattern or not tag:
            message = (
                f"{printable(rule)!r} is not a tag rule; use PATTERN=TAG, e.g. 'docs/api/**=api'"
            )
            raise UsageError(message)
        rules.append({"pattern": pattern, "tag": tag})
    return rules


async def add_library(
    api: ApiClient,
    url: str,
    *,
    library_id: str | None = None,
    ref: str | None = None,
    include: Sequence[str] = (),
    exclude: Sequence[str] = (),
    tag_rules: Sequence[str] = (),
    credential: dict[str, str] | None = None,
    wait: bool = False,
    as_json: bool = False,
    interval: float = POLL_SECONDS,
    give_up_after: float = WAIT_SECONDS,
) -> None:
    """``POST /libraries``, then optionally follow the import job."""
    rules = parse_tag_rules(tag_rules)
    body: dict[str, Any] = {
        "url": url,
        "library_id": library_id,
        "ref": ref,
        "include_paths": list(include),
        "exclude_paths": list(exclude),
        "tag_rules": rules,
        "credential": credential,
    }
    added = await api.request("POST", "/libraries", json={k: v for k, v in body.items() if v})
    await _report_added(
        api, added, wait=wait, as_json=as_json, interval=interval, give_up_after=give_up_after
    )


async def preview_import(
    api: ApiClient,
    url: str,
    *,
    ref: str | None = None,
    include: Sequence[str] = (),
    exclude: Sequence[str] = (),
    credential: dict[str, str] | None = None,
    as_json: bool = False,
) -> None:
    """``add --dry-run``: ``POST /repositories/preview`` with what ``add`` would send.

    Prints the files an import would take, how many there are and whether the list was cut;
    no sizes (the server would have to download every file to know them). Nothing is stored.
    """
    body: dict[str, Any] = {
        "url": url,
        "ref": ref,
        "include_paths": list(include),
        "exclude_paths": list(exclude),
        "credential": credential,
    }
    preview = await api.request(
        "POST", "/repositories/preview", json={k: v for k, v in body.items() if v}
    )
    if as_json:
        dump(preview)
        return
    files, total = preview["files"], preview["total"]
    kind = preview["ref_kind"]
    sha = "" if kind == "commit" else f", {preview['commit_sha'][:9]}"  # the ref is the SHA
    where = f"{preview['ref']} ({kind}{sha})"
    if not total:
        say(f"Dry run of {where}: no file matches; check --path and --exclude. Nothing stored.")
        return
    noun = "file" if total == 1 else "files"
    say(f"Dry run of {where}: an import would take {total} {noun}. Nothing stored.")
    for path in files:
        say(path)
    if preview["truncated"]:
        say(f"... truncated: {len(files)} of {total} files listed.")


async def add_version(
    api: ApiClient,
    library: str,
    ref: str,
    *,
    credential: dict[str, str] | None = None,
    wait: bool = False,
    as_json: bool = False,
    interval: float = POLL_SECONDS,
    give_up_after: float = WAIT_SECONDS,
) -> None:
    """``POST /libraries/{owner}/{repo}/versions``, then optionally follow the import job."""
    body = {"ref": ref} | ({"credential": credential} if credential else {})
    added = await api.request("POST", f"{_library_path(library)}/versions", json=body)
    await _report_added(
        api, added, wait=wait, as_json=as_json, interval=interval, give_up_after=give_up_after
    )


async def _report_added(
    api: ApiClient,
    added: dict[str, Any],
    *,
    wait: bool,
    as_json: bool,
    interval: float,
    give_up_after: float,
) -> None:
    what = f"{added['library_id']}@{added['ref']}"
    job = None
    if wait:
        job = await wait_for_job(
            api,
            added["job_id"],
            label=what,
            progress=to_stderr,
            interval=interval,
            give_up_after=give_up_after,
        )
    if as_json:
        dump({"added": added, "job": job})
        return
    sha = added["commit_sha"][:9]
    say(f"Added {what} ({added['ref_kind']}, {sha}); import job {added['job_id']}.")
    if job:
        say(f"Done: {_finished(job)}.")
    else:
        say("The import runs in the background; follow it with --wait or in the web UI.")


async def list_libraries(api: ApiClient, *, as_json: bool = False) -> None:
    """``GET /libraries``, every page."""
    libraries: list[dict[str, Any]] = []
    cursor = None
    while True:
        params = {"limit": PAGE} | ({"cursor": cursor} if cursor else {})
        page = await api.request("GET", "/libraries", params=params)
        libraries += page["libraries"]
        if not (cursor := page["next_cursor"]):
            break
    if as_json:
        dump({"libraries": libraries})
        return
    if not libraries:
        say("No libraries yet; add one with `exactdocs add <git-url>`.")
        return
    rows = [
        [
            lib["id"],
            ", ".join(
                r["ref"] + ("*" if r["is_default"] else "") for r in lib["refs"][:MAX_REFS_SHOWN]
            )
            + (f" (+{lib['version_count'] - MAX_REFS_SHOWN} more)"
               if lib["version_count"] > MAX_REFS_SHOWN else ""),
            lib["title"],
        ]
        for lib in libraries
    ]  # fmt: skip
    say(table(["LIBRARY", "VERSIONS (* default)", "TITLE"], rows))


async def _follow(
    api: ApiClient, synced: dict[str, Any], interval: float, give_up_after: float
) -> tuple[dict[str, Any], ClientError | None]:
    """Wait for every queued import of a sync; the jobs by ref, and the first failure."""
    jobs: dict[str, Any] = {}
    failure = None
    for version in synced["versions"]:
        if version["status"] != "queued":
            continue
        label = f"{synced['library_id']}@{version['ref']}"
        try:
            jobs[version["ref"]] = await wait_for_job(
                api,
                version["job_id"],
                label=label,
                progress=to_stderr,
                interval=interval,
                give_up_after=give_up_after,
            )
        except ImportFailedError as exc:
            failure = failure or exc
    return jobs, failure


async def _reimport_moved_tags(
    api: ApiClient, library: str, synced: dict[str, Any], wanted: Collection[str] | None
) -> list[dict[str, Any]]:
    """Re-import, in place in ``synced``, the tags the sync reported as ``tag_moved``.

    ``wanted`` names the tags to confirm (``None``: every moved tag). Returns the rows whose
    re-import was queued. A tag whose re-import is refused (it moved back, an import of it started
    meanwhile...) stays ``failed``, with the refusal as its code and reason.
    """
    path = f"{_library_path(library)}/versions/reimport"
    queued = []
    for version in synced["versions"]:
        if version["status"] != "failed" or version.get("error_code") != TAG_MOVED:
            continue
        if wanted is not None and version["ref"] not in wanted:
            continue
        try:
            reimported = await api.request("POST", path, json={"ref": version["ref"]})
        except ApiError as exc:
            version.update(error_code=exc.code, error=exc.detail)
            continue
        version.update(
            status="queued",
            previous_commit_sha=reimported["previous_commit_sha"],
            commit_sha=reimported["commit_sha"],
            job_id=reimported["job_id"],
            error_code=None,
            error=None,
        )
        queued.append(version)
    return queued


async def _sync(api: ApiClient, library: str, *, confirming: str | None) -> dict[str, Any]:
    """``POST .../sync``: a 422 (the remote could not be read) is a failed sync, exit 6.

    ``confirming`` is the confirmation flag the user passed, named in the hint of a 409.
    """
    try:
        return await api.request("POST", f"{_library_path(library)}/sync")
    except ApiError as exc:
        if exc.status == CONFLICT_STATUS and confirming:
            # Nothing was checked, so no moved tag was seen either: say when to confirm.
            detail = f"{exc.detail}; run the sync with {confirming} again once that import finished"
            raise ApiError(exc.status, exc.code, detail) from None
        if exc.status != SYNC_FAILED_STATUS:
            raise
        message = f"sync of {printable(library)} failed [{printable(exc.code)}]: {exc.detail}"
        raise ImportFailedError(message) from None


async def sync_library(
    api: ApiClient,
    library: str,
    *,
    confirm: bool | Collection[str] = False,
    wait: bool = False,
    as_json: bool = False,
    interval: float = POLL_SECONDS,
    give_up_after: float = WAIT_SECONDS,
) -> None:
    """``POST /libraries/{owner}/{repo}/sync``; ``--wait`` follows every queued import.

    ``confirm`` re-imports tags the sync reports as moved at their new commit
    (``POST .../versions/reimport``): ``True`` every one of them, a collection of refs only those.
    They are followed like a queued branch, and each one's old and new commit is printed. Any
    version that could not be synced (the remote could not be read, a branch or tag is gone, a tag
    moved and was not confirmed, a named tag did not move, a queued import failed) raises
    ``ImportFailedError`` naming each reason and code.
    """
    wanted = None if confirm is True else set(confirm or ())
    flag = None if not confirm else "--confirm" if confirm is True else "--confirm-tag"
    synced = await _sync(api, library, confirming=flag)
    reimported = await _reimport_moved_tags(api, library, synced, wanted) if confirm else []
    versions = synced["versions"]
    jobs: dict[str, Any] = {}
    failure = None
    if wait:
        jobs, failure = await _follow(api, synced, interval, give_up_after)
    if as_json:
        dump({"library": synced["library_id"], "versions": versions, "jobs": jobs})
    else:
        rows = [[v["ref"], v["ref_kind"], v["status"], v["commit_sha"][:9]] for v in versions]
        say(table(["REF", "KIND", "STATUS", "COMMIT"], rows))
        for v in reimported:  # a tag that moved is news even when confirmed: say from where
            say(
                f"{v['ref']}: re-import queued, "
                f"{v['previous_commit_sha'][:9]} -> {v['commit_sha'][:9]}"
            )
        queued = sum(v["status"] == "queued" for v in versions)
        if queued and not wait:
            say(f"{queued} import(s) queued; follow them with --wait or in the web UI.")
        for ref, job in jobs.items():
            say(f"{ref}: {_finished(job)}.")
    failed = [v for v in versions if v["status"] == "failed"]
    moved = {v["ref"] for v in reimported} | {
        v["ref"] for v in failed if v.get("error_code") == TAG_MOVED
    }
    unmoved = sorted((wanted or set()) - moved - {v["ref"] for v in failed})
    if failure or failed or unmoved:
        parts = [str(failure)] if failure else []
        parts += [_sync_failure(v) for v in failed]
        parts += [
            f"{printable(ref)} was not re-imported: the sync did not report it as a moved tag"
            for ref in unmoved
        ]
        if any(v.get("error_code") == TAG_MOVED for v in failed):
            parts.append(
                f"re-import moved tags at their new commit with "
                f"`exactdocs sync {printable(library)} --confirm`"
            )
        raise ImportFailedError("; ".join(parts))


def _sync_failure(version: dict[str, Any]) -> str:
    code = f" [{printable(version['error_code'])}]" if version.get("error_code") else ""
    reason = printable(version.get("error") or "see the jobs")
    return f"sync of {printable(version['ref'])} failed{code}: {reason}"


def removal_prompt(target: str) -> str:
    """Return the question asked before a removal."""
    library, ref = split_target(target)
    what = f"version {ref} of /{library}" if ref else f"/{library} with all its versions"
    return f"Remove {what}? Its imported content is deleted. [y/N] "


async def remove(api: ApiClient, target: str, *, as_json: bool = False) -> None:
    """``DELETE`` a version (``/owner/repo/ref``) or a whole library (``/owner/repo``)."""
    library, ref = split_target(target)
    path = _library_path(library) + (f"/versions/{quote(ref, safe='/')}" if ref else "")
    result = await api.request("DELETE", path)
    if as_json:
        dump(result)
        return
    what = f"{result['ref']} of {result['library']}" if result["ref"] else result["library"]
    say(f"Removed {what}.")
    if result["ref"] and result["default_version"]:
        say(f"{result['library']} now resolves to {result['default_version']}.")


async def create_token(api: ApiClient, name: str, days: int | None) -> dict[str, Any]:
    """``POST /tokens`` (a session is needed) and return the grant; ``days=None`` never expires."""
    body: dict[str, Any] = {"name": name}
    if days is not None:
        body["expires_at"] = (datetime.now(UTC) + timedelta(days=days)).isoformat()
    return await api.request("POST", "/tokens", json=body)


async def token_create(api: ApiClient, name: str, days: int | None, *, as_json: bool) -> None:
    """Create a token; the secret is shown this once."""
    grant = await create_token(api, name, days)
    if as_json:
        dump(grant)
        return
    say(f"Created token {grant['name']!r} ({grant['id']}); copy it now, it is not shown again:")
    sys.stdout.write(printable(grant["token"]) + "\n")


async def token_list(api: ApiClient, *, as_json: bool) -> None:
    """``GET /tokens``."""
    tokens = (await api.request("GET", "/tokens"))["tokens"]
    if as_json:
        dump({"tokens": tokens})
        return
    rows = [
        [t["id"], t["name"], t["prefix"] + "...", (t["expires_at"] or "never")[:10],
         (t["last_used_at"] or "never")[:10]]
        for t in tokens
    ]  # fmt: skip
    say(table(["ID", "NAME", "PREFIX", "EXPIRES", "LAST USED"], rows))


async def token_revoke(api: ApiClient, token_id: str) -> None:
    """``DELETE /tokens/{id}``."""
    await api.request("DELETE", f"/tokens/{quote(token_id, safe='')}")
    say(f"Revoked token {token_id}.")


def _one_line(text: str) -> str:
    return " ".join(text.split())


async def find_library(
    api: ApiClient, name: str, query: str | None, *, as_json: bool = False
) -> None:
    """``ctx7 library``: ``GET /c7/search``; a missing query defaults to the name."""
    found = await api.request(
        "GET", "/c7/search", params={"libraryName": name, "query": query or name}
    )
    results = found["results"]
    if as_json:  # ctx7 prints the bare list; the notice goes to stderr to keep stdout parseable
        to_stderr(found["notice"])
        dump(results)
        return
    say(found["notice"])
    if not results:
        say(f"No libraries found matching {name!r}")
        return
    for number, entry in enumerate(results, 1):
        say("")
        say(f"{number}. Title: {_one_line(entry['title'])}")
        say(f"   Context7-compatible library ID: {_one_line(entry['id'])}")
        say(f"   Description: {_one_line(entry['description'])}")
        say(f"   Default version: {_one_line(entry['defaultVersion'])}")
        say(f"   Articles: {entry['articles']}")
        say(f"   Chunks: {entry['totalSnippets']}")
        say(f"   Versions: {', '.join(_one_line(v) for v in entry['versions'])}")
        say(f"   Source: {_one_line(entry['sourceUrl'])}")


async def query_docs(
    api: ApiClient, library_id: str, query: str, *, language: str | None = None, as_json: bool
) -> None:
    """``ctx7 docs``: ``GET /c7/docs``. The text keeps the server's notice and line breaks."""
    if not LIBRARY_ID.match(library_id):
        message = (
            f"invalid library ID {printable(library_id)!r}; expected /owner/repo, "
            "/owner/repo/version or /owner/repo@version (find it with `exactdocs library <name>`)"
        )
        raise UsageError(message)
    params = {"libraryId": library_id, "query": query, "type": "json" if as_json else "txt"}
    if language:
        params["language"] = language
    if as_json:
        dump(await api.request("GET", "/c7/docs", params=params))
        return
    text = printable_text(await api.request_text("GET", "/c7/docs", params=params))
    sys.stdout.write(text if text.endswith("\n") else text + "\n")
