"""Operator-supplied provider icons: type by content, bounded size, and the SVG allowlist."""

import struct
import zlib
from pathlib import Path

import pytest

from exactdocs.identity.adapters.driven.icons import check_icon, read_icon
from exactdocs.identity.constants import MAX_ICON_BYTES, MAX_ICON_PIXELS

SVG = 'xmlns="http://www.w3.org/2000/svg"'


def png(width: int, height: int) -> bytes:
    """A real (tiny) PNG header of this size: signature, IHDR and IEND."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IEND", b"")


def webp(kind: bytes, payload: bytes) -> bytes:
    body = b"WEBP" + kind + struct.pack("<I", len(payload)) + payload
    return b"RIFF" + struct.pack("<I", len(body)) + body


def vp8(width: int, height: int) -> bytes:
    return webp(b"VP8 ", b"\x00" * 3 + b"\x9d\x01\x2a" + struct.pack("<HH", width, height))


def vp8l(width: int, height: int) -> bytes:
    bits = (width - 1) | ((height - 1) << 14)
    return webp(b"VP8L", b"\x2f" + struct.pack("<I", bits))


def vp8x(width: int, height: int) -> bytes:
    size = (width - 1).to_bytes(3, "little") + (height - 1).to_bytes(3, "little")
    return webp(b"VP8X", b"\x00" * 4 + size)


def svg(body: str, attributes: str = 'viewBox="0 0 24 24"') -> bytes:
    return f"<svg {SVG} {attributes}>{body}</svg>".encode()


@pytest.mark.parametrize(
    ("content", "media_type"),
    [
        (png(32, 32), "image/png"),
        (vp8(64, 48), "image/webp"),
        (vp8l(512, 512), "image/webp"),
        (vp8x(100, 20), "image/webp"),
        (svg('<path d="M0 0h24v24H0z"/>'), "image/svg+xml"),
    ],
)
def test_the_type_is_told_by_the_content(content: bytes, media_type: str) -> None:
    icon = check_icon(content)

    assert icon.media_type == media_type
    assert len(icon.version) == 16
    if media_type != "image/svg+xml":
        assert icon.content == content  # raster images are served as they are


@pytest.mark.parametrize(
    "content",
    [
        png(MAX_ICON_PIXELS + 1, 16),
        png(16, MAX_ICON_PIXELS + 1),
        vp8l(MAX_ICON_PIXELS + 1, 1),
        vp8x(1, 4000),
        svg("", f'width="{MAX_ICON_PIXELS + 1}" height="10"'),
        svg("", 'width="600px" height="10px"'),
    ],
)
def test_an_icon_with_too_many_pixels_is_refused(content: bytes) -> None:
    with pytest.raises(ValueError, match="pixels"):
        check_icon(content)


def test_an_icon_too_big_is_refused_and_read_no_further(tmp_path: Path) -> None:
    big = tmp_path / "icon.svg"
    big.write_bytes(svg("<!--" + "x" * MAX_ICON_BYTES + "-->"))

    with pytest.raises(ValueError, match="larger than"):
        read_icon(big)
    with pytest.raises(ValueError, match="cannot be read"):
        read_icon(tmp_path / "missing.png")


@pytest.mark.parametrize(
    "content",
    [
        b"GIF89a\x01\x00\x01\x00",
        b"\x89PNG\r\n\x1a\nshort",
        webp(b"ALPH", b"\x00" * 16),
        b"<html><body>hi</body></html>",
        b'<svg xmlns="http://www.w3.org/1999/xhtml"></svg>',
        b"<svg><path/></svg>",  # no SVG namespace
        b'<svg xmlns="http://www.w3.org/2000/svg"><path>',  # not well-formed
        b"\xff\xfe<\x00s\x00",  # not UTF-8
        png(0, 10),
    ],
)
def test_what_is_not_an_acceptable_image_is_refused(content: bytes) -> None:
    with pytest.raises(ValueError, match="icon"):
        check_icon(content)


@pytest.mark.parametrize(
    "content",
    [
        b'<!DOCTYPE svg [<!ENTITY x "boom">]><svg xmlns="http://www.w3.org/2000/svg">&x;</svg>',
        b'<!doctype svg SYSTEM "file:///etc/passwd"><svg xmlns="http://www.w3.org/2000/svg"/>',
        b'<?xml version="1.0"?><!ENTITY  % x SYSTEM "http://evil.example/">',
    ],
)
def test_a_doctype_or_an_entity_is_refused_before_parsing(content: bytes) -> None:
    with pytest.raises(ValueError, match="DOCTYPE"):
        check_icon(content)


def test_an_svg_nested_too_deep_is_refused() -> None:
    with pytest.raises(ValueError, match="deeper"):
        check_icon(svg("<g>" * 40 + "</g>" * 40))


def test_scripts_handlers_and_foreign_content_are_dropped() -> None:
    dirty = svg(
        "<script>alert(1)</script>"
        '<foreignObject><body xmlns="http://www.w3.org/1999/xhtml">hi</body></foreignObject>'
        "<style>@import url(https://evil.example/x.css);</style>"
        '<image href="https://evil.example/track.png"/>'
        '<a href="javascript:alert(1)"><path d="M1 1"/></a>'
        '<path d="M0 0h24v24H0z" fill="#5865F2" onload="alert(1)" onclick="x()"/>'
        '<animate attributeName="href" to="javascript:alert(1)"/>'
        "<text>visible text</text>"
        "<title>Our IdP</title>",
        'viewBox="0 0 24 24" onload="alert(1)" xmlns:x="urn:x" x:evil="1"',
    )

    clean = check_icon(dirty).content.decode()

    for gone in ("script", "alert", "foreignObject", "style", "@import", "evil.example", "<a",
                 "image", "onload", "onclick", "animate", "visible text", "urn:x"):  # fmt: skip
        assert gone not in clean, gone
    assert 'fill="#5865F2"' in clean
    assert "<title>Our IdP</title>" in clean
    assert clean.startswith('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">')


def test_only_references_into_the_svg_itself_are_kept() -> None:
    dirty = svg(
        '<defs><linearGradient id="g"><stop offset="0" stop-color="red"/></linearGradient>'
        '<path id="p" d="M0 0"/></defs>'
        '<use href="#p"/>'
        '<use xmlns:xlink="http://www.w3.org/1999/xlink" xlink:href="#p"/>'
        '<use href="https://evil.example/sprite.svg#p"/>'
        '<use href="data:image/svg+xml;base64,PHN2Zz4="/>'
        '<rect fill="url(#g)" width="4" height="4"/>'
        '<rect fill="url(https://evil.example/x)" stroke="url( \'#g\' )" width="4" height="4"/>'
        '<rect style="fill:url(#g);stroke:url(javascript:alert(1));opacity:0.5;'
        'behavior:url(x.htc);background:url(x)" width="4" height="4"/>'
        '<rect fill="\\75 rl(x)" width="1" height="1"/>'
    )

    clean = check_icon(dirty).content.decode()

    assert clean.count('href="#p"') == 2  # xlink:href kept as plain href
    assert "evil.example" not in clean
    assert "data:" not in clean
    assert 'fill="url(#g)"' in clean
    assert "stroke=\"url( '#g' )\"" in clean
    assert 'style="fill:url(#g);opacity:0.5"' in clean
    assert "\\75" not in clean
    assert "javascript" not in clean


def test_an_svg_without_an_absolute_size_is_sized_by_the_page() -> None:
    assert check_icon(svg("", 'width="100%" height="2em"')).media_type == "image/svg+xml"
    assert check_icon(svg("", 'width="24.5" height="24px"')).media_type == "image/svg+xml"
