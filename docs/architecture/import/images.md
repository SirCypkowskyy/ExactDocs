# Images and logos

!!! abstract "TL;DR"
    - Relative article images are collected at import: at most 2 MiB each, 1000 and 64 MiB per
      version, type sniffed from the bytes; the rest are skipped problems and never fail the job.
    - `/asset` serves them to signed-in callers only, with `nosniff` and a sandboxing CSP; SVG is
      served as is, and one declaring entities is refused.
    - A library takes its logo from its default version: logo images at the top of the README, else
      `LOGO_FILES`, at most 512 KiB, and no URL is ever fetched.
    - A raster logo needs 16 to 4096 pixels a side, an SVG is cleaned by `clean_svg`, and any logo
      failure leaves the old logo in place.

## Images

### Collecting

- Articles' relative `![](../...)` images are collected at parse time, resolved against the article's
  folder, as the web renderer does. Absolute URLs, `data:` and paths leaving the repository are
  ignored.
- The first checkout already holds those inside the selected paths. The rest come from a second,
  literal-path `GitGateway.fetch_files` (glob characters escaped, no README, its own download
  limit).

### Limits

| Limit | Value |
|---|---|
| per image | `EXACTDOCS_MAX_IMAGE_BYTES` (2 MiB); a plain file, never a symlink |
| type | **sniffed from the bytes**: PNG, JPEG, GIF, WebP or SVG; anything else is `not_an_image` |
| per version | 1000 images and `EXACTDOCS_MAX_IMAGES_BYTES` (64 MiB) |

The rest, and images the repository lacks, are listed as skipped problems of the job and never fail
it.

### Storing

The catalog stores each blob once (`catalog_image_blobs`, keyed by git blob SHA) and lists them per
manifest (`catalog_manifest_images`), so they are activated, superseded, removed and collected (#45)
together with the articles.

### Serving

`GET /api/v1/libraries/{owner}/{repo}/asset?ref=&path=` serves them to signed-in callers only, like
every `/api/v1` route. No `ref` means the default version. The response carries:

- the stored type;
- `X-Content-Type-Options: nosniff`;
- `Cache-Control: private, no-cache`;
- `ETag` = blob SHA (`If-None-Match` answers 304);
- `Content-Security-Policy: default-src 'none'; style-src 'unsafe-inline'; sandbox`.

!!! info "Why SVG is served"

    **SVG** is served, not rasterized or refused: it is what diagrams are made of. In an `<img>` a
    browser runs no script and loads nothing, and opened directly it is an attachment under that
    CSP, so a hostile SVG can neither run nor phone home. SVGs declaring entities are refused.

Not stored: images in raw HTML, MDX components or front matter.

## Project logos (#504)

A library carries the logo of its **default version**, as it takes that version's title and
description (LIB-07), so an import of an older tag never replaces it.

### Where it is found

After the publish, an import or re-sync of the version that is the default then
(`LibraryLogos.wants_logo`, so no other import reads anything) looks, in order, at:

1. **Images at the top of the root README** (before the first heading below H1) whose `src` or `alt`
   says "logo" and that are no badge. Markdown or HTML `<img>`, also in an `<h1>` or a `<picture>`;
   at most 4 (`ReadmeSummary.logos`, read with the README).
    - A relative `src` resolves against the root.
    - An absolute URL counts only when it points into the library's own GitHub repository
      (`raw.githubusercontent.com/<owner>/<repo>/<ref>/<path>`,
      `github.com/.../raw|blob/<ref>/<path>`). It names `<path>` of the **imported commit**: no URL
      is ever fetched.
2. **The conventional files** `LOGO_FILES` (`logo.svg`, `.github/logo.png`, `assets/logo.*`,
   `docs/public/logo.svg`, `docs/assets/logo.png`, `static/img/logo.svg`, ...).

All candidates are read in one `RepositoryFiles.read_files` (the commit's trees, then each existing
file's blob, also outside the selected paths), at most `MAX_LOGO_BYTES` (512 KiB) each.

### What is kept

`check_logo`, in a thread, keeps the first candidate whose sniffed type is PNG, JPEG, WebP or SVG (no
GIF).

- **A raster image** is kept byte for byte when its header (never decoded) says 16 to 4096 pixels a
  side and at most 2048 x 2048 pixels in all. A 1 x 1 spacer is no logo and a decompression bomb is
  refused.
- **An SVG is cleaned** (`clean_svg`):
    - expat parses it and refuses any DTD internal subset, entity declaration or undeclared entity
      before anything is expanded, and more than 10,000 elements;
    - only SVG-namespace shapes, text, paint servers, clipping, masks, filters and `<style>` are
      kept. Scripts, `foreignObject`, `image`, animations, metadata and editors' elements go with
      their content;
    - event handlers and foreign-namespace attributes go;
    - any value or `<style>` with `url()` to another document, `javascript:`, `@import`, an
      expression or a CSS escape goes;
    - `href` stays only as `#fragment`;
    - `<use>` may neither copy another `<use>` nor copy more than 10,000 elements in all (copies of
      copies multiply);
    - the result is written anew as UTF-8.

### Never fatal

- The logo step is no durable step: like the README text it reads what is imported now and replaces
  the logo whole.
- Any failure (the remote, the catalog) is logged and the library keeps the logo it had.
- A version with no usable candidate removes the library's logo.
- `ReadmeSummary.logos` changed the import's step results: `STEPS_VERSION` `jobs-12`.

### Stored

- `catalog_library_logos`: one row per library (`digest`, `content_type`, `data`, `path`, `ref`),
  with a foreign key to `catalog_libraries` with `ON DELETE CASCADE`, so a removed library loses it.
- Behind the catalog's `LibraryLogos` port. `ApplyLogo` re-checks type and size, keeps only the
  default version's and skips identical bytes.
- The library repository reads the digest with a left join into `Library.logo`, so `LibrarySummary`
  and `LibraryDetail` carry `logo` (16 hex digits of the SHA-256) without reading the bytes.

### Served

- `GET /api/v1/libraries/{owner}/{repo}/logo` (`GetLogo`, library read access) with the asset
  headers above.
- `?v=<logo>` makes it `immutable` for a year, so a list of libraries costs no request once seen.
- Pinning another default or removing the default version does not re-derive the logo until that
  version is imported again, as for the title.

## Relative links and images in the UI

- **Links.** A link to `.md`/`.mdx` stays in the app (same version, resolved path, same `#anchor`).
  Any other repository file opens on the host's blob page at the commit. A link to an article the
  import left out lands on "Not in this version", which offers the same file on the host.
- **Images** load from `/asset` first (public and private libraries alike). If that fails (404: a
  version imported before #64, or an image skipped as too large):
    - a **public** library falls back to the host's raw URL at the commit;
    - a private one, or a failed fallback, shows the alt text.
- Images are `loading="lazy" decoding="async"`. Their size is not stored, so CSS bounds them
  (`max-width: 100%`) and no `width`/`height` is set.
- **Moved articles.** A path the version does not have is first looked up in the version's renames
  (`renamed-path`, forward, one hop, short timeout, no retry).
    - An article git saw moved when the version was imported opens at its new path, same version and
      `#anchor`.
    - The URL is replaced, so Back skips the old path, and a "Moved from" line above the article
      (carried in history state) names it.
    - No rename, or a failed lookup, keeps the "Not in this version" page.
