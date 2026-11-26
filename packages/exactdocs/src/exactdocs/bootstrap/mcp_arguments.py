"""Take the arguments agents send as they mean them, before a tool validates them (#573).

Weaker models call tools loosely: an empty string for an argument they mean to leave out, a
``limit`` beyond the maximum, a library's name where its ID goes. A strict schema turns each of
those into a lost turn. This middleware, run on every ``tools/call`` before validation:

- drops an optional argument that is ``null`` or blank: it counts as not given;
- clamps a number outside its schema's ``minimum``/``maximum`` to the range, with a note;
- resolves a library name given as ``library`` or ``libraryId`` to the one library it means
  (retrieval's ``ResolveLibraryName``), with a note; no match or several is an error that lists
  the candidate IDs. A ``library`` holding ``/owner/repo/<ref>`` is split into the ID and ``ref``
  when the call gives no ``ref``;
- still refuses an argument the tool does not have, never ignoring it, but names the tool's real
  arguments in the error.

Notes go in the result: a last text block, and ``notes`` in the structured content of a tool that
has an output schema (each listed output schema declares it). The tool's own answer may carry
notes too, in its structured ``notes``: a ref read as the version it names but for a leading
``v`` (#605), resolved where every caller gets it, REST included. They join the middleware's.
"""

import re
from collections.abc import Mapping, Sequence
from typing import Any

from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools import Tool, ToolResult
from mcp import types as mt

from exactdocs.bootstrap.constants import (
    LIBRARY_ARGUMENTS,
    NOTES,
    NOTES_SCHEMA,
    VERSIONED_ID,
    WHOLE_NUMBER,
)
from exactdocs.retrieval.dtos import ResolveLibraryNameQuery
from exactdocs.retrieval.ports.driving import ResolveLibraryName
from exactdocs_kernel import LIBRARY_ID_PATTERN, DomainError


class LenientArguments(Middleware):
    """Normalize a tool call's arguments as the module docstring says, and report the changes."""

    def __init__(self, *, resolve_library_name: ResolveLibraryName) -> None:
        """Keep the port that resolves library names.

        Args:
            resolve_library_name: Picks the one library a name means, or says why not.
        """
        self._resolve = resolve_library_name

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        """Normalize the arguments, call the tool, and add the notes to its result.

        Args:
            context: The tool call.
            call_next: The rest of the middleware chain and the tool.

        Returns:
            The tool's result, with the notes when an argument was changed.
        """
        server = context.fastmcp_context.fastmcp if context.fastmcp_context else None
        tool = await server.get_tool(context.message.name) if server is not None else None
        if tool is None:  # an unknown tool: FastMCP says so
            return await call_next(context)
        arguments, notes = await self.normalized(tool, dict(context.message.arguments or {}))
        message = context.message.model_copy(update={"arguments": arguments})
        result = await call_next(context.copy(message=message))
        return with_notes(result, notes, structured=tool.output_schema is not None)

    async def on_list_tools(
        self,
        context: MiddlewareContext[mt.ListToolsRequest],
        call_next: CallNext[mt.ListToolsRequest, Sequence[Tool]],
    ) -> Sequence[Tool]:
        """Declare ``notes`` in every structured tool's output schema.

        Args:
            context: The listing.
            call_next: The rest of the middleware chain.

        Returns:
            The tools, each output schema with an optional ``notes`` property.
        """
        return [noted(tool) for tool in await call_next(context)]

    async def normalized(
        self, tool: Tool, arguments: Mapping[str, Any]
    ) -> tuple[dict[str, Any], list[str]]:
        """Return the arguments the tool gets, and a note for each one changed on the way.

        Args:
            tool: The tool called, with its input schema.
            arguments: The arguments as the client sent them.

        Returns:
            The arguments to validate, and the notes.

        Raises:
            ToolError: An argument the tool does not have, or a library name that names no
                library or several (with the domain error as the cause).
        """
        properties: Mapping[str, Mapping[str, Any]] = tool.parameters.get("properties", {})
        required = set(tool.parameters.get("required", []))
        unknown = sorted(set(arguments) - set(properties))
        if unknown:
            raise ToolError(unknown_arguments(tool.name, unknown, properties, required))
        kept = {
            name: value
            for name, value in arguments.items()
            if name in required or not _blank(value)  # an empty optional one: not given
        }
        notes: list[str] = []
        for name, value in kept.items():
            number, note = clamped(name, value, properties[name])
            kept[name] = number
            notes += [note] if note else []
        for name in sorted(LIBRARY_ARGUMENTS & set(kept)):
            notes += await self._library(name, kept, properties)
        return kept, notes

    async def _library(
        self, name: str, arguments: dict[str, Any], properties: Mapping[str, object]
    ) -> list[str]:
        """Put the library's ID in place of a name, in ``arguments``; split a versioned ID.

        Args:
            name: ``library`` or ``libraryId``.
            arguments: The call's arguments, changed in place.
            properties: The tool's arguments, to know whether it takes a ``ref``.

        Returns:
            The notes of what was changed; none when the argument was an ID already.

        Raises:
            ToolError: No library or several match the name; the domain error is the cause.
        """
        value = arguments[name]
        if not isinstance(value, str):
            return []  # left to validation
        text = value.strip()
        if name == "libraryId" and text.startswith("/"):
            return []  # an ID, with or without its version: query-docs reads it
        if re.fullmatch(LIBRARY_ID_PATTERN, text):
            arguments[name] = text
            return []
        versioned = VERSIONED_ID.fullmatch(text)
        if versioned and "ref" in properties and "ref" not in arguments:
            arguments[name], arguments["ref"] = versioned.group(1), versioned.group(2)
            note = (
                f"{name} {text!r} holds a version: used {versioned.group(1)!r} at ref "
                f"{versioned.group(2)!r}."
            )
            return [note]
        try:
            found = await self._resolve(ResolveLibraryNameQuery(name=text))
        except DomainError as error:
            raise ToolError(str(error)) from error
        arguments[name] = found.id
        return [f"{name} {text!r} is a name, not an ID: resolved to {found.id!r}."]


def _blank(value: object) -> bool:
    """Tell whether an argument's value means "not given": ``null`` or blank text.

    Args:
        value: The value sent.

    Returns:
        True for ``None`` and for a string with nothing but whitespace.
    """
    return value is None or (isinstance(value, str) and not value.strip())


def clamped(name: str, value: object, spec: Mapping[str, Any]) -> tuple[object, str | None]:
    """Clamp a whole number to the range its schema declares; text holding one is read first.

    Args:
        name: The argument.
        value: Its value as sent.
        spec: Its JSON schema, maybe an ``anyOf`` of an integer and ``null``.

    Returns:
        The value to validate (unchanged when it is no number or has no range), and a note when
        it was clamped.
    """
    bounds = _range(spec)
    if bounds is None or isinstance(value, bool):
        return value, None
    if isinstance(value, str) and WHOLE_NUMBER.fullmatch(value):
        value = int(value)
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if not isinstance(value, int):
        return value, None  # left to validation
    low, high = bounds
    if high is not None and value > high:
        return high, f"{name} {value} is above the maximum of {high}: {high} was used."
    if low is not None and value < low:
        return low, f"{name} {value} is below the minimum of {low}: {low} was used."
    return value, None


def _range(spec: Mapping[str, Any]) -> tuple[int | None, int | None] | None:
    """Read the range of an integer argument from its JSON schema.

    Args:
        spec: The argument's schema; an integer may sit in an ``anyOf`` with ``null``.

    Returns:
        ``(minimum, maximum)``, either ``None`` when unbounded; ``None`` for no integer or no
        bound at all.
    """
    integer = next(
        (s for s in [spec, *spec.get("anyOf", [])] if s.get("type") == "integer"),
        None,
    )
    if integer is None or ("minimum" not in integer and "maximum" not in integer):
        return None
    return integer.get("minimum"), integer.get("maximum")


def unknown_arguments(
    tool: str,
    unknown: Sequence[str],
    properties: Mapping[str, Mapping[str, Any]],
    required: set[str],
) -> str:
    """Say which arguments the tool does not have, and which it has.

    Args:
        tool: The tool's name.
        unknown: The arguments it does not have, as sent.
        properties: Its arguments, with their schemas.
        required: The ones it requires.

    Returns:
        The message, naming each real argument, its type and whether it is required.
    """
    real = ", ".join(
        f"{name} ({_type_of(spec)}{', required' if name in required else ''})"
        for name, spec in properties.items()
    )
    names = ", ".join(repr(u[:64]) for u in unknown[:10])
    return f"invalid_arguments: {tool} has no argument {names}; its arguments are: {real}"


def _type_of(spec: Mapping[str, Any]) -> str:
    """Name an argument's JSON type for an error message.

    Args:
        spec: The argument's schema.

    Returns:
        Its type, or the types of its ``anyOf`` but ``null``, joined by ``|``.
    """
    if "type" in spec:
        return str(spec["type"])
    kinds = [str(s.get("type", "object")) for s in spec.get("anyOf", []) if s.get("type") != "null"]
    return " | ".join(kinds) or "any"


def with_notes(result: ToolResult, notes: Sequence[str], *, structured: bool) -> ToolResult:
    """Add the notes to a result: a last text block, and ``notes`` in its structured content.

    The notes the tool's answer carries itself (its structured ``notes``) follow the middleware's,
    in the text block and in ``notes``.

    Args:
        result: The tool's result.
        notes: What was changed in the arguments.
        structured: Whether the tool has an output schema (that declares ``notes``).

    Returns:
        The result with the notes; as it is when there are none.
    """
    data = result.structured_content
    told = data.get(NOTES) if isinstance(data, dict) else None
    own = [str(note) for note in told] if isinstance(told, list) else []
    every = [*notes, *own]
    if not every:
        return result
    content = [*result.content, mt.TextContent(type="text", text="Notes: " + " ".join(every))]
    if isinstance(data, dict) and (structured or own):
        data = {**data, NOTES: every}
    return ToolResult(content=content, structured_content=data, meta=result.meta)


def noted(tool: Tool) -> Tool:
    """Declare the optional ``notes`` in a tool's output schema, when it has one of objects.

    Args:
        tool: The tool as registered.

    Returns:
        A copy whose output schema has ``notes``; the tool itself when it has no such schema.
    """
    schema = tool.output_schema
    if not schema or "properties" not in schema:
        return tool
    properties = {**schema["properties"], NOTES: dict(NOTES_SCHEMA)}
    return tool.model_copy(update={"output_schema": {**schema, "properties": properties}})
