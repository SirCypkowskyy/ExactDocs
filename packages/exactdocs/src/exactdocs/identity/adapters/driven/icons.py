"""Operator-supplied icons of sign-in providers: PNG, WebP or SVG, bounded in size and sanitised.

An icon is read once, when the server starts, from the file a provider's ``icon_file`` names, and
served from ExactDocs' own origin (``GET /api/v1/auth/<name>/icon``), never from the provider's.
What is accepted:

- at most ``MAX_ICON_BYTES``, and at most ``MAX_ICON_PIXELS`` wide and high (read from the PNG
  ``IHDR`` chunk, the WebP ``VP8``/``VP8L``/``VP8X`` header, or an SVG's own ``width`` and
  ``height`` when they are absolute);
- the type is told by the content (its magic bytes), never by the file's name;
- an SVG is rebuilt from an allowlist: SVG elements that draw shapes and gradients, their
  presentation attributes, references to its own ``#ids`` only. Scripts, event handlers,
  ``foreignObject``, ``style`` elements, external references (``href``, ``url(...)``) and
  anything outside the SVG namespace are dropped; a DOCTYPE (and so any entity) is refused.
"""

import re
from pathlib import Path
from xml.etree import ElementTree as ET  # ruff: ignore[suspicious-xml-etree-import] - see _parse_svg

from exactdocs.identity.constants import (
    _PNG_HEADER_END,
    _VP8_START_CODE,
    _VP8L_SIGNATURE,
    _WEBP_VP8_END,
    _WEBP_VP8L_END,
    _WEBP_VP8X_END,
    ICON_ALLOWED_PROPERTIES,
    ICON_ALLOWED_SVG_ELEMENTS,
    ICON_KEPT_TEXT_ELEMENTS,
    ICON_LOCAL_REFERENCE,
    ICON_PNG_SIGNATURE,
    ICON_SVG_NAMESPACE,
    ICON_UNSAFE_VALUE,
    ICON_XLINK_NAMESPACE,
    MAX_ICON_BYTES,
    MAX_ICON_PIXELS,
    MAX_ICON_SVG_DEPTH,
)
from exactdocs.identity.models import ProviderIcon


def read_icon(path: Path) -> ProviderIcon:
    """Read an icon file and check it (see the module docstring).

    Args:
        path: The file.

    Returns:
        The icon, an SVG sanitised.

    Raises:
        ValueError: It cannot be read, is too big, or is no acceptable PNG, WebP or SVG.
    """
    try:
        with path.open("rb") as file:
            content = file.read(MAX_ICON_BYTES + 1)
    except OSError as error:
        message = f"the icon file cannot be read ({error.strerror or type(error).__name__})"
        raise ValueError(message) from None
    return check_icon(content)


def check_icon(content: bytes) -> ProviderIcon:
    """Check an icon's bytes and return it, an SVG rebuilt from the allowlist.

    Args:
        content: The file's bytes.

    Returns:
        The icon.

    Raises:
        ValueError: Too big, too many pixels, or not a PNG, WebP or SVG this accepts.
    """
    if len(content) > MAX_ICON_BYTES:
        message = f"the icon is larger than {MAX_ICON_BYTES} bytes"
        raise ValueError(message)
    if content.startswith(ICON_PNG_SIGNATURE):
        media_type, (width, height) = "image/png", _png_size(content)
    elif content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        media_type, (width, height) = "image/webp", _webp_size(content)
    else:
        media_type = "image/svg+xml"
        content, (width, height) = _sanitised_svg(content)
    if width == 0 or height == 0:
        message = "the icon has no pixels"
        raise ValueError(message)
    if (width or 0) > MAX_ICON_PIXELS or (height or 0) > MAX_ICON_PIXELS:
        message = f"the icon is larger than {MAX_ICON_PIXELS}x{MAX_ICON_PIXELS} pixels"
        raise ValueError(message)
    return ProviderIcon(media_type=media_type, content=content)


def _png_size(content: bytes) -> tuple[int, int]:
    """Read a PNG's width and height from its ``IHDR`` chunk (always the first).

    Args:
        content: The PNG.

    Returns:
        Width and height.

    Raises:
        ValueError: The PNG has no ``IHDR`` chunk where one must be.
    """
    if len(content) < _PNG_HEADER_END or content[12:16] != b"IHDR":
        message = "the PNG icon is malformed"
        raise ValueError(message)
    return int.from_bytes(content[16:20], "big"), int.from_bytes(content[20:24], "big")


def _webp_size(content: bytes) -> tuple[int, int]:
    """Read a WebP's width and height from its first chunk (``VP8 ``, ``VP8L`` or ``VP8X``).

    Args:
        content: The WebP.

    Returns:
        Width and height.

    Raises:
        ValueError: The first chunk is none of the three, or too short.
    """
    chunk = content[12:16]
    if chunk == b"VP8 " and len(content) >= _WEBP_VP8_END and content[23:26] == _VP8_START_CODE:
        width = int.from_bytes(content[26:28], "little") & 0x3FFF
        height = int.from_bytes(content[28:30], "little") & 0x3FFF
        return width, height
    if chunk == b"VP8L" and len(content) >= _WEBP_VP8L_END and content[20] == _VP8L_SIGNATURE:
        bits = int.from_bytes(content[21:25], "little")
        return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    if chunk == b"VP8X" and len(content) >= _WEBP_VP8X_END:
        width = int.from_bytes(content[24:27], "little") + 1
        height = int.from_bytes(content[27:30], "little") + 1
        return width, height
    message = "the WebP icon is malformed"
    raise ValueError(message)


def _sanitised_svg(content: bytes) -> tuple[bytes, tuple[int | None, int | None]]:
    """Rebuild an SVG from the allowlist and read its absolute size, if it states one.

    Args:
        content: The file's bytes, which should be an SVG document.

    Returns:
        The rebuilt document (UTF-8), and its width and height (``None`` when not absolute).

    Raises:
        ValueError: Not an ``<svg>`` in the SVG namespace.
    """
    root = _parse_svg(content)
    if root.tag != f"{{{ICON_SVG_NAMESPACE}}}svg":
        message = f'an SVG icon\'s root must be <svg xmlns="{ICON_SVG_NAMESPACE}">'
        raise ValueError(message)
    clean = _clean(root, depth=0)
    if clean is None:  # never: the root is an allowed <svg>
        clean = ET.Element("svg", {"xmlns": ICON_SVG_NAMESPACE})
    size = (_pixels(clean.get("width")), _pixels(clean.get("height")))
    return ET.tostring(clean, encoding="unicode").encode(), size


def _parse_svg(content: bytes) -> ET.Element:
    """Parse the SVG's XML, refusing a DOCTYPE first.

    Without a DOCTYPE there are no entities to expand (no billion laughs, no external entity),
    which is all the standard library's parser would need guarding against; expat refuses
    anything that is not well-formed.

    Args:
        content: The file's bytes.

    Returns:
        The root element.

    Raises:
        ValueError: Not UTF-8, a DOCTYPE or an entity, or not well-formed XML.
    """
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        message = "the icon is not a PNG, a WebP or a UTF-8 SVG"
        raise ValueError(message) from None
    if re.search(r"<!\s*(DOCTYPE|ENTITY)", text, re.IGNORECASE):
        message = "an SVG icon may not have a DOCTYPE or entities"
        raise ValueError(message)
    try:
        return ET.fromstring(text)  # ruff: ignore[suspicious-xml-element-tree-usage] - no DOCTYPE
    except ET.ParseError:
        message = "the icon is not a PNG, a WebP or a well-formed SVG"
        raise ValueError(message) from None


def _clean(element: ET.Element, *, depth: int) -> ET.Element | None:
    """Copy an element, its allowed attributes and its allowed children.

    Args:
        element: The element of the parsed SVG.
        depth: How deep it is (the root is 0).

    Returns:
        The copy; ``None`` when the element is not allowed (it is dropped with its children).

    Raises:
        ValueError: The SVG nests deeper than ``MAX_ICON_SVG_DEPTH``.
    """
    if depth > MAX_ICON_SVG_DEPTH:
        message = f"the SVG icon nests deeper than {MAX_ICON_SVG_DEPTH} elements"
        raise ValueError(message)
    namespace, _, name = str(element.tag).rpartition("}")
    if namespace != f"{{{ICON_SVG_NAMESPACE}" or name not in ICON_ALLOWED_SVG_ELEMENTS:
        return None
    # Unqualified names, the root declaring SVG's namespace as the default: what browsers read.
    copy = ET.Element(name, {"xmlns": ICON_SVG_NAMESPACE} if depth == 0 else {})
    for attribute, value in element.attrib.items():
        if (kept := _attribute(attribute, value)) is not None:
            copy.set(*kept)
    if name in ICON_KEPT_TEXT_ELEMENTS and element.text:
        copy.text = element.text
    for child in element:
        if (cleaned := _clean(child, depth=depth + 1)) is not None:
            copy.append(cleaned)
    return copy


def _attribute(attribute: str, value: str) -> tuple[str, str] | None:
    """Return an attribute as it is kept, or ``None`` to drop it.

    ``href`` (plain or ``xlink:``) is kept, as plain ``href``, only when it points into the
    document itself (``#id``). ``style`` keeps its allowed properties with safe values. Any other
    attribute is kept when it is a presentation attribute of the allowlist (no namespace) with a
    safe value.

    Args:
        attribute: The attribute's name, ``{namespace}name`` when it has one.
        value: Its value.

    Returns:
        The name and value to keep, or ``None``.
    """
    if attribute in {"href", f"{{{ICON_XLINK_NAMESPACE}}}href"}:
        return ("href", value) if re.fullmatch(ICON_LOCAL_REFERENCE, value.strip()) else None
    if attribute == "style":
        kept = _style(value)
        return ("style", kept) if kept else None
    if attribute not in ICON_ALLOWED_PROPERTIES or not _safe(value):
        return None
    return attribute, value


def _style(value: str) -> str:
    """Keep the allowed properties of a ``style`` attribute whose values are safe.

    Args:
        value: The attribute's value (CSS declarations).

    Returns:
        The kept declarations, ``;``-separated; empty when none is kept.
    """
    kept = []
    for declaration in value.split(";"):
        name, colon, declared = declaration.partition(":")
        name, declared = name.strip(), declared.strip()
        if colon and name in ICON_ALLOWED_PROPERTIES and declared and _safe(declared):
            kept.append(f"{name}:{declared}")
    return ";".join(kept)


def _safe(value: str) -> bool:
    """Whether a presentation value refers to nothing outside the document and runs nothing.

    Args:
        value: The value.

    Returns:
        ``False`` for what ``ICON_UNSAFE_VALUE`` matches, or a ``url(...)`` other than
        ``url(#id)``.
    """
    if re.search(ICON_UNSAFE_VALUE, value, re.IGNORECASE):
        return False
    references = re.findall(r"url\(([^)]*)\)", value, re.IGNORECASE)
    if value.lower().count("url(") != len(references):
        return False  # an unclosed url(
    return all(
        re.fullmatch(ICON_LOCAL_REFERENCE, reference.strip().strip("'\"").strip())
        for reference in references
    )


def _pixels(value: str | None) -> int | None:
    """Read an absolute SVG length (``24``, ``24px``, ``24.5``) as whole pixels, rounded up.

    Args:
        value: The ``width`` or ``height`` attribute, if any.

    Returns:
        The pixels; ``None`` for a missing or relative length (``100%``, ``2em``).
    """
    if value is None or not (match := re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(?:px)?\s*", value)):
        return None
    number = float(match.group(1))
    whole = int(number)
    return whole if number == whole else whole + 1
