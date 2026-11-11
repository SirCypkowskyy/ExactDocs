"""Repo guidance for the agentic explorer (RET-08): harness Repo Context over stored files.

Loaded by ``ai_explorer_sdk`` only, so only once an agentic search runs. A library's
``AGENTS.md`` / ``CLAUDE.md`` files are kept with each version's manifest in the database; a run
gets the files of the manifest it searches (``GuidanceFiles``, already bounded and with every
``<context>`` tag defused) as a **read-only workspace** that holds those files and nothing else:
no checkout, no host path, no command. Harness ``RepoContext`` reads them from it:

- **nested traversal** (always): when the agent opens a folder (lists it, or reads an article or
  a chunk in it), that folder's file is enqueued as a **user-channel** note, inside a
  ``<context-file>`` block, never as system instructions;
- **walk-up autoload** (only for a trusted library): the root's file becomes part of the system
  instructions too.

The read tools are not file tools, so ``Traversals`` emits the harness's ``DirectoryListedEvent``
/ ``FileReadEvent`` after each read the way ``FileSystem`` would; RepoContext listens for them.
Nothing here can add a tool, change a limit or reach another version: the tools, the browser and
the bounds are fixed before the run, and the workspace only answers for the files it was given.
"""

import posixpath
from collections.abc import AsyncGenerator, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from typing import Any, Never

from pydantic_ai import RunContext
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.messages import (
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelResponse,
    ToolCallPart,
)
from pydantic_ai.models import CompletedStreamedResponse, ModelRequestParameters, StreamedResponse
from pydantic_ai.models.wrapper import WrapperModel
from pydantic_ai.settings import ModelSettings
from pydantic_ai.tools import ToolDefinition
from pydantic_ai.workspaces import (
    FileEntry,
    ReadOnlyWorkspace,
    Workspace,
    WorkspaceReadOnlyError,
    WorkspaceRef,
)
from pydantic_ai_harness.filesystem import DirectoryListedEvent, FileReadEvent
from pydantic_ai_harness.repo_context import RepoContext

from exactdocs.retrieval.constants import (
    GUIDANCE_CHUNK_READ,
    GUIDANCE_FOLDER_READS,
    GUIDANCE_LISTING,
    GUIDANCE_READ_ONLY,
    GUIDANCE_ROOT,
    INSTRUCTION_FILE_NAMES,
)
from exactdocs.retrieval.models import GuidanceFiles, estimated_tokens


def _absolute(path: str) -> str:
    """Place a repository path in the workspace.

    Args:
        path: Repository-relative.

    Returns:
        Its absolute, normalized path under ``GUIDANCE_ROOT``.
    """
    return posixpath.normpath(posixpath.join(GUIDANCE_ROOT, path))


def _folders(paths: Sequence[str]) -> frozenset[str]:
    """Name every folder that holds a file, up to the root.

    Args:
        paths: The files' absolute paths.

    Returns:
        The folders, the root included.
    """
    found = {GUIDANCE_ROOT}
    for path in paths:
        folder = posixpath.dirname(path)
        while folder.startswith(GUIDANCE_ROOT) and folder not in found:
            found.add(folder)
            folder = posixpath.dirname(folder)
    return frozenset(found)


@dataclass(frozen=True, slots=True, kw_only=True)
class GuidanceBackend:
    """A workspace backend over one version's stored instruction files, in memory and read-only.

    Implements pydantic-ai's ``WorkspaceBackend``, ``SupportsFilesystem`` and
    ``SupportsRealpath`` structurally. It holds the files of the ``GuidanceFiles`` it was built
    from and the folders above them; every other path is missing, a write or a removal is
    refused, and there are no commands (``ReadOnlyWorkspace`` refuses them too) and no symlinks.
    """

    files: Mapping[str, bytes]
    """Each file's text (UTF-8) by its absolute path in the workspace."""
    folders: frozenset[str] = field(default_factory=frozenset)
    """Every folder above a file, the root included."""

    @classmethod
    def of(cls, guidance: GuidanceFiles) -> GuidanceBackend:
        """Hold a run's files.

        Args:
            guidance: The files of the searched manifest.

        Returns:
            The backend.
        """
        files = {_absolute(f.path): f.content.encode() for f in guidance.files}
        return cls(files=files, folders=_folders(list(files)))

    @property
    def ref(self) -> WorkspaceRef | None:
        """Name no environment: there is nothing to attach to later.

        Returns:
            None.
        """
        return None

    async def working_dir(self) -> str:
        """The repository's root.

        Returns:
            ``GUIDANCE_ROOT``.
        """
        return GUIDANCE_ROOT

    async def read_bytes(self, path: str) -> bytes:
        """Read a file.

        Args:
            path: Absolute.

        Returns:
            Its bytes.

        Raises:
            IsADirectoryError: The path is a folder.
            FileNotFoundError: The workspace has no such file.
        """
        if path in self.folders:
            raise IsADirectoryError(path)
        if path not in self.files:
            raise FileNotFoundError(path)
        return self.files[path]

    async def stat(self, path: str) -> FileEntry:
        """Describe a file or folder.

        Args:
            path: Absolute.

        Returns:
            Its entry.

        Raises:
            FileNotFoundError: The workspace has no such path.
        """
        name = posixpath.basename(path)
        if path in self.files:
            return FileEntry(name=name, path=path, is_dir=False, size=len(self.files[path]))
        if path in self.folders:
            return FileEntry(name=name, path=path, is_dir=True, size=None)
        raise FileNotFoundError(path)

    async def list_dir(self, path: str) -> Sequence[FileEntry]:
        """List a folder's files and folders (not recursive).

        Args:
            path: Absolute.

        Returns:
            Its entries, by name.

        Raises:
            FileNotFoundError: The workspace has no such folder.
        """
        if path not in self.folders:
            raise FileNotFoundError(path)
        inside = [p for p in (*self.files, *self.folders) if posixpath.dirname(p) == path]
        return [await self.stat(p) for p in sorted(inside) if p != path]

    async def exists(self, path: str) -> bool:
        """Say whether a file or folder exists.

        Args:
            path: Absolute.

        Returns:
            True for a held file or a folder above one.
        """
        return path in self.files or path in self.folders

    async def realpath(self, path: str) -> str:
        """Resolve a path: there are no symlinks, so only normalize it.

        Args:
            path: Absolute.

        Returns:
            The normalized path.
        """
        return posixpath.normpath(path)

    async def write_bytes(self, path: str, data: bytes) -> Never:
        """Refuse.

        Args:
            path: Ignored.
            data: Ignored.

        Raises:
            WorkspaceReadOnlyError: Always.
        """
        del path, data
        raise WorkspaceReadOnlyError(GUIDANCE_READ_ONLY)

    async def make_dir(self, path: str) -> Never:
        """Refuse.

        Args:
            path: Ignored.

        Raises:
            WorkspaceReadOnlyError: Always.
        """
        del path
        raise WorkspaceReadOnlyError(GUIDANCE_READ_ONLY)

    async def remove(self, path: str) -> Never:
        """Refuse.

        Args:
            path: Ignored.

        Raises:
            WorkspaceReadOnlyError: Always.
        """
        del path
        raise WorkspaceReadOnlyError(GUIDANCE_READ_ONLY)


def _folder_of_listing(prefix: object) -> str | None:
    """Name the folder ``list_articles`` opened, relative to the root.

    Args:
        prefix: Its ``prefix`` argument.

    Returns:
        The folder (``.`` for the root), or ``None`` for an argument that is not text.
    """
    if not isinstance(prefix, str):
        return None
    return prefix.strip("/") or "."


@dataclass(slots=True, kw_only=True)  # conventions: allow-mutable-dataclass -- capability base
class Traversals(AbstractCapability[object]):
    """Tells RepoContext which folders the agent opened, as the harness's filesystem would.

    After a read tool returns (inside ``run_code`` too), it emits ``DirectoryListedEvent`` for
    ``list_articles(prefix)`` and ``FileReadEvent`` for an article an outline, an article or a
    chunk read found. Paths are relative to the workspace root; RepoContext ignores any that
    leads out of it. With ``skip_root`` (a trusted library) the root is not reported: its file
    is in the system instructions already.
    """

    skip_root: bool = False
    """Do not report the root (its file is autoloaded)."""

    async def after_tool_execute(
        self,
        ctx: RunContext[object],
        *,
        call: ToolCallPart,
        tool_def: ToolDefinition,
        args: dict[str, object],
        result: object,
    ) -> object:
        """Report the folder the read opened, then hand the result on unchanged.

        Args:
            ctx: The run.
            call: The tool call.
            tool_def: The tool's definition.
            args: Its validated arguments.
            result: What it returned.

        Returns:
            ``result``.
        """
        del tool_def
        if call.tool_name == GUIDANCE_LISTING and isinstance(result, Sequence) and result:
            folder = _folder_of_listing(args.get("prefix", ""))
            if folder is not None and not (self.skip_root and folder == "."):
                event = DirectoryListedEvent(
                    path=folder, root_dir=GUIDANCE_ROOT, entry_count=len(result)
                )
                await ctx.emit(event)
            return result
        path = self._article(call.tool_name, args, result)
        if path is not None and not (self.skip_root and "/" not in path.strip("/")):
            await ctx.emit(FileReadEvent(path=path, root_dir=GUIDANCE_ROOT, content_hash=""))
        return result

    @staticmethod
    def _article(tool: str, args: Mapping[str, object], result: object) -> str | None:
        """Name the article a read found.

        Args:
            tool: The read tool.
            args: Its arguments.
            result: What it returned.

        Returns:
            The article's path, or ``None`` when the read found none (or named no article).
        """
        if not isinstance(result, Mapping) or not result.get("found"):
            return None
        if tool in GUIDANCE_FOLDER_READS:
            found = args.get(GUIDANCE_FOLDER_READS[tool])
        elif tool == GUIDANCE_CHUNK_READ:
            found = result.get("article_path")
        else:
            return None
        return found if isinstance(found, str) and found else None


def guidance_capabilities(guidance: GuidanceFiles) -> list[AbstractCapability[object]]:
    """The capabilities that give a run its repo guidance.

    Args:
        guidance: The searched manifest's files.

    Returns:
        RepoContext (nested notes on the user channel; the root's file as system instructions
        only for a trusted library, no inventory tool) and ``Traversals``.
    """
    return [
        RepoContext(
            filenames=INSTRUCTION_FILE_NAMES,
            autoload_instructions=guidance.trusted,
            expose_inventory_tool=False,
            nested_traversal=True,
            nested_inject="contents",
        ),
        Traversals(skip_root=guidance.trusted),
    ]


def guidance_workspace(guidance: GuidanceFiles) -> Workspace:
    """The read-only workspace that holds a run's files and nothing else.

    Args:
        guidance: The searched manifest's files.

    Returns:
        The workspace to run the agent in.
    """
    return ReadOnlyWorkspace(Workspace(GuidanceBackend.of(guidance)))


def _estimated_tokens(text: bytes) -> int:
    """Estimate tokens from serialized text with ``models.estimated_tokens``.

    The bytes are read as UTF-8, so a CJK character counts as a token, not as 3 bytes over
    ``CHARS_PER_TOKEN``.

    Args:
        text: The serialized messages or response (UTF-8).

    Returns:
        At least one token.
    """
    return max(1, estimated_tokens(text.decode("utf-8", errors="replace")))


class UsageFloor(WrapperModel):
    """Counts a streamed response at least by its characters (RET-08).

    Repo guidance makes every model request of the run stream (RepoContext listens to its
    events). A server that ignores ``stream_options.include_usage`` reports zero (or a token
    count it made up), so the run's ``UsageLimits`` and ``SpendLimits`` would count nothing for
    exactly the runs that carry the most untrusted text. Each side of a streamed response
    counts as the larger of what it reports and ``models.estimated_tokens`` (4 characters per
    token for ASCII, 1.5 in long runs without whitespace, 4 tokens above U+FFFF, a token per other
    character: input from the request's serialized messages, output from the response's parts).
    The estimate can still undercount dense code, so an honest report is kept. The stream is read
    whole before it is handed on (nothing of it is shown to anyone meanwhile).
    """

    @asynccontextmanager
    async def request_stream(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
        run_context: RunContext[Any] | None = None,
    ) -> AsyncGenerator[StreamedResponse]:
        """Stream the wrapped model's response, then replay it with its usage made countable.

        Args:
            messages: The request.
            model_settings: Its settings.
            model_request_parameters: Its tools and output.
            run_context: The run.

        Yields:
            The response, as a stream of its parts.
        """
        async with self.wrapped.request_stream(
            messages, model_settings, model_request_parameters, run_context
        ) as stream:
            async for _ in stream:
                pass
            response = stream.get()
        yield CompletedStreamedResponse(
            _counted(response, messages),
            model_request_parameters=model_request_parameters,
            replay_events=True,
        )


def _counted(response: ModelResponse, messages: Sequence[ModelMessage]) -> ModelResponse:
    """Count each side of a response as at least its character estimate.

    Args:
        response: What the stream gave.
        messages: The request it answered.

    Returns:
        The response as it is when its usage covers the estimate, else with the estimate.
    """
    sent = _estimated_tokens(ModelMessagesTypeAdapter.dump_json(list(messages)))
    received = _estimated_tokens(ModelMessagesTypeAdapter.dump_json([response]))
    reported = response.usage
    if reported.input_tokens >= sent and reported.output_tokens >= received:
        return response
    usage = replace(
        reported,
        input_tokens=max(reported.input_tokens, sent),
        output_tokens=max(reported.output_tokens, received),
    )
    return replace(response, usage=usage)
