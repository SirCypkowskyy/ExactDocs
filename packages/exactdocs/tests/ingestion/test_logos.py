"""Project logos (#504): where the importer looks, what it keeps, and how an SVG is cleaned."""

import pytest

from exactdocs.ingestion.constants import (
    LOGO_FILES,
    MAX_LOGO_BYTES,
    MAX_LOGO_SVG_ELEMENTS,
    MAX_README_LOGOS,
)
from exactdocs.ingestion.models import (
    FetchedFile,
    ProblemCode,
    ProposedId,
    RepositoryHost,
    RepositoryUrl,
    check_logo,
    clean_svg,
    image_size,
    logo_candidates,
    pick_logo,
    readme_summary,
)

GITHUB = RepositoryUrl(
    url="https://github.com/Acme/Payments",
    host_kind=RepositoryHost.GITHUB,
    library_id=ProposedId("/acme/payments"),
)
ELSEWHERE = RepositoryUrl(
    url="https://git.example.com/acme/payments.git",
    host_kind=RepositoryHost.GIT,
    library_id=ProposedId("/acme/payments"),
)
SVG_NS = 'xmlns="http://www.w3.org/2000/svg"'


def png(width: int, height: int) -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n" + b"\0\0\0\rIHDR" + width.to_bytes(4) + height.to_bytes(4) + b"\0" * 9
    )


def jpeg(width: int, height: int) -> bytes:
    app0 = b"\xff\xe0" + (16).to_bytes(2) + b"JFIF\0" + b"\0" * 9
    frame = b"\xff\xc0" + (17).to_bytes(2) + b"\x08" + height.to_bytes(2) + width.to_bytes(2)
    return b"\xff\xd8" + app0 + b"\xff" + frame + b"\0" * 12  # a fill byte before the frame


def webp(chunk: bytes, payload: bytes) -> bytes:
    body = b"WEBP" + chunk + len(payload).to_bytes(4, "little") + payload
    return b"RIFF" + len(body).to_bytes(4, "little") + body


def vp8(width: int, height: int) -> bytes:
    size = width.to_bytes(2, "little") + height.to_bytes(2, "little")
    return webp(b"VP8 ", b"\0\0\0\x9d\x01\x2a" + size + b"\0" * 4)


def vp8l(width: int, height: int) -> bytes:
    bits = (width - 1) | ((height - 1) << 14)
    return webp(b"VP8L", b"\x2f" + bits.to_bytes(4, "little") + b"\0" * 8)


def vp8x(width: int, height: int) -> bytes:
    size = (width - 1).to_bytes(3, "little") + (height - 1).to_bytes(3, "little")
    return webp(b"VP8X", b"\0\0\0\0" + size + b"\0" * 4)


def svg(body: str, *, attributes: str = "") -> bytes:
    return f"<svg {SVG_NS}{attributes}>{body}</svg>".encode()


# ---------------------------------------------------------------- where the importer looks


def test_the_readme_offers_the_images_at_its_top_that_say_logo() -> None:
    readme = """<p align="center">
  <a href="https://acme.dev"><img src="docs/img/acme-logo.svg" alt="Acme"></a>
</p>
<h1 align="center"><img src=".github/banner.png" alt="Acme logo"></h1>
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="brand/dark.svg">
  <img src="brand/light.svg" alt="Acme">
</picture>

![CI](https://img.shields.io/badge/logo-github)
![](./assets/acme_logo.png)

# Acme

Payments for everyone.

## Install

![logo](docs/late-logo.png)
"""
    summary = readme_summary(readme)

    assert summary.logos == (
        "docs/img/acme-logo.svg",  # the path says logo
        ".github/banner.png",  # the alt says logo, also inside an <h1>
        "./assets/acme_logo.png",  # `_logo` is a word of its own
    )
    assert summary.title == "Acme"
    assert summary.description == "Payments for everyone."


def test_a_readme_offers_at_most_a_few_logos() -> None:
    images = "\n".join(f"![logo](logo-{n}.svg)" for n in range(10))

    assert len(readme_summary(f"{images}\n\n# Acme\n").logos) == MAX_README_LOGOS


@pytest.mark.parametrize(
    "readme",
    [
        "# Acme\n\n![Catalogo](docs/catalogo.png) ![Logout](logout.svg)\n",
        "# Acme\n\n![build](https://img.shields.io/badge/build-logo-green)\n",
        "# Acme\n\nNo images at all.\n",
    ],
    ids=["another word", "a badge", "no image"],
)
def test_images_that_are_not_logos_are_not_offered(readme: str) -> None:
    assert readme_summary(readme).logos == ()


def test_the_readmes_logos_come_first_then_the_conventional_files() -> None:
    candidates = logo_candidates(("docs/img/logo.svg", "./logo.svg"), GITHUB)

    assert candidates == ("docs/img/logo.svg", *LOGO_FILES)  # `logo.svg` only once


@pytest.mark.parametrize(
    ("source", "path"),
    [
        ("https://raw.githubusercontent.com/acme/payments/main/docs/logo.png", "docs/logo.png"),
        (
            "https://raw.githubusercontent.com/Acme/Payments/refs/heads/main/assets/logo.svg",
            "assets/logo.svg",
        ),
        ("https://github.com/acme/payments/raw/v1.4.0/brand/logo.svg", "brand/logo.svg"),
        (
            "https://github.com/acme/payments/blob/main/brand/logo%20dark.svg?raw=true",
            "brand/logo dark.svg",
        ),
    ],
)
def test_a_url_into_the_librarys_own_github_repository_names_a_file_of_the_commit(
    source: str, path: str
) -> None:
    candidates = logo_candidates((source,), GITHUB)

    assert candidates[0] == path
    assert set(candidates) == {path, *LOGO_FILES}


@pytest.mark.parametrize(
    ("source", "repository"),
    [
        ("https://raw.githubusercontent.com/other/repo/main/logo-x.svg", GITHUB),
        ("https://github.com/acme/payments/tree/main/logo-x.svg", GITHUB),
        ("https://acme.dev/img/logo-x.svg", GITHUB),
        ("https://raw.githubusercontent.com/acme/payments/main/logo-x.svg", ELSEWHERE),
        ("//raw.githubusercontent.com/acme/payments/main/logo-x.svg", GITHUB),
        ("../outside/logo-x.svg", GITHUB),
        ("https://[::1/logo-x.svg", GITHUB),
    ],
    ids=["another repository", "a page", "another site", "not github", "no scheme", "out", "bad"],
)
def test_any_other_url_is_never_a_candidate(source: str, repository: RepositoryUrl) -> None:
    assert logo_candidates((source,), repository) == LOGO_FILES


# ---------------------------------------------------------------- what the importer keeps


@pytest.mark.parametrize(
    ("data", "size"),
    [
        (png(640, 320), (640, 320)),
        (jpeg(300, 200), (300, 200)),
        (vp8(120, 60), (120, 60)),
        (vp8l(512, 256), (512, 256)),
        (vp8x(1000, 500), (1000, 500)),
        (b"\x89PNG\r\n\x1a\n\0\0", None),
        (b"\xff\xd8\xff\xda\0\0", None),
        (b"GIF89a" + b"\0" * 20, None),
    ],
    ids=["png", "jpeg", "webp lossy", "webp lossless", "webp extended", "cut", "no frame", "gif"],
)
def test_a_raster_images_size_is_read_from_its_header(
    data: bytes, size: tuple[int, int] | None
) -> None:
    assert image_size(data) == size


@pytest.mark.parametrize(
    "data",
    [png(16, 16), png(4096, 1024), jpeg(2048, 2048), vp8l(200, 100)],
    ids=["smallest", "widest", "most pixels", "webp"],
)
def test_a_raster_logo_within_bounds_is_kept_as_it_is(data: bytes) -> None:
    checked = check_logo(data)

    assert checked is not None
    assert checked[1] == data


@pytest.mark.parametrize(
    "data",
    [
        png(1, 1),
        png(15, 400),
        png(4097, 100),
        png(2049, 2048),
        b"GIF89a\x10\0\x10\0" + b"\0" * 10,
        b"%PDF-1.7 logo",
        b"",
        png(64, 64) + b"\0" * MAX_LOGO_BYTES,
    ],
    ids=["pixel", "thin", "too wide", "too many pixels", "gif", "pdf", "empty", "too big"],
)
def test_anything_else_is_no_logo(data: bytes) -> None:
    assert check_logo(data) is None


def test_the_first_usable_candidate_is_the_logo() -> None:
    found = {
        "logo.svg": FetchedFile(problem="larger than 524288 bytes", code=ProblemCode.TOO_LARGE),
        "logo.png": FetchedFile(data=png(1, 1)),
        "assets/logo.png": FetchedFile(data=png(64, 64)),
        "docs/logo.svg": FetchedFile(data=svg('<rect width="1" height="1"/>')),
    }

    logo = pick_logo(
        ("logo.svg", "logo.png", "missing.png", "assets/logo.png", "docs/logo.svg"), found
    )

    assert logo is not None
    assert (logo.path, logo.content_type) == ("assets/logo.png", "image/png")
    assert pick_logo(("logo.svg", "logo.png"), found) is None


# ---------------------------------------------------------------- how an SVG is cleaned


def test_an_svg_logo_keeps_its_drawing_and_loses_everything_that_runs_or_loads() -> None:
    dirty = b"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" "http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">
<?xml-stylesheet href="https://evil.example/a.css"?>
<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"
     xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"
     viewBox="0 0 24 24" onload="steal()" inkscape:version="1.3" xml:space="preserve">
  <!-- made by hand -->
  <title>Acme &amp; Co</title>
  <script>steal()</script>
  <style>.a { fill: #c82828 } g > .b { stroke: red }</style>
  <style>@import url(https://evil.example/a.css);</style>
  <defs><linearGradient id="g"><stop offset="0" stop-color="#fff"/></linearGradient></defs>
  <path class="a" d="M0 0h24v24H0z" fill="url(#g)" style="fill: url(https://evil.example/t)"/>
  <use xlink:href="#g"/>
  <use href="https://evil.example/sprite.svg#icon"/>
  <a href="javascript:steal()"><text x="1" y="20" onclick="steal()">Acme</text></a>
  <foreignObject><div xmlns="http://www.w3.org/1999/xhtml">html</div></foreignObject>
  <image href="https://evil.example/pixel.png"/>
  <set attributeName="href" to="javascript:steal()"/>
  <animate attributeName="fill" values="red;blue"/>
  <metadata><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"/></metadata>
  <inkscape:grid/>
</svg>"""

    cleaned = clean_svg(dirty)

    assert cleaned is not None
    text = cleaned.decode()
    assert text.startswith(f'<svg {SVG_NS} viewBox="0 0 24 24" xml:space="preserve">')
    for kept in (
        "<title>Acme &amp; Co</title>",
        "<style>.a { fill: #c82828 } g &gt; .b { stroke: red }</style>",
        'fill="url(#g)"',
        '<use href="#g">',
        '<text x="1" y="20">Acme</text>',
    ):
        assert kept in text
    for gone in (
        "script", "steal", "evil", "onload", "onclick", "inkscape", "foreignObject", "<image",
        "<set", "<animate", "metadata", "@import", "style=", "javascript", "DOCTYPE", "<?xml",
        "<!--",
    ):  # fmt: skip
        assert gone not in text


@pytest.mark.parametrize(
    "data",
    [
        b'<!DOCTYPE svg [<!ENTITY a "aaaaaaaaaa">]><svg xmlns="http://www.w3.org/2000/svg">&a;</svg>',
        b'<!DOCTYPE svg [<!ATTLIST svg onload CDATA "steal()">]><svg xmlns="http://www.w3.org/2000/svg"/>',
        b'<!DOCTYPE svg SYSTEM "https://evil.example/x.dtd"><svg xmlns="http://www.w3.org/2000/svg">&x;</svg>',
        b"<svg><rect/></svg>",
        b'<html xmlns="http://www.w3.org/2000/svg"/>',
        b'<svg xmlns="http://www.w3.org/2000/svg"><rect>',
        "<svg xmlns='http://www.w3.org/2000/svg'><text>café</text></svg>".encode("latin-1"),
    ],
    ids=[
        "entity",
        "internal subset",
        "external entity",
        "no namespace",
        "not svg",
        "broken",
        "bad utf-8",
    ],
)
def test_an_svg_that_declares_or_needs_a_dtd_or_is_no_svg_is_refused(data: bytes) -> None:
    assert clean_svg(data) is None


def test_an_svg_in_another_declared_encoding_is_written_back_as_utf_8() -> None:
    utf16 = "<svg xmlns='http://www.w3.org/2000/svg'><text>café</text></svg>".encode("utf-16")

    assert clean_svg(utf16) == f"<svg {SVG_NS}><text>café</text></svg>".encode()


def test_copies_of_copies_refuse_an_svg() -> None:
    doubling = (
        '<g id="a"><rect/></g>'
        '<g id="b"><use href="#a"/><use href="#a"/></g>'
        '<g id="c"><use href="#b"/><use href="#b"/></g>'
    )
    flat = '<g id="a"><rect/><rect/></g><use href="#a"/><use href="#a"/>'

    assert clean_svg(svg(doubling)) is None
    assert clean_svg(svg('<g id="a"><use href="#a"/></g>')) is None  # a copy of itself
    assert clean_svg(svg(flat)) is not None


def test_an_svg_too_big_to_be_a_logo_is_refused() -> None:
    many = svg("<rect/>" * (MAX_LOGO_SVG_ELEMENTS + 1))
    copied = svg(
        '<g id="a">'
        + "<rect/>" * 1000
        + "</g>"
        + '<use href="#a"/>' * (MAX_LOGO_SVG_ELEMENTS // 1000 + 1)
    )

    assert clean_svg(many) is None
    assert clean_svg(copied) is None


def test_a_deeply_nested_svg_is_cleaned_without_recursion() -> None:
    depth = MAX_LOGO_SVG_ELEMENTS - 2  # with the <svg> and the <rect>: exactly the bound
    nested = svg("<g>" * depth + "<rect/>" + "</g>" * depth)

    cleaned = clean_svg(nested)

    assert cleaned is not None
    assert cleaned.count(b"<g>") == depth
