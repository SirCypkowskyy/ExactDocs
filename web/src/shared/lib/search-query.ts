/** The API's cap on a search query (docs/rest-api.md): 1000 characters. */
export const MAX_QUERY = 1000;

/**
 * The query as sent: trimmed, nothing when empty, capped at 1000 characters. The cap counts code
 * points, like the API, so an emoji is never cut in half (a lone surrogate throws in
 * `encodeURIComponent`).
 */
export function normalizeQuery(raw: string | undefined): string | undefined {
  const capped = Array.from((raw ?? "").trim())
    .slice(0, MAX_QUERY)
    .join("")
    .trim();
  return capped === "" ? undefined : capped;
}

/** The API's cap on a library id (`/owner/repo`) in the `library` filter: 256 characters. */
export const MAX_LIBRARY_ID = 256;
