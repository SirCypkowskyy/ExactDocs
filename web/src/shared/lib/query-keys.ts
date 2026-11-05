/**
 * The root of every query the browse page makes (libraries, trees, articles). Invalidate it after
 * an import or a refresh so an open browse page reloads what it shows:
 * `queryClient.invalidateQueries({ queryKey: BROWSE_KEY })`.
 */
export const BROWSE_KEY = ["browse"] as const;

/**
 * The root of the search across every library, under `BROWSE_KEY` so whatever invalidates that
 * drops these hits too. `*search-all*` cannot be a GitHub owner, so it never names a library.
 */
export const SEARCH_ALL_KEY = [...BROWSE_KEY, "*search-all*"] as const;

/** The root of the libraries list, its sync badges and import jobs. */
export const LIBRARIES_KEY = ["libraries"] as const;
